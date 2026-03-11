import os
import secrets
from datetime import UTC, datetime
from urllib.parse import urlparse

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for
from dotenv import load_dotenv
from pymongo.errors import PyMongoError

import extensions
from auth_helpers import (
    compose_and_filters,
    current_user,
    get_session_user_oid,
    normalize_email,
    normalize_username,
    youtube_playlist_visibility_clause,
)
from blueprints.accounts import bp as accounts_bp
from blueprints.admin import bp as admin_bp
from blueprints.main import bp as main_bp
from blueprints.playlists import bp as playlists_bp
from blueprints.songs import bp as songs_bp
from i18n import get_lang, t


def register_error_handlers(app):
    def make_handler(code):
        def handler(error):
            return render_template("errors/base_error.jinja", error=error, error_code=code), code

        return handler

    handled_codes = [400, 401, 403, 404, 405, 408, 413, 429, 500, 501, 502, 503, 504]
    for code in handled_codes:
        app.register_error_handler(code, make_handler(code))

    @app.errorhandler(PyMongoError)
    def handle_mongo_error(error):
        app.logger.exception("MongoDB operation failed", exc_info=error)
        requested_with = (request.headers.get("X-Requested-With") or "").strip().lower()
        accept = (request.headers.get("Accept") or "").lower()
        wants_json = request.is_json or requested_with == "xmlhttprequest" or "application/json" in accept
        if wants_json:
            return jsonify({"ok": False, "message": t("errors.503.msg")}), 503
        return render_template("errors/base_error.jinja", error=error, error_code=503), 503


def root_admin_exists():
    return extensions.users_col.count_documents({"is_admin": True, "is_root_admin": True}, limit=1) > 0


def _dedupe_listening_history():
    now = datetime.now(UTC)
    duplicate_rows = list(
        extensions.listening_history_col.aggregate(
            [
                {
                    "$group": {
                        "_id": {"user_id": "$user_id", "song_id": "$song_id"},
                        "ids": {"$push": "$_id"},
                        "count": {"$sum": 1},
                        "play_sum": {"$sum": {"$ifNull": ["$play_count", 0]}},
                    }
                },
                {"$match": {"count": {"$gt": 1}}},
            ]
        )
    )
    for row in duplicate_rows:
        ids = [oid for oid in row.get("ids", []) if oid]
        if len(ids) < 2:
            continue
        docs = list(
            extensions.listening_history_col.find({"_id": {"$in": ids}}).sort(
                [("updated_at", -1), ("created_at", -1), ("_id", -1)]
            )
        )
        if not docs:
            continue
        keep = docs[0]
        keep_id = keep["_id"]
        drop_ids = [doc["_id"] for doc in docs[1:] if doc.get("_id")]
        merged_play_count = sum(max(0, int((doc.get("play_count", 0) or 0))) for doc in docs)
        update_payload = {
            "play_count": merged_play_count,
            "updated_at": keep.get("updated_at") or now,
            "last_position": float(keep.get("last_position", 0.0) or 0.0),
            "last_duration": float(keep.get("last_duration", 0.0) or 0.0),
        }
        created_candidates = [doc.get("created_at") for doc in docs if doc.get("created_at") is not None]
        if created_candidates:
            update_payload["created_at"] = min(created_candidates)
        if keep.get("last_completed_at") is not None:
            update_payload["last_completed_at"] = keep.get("last_completed_at")
        extensions.listening_history_col.update_one({"_id": keep_id}, {"$set": update_payload}, upsert=False)
        if drop_ids:
            extensions.listening_history_col.delete_many({"_id": {"$in": drop_ids}})


def _dedupe_for_unique_index(collection, unique_fields):
    group_id = {field: f"${field}" for field in unique_fields}
    duplicate_rows = list(
        collection.aggregate(
            [
                {"$group": {"_id": group_id, "ids": {"$push": "$_id"}, "count": {"$sum": 1}}},
                {"$match": {"count": {"$gt": 1}}},
            ]
        )
    )
    for row in duplicate_rows:
        ids = [oid for oid in row.get("ids", []) if oid]
        if len(ids) < 2:
            continue
        docs = list(collection.find({"_id": {"$in": ids}}, {"_id": 1}).sort([("_id", -1)]))
        if not docs:
            continue
        keep_id = docs[0]["_id"]
        drop_ids = [doc["_id"] for doc in docs[1:] if doc.get("_id") and doc.get("_id") != keep_id]
        if drop_ids:
            collection.delete_many({"_id": {"$in": drop_ids}})


def _ensure_unique_index_with_dedupe(collection, key_spec, name, dedupe_callback=None, logger=None):
    key_spec_list = [(field, int(order)) for field, order in key_spec]
    try:
        for index in collection.list_indexes():
            index_key = list((index.get("key") or {}).items())
            if index_key == key_spec_list and not bool(index.get("unique", False)) and index.get("name") != name:
                collection.drop_index(index.get("name"))
                if logger:
                    logger.info("Dropped non-unique conflicting index %s before creating %s", index.get("name"), name)
    except Exception as exc:
        if logger:
            logger.warning("Could not inspect/drop conflicting indexes for %s: %s", name, exc)

    try:
        collection.create_index(key_spec, unique=True, name=name)
        return
    except Exception as exc:
        if logger:
            logger.warning("Unique index %s initial creation failed: %s. Attempting dedupe.", name, exc)

    try:
        if callable(dedupe_callback):
            dedupe_callback()
        else:
            fields = [field for field, _order in key_spec]
            _dedupe_for_unique_index(collection, fields)
        collection.create_index(key_spec, unique=True, name=name)
    except Exception as exc:
        if logger:
            logger.warning("Unique index %s still unavailable after dedupe: %s", name, exc)


def create_app():
    load_dotenv()
    app = Flask(__name__)
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-me-in-production")
    app.config["APP_NAME"] = "PulseBeat"
    app.config["MONGO_URI"] = os.getenv(
        "MONGO_URI",
        "mongodb://localhost:27017/musicPlayer",
    )
    app.config["MONGO_DB_NAME"] = "musicPlayer"
    app.config["UPLOAD_DIR"] = os.path.join(app.static_folder, "uploads")
    app.config["PAGE_SIZE"] = 50
    app.config["MAIL_ENABLED"] = os.getenv("MAIL_ENABLED", "1") == "1"
    app.config["MAIL_HOST"] = os.getenv("MAIL_HOST", "")
    app.config["MAIL_PORT"] = int(os.getenv("MAIL_PORT", "587"))
    app.config["MAIL_USERNAME"] = os.getenv("MAIL_USERNAME", "")
    app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD", "")
    app.config["MAIL_USE_TLS"] = os.getenv("MAIL_USE_TLS", "1") == "1"
    app.config["MAIL_USE_SSL"] = os.getenv("MAIL_USE_SSL", "0") == "1"
    app.config["MAIL_FROM"] = os.getenv("MAIL_FROM", "")
    app.config["APP_BASE_URL"] = os.getenv("APP_BASE_URL", "")
    app.config["PASSWORD_RESET_TOKEN_MAX_AGE"] = int(os.getenv("PASSWORD_RESET_TOKEN_MAX_AGE", "3600"))
    app.config["PASSWORD_RESET_SALT"] = os.getenv("PASSWORD_RESET_SALT", "pulsebeat-reset-salt")
    app.config["EMAIL_VERIFICATION_TOKEN_MAX_AGE"] = int(os.getenv("EMAIL_VERIFICATION_TOKEN_MAX_AGE", "86400"))
    app.config["EMAIL_VERIFICATION_SALT"] = os.getenv("EMAIL_VERIFICATION_SALT", "pulsebeat-email-verify")
    app.config["TWO_FACTOR_CODE_MAX_AGE"] = int(os.getenv("TWO_FACTOR_CODE_MAX_AGE", "600"))
    app.config["TWO_FACTOR_TOGGLE_TOKEN_MAX_AGE"] = int(os.getenv("TWO_FACTOR_TOGGLE_TOKEN_MAX_AGE", "3600"))
    app.config["TWO_FACTOR_TOGGLE_SALT"] = os.getenv("TWO_FACTOR_TOGGLE_SALT", "pulsebeat-two-factor-toggle")
    app.config["GOOGLE_CLIENT_ID"] = os.getenv("GOOGLE_CLIENT_ID", "")
    app.config["GOOGLE_CLIENT_SECRET"] = os.getenv("GOOGLE_CLIENT_SECRET", "")
    app.config["GOOGLE_REDIRECT_URI"] = os.getenv("GOOGLE_REDIRECT_URI", "")
    app.config["YOUTUBE_SYNC_CLIENT_ID"] = os.getenv("YOUTUBE_SYNC_CLIENT_ID", app.config["GOOGLE_CLIENT_ID"])
    app.config["YOUTUBE_SYNC_CLIENT_SECRET"] = os.getenv("YOUTUBE_SYNC_CLIENT_SECRET", app.config["GOOGLE_CLIENT_SECRET"])
    app.config["YOUTUBE_SYNC_MAX_TRACKS_PER_PLAYLIST"] = int(os.getenv("YOUTUBE_SYNC_MAX_TRACKS_PER_PLAYLIST", "5000"))
    app.config["YOUTUBE_SYNC_MAX_PLAYLIST_PAGES"] = int(os.getenv("YOUTUBE_SYNC_MAX_PLAYLIST_PAGES", "20"))
    app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_CONTENT_LENGTH", str(25 * 1024 * 1024)))
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = os.getenv(
        "SESSION_COOKIE_SECURE",
        "1" if app.config.get("APP_BASE_URL", "").strip().lower().startswith("https://") else "0",
    ) == "1"

    extensions.init_mongo(app)
    now = datetime.now(UTC)
    extensions.users_col.update_many({"email_verified": {"$exists": False}}, {"$set": {"email_verified": True, "email_verified_at": now}})
    extensions.users_col.update_many({"email_verification_sent_at": {"$exists": False}}, {"$set": {"email_verification_sent_at": None}})
    extensions.users_col.update_many({"auth_provider": {"$exists": False}}, {"$set": {"auth_provider": "local"}})
    extensions.users_col.update_many(
        {"auth_provider": "google"},
        {
            "$set": {
                "require_password_change": False,
                "two_factor_enabled": False,
                "two_factor_prompt_pending": False,
            },
            "$unset": {"password_compromised_at": ""},
        },
    )
    extensions.users_col.update_many({"session_token_version": {"$exists": False}}, {"$set": {"session_token_version": 0}})
    extensions.users_col.update_many({"login_failure_count": {"$exists": False}}, {"$set": {"login_failure_count": 0}})
    extensions.users_col.update_many({"login_lock_level": {"$exists": False}}, {"$set": {"login_lock_level": 0}})
    extensions.users_col.update_many({"login_lock_until": {"$exists": False}}, {"$set": {"login_lock_until": None}})
    extensions.users_col.update_many({"dismissed_admin_alerts": {"$exists": False}}, {"$set": {"dismissed_admin_alerts": []}})
    extensions.users_col.update_many({"player_crossfade_enabled": {"$exists": False}}, {"$set": {"player_crossfade_enabled": True}})
    extensions.users_col.update_many({"player_normalize_volume_enabled": {"$exists": False}}, {"$set": {"player_normalize_volume_enabled": True}})
    extensions.users_col.update_many({"two_factor_enabled": {"$exists": False}}, {"$set": {"two_factor_enabled": False}})
    extensions.users_col.update_many({"two_factor_prompt_pending": {"$exists": False}}, {"$set": {"two_factor_prompt_pending": False}})
    extensions.songs_col.update_many({"is_available": {"$exists": False}}, {"$set": {"is_available": True}})
    extensions.songs_col.update_many({"availability_reason": {"$exists": False}}, {"$set": {"availability_reason": ""}})
    for user in extensions.users_col.find({}, {"email": 1, "username": 1}):
        extensions.users_col.update_one(
            {"_id": user["_id"]},
            {"$set": {"email_normalized": normalize_email(user.get("email", "")), "username_normalized": normalize_username(user.get("username", ""))}},
        )
    extensions.users_col.create_index("email_normalized", unique=True, name="uniq_users_email_normalized")
    extensions.users_col.create_index("username_normalized", unique=True, name="uniq_users_username_normalized")
    extensions.songs_col.create_index("audio_fingerprint", name="idx_songs_audio_fingerprint")
    extensions.external_integrations_col.create_index([("user_id", 1), ("provider", 1)], unique=True, name="uniq_ext_integration_user_provider")
    extensions.external_playlists_col.create_index(
        [("user_id", 1), ("provider", 1), ("external_playlist_id", 1)],
        unique=True,
        name="uniq_ext_playlist_user_provider_id",
    )
    extensions.external_playlists_col.create_index([("user_id", 1), ("synced_at", -1)], name="idx_ext_playlist_user_synced")
    extensions.data_exports_col.create_index([("user_id", 1), ("created_at", -1)], name="idx_data_exports_user_created")
    _ensure_unique_index_with_dedupe(
        extensions.listening_history_col,
        [("user_id", 1), ("song_id", 1)],
        "uniq_history_user_song",
        dedupe_callback=_dedupe_listening_history,
        logger=app.logger,
    )
    _ensure_unique_index_with_dedupe(
        extensions.song_votes_col,
        [("song_id", 1), ("user_id", 1)],
        "uniq_song_vote_song_user",
        logger=app.logger,
    )
    if getattr(extensions, "comment_votes_col", None) is not None:
        _ensure_unique_index_with_dedupe(
            extensions.comment_votes_col,
            [("comment_id", 1), ("user_id", 1)],
            "uniq_comment_vote_comment_user",
            logger=app.logger,
        )
    os.makedirs(app.config["UPLOAD_DIR"], exist_ok=True)

    app.register_blueprint(accounts_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(songs_bp)
    app.register_blueprint(playlists_bp)
    register_error_handlers(app)

    @app.route("/favicon.ico")
    def favicon():
        return ("", 204)

    @app.before_request
    def enforce_initial_setup_and_password_change():
        setup_done = root_admin_exists()
        endpoint = request.endpoint or ""
        if not setup_done:
            allowed = {"accounts.setup_admin", "static"}
            if endpoint in allowed or endpoint.startswith("static"):
                return None
            return redirect(url_for("accounts.setup_admin"))

        user_oid = get_session_user_oid()
        if not user_oid:
            return None
        user = extensions.users_col.find_one({"_id": user_oid}, {"require_password_change": 1, "auth_provider": 1, "session_token_version": 1})
        session_version = int(session.get("session_token_version", -1))
        user_version = int((user or {}).get("session_token_version", 0) or 0)
        if not user or session_version != user_version:
            session.clear()
            if endpoint == "static" or endpoint.startswith("static"):
                return None
            if endpoint not in {"accounts.login", "accounts.google_login", "accounts.google_callback", "accounts.setup_admin", "static"} and not endpoint.startswith("static"):
                flash(t("flash.accounts.session_invalidated"), "warning")
            return redirect(url_for("accounts.login"))
        if not user or user.get("auth_provider") == "google" or not user.get("require_password_change", False):
            return None

        allowed_when_forced = {
            "accounts.manage_account",
            "accounts.change_password",
            "main.set_language",
            "static",
        }
        allowed_paths = {
            url_for("accounts.manage_account"),
            url_for("accounts.change_password"),
        }
        if endpoint in allowed_when_forced or endpoint.startswith("static") or request.path in allowed_paths:
            return None

        flash(t("flash.accounts.password_change_required"), "warning")
        return redirect(url_for("accounts.manage_account"))

    def same_origin(raw_url: str) -> bool:
        if not raw_url:
            return True
        try:
            parsed = urlparse(raw_url)
        except Exception:
            return False
        if not parsed.netloc:
            return True
        forwarded_proto = (request.headers.get("X-Forwarded-Proto", "") or "").split(",")[0].strip()
        request_scheme = forwarded_proto or request.scheme
        return parsed.scheme == request_scheme and parsed.netloc == request.host

    @app.before_request
    def enforce_request_security():
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return None
        endpoint = request.endpoint or ""
        if endpoint.startswith("static"):
            return None

        origin = request.headers.get("Origin", "").strip()
        referer = request.headers.get("Referer", "").strip()
        if origin and not same_origin(origin):
            abort(403)
        if (not origin) and referer and not same_origin(referer):
            abort(403)

        content_type = (request.content_type or "").lower()
        requested_with = (request.headers.get("X-Requested-With", "") or "").strip().lower()
        requires_token = request.is_json or ("application/json" in content_type) or requested_with == "xmlhttprequest"
        if not requires_token:
            return None

        csrf_token = session.get("csrf_token", "")
        if not csrf_token:
            csrf_token = secrets.token_urlsafe(32)
            session["csrf_token"] = csrf_token

        sent_token = (request.headers.get("X-CSRF-Token", "") or request.form.get("csrf_token", "")).strip()
        if not sent_token or not secrets.compare_digest(sent_token, csrf_token):
            abort(403)
        return None

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'; "
            "img-src 'self' data: https:; "
            "media-src 'self' https: blob:; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline' https://www.youtube.com https://s.ytimg.com; "
            "frame-src 'self' https://www.youtube.com https://www.youtube-nocookie.com; "
            "connect-src 'self' https://www.youtube.com https://s.ytimg.com https://*.googlevideo.com;",
        )
        return response

    @app.context_processor
    def inject_global_data():
        csrf_token = session.get("csrf_token", "")
        if not csrf_token:
            csrf_token = secrets.token_urlsafe(32)
            session["csrf_token"] = csrf_token
        user = current_user()
        nav_playlists = []
        if user:
            user_oid = get_session_user_oid()
            nav_query = compose_and_filters({"user_id": user_oid}, youtube_playlist_visibility_clause()) or {"user_id": user_oid}
            raw = list(extensions.playlists_col.find(nav_query).sort("created_at", -1).limit(6))
            nav_playlists = [{"id": str(p["_id"]), "name": p.get("name") or t("defaults.unnamed")} for p in raw]
        return {
            "app_name": app.config["APP_NAME"],
            "current_user": user,
            "nav_playlists": nav_playlists,
            "current_lang": get_lang(),
            "t": t,
            "setup_required": not root_admin_exists(),
            "csrf_token": csrf_token,
        }

    return app


app = create_app()


if __name__ == "__main__":
    # Render fournit un port via la variable d'environnement PORT
    port = int(os.environ.get("PORT", 5000))
    # On force l'hôte à 0.0.0.0 pour être accessible de l'extérieur
    app.run(host="0.0.0.0", port=port)
