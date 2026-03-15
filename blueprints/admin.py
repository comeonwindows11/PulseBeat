import hashlib
import html
import os
import shutil
from datetime import datetime, timedelta
from math import ceil

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pymongo.errors import DuplicateKeyError, PyMongoError
from werkzeug.routing import BuildError
from werkzeug.security import check_password_hash, generate_password_hash

import extensions
from auth_helpers import (
    admin_required,
    cleanup_song,
    cleanup_user,
    compose_and_filters,
    get_database_audio_storage_settings,
    get_session_user_oid,
    is_youtube_integration_enabled,
    save_app_settings,
    normalize_email,
    normalize_username,
    notify_admins,
    parse_object_id,
    password_policy_ok,
    password_pwned_status,
    safe_mongo_update_one,
    send_email_message,
    username_policy_ok,
    user_choice_list,
    youtube_song_visibility_clause,
)
from i18n import tr

bp = Blueprint("admin", __name__, url_prefix="/admin")
PLATFORM_RESET_REQUEST_KEY = "platform_reset_request"


def create_audit_log(admin_user_id, action, target_type, target_id=None, details=None):
    extensions.admin_audit_col.insert_one(
        {
            "admin_user_id": admin_user_id,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "details": details or {},
            "created_at": datetime.utcnow(),
        }
    )


def _build_alert_key(prefix: str, status_doc: dict | None, primary_time_field: str = "updated_at") -> str:
    if not status_doc:
        return ""
    timestamp = status_doc.get(primary_time_field) or status_doc.get("updated_at") or status_doc.get("last_failed_at")
    if isinstance(timestamp, datetime):
        timestamp_text = timestamp.isoformat()
    else:
        timestamp_text = str(timestamp or "")
    return f"{prefix}:{timestamp_text}"


def _platform_reset_serializer():
    salt = current_app.config.get("PLATFORM_RESET_SALT", "pulsebeat-platform-reset")
    return URLSafeTimedSerializer(current_app.secret_key, salt=salt)


def _platform_reset_fingerprint(user, nonce: str):
    raw = "|".join(
        [
            str((user or {}).get("_id", "")),
            normalize_email((user or {}).get("email", "")),
            str((user or {}).get("password_hash", "")),
            str((user or {}).get("session_token_version", 0) or 0),
            str(nonce or ""),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _build_platform_reset_link(user, nonce: str):
    token = _platform_reset_serializer().dumps(
        {
            "uid": str((user or {}).get("_id", "")),
            "nonce": str(nonce or ""),
            "fp": _platform_reset_fingerprint(user, nonce),
        }
    )
    base_url = current_app.config.get("APP_BASE_URL", "").strip()
    if base_url:
        return f"{base_url.rstrip('/')}{url_for('admin.confirm_platform_reset', token=token)}"
    return url_for("admin.confirm_platform_reset", token=token, _external=True)


def _send_platform_reset_email(user, link: str):
    username = (user or {}).get("username", "admin")
    expires_minutes = max(1, int(current_app.config.get("PLATFORM_RESET_TOKEN_MAX_AGE", 1800) / 60))
    plain_text = (
        f"{tr('admin.reset_email_greeting', username=username)}\n\n"
        f"{tr('admin.reset_email_body')}\n{link}\n\n"
        f"{tr('admin.reset_email_expiry', minutes=expires_minutes)}\n\n"
        f"{tr('admin.reset_email_ignore')}"
    )
    html_body = f"""
<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#f4f6fb;font-family:Arial,Helvetica,sans-serif;color:#101828;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f4f6fb;padding:24px 0;">
      <tr>
        <td align="center">
          <table role="presentation" width="640" cellspacing="0" cellpadding="0" style="max-width:640px;width:100%;background:#ffffff;border-radius:14px;overflow:hidden;border:1px solid #e3eaf3;">
            <tr>
              <td style="background:linear-gradient(135deg,#ff8a1f,#ff4f4f);padding:20px 28px;color:#fff;font-size:22px;font-weight:700;">PulseBeat</td>
            </tr>
            <tr>
              <td style="padding:28px;">
                <h1 style="margin:0 0 14px 0;font-size:22px;line-height:1.3;color:#101828;">{html.escape(tr('admin.reset_email_subject'))}</h1>
                <p style="margin:0 0 12px 0;font-size:15px;line-height:1.6;">{html.escape(tr('admin.reset_email_greeting', username=username))}</p>
                <p style="margin:0 0 18px 0;font-size:15px;line-height:1.6;">{html.escape(tr('admin.reset_email_body'))}</p>
                <p style="margin:0 0 22px 0;">
                  <a href="{html.escape(link)}" style="display:inline-block;background:#dc2626;color:#ffffff;text-decoration:none;padding:12px 18px;border-radius:10px;font-size:14px;font-weight:700;">{html.escape(tr('admin.reset_email_cta'))}</a>
                </p>
                <p style="margin:0 0 8px 0;font-size:13px;line-height:1.5;color:#5b6472;">{html.escape(tr('admin.reset_email_expiry', minutes=expires_minutes))}</p>
                <p style="margin:0;font-size:13px;line-height:1.5;color:#5b6472;">{html.escape(tr('admin.reset_email_ignore'))}</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""
    return send_email_message((user or {}).get("email", ""), tr("admin.reset_email_subject"), plain_text, html_body)


def _queue_platform_reset_request(user):
    now = datetime.utcnow()
    expires_at = now + timedelta(seconds=int(current_app.config.get("PLATFORM_RESET_TOKEN_MAX_AGE", 1800) or 1800))
    nonce = os.urandom(24).hex()
    token_hash = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
    safe_mongo_update_one(
        extensions.users_col,
        {"_id": user.get("_id")},
        {"$set": {PLATFORM_RESET_REQUEST_KEY: {"token_hash": token_hash, "created_at": now, "expires_at": expires_at}}},
    )
    return _build_platform_reset_link(user, nonce)


def _load_platform_reset_request(token: str):
    max_age = int(current_app.config.get("PLATFORM_RESET_TOKEN_MAX_AGE", 1800))
    try:
        payload = _platform_reset_serializer().loads(token, max_age=max_age)
    except (SignatureExpired, BadSignature):
        return None, "", tr("flash.admin.reset_invalid")

    user_oid = parse_object_id(payload.get("uid", ""))
    nonce = str(payload.get("nonce", "") or "").strip()
    if not user_oid or not nonce:
        return None, "", tr("flash.admin.reset_invalid")

    user = extensions.users_col.find_one({"_id": user_oid})
    if not user or not user.get("is_root_admin", False):
        return None, "", tr("flash.admin.reset_invalid")

    if payload.get("fp") != _platform_reset_fingerprint(user, nonce):
        return None, "", tr("flash.admin.reset_invalid")

    request_doc = (user or {}).get(PLATFORM_RESET_REQUEST_KEY) or {}
    expires_at = request_doc.get("expires_at")
    if not request_doc or not isinstance(expires_at, datetime) or expires_at <= datetime.utcnow():
        return None, "", tr("flash.admin.reset_invalid")

    token_hash = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
    if str(request_doc.get("token_hash", "") or "") != token_hash:
        return None, "", tr("flash.admin.reset_invalid")

    return user, token_hash, ""


def _clear_platform_reset_request(user_oid):
    safe_mongo_update_one(extensions.users_col, {"_id": user_oid}, {"$unset": {PLATFORM_RESET_REQUEST_KEY: ""}})


def _remove_uploaded_audio_files():
    upload_dir = current_app.config.get("UPLOAD_DIR", "")
    if not upload_dir or not os.path.isdir(upload_dir):
        return
    for entry in os.scandir(upload_dir):
        if entry.is_file() or entry.is_symlink():
            os.unlink(entry.path)
        elif entry.is_dir():
            shutil.rmtree(entry.path)
    os.makedirs(upload_dir, exist_ok=True)


def _perform_platform_reset():
    _remove_uploaded_audio_files()
    extensions.mongo_client.drop_database(current_app.config["MONGO_DB_NAME"])


def _get_root_admin_or_redirect():
    admin_oid = get_session_user_oid()
    admin_user = extensions.users_col.find_one({"_id": admin_oid})
    if not admin_user or not admin_user.get("is_root_admin", False):
        flash(tr("flash.admin.only_root_settings"), "danger")
        return None
    return admin_user


def _email_in_use_anywhere(email: str) -> bool:
    normalized = normalize_email(email)
    if not normalized:
        return False
    return (
        extensions.users_col.find_one(
            {
                "$or": [
                    {"email_normalized": normalized},
                    {"backup_email_normalized": normalized},
                    {"pending_backup_email_normalized": normalized},
                    {"pending_email_change_normalized": normalized},
                ]
            },
            {"_id": 1},
        )
        is not None
    )


@bp.route("")
@admin_required
def dashboard():
    per_page = int(current_app.config.get("PAGE_SIZE", 50))
    users_page_raw = request.args.get("users_page", "1").strip()
    users_page = max(1, int(users_page_raw)) if users_page_raw.isdigit() else 1
    songs_page_raw = request.args.get("songs_page", "1").strip()
    songs_page = max(1, int(songs_page_raw)) if songs_page_raw.isdigit() else 1
    comments_page_raw = request.args.get("comments_page", "1").strip()
    comments_page = max(1, int(comments_page_raw)) if comments_page_raw.isdigit() else 1
    reports_page_raw = request.args.get("reports_page", "1").strip()
    reports_page = max(1, int(reports_page_raw)) if reports_page_raw.isdigit() else 1
    logs_page_raw = request.args.get("logs_page", "1").strip()
    logs_page = max(1, int(logs_page_raw)) if logs_page_raw.isdigit() else 1

    users_total = extensions.users_col.count_documents({})
    users_pages = max(1, ceil(users_total / per_page)) if users_total else 1
    users_page = min(users_page, users_pages)
    users = list(extensions.users_col.find().sort("created_at", -1).skip((users_page - 1) * per_page).limit(per_page))

    songs_query = compose_and_filters({}, youtube_song_visibility_clause()) or {}
    songs_total = extensions.songs_col.count_documents(songs_query)
    songs_pages = max(1, ceil(songs_total / per_page)) if songs_total else 1
    songs_page = min(songs_page, songs_pages)
    songs = list(
        extensions.songs_col.find(songs_query).sort("created_at", -1).skip((songs_page - 1) * per_page).limit(per_page)
    )

    comments_total = extensions.song_comments_col.count_documents({})
    comments_pages = max(1, ceil(comments_total / per_page)) if comments_total else 1
    comments_page = min(comments_page, comments_pages)
    comments = list(
        extensions.song_comments_col.find().sort("created_at", -1).skip((comments_page - 1) * per_page).limit(per_page)
    )

    reports_total = extensions.song_reports_col.count_documents({"status": "open"})
    reports_pages = max(1, ceil(reports_total / per_page)) if reports_total else 1
    reports_page = min(reports_page, reports_pages)
    reports = list(
        extensions.song_reports_col.find({"status": "open"}).sort("created_at", -1).skip((reports_page - 1) * per_page).limit(per_page)
    )

    logs_total = extensions.admin_audit_col.count_documents({})
    logs_pages = max(1, ceil(logs_total / per_page)) if logs_total else 1
    logs_page = min(logs_page, logs_pages)
    logs = list(extensions.admin_audit_col.find().sort("created_at", -1).skip((logs_page - 1) * per_page).limit(per_page))

    me = extensions.users_col.find_one({"_id": get_session_user_oid()})
    password_check_status = extensions.system_status_col.find_one({"key": "password_leak_service"})
    moderation_status = extensions.system_status_col.find_one({"key": "auto_moderation"})
    password_alert_key = _build_alert_key("password_leak_service_down", password_check_status, primary_time_field="last_failed_at")
    moderation_alert_key = _build_alert_key("auto_moderation_alert", moderation_status)
    dismissed_admin_alerts = {
        value.strip()
        for value in (me or {}).get("dismissed_admin_alerts", [])
        if isinstance(value, str) and value.strip()
    }
    show_password_alert = bool(
        password_check_status
        and password_check_status.get("status") == "down"
        and password_alert_key
        and password_alert_key not in dismissed_admin_alerts
    )
    show_moderation_alert = bool(
        moderation_status
        and moderation_status.get("status") == "alert"
        and moderation_alert_key
        and moderation_alert_key not in dismissed_admin_alerts
    )
    weak_recovery_accounts_count = extensions.users_col.count_documents(
        {
            "auth_provider": {"$ne": "google"},
            "$and": [
                {"$or": [{"two_factor_enabled": False}, {"two_factor_enabled": {"$exists": False}}]},
                {
                    "$or": [
                        {"backup_email_verified": False},
                        {"backup_email_verified": {"$exists": False}},
                        {"backup_email_normalized": ""},
                        {"backup_email_normalized": {"$exists": False}},
                    ]
                },
            ],
        }
    )
    youtube_integration_enabled = is_youtube_integration_enabled(True)
    try:
        youtube_toggle_url = url_for("admin.set_youtube_toggle")
    except BuildError:
        youtube_toggle_url = ""
    database_audio_settings = get_database_audio_storage_settings()
    database_audio_enabled = bool(database_audio_settings.get("enabled", False))
    database_audio_allowed_user_ids = [
        parse_object_id(value) for value in database_audio_settings.get("allowed_user_ids", [])
    ]
    database_audio_allowed_user_ids = [value for value in database_audio_allowed_user_ids if value]
    database_audio_allowed_users = []
    if database_audio_allowed_user_ids:
        users_by_id = {
            row["_id"]: row
            for row in extensions.users_col.find(
                {"_id": {"$in": database_audio_allowed_user_ids}},
                {"username": 1, "email": 1},
            )
        }
        for raw_value in database_audio_settings.get("allowed_user_ids", []):
            oid = parse_object_id(raw_value)
            if oid and oid in users_by_id:
                row = users_by_id[oid]
                database_audio_allowed_users.append(
                    {
                        "id": str(oid),
                        "username": row.get("username", "user"),
                        "email": row.get("email", ""),
                    }
                )
    database_audio_settings_url = url_for("admin.save_database_audio_storage_settings")

    return render_template(
        "admin/dashboard.jinja",
        users=users,
        songs=songs,
        comments=comments,
        reports=reports,
        audit_logs=logs,
        users_page=users_page,
        users_pages=users_pages,
        songs_page=songs_page,
        songs_pages=songs_pages,
        comments_page=comments_page,
        comments_pages=comments_pages,
        reports_page=reports_page,
        reports_pages=reports_pages,
        logs_page=logs_page,
        logs_pages=logs_pages,
        now=datetime.utcnow(),
        me=me,
        password_check_status=password_check_status,
        moderation_status=moderation_status,
        password_alert_key=password_alert_key,
        moderation_alert_key=moderation_alert_key,
        show_password_alert=show_password_alert,
        show_moderation_alert=show_moderation_alert,
        weak_recovery_accounts_count=weak_recovery_accounts_count,
        youtube_integration_enabled=youtube_integration_enabled,
        youtube_toggle_url=youtube_toggle_url,
        database_audio_enabled=database_audio_enabled,
        database_audio_allowed_users=database_audio_allowed_users,
        database_audio_settings_url=database_audio_settings_url,
        admin_user_picker_choices=user_choice_list(),
    )


@bp.route("/youtube-toggle", methods=["POST"])
@admin_required
def set_youtube_toggle():
    admin_user = _get_root_admin_or_redirect()
    if not admin_user:
        return redirect(url_for("admin.dashboard"))
    admin_oid = admin_user["_id"]

    enabled = request.form.get("enable_youtube_integration", "0") == "1"
    save_app_settings({"enable_youtube_integration": enabled})
    create_audit_log(
        admin_oid,
        "toggle_youtube_integration",
        "app_settings",
        "global",
        {"enable_youtube_integration": enabled},
    )
    flash(tr("flash.admin.youtube_settings_saved_enabled" if enabled else "flash.admin.youtube_settings_saved_disabled"), "success")
    return redirect(url_for("admin.dashboard"))


@bp.route("/database-audio-storage", methods=["POST"])
@admin_required
def save_database_audio_storage_settings():
    admin_oid = get_session_user_oid()
    enabled = request.form.get("enable_database_audio_storage", "0") == "1"
    raw_ids = request.form.getlist("database_audio_storage_allowed_user_ids")
    allowed_ids = []
    for raw_id in raw_ids:
        oid = parse_object_id(raw_id)
        if oid:
            allowed_ids.append(str(oid))
    allowed_ids = list(dict.fromkeys(allowed_ids))
    save_app_settings(
        {
            "enable_database_audio_storage": enabled,
            "database_audio_storage_allowed_user_ids": allowed_ids,
        }
    )
    create_audit_log(
        admin_oid,
        "save_database_audio_storage_settings",
        "app_settings",
        "global",
        {
            "enable_database_audio_storage": enabled,
            "allowed_user_count": len(allowed_ids),
        },
    )
    flash(tr("flash.admin.database_audio_settings_saved"), "success")
    return redirect(url_for("admin.dashboard"))


@bp.route("/reset/request", methods=["POST"])
@admin_required
def request_platform_reset():
    admin_user = _get_root_admin_or_redirect()
    if not admin_user:
        return redirect(url_for("admin.dashboard"))

    if str(admin_user.get("auth_provider", "local") or "local").strip().lower() == "google":
        flash(tr("flash.admin.reset_local_only"), "danger")
        return redirect(url_for("admin.dashboard"))

    password = request.form.get("current_password", "")
    if not password or not check_password_hash(str(admin_user.get("password_hash", "")), password):
        flash(tr("flash.admin.reset_password_invalid"), "danger")
        return redirect(url_for("admin.dashboard"))

    try:
        reset_link = _queue_platform_reset_request(admin_user)
        if not _send_platform_reset_email(admin_user, reset_link):
            _clear_platform_reset_request(admin_user["_id"])
            flash(tr("flash.admin.reset_email_failed"), "danger")
            return redirect(url_for("admin.dashboard"))
    except Exception as exc:
        current_app.logger.exception("Unable to queue platform reset", exc_info=exc)
        _clear_platform_reset_request(admin_user["_id"])
        flash(tr("flash.admin.reset_email_failed"), "danger")
        return redirect(url_for("admin.dashboard"))

    create_audit_log(admin_user["_id"], "request_platform_reset", "platform", "global")
    flash(tr("flash.admin.reset_email_sent"), "warning")
    return redirect(url_for("admin.dashboard"))


@bp.route("/reset/confirm/<token>", methods=["GET"])
def confirm_platform_reset(token):
    user, _token_hash, error = _load_platform_reset_request(token)
    if error:
        flash(error, "danger")
        return redirect(url_for("accounts.login"))

    return render_template(
        "admin/reset_confirm.jinja",
        reset_token=token,
        reset_owner={"username": user.get("username", "admin"), "email": user.get("email", "")},
    )


@bp.route("/reset/cancel/<token>", methods=["POST"])
def cancel_platform_reset(token):
    user, _token_hash, error = _load_platform_reset_request(token)
    if error:
        flash(error, "danger")
        return redirect(url_for("accounts.login"))

    _clear_platform_reset_request(user["_id"])
    create_audit_log(user["_id"], "cancel_platform_reset", "platform", "global")
    flash(tr("flash.admin.reset_cancelled"), "info")
    return redirect(url_for("admin.dashboard"))


@bp.route("/reset/execute/<token>", methods=["POST"])
def execute_platform_reset(token):
    user, token_hash, error = _load_platform_reset_request(token)
    if error:
        return jsonify({"ok": False, "message": error}), 400

    consume_result = safe_mongo_update_one(
        extensions.users_col,
        {"_id": user["_id"], f"{PLATFORM_RESET_REQUEST_KEY}.token_hash": token_hash},
        {"$unset": {PLATFORM_RESET_REQUEST_KEY: ""}},
    )
    if not consume_result or int(getattr(consume_result, "matched_count", 0) or 0) <= 0:
        return jsonify({"ok": False, "message": tr("flash.admin.reset_invalid")}), 409

    try:
        current_app.logger.warning("PulseBeat platform reset triggered by root admin %s", user.get("email", "unknown"))
        _perform_platform_reset()
        session.clear()
        return jsonify({"ok": True, "message": tr("admin.reset_complete_body")})
    except PyMongoError as exc:
        current_app.logger.exception("Database reset failed", exc_info=exc)
    except OSError as exc:
        current_app.logger.exception("File cleanup failed during platform reset", exc_info=exc)
    except Exception as exc:
        current_app.logger.exception("Unexpected platform reset failure", exc_info=exc)

    return jsonify({"ok": False, "message": tr("admin.reset_execute_failed")}), 500


@bp.route("/create-admin", methods=["POST"])
@admin_required
def create_admin():
    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")
    if not username or not email or not password:
        flash(tr("flash.accounts.fields_required"), "danger")
        return redirect(url_for("admin.dashboard"))
    email = normalize_email(email)
    if not username_policy_ok(username):
        flash(tr("flash.accounts.username_invalid"), "danger")
        return redirect(url_for("admin.dashboard"))
    if extensions.users_col.find_one({"username_normalized": normalize_username(username)}):
        flash(tr("flash.accounts.username_exists"), "danger")
        return redirect(url_for("admin.dashboard"))
    if password != confirm_password:
        flash(tr("flash.accounts.password_mismatch"), "danger")
        return redirect(url_for("admin.dashboard"))
    if not password_policy_ok(password):
        flash(tr("flash.accounts.password_policy_invalid"), "danger")
        return redirect(url_for("admin.dashboard"))

    status, _count = password_pwned_status(password, timeout_seconds=10)
    if status == "pwned":
        flash(tr("flash.accounts.password_compromised"), "danger")
        return redirect(url_for("admin.dashboard"))
    if _email_in_use_anywhere(email):
        flash(tr("flash.accounts.email_exists"), "danger")
        return redirect(url_for("admin.dashboard"))

    try:
        user_id = extensions.users_col.insert_one(
            {
                "username": username,
                "username_normalized": normalize_username(username),
                "email": email,
                "email_normalized": normalize_email(email),
                "password_hash": generate_password_hash(password),
                "is_admin": True,
                "is_root_admin": False,
                "require_password_change": False,
                "auth_provider": "local",
                "email_verified": True,
                "email_verified_at": datetime.utcnow(),
                "email_verification_sent_at": None,
                "two_factor_enabled": False,
                "two_factor_email_enabled": False,
                "two_factor_totp_enabled": False,
                "two_factor_totp_secret": "",
                "two_factor_totp_pending_secret": "",
                "two_factor_totp_pending_created_at": None,
                "two_factor_preferred_method": "",
                "two_factor_prompt_pending": True,
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
                "created_at": datetime.utcnow(),
            }
        ).inserted_id
    except DuplicateKeyError:
        if extensions.users_col.find_one({"username_normalized": normalize_username(username)}):
            flash(tr("flash.accounts.username_exists"), "danger")
        else:
            flash(tr("flash.accounts.email_exists"), "danger")
        return redirect(url_for("admin.dashboard"))
    except PyMongoError:
        current_app.logger.warning("Unable to create admin account", exc_info=True)
        flash(tr("errors.503.msg"), "warning")
        return redirect(url_for("admin.dashboard"))
    create_audit_log(get_session_user_oid(), "create_admin", "user", user_id, {"email": email})
    flash(tr("flash.admin.created"), "success")
    return redirect(url_for("admin.dashboard"))


@bp.route("/user/<user_id>/delete", methods=["POST"])
@admin_required
def delete_user(user_id):
    user_oid = parse_object_id(user_id)
    delete_songs = request.form.get("delete_songs", "yes") == "yes"
    if not user_oid:
        flash(tr("flash.songs.invalid_request"), "danger")
        return redirect(url_for("admin.dashboard"))

    actor_oid = get_session_user_oid()
    actor = extensions.users_col.find_one({"_id": actor_oid})
    target = extensions.users_col.find_one({"_id": user_oid})
    if not target:
        flash(tr("flash.songs.invalid_request"), "danger")
        return redirect(url_for("admin.dashboard"))

    if target.get("is_root_admin", False):
        flash(tr("flash.admin.root_admin_delete_forbidden"), "danger")
        return redirect(url_for("admin.dashboard"))

    if target.get("is_admin", False) and not actor.get("is_root_admin", False):
        flash(tr("flash.admin.only_root_can_delete_admin"), "danger")
        return redirect(url_for("admin.dashboard"))

    deleted = cleanup_user(user_oid, delete_songs=delete_songs)
    if not deleted:
        flash(tr("flash.admin.root_admin_delete_forbidden"), "danger")
        return redirect(url_for("admin.dashboard"))

    create_audit_log(actor_oid, "delete_user", "user", user_oid, {"delete_songs": delete_songs})
    flash(tr("flash.admin.user_deleted"), "success")
    return redirect(url_for("admin.dashboard"))


@bp.route("/user/<user_id>/ban", methods=["POST"])
@admin_required
def ban_user(user_id):
    user_oid = parse_object_id(user_id)
    days_raw = request.form.get("days", "7").strip()
    if not user_oid or not days_raw.isdigit():
        flash(tr("flash.songs.invalid_request"), "danger")
        return redirect(url_for("admin.dashboard"))
    target = extensions.users_col.find_one({"_id": user_oid})
    if target and target.get("is_root_admin", False):
        flash(tr("flash.admin.root_admin_ban_forbidden"), "danger")
        return redirect(url_for("admin.dashboard"))

    days = max(1, min(int(days_raw), 365))
    banned_until = datetime.utcnow() + timedelta(days=days)
    extensions.users_col.update_one({"_id": user_oid}, {"$set": {"banned_until": banned_until}})
    create_audit_log(get_session_user_oid(), "ban_user", "user", user_oid, {"days": days})
    flash(tr("flash.admin.user_banned"), "success")
    return redirect(url_for("admin.dashboard"))


@bp.route("/user/<user_id>/unban", methods=["POST"])
@admin_required
def unban_user(user_id):
    user_oid = parse_object_id(user_id)
    if not user_oid:
        flash(tr("flash.songs.invalid_request"), "danger")
        return redirect(url_for("admin.dashboard"))
    target = extensions.users_col.find_one({"_id": user_oid})
    if target and target.get("is_root_admin", False):
        flash(tr("flash.admin.root_admin_ban_forbidden"), "danger")
        return redirect(url_for("admin.dashboard"))

    extensions.users_col.update_one({"_id": user_oid}, {"$unset": {"banned_until": ""}})
    create_audit_log(get_session_user_oid(), "unban_user", "user", user_oid)
    flash(tr("flash.admin.user_unbanned"), "success")
    return redirect(url_for("admin.dashboard"))


@bp.route("/comment/<comment_id>/delete", methods=["POST"])
@admin_required
def delete_comment(comment_id):
    comment_oid = parse_object_id(comment_id)
    if not comment_oid:
        flash(tr("flash.songs.invalid_request"), "danger")
        return redirect(url_for("admin.dashboard"))
    comment = extensions.song_comments_col.find_one({"_id": comment_oid})
    if comment:
        rows = list(extensions.song_comments_col.find({"$or": [{"_id": comment_oid}, {"parent_comment_id": comment_oid}]}, {"_id": 1}))
        ids = [r.get("_id") for r in rows if r.get("_id")]
        extensions.song_comments_col.delete_many({"$or": [{"_id": comment_oid}, {"parent_comment_id": comment_oid}]})
        if ids and getattr(extensions, "comment_votes_col", None) is not None:
            extensions.comment_votes_col.delete_many({"comment_id": {"$in": ids}})
        create_audit_log(get_session_user_oid(), "delete_comment", "comment", comment_oid)
    flash(tr("flash.admin.comment_deleted"), "success")
    return redirect(url_for("admin.dashboard"))


@bp.route("/report/<report_id>/resolve", methods=["POST"])
@admin_required
def resolve_report(report_id):
    report_oid = parse_object_id(report_id)
    action = request.form.get("action", "resolve_only")
    if not report_oid:
        flash(tr("flash.songs.invalid_request"), "danger")
        return redirect(url_for("admin.dashboard"))

    report = extensions.song_reports_col.find_one({"_id": report_oid})
    if not report:
        flash(tr("flash.admin.report_not_found"), "danger")
        return redirect(url_for("admin.dashboard"))

    if action == "delete_song" and report.get("target_song_id"):
        song = extensions.songs_col.find_one({"_id": report.get("target_song_id")})
        if song:
            cleanup_song(song)
    if action == "delete_comment" and report.get("target_comment_id"):
        rows = list(
            extensions.song_comments_col.find(
                {"$or": [{"_id": report.get("target_comment_id")}, {"parent_comment_id": report.get("target_comment_id")}]},
                {"_id": 1},
            )
        )
        ids = [r.get("_id") for r in rows if r.get("_id")]
        extensions.song_comments_col.delete_many(
            {"$or": [{"_id": report.get("target_comment_id")}, {"parent_comment_id": report.get("target_comment_id")}]}
        )
        if ids and getattr(extensions, "comment_votes_col", None) is not None:
            extensions.comment_votes_col.delete_many({"comment_id": {"$in": ids}})

    extensions.song_reports_col.update_one(
        {"_id": report_oid},
        {
            "$set": {
                "status": "resolved",
                "resolved_at": datetime.utcnow(),
                "resolved_by": get_session_user_oid(),
                "resolution_action": action,
            }
        },
    )
    create_audit_log(get_session_user_oid(), "resolve_report", "report", report_oid, {"action": action})
    flash(tr("flash.admin.report_resolved"), "success")
    return redirect(url_for("admin.dashboard"))


@bp.route("/report/<report_id>/dismiss", methods=["POST"])
@admin_required
def dismiss_report(report_id):
    report_oid = parse_object_id(report_id)
    if not report_oid:
        flash(tr("flash.songs.invalid_request"), "danger")
        return redirect(url_for("admin.dashboard"))
    extensions.song_reports_col.update_one(
        {"_id": report_oid},
        {
            "$set": {
                "status": "dismissed",
                "resolved_at": datetime.utcnow(),
                "resolved_by": get_session_user_oid(),
            }
        },
    )
    create_audit_log(get_session_user_oid(), "dismiss_report", "report", report_oid)
    flash(tr("flash.admin.report_dismissed"), "success")
    return redirect(url_for("admin.dashboard"))


@bp.route("/alerts/dismiss", methods=["POST"])
@admin_required
def dismiss_dashboard_alert():
    payload = request.get_json(silent=True) or {}
    alert_key = str(payload.get("alert_key", "")).strip()
    if not alert_key:
        return jsonify({"ok": False, "message": tr("flash.songs.invalid_request")}), 400

    admin_oid = get_session_user_oid()
    extensions.users_col.update_one(
        {"_id": admin_oid},
        {"$addToSet": {"dismissed_admin_alerts": alert_key}},
    )
    create_audit_log(admin_oid, "dismiss_dashboard_alert", "dashboard_alert", details={"alert_key": alert_key})
    return jsonify({"ok": True})


@bp.route("/alerts/restore", methods=["POST"])
@admin_required
def restore_dashboard_alert():
    payload = request.get_json(silent=True) or {}
    alert_key = str(payload.get("alert_key", "")).strip()
    if not alert_key:
        return jsonify({"ok": False, "message": tr("flash.songs.invalid_request")}), 400

    admin_oid = get_session_user_oid()
    extensions.users_col.update_one(
        {"_id": admin_oid},
        {"$pull": {"dismissed_admin_alerts": alert_key}},
    )
    create_audit_log(admin_oid, "restore_dashboard_alert", "dashboard_alert", details={"alert_key": alert_key})
    return jsonify({"ok": True})
