import hashlib
import os
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for
from dotenv import load_dotenv
from pymongo.errors import PyMongoError

import extensions
from server_cache import init_server_cache, prune_server_cache
from auth_helpers import (
    InvalidStoredDocumentError,
    apply_session_security_cookies,
    compose_and_filters,
    count_unread_notifications,
    current_user,
    ensure_request_device_id,
    get_user_notifications,
    get_session_user_oid,
    normalize_email,
    normalize_username,
    safe_mongo_update_one,
    validate_or_purge_document,
    validate_bound_session_request,
    youtube_playlist_visibility_clause,
)
from blueprints.accounts import bp as accounts_bp, start_external_import_scheduler
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

    handled_codes = [400, 401, 403, 404, 405, 408, 413, 418, 422, 429, 500, 501, 502, 503, 504]
    for code in handled_codes:
        app.register_error_handler(code, make_handler(code))

    @app.errorhandler(InvalidStoredDocumentError)
    def handle_invalid_document_error(error):
        app.logger.warning(
            "Invalid stored document reached request boundary (collection=%s, document_id=%s, reason=%s)",
            getattr(error, "collection_name", "unknown"),
            getattr(error, "document_id", ""),
            getattr(error, "reason", "invalid_document"),
        )
        requested_with = (request.headers.get("X-Requested-With") or "").strip().lower()
        accept = (request.headers.get("Accept") or "").lower()
        wants_json = request.is_json or requested_with == "xmlhttprequest" or "application/json" in accept
        if wants_json:
            return jsonify({"ok": False, "message": t("errors.422.msg")}), 422
        return render_template("errors/base_error.jinja", error=error, error_code=422), 422

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


def _dino_actor_identity():
    user = current_user()
    if user:
        return {
            "owner_key": f"user:{user.get('_id')}",
            "actor_type": "user",
            "user_id": user.get("_id"),
            "display_name": str(user.get("username") or user.get("email") or "PulseBeat user"),
            "guest_code": "",
        }

    device_id = ensure_request_device_id()
    guest_digest = hashlib.sha256((device_id or "").encode("utf-8")).hexdigest()
    guest_code = guest_digest[:6].upper() or "GUEST"
    return {
        "owner_key": f"guest:{guest_digest}",
        "actor_type": "guest",
        "user_id": None,
        "display_name": "",
        "guest_code": guest_code,
    }


def _serialize_dino_entry(entry):
    actor_type = str(entry.get("actor_type") or "guest")
    if actor_type == "user" and str(entry.get("display_name") or "").strip():
        name = str(entry.get("display_name") or "").strip()
    else:
        name = f"{t('errors.easter_egg_guest_label')} {str(entry.get('guest_code') or 'GUEST').upper()}"
    return {
        "name": name,
        "score": int(entry.get("best_score", 0) or 0),
        "updated_at": entry.get("updated_at").isoformat() if entry.get("updated_at") else "",
    }


def get_dino_leaderboard_snapshot():
    projection = {"best_score": 1, "display_name": 1, "actor_type": 1, "guest_code": 1, "updated_at": 1}
    players = [
        row
        for row in (
            validate_or_purge_document("dino_leaderboard", item, context="app.get_dino_leaderboard_snapshot.players")
            for item in extensions.dino_leaderboard_col.find({"is_robot": False}, projection)
            .sort([("best_score", -1), ("updated_at", 1), ("_id", 1)])
            .limit(3)
        )
        if row
    ]
    robots = [
        row
        for row in (
            validate_or_purge_document("dino_leaderboard", item, context="app.get_dino_leaderboard_snapshot.robots")
            for item in extensions.dino_leaderboard_col.find({"is_robot": True}, projection)
            .sort([("best_score", -1), ("updated_at", 1), ("_id", 1)])
            .limit(3)
        )
        if row
    ]
    return {
        "players": [_serialize_dino_entry(row) for row in players],
        "robots": [_serialize_dino_entry(row) for row in robots],
    }


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
        docs = [
            item
            for item in (
                validate_or_purge_document("listening_history", doc, context="app._dedupe_listening_history")
                for doc in docs
            )
            if item
        ]
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
    os.makedirs(app.instance_path, exist_ok=True)
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
    app.config["TWO_FACTOR_TOTP_PENDING_MAX_AGE"] = int(os.getenv("TWO_FACTOR_TOTP_PENDING_MAX_AGE", "900"))
    app.config["PLATFORM_RESET_TOKEN_MAX_AGE"] = int(os.getenv("PLATFORM_RESET_TOKEN_MAX_AGE", "1800"))
    app.config["PLATFORM_RESET_SALT"] = os.getenv("PLATFORM_RESET_SALT", "pulsebeat-platform-reset")
    app.config["DEVICE_COOKIE_NAME"] = os.getenv("DEVICE_COOKIE_NAME", "pulsebeat_device_id")
    app.config["DEVICE_COOKIE_MAX_AGE"] = int(os.getenv("DEVICE_COOKIE_MAX_AGE", str(365 * 24 * 3600)))
    app.config["DEVICE_APPROVAL_TOKEN_MAX_AGE"] = int(os.getenv("DEVICE_APPROVAL_TOKEN_MAX_AGE", "1800"))
    app.config["DEVICE_APPROVAL_SALT"] = os.getenv("DEVICE_APPROVAL_SALT", "pulsebeat-device-approval")
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
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=max(1, int(os.getenv("REMEMBER_ME_SESSION_DAYS", "30"))))
    app.config["JS_SERVE_OBFUSCATED"] = os.getenv("JS_SERVE_OBFUSCATED", "1") == "1"
    app.config["SERVER_CACHE_DIR"] = os.getenv("SERVER_CACHE_DIR", os.path.join(app.instance_path, "server_cache"))
    app.config["SERVER_CACHE_JSON_MAX_BYTES"] = int(os.getenv("SERVER_CACHE_JSON_MAX_BYTES", str(20 * 1024 * 1024)))
    app.config["SERVER_CACHE_JSON_MAX_FILES"] = int(os.getenv("SERVER_CACHE_JSON_MAX_FILES", "500"))
    app.config["PUBLIC_PROFILE_CACHE_TTL_SECONDS"] = int(os.getenv("PUBLIC_PROFILE_CACHE_TTL_SECONDS", "180"))
    app.config["PUBLIC_PLAYLIST_CACHE_TTL_SECONDS"] = int(os.getenv("PUBLIC_PLAYLIST_CACHE_TTL_SECONDS", "180"))
    app.config["POPULAR_PUBLIC_SONGS_CACHE_TTL_SECONDS"] = int(os.getenv("POPULAR_PUBLIC_SONGS_CACHE_TTL_SECONDS", "180"))
    app.config["YOUTUBE_AUDIO_CACHE_ENABLED"] = os.getenv("YOUTUBE_AUDIO_CACHE_ENABLED", "1") == "1"
    app.config["YOUTUBE_AUDIO_CACHE_MAX_BYTES"] = int(os.getenv("YOUTUBE_AUDIO_CACHE_MAX_BYTES", str(512 * 1024 * 1024)))
    app.config["YOUTUBE_AUDIO_CACHE_MAX_FILES"] = int(os.getenv("YOUTUBE_AUDIO_CACHE_MAX_FILES", "80"))

    extensions.init_mongo(app)
    init_server_cache(app)
    now = datetime.now(UTC)
    extensions.users_col.update_many({"email_verified": {"$exists": False}}, {"$set": {"email_verified": True, "email_verified_at": now}})
    extensions.users_col.update_many({"email_verification_sent_at": {"$exists": False}}, {"$set": {"email_verification_sent_at": None}})
    extensions.users_col.update_many({"backup_email": {"$exists": False}}, {"$set": {"backup_email": ""}})
    extensions.users_col.update_many({"backup_email_normalized": {"$exists": False}}, {"$set": {"backup_email_normalized": ""}})
    extensions.users_col.update_many({"backup_email_verified": {"$exists": False}}, {"$set": {"backup_email_verified": False}})
    extensions.users_col.update_many({"backup_email_verified_at": {"$exists": False}}, {"$set": {"backup_email_verified_at": None}})
    extensions.users_col.update_many({"backup_email_verification_sent_at": {"$exists": False}}, {"$set": {"backup_email_verification_sent_at": None}})
    extensions.users_col.update_many({"pending_backup_email": {"$exists": False}}, {"$set": {"pending_backup_email": ""}})
    extensions.users_col.update_many({"pending_backup_email_normalized": {"$exists": False}}, {"$set": {"pending_backup_email_normalized": ""}})
    extensions.users_col.update_many({"pending_backup_email_requested_at": {"$exists": False}}, {"$set": {"pending_backup_email_requested_at": None}})
    extensions.users_col.update_many({"pending_email_change": {"$exists": False}}, {"$set": {"pending_email_change": ""}})
    extensions.users_col.update_many({"pending_email_change_normalized": {"$exists": False}}, {"$set": {"pending_email_change_normalized": ""}})
    extensions.users_col.update_many({"pending_email_change_requested_at": {"$exists": False}}, {"$set": {"pending_email_change_requested_at": None}})
    extensions.users_col.update_many({"auth_provider": {"$exists": False}}, {"$set": {"auth_provider": "local"}})
    extensions.users_col.update_many(
        {"auth_provider": "google"},
        {
            "$set": {
                "require_password_change": False,
                "two_factor_enabled": False,
                "two_factor_email_enabled": False,
                "two_factor_totp_enabled": False,
                "two_factor_totp_secret": "",
                "two_factor_totp_pending_secret": "",
                "two_factor_totp_pending_created_at": None,
                "two_factor_preferred_method": "",
                "two_factor_prompt_pending": False,
                "backup_email": "",
                "backup_email_normalized": "",
                "backup_email_verified": False,
                "backup_email_verified_at": None,
                "backup_email_verification_sent_at": None,
                "pending_backup_email": "",
                "pending_backup_email_normalized": "",
                "pending_backup_email_requested_at": None,
                "pending_email_change": "",
                "pending_email_change_normalized": "",
                "pending_email_change_requested_at": None,
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
    extensions.users_col.update_many(
        {"two_factor_email_enabled": {"$exists": False}},
        [{"$set": {"two_factor_email_enabled": {"$ifNull": ["$two_factor_enabled", False]}}}],
    )
    extensions.users_col.update_many({"two_factor_totp_enabled": {"$exists": False}}, {"$set": {"two_factor_totp_enabled": False}})
    extensions.users_col.update_many({"two_factor_totp_secret": {"$exists": False}}, {"$set": {"two_factor_totp_secret": ""}})
    extensions.users_col.update_many({"two_factor_totp_pending_secret": {"$exists": False}}, {"$set": {"two_factor_totp_pending_secret": ""}})
    extensions.users_col.update_many({"two_factor_totp_pending_created_at": {"$exists": False}}, {"$set": {"two_factor_totp_pending_created_at": None}})
    extensions.users_col.update_many(
        {"two_factor_preferred_method": {"$exists": False}},
        [
            {
                "$set": {
                    "two_factor_preferred_method": {
                        "$cond": [
                            {"$eq": [{"$ifNull": ["$two_factor_enabled", False]}, True]},
                            "email",
                            "",
                        ]
                    }
                }
            }
        ],
    )
    extensions.users_col.update_many({"trusted_devices": {"$exists": False}}, {"$set": {"trusted_devices": []}})
    extensions.users_col.update_many({"active_sessions": {"$exists": False}}, {"$set": {"active_sessions": []}})
    extensions.users_col.update_many({"pending_device_approvals": {"$exists": False}}, {"$set": {"pending_device_approvals": []}})
    extensions.songs_col.update_many({"is_available": {"$exists": False}}, {"$set": {"is_available": True}})
    extensions.songs_col.update_many({"availability_reason": {"$exists": False}}, {"$set": {"availability_reason": ""}})
    extensions.songs_col.update_many({"storage_mode": {"$exists": False}}, {"$set": {"storage_mode": "server"}})
    extensions.songs_col.update_many({"gridfs_file_id": {"$exists": False}}, {"$set": {"gridfs_file_id": None}})
    extensions.songs_col.update_many({"audio_cache_status": {"$exists": False}}, {"$set": {"audio_cache_status": "server_only"}})
    extensions.songs_col.update_many({"audio_cache_error": {"$exists": False}}, {"$set": {"audio_cache_error": ""}})
    extensions.songs_col.update_many({"original_file_name": {"$exists": False}}, {"$set": {"original_file_name": ""}})
    extensions.songs_col.update_many({"audio_content_type": {"$exists": False}}, {"$set": {"audio_content_type": ""}})
    extensions.songs_col.update_many({"audio_file_size": {"$exists": False}}, {"$set": {"audio_file_size": 0}})
    for user in extensions.users_col.find({}, {"email": 1, "username": 1}):
        extensions.users_col.update_one(
            {"_id": user["_id"]},
            {"$set": {"email_normalized": normalize_email(user.get("email", "")), "username_normalized": normalize_username(user.get("username", ""))}},
        )
    extensions.users_col.create_index("email_normalized", unique=True, name="uniq_users_email_normalized")
    extensions.users_col.create_index("username_normalized", unique=True, name="uniq_users_username_normalized")
    extensions.songs_col.create_index("audio_fingerprint", name="idx_songs_audio_fingerprint")
    extensions.songs_col.create_index([("storage_mode", 1), ("created_at", -1)], name="idx_songs_storage_mode_created")
    extensions.songs_col.create_index([("gridfs_file_id", 1)], name="idx_songs_gridfs_file_id")
    extensions.songs_col.create_index([("audio_cache_status", 1), ("created_at", -1)], name="idx_songs_audio_cache_status_created")
    extensions.songs_col.create_index([("created_by", 1), ("created_at", -1)], name="idx_songs_creator_created")
    extensions.songs_col.create_index([("created_by", 1), ("visibility", 1), ("created_at", -1)], name="idx_songs_creator_visibility_created")
    extensions.playlists_col.create_index([("user_id", 1), ("updated_at", -1)], name="idx_playlists_user_updated")
    extensions.playlists_col.create_index([("user_id", 1), ("visibility", 1), ("updated_at", -1)], name="idx_playlists_user_visibility_updated")
    extensions.song_comments_col.create_index([("user_id", 1), ("created_at", -1)], name="idx_song_comments_user_created")
    extensions.external_integrations_col.create_index([("user_id", 1), ("provider", 1)], unique=True, name="uniq_ext_integration_user_provider")
    extensions.external_playlists_col.create_index(
        [("user_id", 1), ("provider", 1), ("external_playlist_id", 1)],
        unique=True,
        name="uniq_ext_playlist_user_provider_id",
    )
    extensions.external_playlists_col.create_index([("user_id", 1), ("synced_at", -1)], name="idx_ext_playlist_user_synced")
    extensions.external_import_jobs_col.create_index([("status", 1), ("created_at", 1)], name="idx_ext_import_jobs_status_created")
    extensions.external_import_jobs_col.create_index([("user_id", 1), ("updated_at", -1)], name="idx_ext_import_jobs_user_updated")
    extensions.external_import_jobs_col.create_index([("local_playlist_id", 1), ("updated_at", -1)], name="idx_ext_import_jobs_playlist_updated")
    extensions.data_exports_col.create_index([("user_id", 1), ("created_at", -1)], name="idx_data_exports_user_created")
    _ensure_unique_index_with_dedupe(
        extensions.creator_subscriptions_col,
        [("creator_id", 1), ("subscriber_id", 1)],
        "uniq_creator_subscription_pair",
        logger=app.logger,
    )
    extensions.creator_subscriptions_col.create_index([("creator_id", 1), ("created_at", -1)], name="idx_creator_subscriptions_creator_created")
    extensions.creator_subscriptions_col.create_index([("subscriber_id", 1), ("created_at", -1)], name="idx_creator_subscriptions_subscriber_created")
    _ensure_unique_index_with_dedupe(
        extensions.user_notifications_col,
        [("recipient_user_id", 1), ("notification_type", 1), ("content_type", 1), ("content_id", 1)],
        "uniq_user_notification_publication",
        logger=app.logger,
    )
    extensions.user_notifications_col.create_index([("recipient_user_id", 1), ("created_at", -1)], name="idx_user_notifications_recipient_created")
    extensions.user_notifications_col.create_index([("recipient_user_id", 1), ("is_read", 1), ("created_at", -1)], name="idx_user_notifications_recipient_read")
    _ensure_unique_index_with_dedupe(
        extensions.dino_leaderboard_col,
        [("owner_key", 1), ("is_robot", 1)],
        "uniq_dino_leaderboard_owner_mode",
        logger=app.logger,
    )
    extensions.dino_leaderboard_col.create_index([("is_robot", 1), ("best_score", -1), ("updated_at", 1)], name="idx_dino_leaderboard_mode_score")
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
    prune_server_cache(app)

    app.register_blueprint(accounts_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(songs_bp)
    app.register_blueprint(playlists_bp)
    register_error_handlers(app)
    start_external_import_scheduler(app)

    @app.route("/favicon.ico")
    def favicon():
        return ("", 204)

    @app.route("/dino")
    def dino_easter_egg():
        return render_template(
            "errors/easter_egg_teapot.jinja",
            error_code=418,
            dino_leaderboard=get_dino_leaderboard_snapshot(),
        ), 418

    @app.route("/dino/leaderboard", methods=["GET", "POST"])
    def dino_leaderboard_api():
        if request.method == "GET":
            return jsonify({"ok": True, **get_dino_leaderboard_snapshot()})

        payload = request.get_json(silent=True) or {}
        try:
            score = int(payload.get("score", 0) or 0)
        except (TypeError, ValueError):
            score = 0
        score = max(0, min(score, 10_000_000))
        if score <= 0:
            return jsonify({"ok": False, "message": t("errors.easter_egg_leaderboard_invalid_score")}), 400

        identity = _dino_actor_identity()
        is_robot = bool(payload.get("is_robot", False))
        now = datetime.now(UTC)
        existing = extensions.dino_leaderboard_col.find_one(
            {"owner_key": identity["owner_key"], "is_robot": is_robot},
            {"best_score": 1},
        )
        existing = validate_or_purge_document("dino_leaderboard", existing, context="app.dino_leaderboard_api.existing")
        existing_score = int((existing or {}).get("best_score", 0) or 0)

        update_doc = {
            "$setOnInsert": {
                "owner_key": identity["owner_key"],
                "actor_type": identity["actor_type"],
                "user_id": identity["user_id"],
                "guest_code": identity["guest_code"],
                "is_robot": is_robot,
                "created_at": now,
            },
            "$set": {
                "updated_at": now,
            },
        }
        if identity["display_name"]:
            update_doc["$set"]["display_name"] = identity["display_name"]
        if identity["guest_code"]:
            update_doc["$set"]["guest_code"] = identity["guest_code"]
        if score > existing_score:
            update_doc["$set"]["best_score"] = score
            update_doc["$set"]["best_score_at"] = now

        try:
            safe_mongo_update_one(
                extensions.dino_leaderboard_col,
                {"owner_key": identity["owner_key"], "is_robot": is_robot},
                update_doc,
                upsert=True,
                max_retries=3,
            )
        except PyMongoError:
            app.logger.exception("Failed to store dino leaderboard entry")
            return jsonify({"ok": False, "message": t("errors.503.msg")}), 503

        return jsonify({"ok": True, "improved": score > existing_score, **get_dino_leaderboard_snapshot()})

    @app.before_request
    def enforce_initial_setup_and_password_change():
        setup_done = root_admin_exists()
        endpoint = request.endpoint or ""
        if endpoint != "static" and not endpoint.startswith("static"):
            ensure_request_device_id()
        if not setup_done:
            allowed = {"accounts.setup_admin", "dino_easter_egg", "dino_leaderboard_api", "static"}
            if endpoint in allowed or endpoint.startswith("static"):
                return None
            return redirect(url_for("accounts.setup_admin"))

        user_oid = get_session_user_oid()
        if not user_oid:
            return None
        user = extensions.users_col.find_one(
            {"_id": user_oid},
            {
                "require_password_change": 1,
                "auth_provider": 1,
                "session_token_version": 1,
                "active_sessions": 1,
                "email": 1,
                "username": 1,
            },
        )
        user = validate_or_purge_document("users", user, context="app.enforce_initial_setup_and_password_change")
        session_version = int(session.get("session_token_version", -1))
        user_version = int((user or {}).get("session_token_version", 0) or 0)
        if not user or session_version != user_version:
            session.clear()
            if endpoint == "static" or endpoint.startswith("static"):
                return None
            if endpoint not in {"accounts.login", "accounts.google_login", "accounts.google_callback", "accounts.setup_admin", "dino_easter_egg", "dino_leaderboard_api", "static"} and not endpoint.startswith("static"):
                flash(t("flash.accounts.session_invalidated"), "warning")
            return redirect(url_for("accounts.login"))
        session_security_response = validate_bound_session_request(user)
        if session_security_response is not None:
            return session_security_response
        if not user or user.get("auth_provider") == "google" or not user.get("require_password_change", False):
            return None

        allowed_when_forced = {
            "accounts.manage_account",
            "accounts.change_password",
            "dino_easter_egg",
            "dino_leaderboard_api",
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
        response = apply_session_security_cookies(response)
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
        def client_js_asset(name: str):
            safe_name = (name or "").strip()
            if not safe_name:
                return ""
            obfuscated_filename = f"dist/{safe_name}.obf.js"
            source_filename = f"js/{safe_name}.js"
            obfuscated_path = os.path.join(app.static_folder, "dist", f"{safe_name}.obf.js")
            if app.config.get("JS_SERVE_OBFUSCATED", True) and os.path.exists(obfuscated_path):
                return obfuscated_filename
            return source_filename

        csrf_token = session.get("csrf_token", "")
        if not csrf_token:
            csrf_token = secrets.token_urlsafe(32)
            session["csrf_token"] = csrf_token
        user = current_user()
        nav_playlists = []
        header_notifications = []
        unread_notification_count = 0
        if user:
            user_oid = get_session_user_oid()
            nav_query = compose_and_filters({"user_id": user_oid}, youtube_playlist_visibility_clause()) or {"user_id": user_oid}
            raw = list(extensions.playlists_col.find(nav_query).sort("created_at", -1).limit(6))
            nav_playlists = [
                {"id": str(p["_id"]), "name": p.get("name") or t("defaults.unnamed")}
                for p in (
                    validate_or_purge_document("playlists", item, context="app.inject_global_data.nav_playlist")
                    for item in raw
                )
                if p
            ]
            unread_notification_count = count_unread_notifications(user_oid)
            header_notifications = get_user_notifications(user_oid, limit=20)
        return {
            "app_name": app.config["APP_NAME"],
            "current_user": user,
            "nav_playlists": nav_playlists,
            "header_notifications": header_notifications,
            "header_notifications_unread": unread_notification_count,
            "current_lang": get_lang(),
            "t": t,
            "setup_required": not root_admin_exists(),
            "csrf_token": csrf_token,
            "client_js_asset": client_js_asset,
        }

    return app


app = create_app()


if __name__ == "__main__":
    # Render fournit un port via la variable d'environnement PORT
    port = int(os.environ.get("PORT", 5000))
    # On force l'hôte à 0.0.0.0 pour être accessible de l'extérieur
    app.run(host="0.0.0.0", port=port)
