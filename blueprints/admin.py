from datetime import datetime, timedelta
from math import ceil

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from werkzeug.routing import BuildError
from werkzeug.security import generate_password_hash

import extensions
from auth_helpers import (
    admin_required,
    cleanup_song,
    cleanup_user,
    compose_and_filters,
    get_session_user_oid,
    is_youtube_integration_enabled,
    normalize_email,
    normalize_username,
    notify_admins,
    parse_object_id,
    password_policy_ok,
    password_pwned_status,
    save_app_settings,
    youtube_song_visibility_clause,
    username_policy_ok,
)
from i18n import tr

bp = Blueprint("admin", __name__, url_prefix="/admin")


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
    youtube_integration_enabled = is_youtube_integration_enabled(True)
    try:
        youtube_toggle_url = url_for("admin.set_youtube_toggle")
    except BuildError:
        youtube_toggle_url = ""

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
        youtube_integration_enabled=youtube_integration_enabled,
        youtube_toggle_url=youtube_toggle_url,
    )


@bp.route("/youtube-toggle", methods=["POST"])
@admin_required
def set_youtube_toggle():
    admin_oid = get_session_user_oid()
    admin_user = extensions.users_col.find_one({"_id": admin_oid}, {"is_root_admin": 1})
    if not admin_user or not admin_user.get("is_root_admin", False):
        flash(tr("flash.admin.only_root_settings"), "danger")
        return redirect(url_for("admin.dashboard"))

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
    if extensions.users_col.find_one({"email_normalized": normalize_email(email)}):
        flash(tr("flash.accounts.email_exists"), "danger")
        return redirect(url_for("admin.dashboard"))

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
            "two_factor_prompt_pending": True,
            "created_at": datetime.utcnow(),
        }
    ).inserted_id
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
