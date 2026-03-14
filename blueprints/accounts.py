import hashlib
import html
import io
import json
import secrets
import smtplib
import csv
import unicodedata
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime, timedelta
from email.message import EmailMessage
from math import ceil
from urllib.parse import urlencode

import re

import requests
from flask import Blueprint, Response, abort, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pymongo.errors import DuplicateKeyError, PyMongoError
from werkzeug.routing import BuildError
from werkzeug.security import check_password_hash, generate_password_hash

import extensions
from auth_helpers import (
    begin_authenticated_session,
    can_access_song,
    compose_and_filters,
    clear_current_session_binding,
    cleanup_song,
    cleanup_user,
    count_creator_subscribers,
    device_summary_text,
    get_creator_subscription,
    get_user_notifications,
    get_request_device_context,
    is_disposable_email,
    get_session_user_oid,
    is_email_verified,
    is_trusted_device,
    is_youtube_integration_enabled,
    is_user_banned,
    login_required,
    normalize_email,
    normalize_username,
    parse_object_id,
    password_policy_ok,
    password_pwned_status,
    list_creator_subscribers,
    mark_notifications_read,
    remember_trusted_device,
    safe_mongo_update_one,
    send_email_message,
    serialize_song,
    song_stream_url,
    visible_song_filter,
    username_policy_ok,
    youtube_playlist_visibility_clause,
)
from i18n import tr

bp = Blueprint("accounts", __name__)
IMPORT_EXECUTOR = ThreadPoolExecutor(max_workers=2)
TWO_FACTOR_CODE_LENGTH = 6
TWO_FACTOR_CODE_MAX_ATTEMPTS = 6


def _normalize_track_identity(value: str) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return ""
    raw = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    raw = re.sub(r"\s*\([^)]*\)", " ", raw)
    raw = re.sub(r"\s*\[[^\]]*\]", " ", raw)
    raw = re.sub(r"[^a-z0-9]+", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw


def root_admin_exists():
    return extensions.users_col.count_documents({"is_admin": True, "is_root_admin": True}, limit=1) > 0


def _build_user_export_payload(user_oid):
    user = extensions.users_col.find_one({"_id": user_oid}, {"password_hash": 0})
    if not user:
        return {}

    payload = {
        "generated_at": datetime.utcnow().isoformat(),
        "user": {
            "id": str(user.get("_id", "")),
            "username": user.get("username", ""),
            "email": user.get("email", ""),
            "is_admin": bool(user.get("is_admin", False)),
            "is_root_admin": bool(user.get("is_root_admin", False)),
            "auth_provider": user.get("auth_provider", "local"),
            "created_at": user.get("created_at").isoformat() if isinstance(user.get("created_at"), datetime) else None,
            "email_verified": bool(user.get("email_verified", False)),
        },
        "songs": [],
        "playlists": [],
        "history": [],
        "comments": [],
        "votes": [],
        "preferences": {
            "recommendation_blocked_song_ids": [str(v) for v in (user.get("recommendation_blocked_song_ids", []) or []) if v],
            "recommendation_blocked_artists": [str(v) for v in (user.get("recommendation_blocked_artists", []) or []) if v],
        },
    }

    for song in extensions.songs_col.find({"created_by": user_oid}).sort("created_at", -1):
        payload["songs"].append(
            {
                "id": str(song.get("_id", "")),
                "title": song.get("title", ""),
                "artist": song.get("artist", ""),
                "genre": song.get("genre", ""),
                "visibility": song.get("visibility", "public"),
                "source_type": song.get("source_type", ""),
                "created_at": song.get("created_at").isoformat() if isinstance(song.get("created_at"), datetime) else None,
                "updated_at": song.get("updated_at").isoformat() if isinstance(song.get("updated_at"), datetime) else None,
                "lyrics_source": song.get("lyrics_source", ""),
                "has_lyrics": bool(song.get("lyrics_text")),
            }
        )

    for playlist in extensions.playlists_col.find({"$or": [{"user_id": user_oid}, {"collaborator_ids": user_oid}]}).sort("updated_at", -1):
        payload["playlists"].append(
            {
                "id": str(playlist.get("_id", "")),
                "name": playlist.get("name", ""),
                "owner_id": str(playlist.get("user_id", "")),
                "is_owner": str(playlist.get("user_id", "")) == str(user_oid),
                "visibility": playlist.get("visibility", "private"),
                "song_ids": [str(v) for v in (playlist.get("song_ids", []) or []) if v],
                "collaborator_ids": [str(v) for v in (playlist.get("collaborator_ids", []) or []) if v],
                "created_at": playlist.get("created_at").isoformat() if isinstance(playlist.get("created_at"), datetime) else None,
                "updated_at": playlist.get("updated_at").isoformat() if isinstance(playlist.get("updated_at"), datetime) else None,
            }
        )

    for row in extensions.listening_history_col.find({"user_id": user_oid}).sort("updated_at", -1):
        payload["history"].append(
            {
                "song_id": str(row.get("song_id", "")),
                "play_count": int(row.get("play_count", 0) or 0),
                "last_position": float(row.get("last_position", 0) or 0),
                "last_duration": float(row.get("last_duration", 0) or 0),
                "updated_at": row.get("updated_at").isoformat() if isinstance(row.get("updated_at"), datetime) else None,
            }
        )

    for comment in extensions.song_comments_col.find({"user_id": user_oid}).sort("created_at", -1):
        payload["comments"].append(
            {
                "id": str(comment.get("_id", "")),
                "song_id": str(comment.get("song_id", "")),
                "parent_comment_id": str(comment.get("parent_comment_id", "")) if comment.get("parent_comment_id") else "",
                "content": comment.get("content", ""),
                "created_at": comment.get("created_at").isoformat() if isinstance(comment.get("created_at"), datetime) else None,
                "edited_at": comment.get("edited_at").isoformat() if isinstance(comment.get("edited_at"), datetime) else None,
            }
        )

    for vote in extensions.song_votes_col.find({"user_id": user_oid}).sort("updated_at", -1):
        payload["votes"].append(
            {
                "song_id": str(vote.get("song_id", "")),
                "vote": int(vote.get("vote", 0) or 0),
                "updated_at": vote.get("updated_at").isoformat() if isinstance(vote.get("updated_at"), datetime) else None,
            }
        )

    return payload


def _build_creator_stats(user_oid):
    song_rows = list(extensions.songs_col.find({"created_by": user_oid}, {"title": 1, "artist": 1}))
    if not song_rows:
        return {
            "song_count": 0,
            "total_plays": 0,
            "total_likes": 0,
            "total_dislikes": 0,
            "top_songs": [],
            "avg_plays_per_song": 0.0,
        }

    song_ids = [row.get("_id") for row in song_rows if row.get("_id")]
    song_map = {row.get("_id"): row for row in song_rows}

    history_rows = list(
        extensions.listening_history_col.aggregate(
            [
                {"$match": {"song_id": {"$in": song_ids}}},
                {"$group": {"_id": "$song_id", "plays": {"$sum": {"$ifNull": ["$play_count", 0]}}}},
            ]
        )
    )
    plays_map = {row.get("_id"): int(row.get("plays", 0) or 0) for row in history_rows}
    total_plays = sum(plays_map.values())

    likes_rows = list(
        extensions.song_votes_col.aggregate(
            [
                {"$match": {"song_id": {"$in": song_ids}, "vote": 1}},
                {"$group": {"_id": None, "count": {"$sum": 1}}},
            ]
        )
    )
    dislikes_rows = list(
        extensions.song_votes_col.aggregate(
            [
                {"$match": {"song_id": {"$in": song_ids}, "vote": -1}},
                {"$group": {"_id": None, "count": {"$sum": 1}}},
            ]
        )
    )
    total_likes = int((likes_rows[0].get("count", 0) if likes_rows else 0) or 0)
    total_dislikes = int((dislikes_rows[0].get("count", 0) if dislikes_rows else 0) or 0)

    ranked = sorted(song_ids, key=lambda sid: plays_map.get(sid, 0), reverse=True)[:10]
    top_songs = []
    for sid in ranked:
        meta = song_map.get(sid) or {}
        top_songs.append(
            {
                "id": str(sid),
                "title": meta.get("title", tr("defaults.untitled")),
                "artist": meta.get("artist", tr("defaults.unknown_artist")),
                "plays": int(plays_map.get(sid, 0) or 0),
                "detail_url": url_for("songs.song_detail", song_id=str(sid)),
            }
        )

    song_count = len(song_ids)
    avg_plays_per_song = (float(total_plays) / float(song_count)) if song_count else 0.0
    return {
        "song_count": song_count,
        "total_plays": int(total_plays),
        "total_likes": total_likes,
        "total_dislikes": total_dislikes,
        "top_songs": top_songs,
        "avg_plays_per_song": round(avg_plays_per_song, 2),
    }


def _login_lock_minutes(level: int) -> int:
    safe_level = max(1, int(level or 1))
    return 10 * (2 ** (safe_level - 1))


def _register_login_failure(user):
    if not user:
        return {"locked": False, "minutes": 0, "remaining_attempts": 0}

    now = datetime.utcnow()
    failures = int(user.get("login_failure_count", 0) or 0) + 1
    if failures >= 6:
        level = int(user.get("login_lock_level", 0) or 0) + 1
        minutes = _login_lock_minutes(level)
        lock_until = now + timedelta(minutes=minutes)
        safe_mongo_update_one(
            extensions.users_col,
            {"_id": user["_id"]},
            {
                "$set": {
                    "login_lock_level": level,
                    "login_lock_until": lock_until,
                    "login_failure_count": 0,
                }
            },
        )
        return {"locked": True, "minutes": minutes, "remaining_attempts": 0}

    remaining = max(0, 6 - failures)
    safe_mongo_update_one(
        extensions.users_col,
        {"_id": user["_id"]},
        {"$set": {"login_failure_count": failures}},
    )
    return {"locked": False, "minutes": 0, "remaining_attempts": remaining}


def _reset_login_lock(user_oid):
    safe_mongo_update_one(
        extensions.users_col,
        {"_id": user_oid},
        {
            "$set": {
                "login_failure_count": 0,
                "login_lock_level": 0,
                "login_lock_until": None,
            }
        },
    )


def _session_version(user) -> int:
    return int(user.get("session_token_version", 0) or 0)


def _bump_session_version(user_oid):
    safe_mongo_update_one(extensions.users_col, {"_id": user_oid}, {"$inc": {"session_token_version": 1}})


def _should_show_two_factor_prompt(user) -> bool:
    if not user:
        return False
    if user.get("auth_provider") == "google":
        return False
    if bool(user.get("two_factor_enabled", False)):
        return False
    return bool(user.get("two_factor_prompt_pending", False))


def _post_login_redirect(user):
    if _should_show_two_factor_prompt(user):
        return url_for("accounts.manage_account", two_factor_prompt="1")
    return url_for("main.index")


def _complete_login(user):
    try:
        begin_authenticated_session(user)
    except PyMongoError:
        current_app.logger.warning("Unable to finalize authenticated session", exc_info=True)
        session.clear()
        flash(tr("flash.accounts.session_security_retry"), "warning")
        return redirect(url_for("accounts.login"))
    flash(tr("flash.accounts.logged_in"), "success")
    return redirect(_post_login_redirect(user))


def find_user_by_email(email: str):
    normalized = normalize_email(email)
    if not normalized:
        return None
    return extensions.users_col.find_one({"email_normalized": normalized})


def find_user_by_username(username: str):
    normalized = normalize_username(username)
    if not normalized:
        return None
    return extensions.users_col.find_one({"username_normalized": normalized})


def find_user_by_login(identifier: str):
    raw = (identifier or "").strip()
    if not raw:
        return None
    if "@" in raw:
        return find_user_by_email(raw)
    return find_user_by_username(raw)


def validate_username_for_create(username: str):
    if not username_policy_ok(username):
        return False, tr("flash.accounts.username_invalid")
    if find_user_by_username(username):
        return False, tr("flash.accounts.username_exists")
    return True, ""


def build_google_username(name: str):
    base = re.sub(r"[^A-Za-z0-9_.-]+", "", (name or "").strip())
    if len(base) < 3:
        base = "GoogleUser"
    base = base[:24]
    candidate = base
    suffix = 1
    while find_user_by_username(candidate):
        suffix += 1
        candidate = f"{base[: max(1, 24 - len(str(suffix)))]}{suffix}"
    return candidate


def validate_password_for_set(password: str, confirm_password: str, allow_unavailable=True):
    if password != confirm_password:
        return False, tr("flash.accounts.password_mismatch")
    if not password_policy_ok(password):
        return False, tr("flash.accounts.password_policy_invalid")

    status, _count = password_pwned_status(password, timeout_seconds=10)
    if status == "pwned":
        return False, tr("flash.accounts.password_compromised")
    if status == "unavailable" and not allow_unavailable:
        return False, tr("flash.accounts.password_check_unavailable")
    return True, ""


def _device_approval_serializer():
    salt = current_app.config.get("DEVICE_APPROVAL_SALT", "pulsebeat-device-approval")
    return URLSafeTimedSerializer(current_app.secret_key, salt=salt)


def _device_approval_fingerprint(user, device_hash: str, ua_hash: str, nonce: str):
    raw = "|".join(
        [
            str(user.get("_id", "")),
            normalize_email(user.get("email", "")),
            str(user.get("session_token_version", 0) or 0),
            str(device_hash or ""),
            str(ua_hash or ""),
            str(nonce or ""),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _build_device_approval_link(user, context: dict, nonce: str):
    token = _device_approval_serializer().dumps(
        {
            "uid": str(user.get("_id", "")),
            "dh": str(context.get("device_hash", "") or ""),
            "uh": str(context.get("ua_hash", "") or ""),
            "nonce": str(nonce or ""),
            "fp": _device_approval_fingerprint(
                user,
                str(context.get("device_hash", "") or ""),
                str(context.get("ua_hash", "") or ""),
                str(nonce or ""),
            ),
        }
    )
    base_url = current_app.config.get("APP_BASE_URL", "").strip()
    if base_url:
        return f"{base_url.rstrip('/')}{url_for('accounts.approve_device', token=token)}"
    return url_for("accounts.approve_device", token=token, _external=True)


def _send_device_approval_email(user, context: dict, link: str):
    recipient_email = normalize_email(user.get("email", ""))
    if not recipient_email:
        return False

    expires_minutes = max(1, int(current_app.config.get("DEVICE_APPROVAL_TOKEN_MAX_AGE", 1800) / 60))
    username = user.get("username", "user")
    summary = device_summary_text(context)
    username_safe = html.escape(username)
    link_safe = html.escape(link)
    summary_safe = html.escape(summary)

    plain_text = (
        f"{tr('auth.device_approval_plain_greeting', username=username)}\n\n"
        f"{tr('auth.device_approval_plain_instruction', device=summary)}\n"
        f"{link}\n\n"
        f"{tr('auth.device_approval_plain_expiry', expires_minutes=expires_minutes)}\n\n"
        f"{tr('auth.device_approval_ignore')}"
    )
    html_body = f"""
<html>
  <body style="margin:0;padding:0;background:#f4f6fb;font-family:Segoe UI,Arial,sans-serif;color:#101828;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f4f6fb;padding:24px 0;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:640px;background:#ffffff;border-radius:18px;overflow:hidden;border:1px solid #d9e1f2;">
            <tr>
              <td style="padding:24px;background:#0f172a;color:#f8fafc;">
                <h1 style="margin:0;font-size:24px;">PulseBeat</h1>
              </td>
            </tr>
            <tr>
              <td style="padding:24px;">
                <h2 style="margin:0 0 14px 0;font-size:22px;color:#101828;">{html.escape(tr('auth.device_approval_heading'))}</h2>
                <p style="margin:0 0 12px 0;line-height:1.6;">{html.escape(tr('auth.device_approval_html_greeting', username=username_safe))}</p>
                <p style="margin:0 0 12px 0;line-height:1.6;">{html.escape(tr('auth.device_approval_html_intro', device=summary_safe))}</p>
                <p style="margin:0 0 22px 0;">
                  <a href="{link_safe}" style="display:inline-block;background:#2563eb;color:#ffffff;text-decoration:none;padding:12px 18px;border-radius:10px;font-size:14px;font-weight:700;">{html.escape(tr('auth.device_approval_button'))}</a>
                </p>
                <p style="margin:0 0 8px 0;font-size:13px;line-height:1.5;color:#5b6472;">{html.escape(tr('auth.device_approval_plain_expiry', expires_minutes=expires_minutes))}</p>
                <p style="margin:0;font-size:13px;line-height:1.5;color:#5b6472;">{html.escape(tr('auth.device_approval_ignore'))}</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""
    return send_email_message(recipient_email, tr("auth.device_approval_subject"), plain_text, html_body)


def _queue_device_approval(user, context: dict):
    now = datetime.utcnow()
    expires_at = now + timedelta(seconds=int(current_app.config.get("DEVICE_APPROVAL_TOKEN_MAX_AGE", 1800) or 1800))
    device_hash = str(context.get("device_hash", "") or "")
    if not device_hash:
        return False

    nonce = secrets.token_urlsafe(24)
    entry = {
        "token_hash": hashlib.sha256(nonce.encode("utf-8")).hexdigest(),
        "device_hash": device_hash,
        "ua_hash": str(context.get("ua_hash", "") or ""),
        "label": str(context.get("label", "") or ""),
        "ip_prefix": str(context.get("ip_prefix", "") or ""),
        "created_at": now,
        "expires_at": expires_at,
    }
    safe_mongo_update_one(
        extensions.users_col,
        {"_id": user.get("_id")},
        {"$pull": {"pending_device_approvals": {"expires_at": {"$lte": now}}}},
    )
    existing = safe_mongo_update_one(
        extensions.users_col,
        {"_id": user.get("_id"), "pending_device_approvals.device_hash": device_hash},
        {
            "$set": {
                "pending_device_approvals.$.token_hash": entry["token_hash"],
                "pending_device_approvals.$.ua_hash": entry["ua_hash"],
                "pending_device_approvals.$.label": entry["label"],
                "pending_device_approvals.$.ip_prefix": entry["ip_prefix"],
                "pending_device_approvals.$.created_at": entry["created_at"],
                "pending_device_approvals.$.expires_at": entry["expires_at"],
            }
        },
    )
    if not existing.matched_count:
        inserted = safe_mongo_update_one(
            extensions.users_col,
            {"_id": user.get("_id"), "pending_device_approvals.device_hash": {"$ne": device_hash}},
            {"$push": {"pending_device_approvals": {"$each": [entry], "$slice": -10}}},
        )
        if not inserted.matched_count:
            safe_mongo_update_one(
                extensions.users_col,
                {"_id": user.get("_id"), "pending_device_approvals.device_hash": device_hash},
                {
                    "$set": {
                        "pending_device_approvals.$.token_hash": entry["token_hash"],
                        "pending_device_approvals.$.ua_hash": entry["ua_hash"],
                        "pending_device_approvals.$.label": entry["label"],
                        "pending_device_approvals.$.ip_prefix": entry["ip_prefix"],
                        "pending_device_approvals.$.created_at": entry["created_at"],
                        "pending_device_approvals.$.expires_at": entry["expires_at"],
                    }
                },
            )
    return _send_device_approval_email(user, context, _build_device_approval_link(user, context, nonce))


def _load_device_approval_user_from_token(token: str):
    max_age = int(current_app.config.get("DEVICE_APPROVAL_TOKEN_MAX_AGE", 1800))
    try:
        payload = _device_approval_serializer().loads(token, max_age=max_age)
    except (SignatureExpired, BadSignature):
        return None, None, tr("flash.accounts.device_approval_invalid")

    user_oid = parse_object_id(payload.get("uid", ""))
    if not user_oid:
        return None, None, tr("flash.accounts.device_approval_invalid")

    user = extensions.users_col.find_one({"_id": user_oid})
    if not user:
        return None, None, tr("flash.accounts.device_approval_invalid")

    device_hash = str(payload.get("dh", "") or "")
    ua_hash = str(payload.get("uh", "") or "")
    nonce = str(payload.get("nonce", "") or "")
    if not device_hash or not nonce:
        return None, None, tr("flash.accounts.device_approval_invalid")

    if payload.get("fp") != _device_approval_fingerprint(user, device_hash, ua_hash, nonce):
        return None, None, tr("flash.accounts.device_approval_invalid")

    token_hash = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
    now = datetime.utcnow()
    for entry in list(user.get("pending_device_approvals", []) or []):
        if str(entry.get("token_hash", "") or "") != token_hash:
            continue
        expires_at = entry.get("expires_at")
        if isinstance(expires_at, datetime) and expires_at <= now:
            break
        if str(entry.get("device_hash", "") or "") != device_hash:
            break
        return user, entry, ""
    return None, None, tr("flash.accounts.device_approval_invalid")


def _enforce_device_gate(user):
    context = get_request_device_context()
    trusted_devices = list(user.get("trusted_devices", []) or [])
    try:
        if not trusted_devices:
            remember_trusted_device(user.get("_id"), context)
            return True, "", ""
        if is_trusted_device(user, context):
            return True, "", ""
        if _queue_device_approval(user, context):
            return False, tr("flash.accounts.device_approval_email_sent"), "info"
        return False, tr("flash.accounts.device_approval_email_failed"), "danger"
    except PyMongoError:
        current_app.logger.warning("Unable to evaluate trusted device gate", exc_info=True)
        return False, tr("flash.accounts.session_security_retry"), "warning"


def _two_factor_toggle_serializer():
    salt = current_app.config.get("TWO_FACTOR_TOGGLE_SALT", "pulsebeat-two-factor-toggle")
    return URLSafeTimedSerializer(current_app.secret_key, salt=salt)


def _two_factor_toggle_fingerprint(user, action: str):
    raw = "|".join(
        [
            str(user.get("_id", "")),
            normalize_email(user.get("email", "")),
            str(user.get("password_hash", "")),
            str(user.get("auth_provider", "local")),
            "1" if bool(user.get("two_factor_enabled", False)) else "0",
            str(action or "").strip().lower(),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _build_two_factor_toggle_link(user, action: str):
    token = _two_factor_toggle_serializer().dumps(
        {
            "uid": str(user.get("_id", "")),
            "action": str(action or "").strip().lower(),
            "fp": _two_factor_toggle_fingerprint(user, action),
        }
    )
    base_url = current_app.config.get("APP_BASE_URL", "").strip()
    if base_url:
        return f"{base_url.rstrip('/')}{url_for('accounts.confirm_two_factor_toggle', token=token)}"
    return url_for("accounts.confirm_two_factor_toggle", token=token, _external=True)


def _send_two_factor_toggle_email(user, action: str):
    recipient_email = normalize_email(user.get("email", ""))
    if not recipient_email:
        return False
    enable = str(action or "").strip().lower() == "enable"
    link = _build_two_factor_toggle_link(user, action)
    expires_minutes = int(current_app.config.get("TWO_FACTOR_TOGGLE_TOKEN_MAX_AGE", 3600) / 60)
    username = user.get("username", "user")
    username_safe = html.escape(username)
    link_safe = html.escape(link)
    plain_text = (
        f"{tr('auth.two_factor_toggle_plain_greeting', username=username)}\n\n"
        f"{tr('auth.two_factor_toggle_plain_instruction_enable' if enable else 'auth.two_factor_toggle_plain_instruction_disable')}\n"
        f"{link}\n\n"
        f"{tr('auth.two_factor_toggle_plain_expiry', expires_minutes=expires_minutes)}\n\n"
        f"{tr('auth.two_factor_toggle_ignore')}"
    )
    html_body = f"""
<!doctype html>
<html>
  <body style=\"margin:0;padding:0;background:#f3f6fb;font-family:Arial,Helvetica,sans-serif;color:#1b2430;\">
    <table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" style=\"background:#f3f6fb;padding:24px 0;\">
      <tr>
        <td align=\"center\">
          <table role=\"presentation\" width=\"640\" cellspacing=\"0\" cellpadding=\"0\" style=\"max-width:640px;width:100%;background:#ffffff;border-radius:14px;overflow:hidden;border:1px solid #e3eaf3;\">
            <tr>
              <td style=\"background:linear-gradient(135deg,#ff8a1f,#ff4f4f);padding:20px 28px;color:#fff;font-size:22px;font-weight:700;\">PulseBeat</td>
            </tr>
            <tr>
              <td style=\"padding:28px;\">
                <h1 style=\"margin:0 0 14px 0;font-size:22px;line-height:1.3;color:#101828;\">{html.escape(tr('auth.two_factor_toggle_heading_enable' if enable else 'auth.two_factor_toggle_heading_disable'))}</h1>
                <p style=\"margin:0 0 12px 0;font-size:15px;line-height:1.6;\">{html.escape(tr('auth.two_factor_toggle_html_greeting', username=username_safe))}</p>
                <p style=\"margin:0 0 18px 0;font-size:15px;line-height:1.6;\">{html.escape(tr('auth.two_factor_toggle_html_intro_enable' if enable else 'auth.two_factor_toggle_html_intro_disable'))}</p>
                <p style=\"margin:0 0 22px 0;\">
                  <a href=\"{link_safe}\" style=\"display:inline-block;background:#2563eb;color:#ffffff;text-decoration:none;padding:12px 18px;border-radius:10px;font-size:14px;font-weight:700;\">{html.escape(tr('auth.two_factor_toggle_button_enable' if enable else 'auth.two_factor_toggle_button_disable'))}</a>
                </p>
                <p style=\"margin:0 0 8px 0;font-size:13px;line-height:1.5;color:#5b6472;\">{html.escape(tr('auth.two_factor_toggle_plain_expiry', expires_minutes=expires_minutes))}</p>
                <p style=\"margin:0 0 14px 0;font-size:13px;line-height:1.5;color:#5b6472;\">{html.escape(tr('auth.two_factor_toggle_ignore'))}</p>
                <p style=\"margin:0;font-size:12px;line-height:1.5;color:#7b8494;word-break:break-all;\">{link_safe}</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""
    subject_key = "auth.two_factor_toggle_subject_enable" if enable else "auth.two_factor_toggle_subject_disable"
    return send_email_message(recipient_email, tr(subject_key), plain_text, html_body)


def _load_two_factor_toggle_user_from_token(token: str):
    max_age = int(current_app.config.get("TWO_FACTOR_TOGGLE_TOKEN_MAX_AGE", 3600))
    try:
        payload = _two_factor_toggle_serializer().loads(token, max_age=max_age)
    except (SignatureExpired, BadSignature):
        return None, "", tr("flash.accounts.two_factor_toggle_invalid")

    user_oid = parse_object_id(payload.get("uid", ""))
    action = str(payload.get("action", "")).strip().lower()
    if not user_oid or action not in {"enable", "disable"}:
        return None, "", tr("flash.accounts.two_factor_toggle_invalid")

    user = extensions.users_col.find_one({"_id": user_oid})
    if not user:
        return None, "", tr("flash.accounts.two_factor_toggle_invalid")
    if user.get("auth_provider") == "google":
        return None, "", tr("flash.accounts.two_factor_not_available_google")

    if payload.get("fp") != _two_factor_toggle_fingerprint(user, action):
        return None, "", tr("flash.accounts.two_factor_toggle_invalid")
    return user, action, ""


def _mask_email(value: str):
    email = normalize_email(value)
    if not email or "@" not in email:
        return ""
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        local_masked = "*" * max(1, len(local))
    else:
        local_masked = f"{local[0]}{'*' * (len(local) - 2)}{local[-1]}"
    return f"{local_masked}@{domain}"


def _two_factor_code_hash(user_id: str, code: str):
    raw = f"{str(user_id)}|{str(code)}|{current_app.secret_key}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _clear_two_factor_session():
    for key in [
        "pending_2fa_user_id",
        "pending_2fa_code_hash",
        "pending_2fa_expires_at",
        "pending_2fa_attempts",
    ]:
        session.pop(key, None)


def _issue_two_factor_code(user):
    code = f"{secrets.randbelow(10 ** TWO_FACTOR_CODE_LENGTH):0{TWO_FACTOR_CODE_LENGTH}d}"
    ttl_seconds = int(current_app.config.get("TWO_FACTOR_CODE_MAX_AGE", 600))
    expires_at = datetime.utcnow() + timedelta(seconds=max(60, ttl_seconds))
    sent = _send_two_factor_code_email(
        normalize_email(user.get("email", "")),
        user.get("username", "user"),
        code,
        max(1, int(ttl_seconds / 60)),
    )
    if not sent:
        return False
    session["pending_2fa_user_id"] = str(user.get("_id", ""))
    session["pending_2fa_code_hash"] = _two_factor_code_hash(str(user.get("_id", "")), code)
    session["pending_2fa_expires_at"] = int(expires_at.timestamp())
    session["pending_2fa_attempts"] = 0
    return True


def _load_pending_two_factor_user():
    user_oid = parse_object_id(session.get("pending_2fa_user_id", ""))
    if not user_oid:
        _clear_two_factor_session()
        return None, tr("flash.accounts.two_factor_session_invalid")
    user = extensions.users_col.find_one({"_id": user_oid})
    if not user:
        _clear_two_factor_session()
        return None, tr("flash.accounts.two_factor_session_invalid")
    if is_user_banned(user):
        _clear_two_factor_session()
        return None, tr("flash.accounts.banned")
    if not is_email_verified(user):
        _clear_two_factor_session()
        return None, tr("flash.accounts.email_not_verified")
    if user.get("auth_provider") == "google" or not bool(user.get("two_factor_enabled", False)):
        _clear_two_factor_session()
        return None, tr("flash.accounts.two_factor_session_invalid")
    return user, ""


def _send_two_factor_code_email(recipient_email: str, username: str, code: str, expires_minutes: int):
    if not recipient_email:
        return False
    code_safe = html.escape(code)
    username_safe = html.escape(username or "user")
    plain_text = (
        f"{tr('auth.two_factor_code_plain_greeting', username=username)}\n\n"
        f"{tr('auth.two_factor_code_plain_instruction', code=code)}\n\n"
        f"{tr('auth.two_factor_code_plain_expiry', expires_minutes=expires_minutes)}\n\n"
        f"{tr('auth.two_factor_code_ignore')}"
    )
    html_body = f"""
<!doctype html>
<html>
  <body style=\"margin:0;padding:0;background:#f3f6fb;font-family:Arial,Helvetica,sans-serif;color:#1b2430;\">
    <table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" style=\"background:#f3f6fb;padding:24px 0;\">
      <tr>
        <td align=\"center\">
          <table role=\"presentation\" width=\"640\" cellspacing=\"0\" cellpadding=\"0\" style=\"max-width:640px;width:100%;background:#ffffff;border-radius:14px;overflow:hidden;border:1px solid #e3eaf3;\">
            <tr>
              <td style=\"background:linear-gradient(135deg,#ff8a1f,#ff4f4f);padding:20px 28px;color:#fff;font-size:22px;font-weight:700;\">PulseBeat</td>
            </tr>
            <tr>
              <td style=\"padding:28px;\">
                <h1 style=\"margin:0 0 14px 0;font-size:22px;line-height:1.3;color:#101828;\">{html.escape(tr('auth.two_factor_code_heading'))}</h1>
                <p style=\"margin:0 0 12px 0;font-size:15px;line-height:1.6;\">{html.escape(tr('auth.two_factor_code_html_greeting', username=username_safe))}</p>
                <p style=\"margin:0 0 12px 0;font-size:15px;line-height:1.6;\">{html.escape(tr('auth.two_factor_code_html_intro'))}</p>
                <p style=\"margin:0 0 20px 0;\">
                  <span style=\"display:inline-block;padding:12px 18px;border-radius:12px;background:#eff4ff;border:1px solid #bfd0ff;color:#12306a;font-size:28px;letter-spacing:0.24em;font-weight:700;\">{code_safe}</span>
                </p>
                <p style=\"margin:0 0 8px 0;font-size:13px;line-height:1.5;color:#5b6472;\">{html.escape(tr('auth.two_factor_code_plain_expiry', expires_minutes=expires_minutes))}</p>
                <p style=\"margin:0;font-size:13px;line-height:1.5;color:#5b6472;\">{html.escape(tr('auth.two_factor_code_ignore'))}</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""
    return send_email_message(recipient_email, tr("auth.two_factor_code_subject"), plain_text, html_body)



def _password_reset_serializer():
    salt = current_app.config.get("PASSWORD_RESET_SALT", "pulsebeat-reset-salt")
    return URLSafeTimedSerializer(current_app.secret_key, salt=salt)


def _password_fingerprint(password_hash: str):
    raw = password_hash or ""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _build_password_reset_link(user):
    token_payload = {
        "uid": str(user["_id"]),
        "fp": _password_fingerprint(user.get("password_hash", "")),
    }
    token = _password_reset_serializer().dumps(token_payload)

    base_url = current_app.config.get("APP_BASE_URL", "").strip()
    if base_url:
        return f"{base_url.rstrip('/')}{url_for('accounts.reset_password', token=token)}"
    return url_for("accounts.reset_password", token=token, _external=True)


def _send_password_reset_email(recipient_email: str, username: str, reset_link: str):
    host = current_app.config.get("MAIL_HOST", "")
    port = int(current_app.config.get("MAIL_PORT", 587))
    mail_from = current_app.config.get("MAIL_FROM", "")
    mail_user = current_app.config.get("MAIL_USERNAME", "")
    mail_pass = current_app.config.get("MAIL_PASSWORD", "")
    use_tls = bool(current_app.config.get("MAIL_USE_TLS", True))
    use_ssl = bool(current_app.config.get("MAIL_USE_SSL", False))
    expires_minutes = int(current_app.config.get("PASSWORD_RESET_TOKEN_MAX_AGE", 3600) / 60)

    if not current_app.config.get("MAIL_ENABLED", False) or not host or not mail_from:
        return False

    username_safe = html.escape(username or "user")
    reset_link_safe = html.escape(reset_link)

    plain_text = (
        f"{tr('auth.reset_email_plain_greeting', username=username)}\n\n"
        f"{tr('auth.reset_email_plain_instruction')}\n{reset_link}\n\n"
        f"{tr('auth.reset_email_plain_expiry', expires_minutes=expires_minutes)}\n\n"
        f"{tr('auth.reset_email_ignore')}"
    )

    html_body = f"""
<!doctype html>
<html>
  <body style=\"margin:0;padding:0;background:#f3f6fb;font-family:Arial,Helvetica,sans-serif;color:#1b2430;\">
    <table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" style=\"background:#f3f6fb;padding:24px 0;\">
      <tr>
        <td align=\"center\">
          <table role=\"presentation\" width=\"640\" cellspacing=\"0\" cellpadding=\"0\" style=\"max-width:640px;width:100%;background:#ffffff;border-radius:14px;overflow:hidden;border:1px solid #e3eaf3;\">
            <tr>
              <td style=\"background:linear-gradient(135deg,#ff8a1f,#ff4f4f);padding:20px 28px;color:#fff;font-size:22px;font-weight:700;\">PulseBeat</td>
            </tr>
            <tr>
              <td style=\"padding:28px;\">
                <h1 style=\"margin:0 0 14px 0;font-size:22px;line-height:1.3;color:#101828;\">{html.escape(tr('auth.reset_email_heading'))}</h1>
                <p style=\"margin:0 0 12px 0;font-size:15px;line-height:1.6;\">{html.escape(tr('auth.reset_email_html_greeting', username=username_safe))}</p>
                <p style=\"margin:0 0 18px 0;font-size:15px;line-height:1.6;\">{html.escape(tr('auth.reset_email_html_intro'))}</p>
                <p style=\"margin:0 0 22px 0;\">
                  <a href=\"{reset_link_safe}\" style=\"display:inline-block;background:#2563eb;color:#ffffff;text-decoration:none;padding:12px 18px;border-radius:10px;font-size:14px;font-weight:700;\">{html.escape(tr('auth.reset_email_button'))}</a>
                </p>
                <p style=\"margin:0 0 8px 0;font-size:13px;line-height:1.5;color:#5b6472;\">{html.escape(tr('auth.reset_email_plain_expiry', expires_minutes=expires_minutes))}</p>
                <p style=\"margin:0 0 14px 0;font-size:13px;line-height:1.5;color:#5b6472;\">{html.escape(tr('auth.reset_email_ignore'))}</p>
                <p style=\"margin:0;font-size:12px;line-height:1.5;color:#7b8494;word-break:break-all;\">{reset_link_safe}</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""

    msg = EmailMessage()
    msg["From"] = mail_from
    msg["To"] = recipient_email
    msg["Subject"] = tr("auth.reset_email_subject")
    msg.set_content(plain_text)
    msg.add_alternative(html_body, subtype="html")

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=10) as server:
                if mail_user and mail_pass:
                    server.login(mail_user, mail_pass)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=10) as server:
                server.ehlo()
                if use_tls:
                    server.starttls()
                    server.ehlo()
                if mail_user and mail_pass:
                    server.login(mail_user, mail_pass)
                server.send_message(msg)
        return True
    except Exception:
        return False


def _load_reset_user_from_token(token: str):
    max_age = int(current_app.config.get("PASSWORD_RESET_TOKEN_MAX_AGE", 3600))
    try:
        payload = _password_reset_serializer().loads(token, max_age=max_age)
    except (SignatureExpired, BadSignature):
        return None, tr("flash.accounts.password_reset_invalid")

    user_oid = parse_object_id(payload.get("uid", ""))
    if not user_oid:
        return None, tr("flash.accounts.password_reset_invalid")

    user = extensions.users_col.find_one({"_id": user_oid})
    if not user:
        return None, tr("flash.accounts.password_reset_invalid")

    if payload.get("fp") != _password_fingerprint(user.get("password_hash", "")):
        return None, tr("flash.accounts.password_reset_invalid")

    return user, ""


def _email_verification_serializer():
    salt = current_app.config.get("EMAIL_VERIFICATION_SALT", "pulsebeat-email-verify")
    return URLSafeTimedSerializer(current_app.secret_key, salt=salt)


def _email_verification_fingerprint(user):
    raw = f"{(user.get('email') or '').strip().lower()}|{user.get('auth_provider', 'local')}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _build_email_verification_link(user):
    token = _email_verification_serializer().dumps({"uid": str(user["_id"]), "fp": _email_verification_fingerprint(user)})
    base_url = current_app.config.get("APP_BASE_URL", "").strip()
    if base_url:
        return f"{base_url.rstrip('/')}{url_for('accounts.verify_email', token=token)}"
    return url_for("accounts.verify_email", token=token, _external=True)


def _send_email_verification_email(recipient_email: str, username: str, verification_link: str):
    expires_minutes = int(current_app.config.get("EMAIL_VERIFICATION_TOKEN_MAX_AGE", 86400) / 60)
    username_safe = html.escape(username or "user")
    verification_link_safe = html.escape(verification_link)
    plain_text = (
        f"{tr('auth.verification_email_plain_greeting', username=username)}\n\n"
        f"{tr('auth.verification_email_plain_instruction')}\n{verification_link}\n\n"
        f"{tr('auth.verification_email_plain_expiry', expires_minutes=expires_minutes)}\n\n"
        f"{tr('auth.verification_email_ignore')}"
    )
    html_body = f"""
<!doctype html>
<html>
  <body style=\"margin:0;padding:0;background:#f3f6fb;font-family:Arial,Helvetica,sans-serif;color:#1b2430;\">
    <table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" style=\"background:#f3f6fb;padding:24px 0;\">
      <tr>
        <td align=\"center\">
          <table role=\"presentation\" width=\"640\" cellspacing=\"0\" cellpadding=\"0\" style=\"max-width:640px;width:100%;background:#ffffff;border-radius:14px;overflow:hidden;border:1px solid #e3eaf3;\">
            <tr>
              <td style=\"background:linear-gradient(135deg,#ff8a1f,#ff4f4f);padding:20px 28px;color:#fff;font-size:22px;font-weight:700;\">PulseBeat</td>
            </tr>
            <tr>
              <td style=\"padding:28px;\">
                <h1 style=\"margin:0 0 14px 0;font-size:22px;line-height:1.3;color:#101828;\">{html.escape(tr('auth.verification_email_heading'))}</h1>
                <p style=\"margin:0 0 12px 0;font-size:15px;line-height:1.6;\">{html.escape(tr('auth.verification_email_html_greeting', username=username_safe))}</p>
                <p style=\"margin:0 0 18px 0;font-size:15px;line-height:1.6;\">{html.escape(tr('auth.verification_email_html_intro'))}</p>
                <p style=\"margin:0 0 22px 0;\">
                  <a href=\"{verification_link_safe}\" style=\"display:inline-block;background:#2563eb;color:#ffffff;text-decoration:none;padding:12px 18px;border-radius:10px;font-size:14px;font-weight:700;\">{html.escape(tr('auth.verification_email_button'))}</a>
                </p>
                <p style=\"margin:0 0 8px 0;font-size:13px;line-height:1.5;color:#5b6472;\">{html.escape(tr('auth.verification_email_plain_expiry', expires_minutes=expires_minutes))}</p>
                <p style=\"margin:0 0 14px 0;font-size:13px;line-height:1.5;color:#5b6472;\">{html.escape(tr('auth.verification_email_ignore'))}</p>
                <p style=\"margin:0;font-size:12px;line-height:1.5;color:#7b8494;word-break:break-all;\">{verification_link_safe}</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""
    return send_email_message(recipient_email, tr("auth.verification_email_subject"), plain_text, html_body)


def _send_email_verification(user):
    sent = _send_email_verification_email(user.get("email", ""), user.get("username", "user"), _build_email_verification_link(user))
    if sent:
        extensions.users_col.update_one({"_id": user["_id"]}, {"$set": {"email_verification_sent_at": datetime.utcnow()}})
    return sent


def _load_verification_user_from_token(token: str):
    max_age = int(current_app.config.get("EMAIL_VERIFICATION_TOKEN_MAX_AGE", 86400))
    try:
        payload = _email_verification_serializer().loads(token, max_age=max_age)
    except (SignatureExpired, BadSignature):
        return None, tr("flash.accounts.email_verification_invalid")

    user_oid = parse_object_id(payload.get("uid", ""))
    if not user_oid:
        return None, tr("flash.accounts.email_verification_invalid")

    user = extensions.users_col.find_one({"_id": user_oid})
    if not user:
        return None, tr("flash.accounts.email_verification_invalid")

    if payload.get("fp") != _email_verification_fingerprint(user):
        return None, tr("flash.accounts.email_verification_invalid")

    return user, ""


def _account_unlock_serializer():
    salt = current_app.config.get("ACCOUNT_UNLOCK_SALT", "pulsebeat-account-unlock")
    return URLSafeTimedSerializer(current_app.secret_key, salt=salt)


def _account_unlock_fingerprint(user):
    lock_until = user.get("login_lock_until")
    lock_until_iso = lock_until.isoformat() if isinstance(lock_until, datetime) else ""
    raw = "|".join(
        [
            str(user.get("_id", "")),
            str(user.get("password_hash", "")),
            str(int(user.get("login_lock_level", 0) or 0)),
            str(int(user.get("login_failure_count", 0) or 0)),
            lock_until_iso,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _build_account_unlock_link(user):
    token = _account_unlock_serializer().dumps({"uid": str(user["_id"]), "fp": _account_unlock_fingerprint(user)})
    base_url = current_app.config.get("APP_BASE_URL", "").strip()
    if base_url:
        return f"{base_url.rstrip('/')}{url_for('accounts.unlock_account', token=token)}"
    return url_for("accounts.unlock_account", token=token, _external=True)


def _send_account_unlock_email(recipient_email: str, username: str, unlock_link: str):
    expires_minutes = int(current_app.config.get("ACCOUNT_UNLOCK_TOKEN_MAX_AGE", 3600) / 60)
    username_safe = html.escape(username or "user")
    unlock_link_safe = html.escape(unlock_link)
    plain_text = (
        f"{tr('auth.unlock_email_plain_greeting', username=username)}\n\n"
        f"{tr('auth.unlock_email_plain_instruction')}\n{unlock_link}\n\n"
        f"{tr('auth.unlock_email_plain_expiry', expires_minutes=expires_minutes)}\n\n"
        f"{tr('auth.unlock_email_ignore')}"
    )
    html_body = f"""
<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#f3f6fb;font-family:Arial,Helvetica,sans-serif;color:#1b2430;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f3f6fb;padding:24px 0;">
      <tr>
        <td align="center">
          <table role="presentation" width="640" cellspacing="0" cellpadding="0" style="max-width:640px;width:100%;background:#ffffff;border-radius:14px;overflow:hidden;border:1px solid #e3eaf3;">
            <tr>
              <td style="background:linear-gradient(135deg,#ff8a1f,#ff4f4f);padding:20px 28px;color:#fff;font-size:22px;font-weight:700;">PulseBeat</td>
            </tr>
            <tr>
              <td style="padding:28px;">
                <h1 style="margin:0 0 14px 0;font-size:22px;line-height:1.3;color:#101828;">{html.escape(tr('auth.unlock_email_heading'))}</h1>
                <p style="margin:0 0 12px 0;font-size:15px;line-height:1.6;">{html.escape(tr('auth.unlock_email_html_greeting', username=username_safe))}</p>
                <p style="margin:0 0 18px 0;font-size:15px;line-height:1.6;">{html.escape(tr('auth.unlock_email_html_intro'))}</p>
                <p style="margin:0 0 22px 0;">
                  <a href="{unlock_link_safe}" style="display:inline-block;background:#2563eb;color:#ffffff;text-decoration:none;padding:12px 18px;border-radius:10px;font-size:14px;font-weight:700;">{html.escape(tr('auth.unlock_email_button'))}</a>
                </p>
                <p style="margin:0 0 8px 0;font-size:13px;line-height:1.5;color:#5b6472;">{html.escape(tr('auth.unlock_email_plain_expiry', expires_minutes=expires_minutes))}</p>
                <p style="margin:0 0 14px 0;font-size:13px;line-height:1.5;color:#5b6472;">{html.escape(tr('auth.unlock_email_ignore'))}</p>
                <p style="margin:0;font-size:12px;line-height:1.5;color:#7b8494;word-break:break-all;">{unlock_link_safe}</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""
    return send_email_message(recipient_email, tr("auth.unlock_email_subject"), plain_text, html_body)


def _load_unlock_user_from_token(token: str):
    max_age = int(current_app.config.get("ACCOUNT_UNLOCK_TOKEN_MAX_AGE", 3600))
    try:
        payload = _account_unlock_serializer().loads(token, max_age=max_age)
    except (SignatureExpired, BadSignature):
        return None, tr("flash.accounts.unlock_invalid")

    user_oid = parse_object_id(payload.get("uid", ""))
    if not user_oid:
        return None, tr("flash.accounts.unlock_invalid")

    user = extensions.users_col.find_one({"_id": user_oid})
    if not user:
        return None, tr("flash.accounts.unlock_invalid")

    if payload.get("fp") != _account_unlock_fingerprint(user):
        return None, tr("flash.accounts.unlock_invalid")

    return user, ""


def _google_redirect_uri():
    configured = current_app.config.get("GOOGLE_REDIRECT_URI", "").strip()
    if configured:
        return configured
    return url_for("accounts.google_callback", _external=True)


SUPPORTED_EXTERNAL_PROVIDERS = {"youtube"}


def _external_provider_name(provider: str) -> str:
    mapping = {
        "youtube": "YouTube",
    }
    return mapping.get(provider, provider)


def _external_provider_is_configured(provider: str) -> bool:
    if provider != "youtube":
        return False
    if not is_youtube_integration_enabled(True):
        return False
    return bool(
        current_app.config.get("YOUTUBE_SYNC_CLIENT_ID", "").strip()
        and current_app.config.get("YOUTUBE_SYNC_CLIENT_SECRET", "").strip()
    )


def _external_redirect_uri(provider: str) -> str:
    base_url = current_app.config.get("APP_BASE_URL", "").strip()
    if base_url:
        return f"{base_url.rstrip('/')}{url_for('accounts.external_provider_callback', provider=provider)}"
    return url_for("accounts.external_provider_callback", provider=provider, _external=True)


def _external_build_authorize_url(provider: str, state_value: str) -> str:
    redirect_uri = _external_redirect_uri(provider)
    if provider != "youtube":
        return ""
    params = {
        "client_id": current_app.config.get("YOUTUBE_SYNC_CLIENT_ID", "").strip(),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/youtube.readonly",
        "access_type": "offline",
        "prompt": "consent",
        "state": state_value,
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


def _external_exchange_code(provider: str, code: str):
    redirect_uri = _external_redirect_uri(provider)
    if provider != "youtube":
        return None
    payload = {
        "client_id": current_app.config.get("YOUTUBE_SYNC_CLIENT_ID", "").strip(),
        "client_secret": current_app.config.get("YOUTUBE_SYNC_CLIENT_SECRET", "").strip(),
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    try:
        res = requests.post("https://oauth2.googleapis.com/token", data=payload, timeout=12)
        data = res.json() if res.ok else {}
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get("access_token"):
        return None
    return data


def _external_refresh_token(provider: str, integration: dict):
    if provider == "youtube":
        refresh_token = (integration or {}).get("refresh_token", "")
        if not refresh_token:
            return None
        payload = {
            "client_id": current_app.config.get("YOUTUBE_SYNC_CLIENT_ID", "").strip(),
            "client_secret": current_app.config.get("YOUTUBE_SYNC_CLIENT_SECRET", "").strip(),
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        try:
            res = requests.post("https://oauth2.googleapis.com/token", data=payload, timeout=12)
            data = res.json() if res.ok else {}
        except Exception:
            return None
        if not isinstance(data, dict) or not data.get("access_token"):
            return None
        data["refresh_token"] = refresh_token
        return data
    return None


def _external_access_token(user_oid, provider: str):
    integration = extensions.external_integrations_col.find_one({"user_id": user_oid, "provider": provider})
    if not integration:
        return None, None

    expires_at = integration.get("expires_at")
    if isinstance(expires_at, datetime) and expires_at <= datetime.utcnow() + timedelta(seconds=30):
        refreshed = _external_refresh_token(provider, integration)
        if not refreshed:
            return None, integration
        set_doc = {
            "access_token": refreshed.get("access_token", ""),
            "updated_at": datetime.utcnow(),
        }
        if refreshed.get("refresh_token"):
            set_doc["refresh_token"] = refreshed.get("refresh_token")
        if refreshed.get("expires_in"):
            set_doc["expires_at"] = datetime.utcnow() + timedelta(seconds=max(0, int(refreshed.get("expires_in", 0))))
        extensions.external_integrations_col.update_one(
            {"_id": integration["_id"]},
            {"$set": set_doc},
        )
        integration = extensions.external_integrations_col.find_one({"_id": integration["_id"]}) or integration

    return integration.get("access_token", ""), integration


def _youtube_sync_payload(access_token: str):
    headers = {"Authorization": f"Bearer {access_token}"}
    playlists = []
    max_tracks_per_playlist = max(1, int(current_app.config.get("YOUTUBE_SYNC_MAX_TRACKS_PER_PLAYLIST", 5000)))
    max_playlist_pages = max(1, int(current_app.config.get("YOUTUBE_SYNC_MAX_PLAYLIST_PAGES", 20)))
    page_token = ""
    for _ in range(max_playlist_pages):
        params = {"part": "snippet", "mine": "true", "maxResults": 25}
        if page_token:
            params["pageToken"] = page_token
        res = requests.get("https://www.googleapis.com/youtube/v3/playlists", headers=headers, params=params, timeout=12)
        if not res.ok:
            break
        data = res.json() if res.content else {}
        for item in data.get("items", [])[:25]:
            playlist_id = ((item or {}).get("id") or "").strip()
            snippet = (item or {}).get("snippet") or {}
            if not playlist_id:
                continue
            tracks = []
            tracks_page = ""
            while len(tracks) < max_tracks_per_playlist:
                t_params = {
                    "part": "snippet,contentDetails",
                    "playlistId": playlist_id,
                    "maxResults": 50,
                }
                if tracks_page:
                    t_params["pageToken"] = tracks_page
                t_res = requests.get(
                    "https://www.googleapis.com/youtube/v3/playlistItems",
                    headers=headers,
                    params=t_params,
                    timeout=12,
                )
                if not t_res.ok:
                    break
                t_data = t_res.json() if t_res.content else {}
                for t_item in t_data.get("items", [])[:50]:
                    snippet_track = (t_item or {}).get("snippet") or {}
                    content_details = (t_item or {}).get("contentDetails") or {}
                    video_id = (content_details.get("videoId") or "").strip()
                    track_title = (snippet_track.get("title") or "").strip()
                    track_artist = (snippet_track.get("videoOwnerChannelTitle") or snippet_track.get("channelTitle") or "").strip()
                    if not video_id or not track_title:
                        continue
                    tracks.append(
                        {
                            "external_track_id": video_id,
                            "title": track_title,
                            "artist": track_artist,
                            "url": f"https://www.youtube.com/watch?v={video_id}",
                            "preview_url": "",
                            "duration_sec": 0,
                        }
                    )
                    if len(tracks) >= max_tracks_per_playlist:
                        break
                tracks_page = (t_data.get("nextPageToken") or "").strip()
                if not tracks_page or len(tracks) >= max_tracks_per_playlist:
                    break

            playlists.append(
                {
                    "external_playlist_id": playlist_id,
                    "name": (snippet.get("title") or "").strip() or "YouTube playlist",
                    "url": f"https://www.youtube.com/playlist?list={playlist_id}",
                    "tracks": tracks[:max_tracks_per_playlist],
                }
            )
        page_token = (data.get("nextPageToken") or "").strip()
        if not page_token:
            break

    return playlists


def _sync_external_provider(user_oid, provider: str):
    if provider == "youtube" and not is_youtube_integration_enabled(True):
        return False, tr("flash.accounts.integration_disabled_by_admin"), 0

    access_token, _integration = _external_access_token(user_oid, provider)
    if not access_token:
        return False, tr("flash.accounts.integration_not_connected"), 0

    if provider != "youtube":
        return False, tr("flash.songs.invalid_request"), 0
    payload = _youtube_sync_payload(access_token)

    now = datetime.utcnow()
    synced = 0
    for playlist in payload:
        pid = str(playlist.get("external_playlist_id", "")).strip()
        if not pid:
            continue
        tracks = []
        for track in playlist.get("tracks", []) or []:
            title = (track.get("title") or "").strip()
            if not title:
                continue
            tracks.append(
                {
                    "external_track_id": str(track.get("external_track_id", "")).strip(),
                    "title": title,
                    "artist": (track.get("artist") or "").strip(),
                    "url": (track.get("url") or "").strip(),
                    "preview_url": (track.get("preview_url") or "").strip(),
                    "duration_sec": int(track.get("duration_sec", 0) or 0),
                }
            )
        extensions.external_playlists_col.update_one(
            {"user_id": user_oid, "provider": provider, "external_playlist_id": pid},
            {
                "$set": {
                    "name": (playlist.get("name") or "").strip() or f"{_external_provider_name(provider)} playlist",
                    "url": (playlist.get("url") or "").strip(),
                    "tracks": tracks,
                    "tracks_count": len(tracks),
                    "synced_at": now,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
        synced += 1

    return True, "", synced


@bp.route("/setup-admin", methods=["GET", "POST"])
def setup_admin():
    if root_admin_exists():
        if get_session_user_oid():
            return redirect(url_for("main.index"))
        return redirect(url_for("accounts.login"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = normalize_email(request.form.get("email", ""))
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not username or not email or not password:
            flash(tr("flash.accounts.fields_required"), "danger")
            return redirect(url_for("accounts.setup_admin"))
        ok_username, username_msg = validate_username_for_create(username)
        if not ok_username:
            flash(username_msg, "danger")
            return redirect(url_for("accounts.setup_admin"))
        if find_user_by_email(email):
            flash(tr("flash.accounts.email_exists"), "danger")
            return redirect(url_for("accounts.setup_admin"))

        ok, msg = validate_password_for_set(password, confirm_password, allow_unavailable=True)
        if not ok:
            flash(msg, "danger")
            return redirect(url_for("accounts.setup_admin"))

        admin_id = extensions.users_col.insert_one(
            {
                "username": username,
                "username_normalized": normalize_username(username),
                "email": email,
                "email_normalized": normalize_email(email),
                "password_hash": generate_password_hash(password),
                "is_admin": True,
                "is_root_admin": True,
                "require_password_change": False,
                "auth_provider": "local",
                "email_verified": False,
                "email_verified_at": None,
                "email_verification_sent_at": None,
                "two_factor_enabled": False,
                "two_factor_prompt_pending": True,
                "created_at": datetime.utcnow(),
            }
        ).inserted_id
        user = extensions.users_col.find_one({"_id": admin_id})
        session["pending_verification_email"] = email
        if _send_email_verification(user):
            flash(tr("flash.accounts.root_admin_created_verify"), "success")
        else:
            flash(tr("flash.accounts.verification_email_failed"), "warning")
        return redirect(url_for("accounts.login"))

    return render_template("accounts/setup_admin.jinja")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if not root_admin_exists():
        return redirect(url_for("accounts.setup_admin"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = normalize_email(request.form.get("email", ""))
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not username or not email or not password:
            flash(tr("flash.accounts.fields_required"), "danger")
            return redirect(url_for("accounts.register"))
        ok_username, username_msg = validate_username_for_create(username)
        if not ok_username:
            flash(username_msg, "danger")
            return redirect(url_for("accounts.register"))
        if find_user_by_email(email):
            flash(tr("flash.accounts.email_exists"), "danger")
            return redirect(url_for("accounts.register"))

        if is_disposable_email(email) and request.form.get("temp_email_ack", "0") != "1":
            flash(tr("flash.accounts.temp_email_confirm_required"), "warning")
            return redirect(url_for("accounts.register"))

        ok, msg = validate_password_for_set(password, confirm_password, allow_unavailable=True)
        if not ok:
            flash(msg, "danger")
            return redirect(url_for("accounts.register"))

        user_id = extensions.users_col.insert_one(
            {
                "username": username,
                "username_normalized": normalize_username(username),
                "email": email,
                "email_normalized": normalize_email(email),
                "password_hash": generate_password_hash(password),
                "is_admin": False,
                "is_root_admin": False,
                "require_password_change": False,
                "auth_provider": "local",
                "email_verified": False,
                "email_verified_at": None,
                "email_verification_sent_at": None,
                "two_factor_enabled": False,
                "two_factor_prompt_pending": True,
                "created_at": datetime.utcnow(),
            }
        ).inserted_id
        user = extensions.users_col.find_one({"_id": user_id})
        session["pending_verification_email"] = email
        if _send_email_verification(user):
            flash(tr("flash.accounts.created_verify"), "success")
        else:
            flash(tr("flash.accounts.verification_email_failed"), "warning")
        return redirect(url_for("accounts.login"))

    return render_template("accounts/register.jinja")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if not root_admin_exists():
        return redirect(url_for("accounts.setup_admin"))

    if request.method == "POST":
        login_id = (request.form.get("login_id", "") or request.form.get("email", "")).strip()
        password = request.form.get("password", "")

        user = find_user_by_login(login_id)
        now = datetime.utcnow()
        if user:
            lock_until = user.get("login_lock_until")
            if lock_until and lock_until > now:
                minutes_left = max(1, int((lock_until - now).total_seconds() // 60) + 1)
                flash(tr("flash.accounts.login_locked", minutes=minutes_left), "danger")
                return redirect(url_for("accounts.login"))

        if not user or not check_password_hash(user.get("password_hash", ""), password):
            if user:
                lock_info = _register_login_failure(user)
                if lock_info.get("locked"):
                    refreshed = extensions.users_col.find_one({"_id": user["_id"]}) or user
                    unlock_link = _build_account_unlock_link(refreshed)
                    sent = _send_account_unlock_email(
                        refreshed.get("email", ""),
                        refreshed.get("username", "user"),
                        unlock_link,
                    )
                    if sent:
                        flash(tr("flash.accounts.login_unlock_email_sent"), "info")
                    else:
                        flash(tr("flash.accounts.login_unlock_email_failed"), "warning")
                    flash(tr("flash.accounts.login_locked", minutes=lock_info.get("minutes", 10)), "danger")
                    return redirect(url_for("accounts.login"))
            flash(tr("flash.accounts.invalid_credentials"), "danger")
            return redirect(url_for("accounts.login"))
        if is_user_banned(user):
            flash(tr("flash.accounts.banned"), "danger")
            return redirect(url_for("accounts.login"))
        if not is_email_verified(user):
            session["pending_verification_email"] = user.get("email", "")
            flash(tr("flash.accounts.email_not_verified"), "warning")
            return redirect(url_for("accounts.login"))

        if user.get("auth_provider") != "google":
            status, _count = password_pwned_status(password, timeout_seconds=10)
        else:
            status, _count = ("safe", 0)
        if status == "pwned":
            extensions.users_col.update_one(
                {"_id": user["_id"]},
                {"$set": {"require_password_change": True, "password_compromised_at": datetime.utcnow()}},
            )
            if True:
                send_email_message(
                    user.get("email", ""),
                    tr("email.password_compromised_subject"),
                    tr("email.password_compromised_body", username=user.get("username", "user")),
                )
            flash(tr("flash.accounts.password_compromised_force_change"), "warning")
        elif status == "unavailable":
            flash(tr("flash.accounts.password_check_unavailable"), "warning")

        _reset_login_lock(user["_id"])
        device_allowed, device_message, device_category = _enforce_device_gate(user)
        if not device_allowed:
            flash(device_message, device_category or "warning")
            return redirect(url_for("accounts.login"))
        if user.get("auth_provider") != "google" and bool(user.get("two_factor_enabled", False)):
            session.clear()
            if not _issue_two_factor_code(user):
                flash(tr("flash.accounts.two_factor_send_failed"), "danger")
                return redirect(url_for("accounts.login"))
            flash(tr("flash.accounts.two_factor_code_sent"), "info")
            return redirect(url_for("accounts.two_factor_challenge"))
        return _complete_login(user)

    return render_template("accounts/login.jinja", pending_verification_email=session.get("pending_verification_email", ""))


@bp.route("/two-factor/challenge", methods=["GET", "POST"])
def two_factor_challenge():
    if get_session_user_oid():
        return redirect(url_for("main.index"))

    user, error = _load_pending_two_factor_user()
    if not user:
        if error:
            flash(error, "warning")
        return redirect(url_for("accounts.login"))

    expires_at_ts = int(session.get("pending_2fa_expires_at", 0) or 0)
    now_ts = int(datetime.utcnow().timestamp())
    if expires_at_ts <= now_ts:
        _clear_two_factor_session()
        flash(tr("flash.accounts.two_factor_code_expired"), "warning")
        return redirect(url_for("accounts.login"))

    if request.method == "POST":
        action = (request.form.get("action", "verify") or "verify").strip().lower()
        if action == "resend":
            if _issue_two_factor_code(user):
                flash(tr("flash.accounts.two_factor_code_sent"), "success")
            else:
                flash(tr("flash.accounts.two_factor_send_failed"), "danger")
            return redirect(url_for("accounts.two_factor_challenge"))

        code_raw = (request.form.get("code", "") or "").strip()
        code = re.sub(r"[^0-9]", "", code_raw)
        expected_hash = str(session.get("pending_2fa_code_hash", "") or "").strip()
        is_valid = bool(code) and len(code) == TWO_FACTOR_CODE_LENGTH and expected_hash and secrets.compare_digest(
            _two_factor_code_hash(str(user.get("_id", "")), code),
            expected_hash,
        )
        if not is_valid:
            attempts = int(session.get("pending_2fa_attempts", 0) or 0) + 1
            session["pending_2fa_attempts"] = attempts
            remaining = max(0, TWO_FACTOR_CODE_MAX_ATTEMPTS - attempts)
            if attempts >= TWO_FACTOR_CODE_MAX_ATTEMPTS:
                _clear_two_factor_session()
                flash(tr("flash.accounts.two_factor_too_many_attempts"), "danger")
                return redirect(url_for("accounts.login"))
            flash(tr("flash.accounts.two_factor_code_invalid", remaining=remaining), "danger")
            return redirect(url_for("accounts.two_factor_challenge"))

        _clear_two_factor_session()
        return _complete_login(user)

    expires_minutes = max(1, int((expires_at_ts - now_ts) / 60) + 1)
    return render_template(
        "accounts/two_factor_challenge.jinja",
        masked_email=_mask_email(user.get("email", "")),
        expires_minutes=expires_minutes,
    )


@bp.route("/google-login")
def google_login():
    client_id = current_app.config.get("GOOGLE_CLIENT_ID", "")
    client_secret = current_app.config.get("GOOGLE_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        flash(tr("flash.auth.google_unavailable"), "danger")
        return redirect(url_for("accounts.login"))

    state = secrets.token_urlsafe(24)
    session["google_oauth_state"] = state
    redirect_uri = _google_redirect_uri()
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    query = "&".join([f"{k}={requests.utils.quote(str(v), safe='')}" for k, v in params.items()])
    return redirect(f"https://accounts.google.com/o/oauth2/v2/auth?{query}")


@bp.route("/google-callback")
def google_callback():
    code = request.args.get("code", "").strip()
    state = request.args.get("state", "").strip()
    saved_state = session.pop("google_oauth_state", "")
    if not code or not state or not saved_state or state != saved_state:
        flash(tr("flash.auth.google_failed"), "danger")
        return redirect(url_for("accounts.login"))

    client_id = current_app.config.get("GOOGLE_CLIENT_ID", "")
    client_secret = current_app.config.get("GOOGLE_CLIENT_SECRET", "")
    redirect_uri = _google_redirect_uri()

    try:
        token_resp = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=10,
        )
        token_data = token_resp.json() if token_resp.ok else {}
        access_token = token_data.get("access_token", "")
        if not access_token:
            raise ValueError("no_access_token")

        userinfo_resp = requests.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        info = userinfo_resp.json() if userinfo_resp.ok else {}
        email = normalize_email(info.get("email") or "")
        username = build_google_username(info.get("name") or info.get("given_name") or "GoogleUser")
        if not email:
            raise ValueError("no_email")
    except Exception:
        flash(tr("flash.auth.google_failed"), "danger")
        return redirect(url_for("accounts.login"))

    existing = find_user_by_email(email)
    if existing and existing.get("auth_provider") != "google":
        flash(tr("flash.auth.google_email_exists"), "danger")
        return redirect(url_for("accounts.login"))

    if existing and is_user_banned(existing):
        flash(tr("flash.accounts.banned"), "danger")
        return redirect(url_for("accounts.login"))

    if not existing:
        user_id = extensions.users_col.insert_one(
            {
                "username": username,
                "username_normalized": normalize_username(username),
                "email": email,
                "email_normalized": normalize_email(email),
                "password_hash": generate_password_hash(secrets.token_hex(32)),
                "is_admin": False,
                "is_root_admin": False,
                "require_password_change": False,
                "auth_provider": "google",
                "email_verified": True,
                "email_verified_at": datetime.utcnow(),
                "email_verification_sent_at": None,
                "two_factor_enabled": False,
                "two_factor_prompt_pending": False,
                "created_at": datetime.utcnow(),
            }
        ).inserted_id
        refreshed = extensions.users_col.find_one({"_id": user_id}) or {"_id": user_id}
    else:
        extensions.users_col.update_one(
            {"_id": existing["_id"]},
            {
                "$set": {
                    "email_verified": True,
                    "email_verified_at": existing.get("email_verified_at") or datetime.utcnow(),
                    "auth_provider": "google",
                    "require_password_change": False,
                    "two_factor_enabled": False,
                    "two_factor_prompt_pending": False,
                },
                "$unset": {"password_compromised_at": ""},
            },
        )
        refreshed = extensions.users_col.find_one({"_id": existing["_id"]}) or existing

    device_allowed, device_message, device_category = _enforce_device_gate(refreshed)
    if not device_allowed:
        flash(device_message, device_category or "warning")
        return redirect(url_for("accounts.login"))

    return _complete_login(refreshed)


@bp.route("/unlock-account/<token>")
def unlock_account(token):
    user, error = _load_unlock_user_from_token(token)
    if not user:
        flash(error, "danger")
        return redirect(url_for("accounts.login"))

    lock_until = user.get("login_lock_until")
    now = datetime.utcnow()
    if not lock_until or lock_until <= now:
        flash(tr("flash.accounts.unlock_not_needed"), "info")
        return redirect(url_for("accounts.login"))

    _reset_login_lock(user["_id"])
    refreshed = extensions.users_col.find_one({"_id": user["_id"]}) or user
    device_allowed, device_message, device_category = _enforce_device_gate(refreshed)
    if not device_allowed:
        flash(device_message, device_category or "warning")
        return redirect(url_for("accounts.login"))
    if refreshed.get("auth_provider") != "google" and bool(refreshed.get("two_factor_enabled", False)):
        session.clear()
        if not _issue_two_factor_code(refreshed):
            flash(tr("flash.accounts.two_factor_send_failed"), "danger")
            return redirect(url_for("accounts.login"))
        flash(tr("flash.accounts.unlock_success"), "success")
        flash(tr("flash.accounts.two_factor_code_sent"), "info")
        return redirect(url_for("accounts.two_factor_challenge"))

    try:
        begin_authenticated_session(refreshed)
    except PyMongoError:
        current_app.logger.warning("Unable to restore session after account unlock", exc_info=True)
        session.clear()
        flash(tr("flash.accounts.session_security_retry"), "warning")
        return redirect(url_for("accounts.login"))
    flash(tr("flash.accounts.unlock_success"), "success")
    return redirect(_post_login_redirect(refreshed))


@bp.route("/approve-device/<token>")
def approve_device(token):
    user, pending_entry, error = _load_device_approval_user_from_token(token)
    if not user or not pending_entry:
        flash(error or tr("flash.accounts.device_approval_invalid"), "danger")
        return redirect(url_for("accounts.login"))

    approved_context = {
        "device_hash": str(pending_entry.get("device_hash", "") or ""),
        "ua_hash": str(pending_entry.get("ua_hash", "") or ""),
        "label": str(pending_entry.get("label", "") or ""),
        "ip_prefix": str(pending_entry.get("ip_prefix", "") or ""),
    }
    try:
        remember_trusted_device(user.get("_id"), approved_context)
        safe_mongo_update_one(
            extensions.users_col,
            {"_id": user.get("_id")},
            {"$pull": {"pending_device_approvals": {"token_hash": str(pending_entry.get("token_hash", "") or "")}}},
        )
    except PyMongoError:
        current_app.logger.warning("Unable to approve trusted device", exc_info=True)
        flash(tr("flash.accounts.session_security_retry"), "warning")
        return redirect(url_for("accounts.login"))

    current_context = get_request_device_context()
    same_device = (
        str(current_context.get("device_hash", "") or "") == approved_context["device_hash"]
        and str(current_context.get("ua_hash", "") or "") == approved_context["ua_hash"]
    )
    refreshed = extensions.users_col.find_one({"_id": user.get("_id")}) or user
    if same_device:
        if refreshed.get("auth_provider") != "google" and bool(refreshed.get("two_factor_enabled", False)):
            session.clear()
            if not _issue_two_factor_code(refreshed):
                flash(tr("flash.accounts.two_factor_send_failed"), "danger")
                return redirect(url_for("accounts.login"))
            flash(tr("flash.accounts.device_approved_login"), "success")
            flash(tr("flash.accounts.two_factor_code_sent"), "info")
            return redirect(url_for("accounts.two_factor_challenge"))
        flash(tr("flash.accounts.device_approved_login"), "success")
        return _complete_login(refreshed)

    flash(tr("flash.accounts.device_approved_relogin"), "success")
    return redirect(url_for("accounts.login"))


@bp.route("/resend-verification", methods=["POST"])
def resend_verification():
    email = normalize_email(request.form.get("email", "") or session.get("pending_verification_email", ""))
    user = find_user_by_email(email) if email else None
    if not user:
        flash(tr("flash.accounts.verification_email_sent"), "success")
        return redirect(url_for("accounts.login"))
    if is_email_verified(user):
        flash(tr("flash.accounts.email_already_verified"), "info")
        return redirect(url_for("accounts.login"))

    session["pending_verification_email"] = email
    if _send_email_verification(user):
        flash(tr("flash.accounts.verification_email_sent"), "success")
    else:
        flash(tr("flash.accounts.verification_email_failed"), "warning")
    return redirect(url_for("accounts.login"))


@bp.route("/verify-email/<token>")
def verify_email(token):
    user, error = _load_verification_user_from_token(token)
    if not user:
        flash(error, "danger")
        return redirect(url_for("accounts.login"))

    if is_email_verified(user):
        flash(tr("flash.accounts.email_already_verified"), "info")
        return redirect(url_for("accounts.login"))

    extensions.users_col.update_one(
        {"_id": user["_id"]},
        {"$set": {"email_verified": True, "email_verified_at": datetime.utcnow()}},
    )
    if session.get("pending_verification_email") == user.get("email", ""):
        session.pop("pending_verification_email", None)
    flash(tr("flash.accounts.email_verified"), "success")
    return redirect(url_for("accounts.login"))


@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = normalize_email(request.form.get("email", ""))
        user = find_user_by_email(email) if email else None

        # Do not reveal auth provider details; this request type is unsupported here.
        if user and user.get("auth_provider") == "google":
            abort(501)

        sent = False
        if user:
            reset_link = _build_password_reset_link(user)
            sent = _send_password_reset_email(user.get("email", ""), user.get("username", "user"), reset_link)

        if user and not sent:
            flash(tr("flash.accounts.password_reset_email_failed"), "warning")
        else:
            flash(tr("flash.accounts.password_reset_email_sent"), "success")

        return redirect(url_for("accounts.login"))

    return render_template("accounts/forgot_password.jinja")


@bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    user, error = _load_reset_user_from_token(token)
    if not user:
        flash(error, "danger")
        return redirect(url_for("accounts.forgot_password"))

    if request.method == "POST":
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not new_password or not confirm_password:
            flash(tr("flash.accounts.fields_required"), "danger")
            return redirect(url_for("accounts.reset_password", token=token))

        ok, msg = validate_password_for_set(new_password, confirm_password, allow_unavailable=True)
        if not ok:
            flash(msg, "danger")
            return redirect(url_for("accounts.reset_password", token=token))

        extensions.users_col.update_one(
            {"_id": user["_id"]},
            {
                "$set": {
                    "password_hash": generate_password_hash(new_password),
                    "require_password_change": False,
                    "password_reset_at": datetime.utcnow(),
                    "active_sessions": [],
                    "pending_device_approvals": [],
                }
            },
        )
        _bump_session_version(user["_id"])
        flash(tr("flash.accounts.password_reset_success"), "success")
        return redirect(url_for("accounts.login"))

    return render_template("accounts/reset_password.jinja", token=token)


@bp.route("/logout", methods=["GET", "POST"])
@bp.route("/logout/", methods=["GET", "POST"])
def logout():
    user_oid = get_session_user_oid()
    if user_oid:
        user = extensions.users_col.find_one({"_id": user_oid}, {"require_password_change": 1})
        if user and user.get("require_password_change", False):
            flash(tr("flash.accounts.password_change_required"), "warning")
            return redirect(url_for("accounts.manage_account"))
        clear_current_session_binding(user_oid)

    session.clear()
    session.modified = True
    flash(tr("flash.accounts.logged_out"), "success")
    response = redirect(url_for("accounts.login"))
    response.delete_cookie(current_app.config.get("SESSION_COOKIE_NAME", "session"), path="/")
    return response


@bp.route("/account/integrations/connect/<provider>")
@login_required
def external_provider_connect(provider):
    provider = (provider or "").strip().lower()
    if provider not in SUPPORTED_EXTERNAL_PROVIDERS:
        flash(tr("flash.songs.invalid_request"), "danger")
        return redirect(url_for("accounts.manage_account"))
    if provider == "youtube" and not is_youtube_integration_enabled(True):
        flash(tr("flash.accounts.integration_disabled_by_admin"), "warning")
        return redirect(url_for("accounts.manage_account"))
    if not _external_provider_is_configured(provider):
        flash(tr("flash.accounts.integration_not_configured", provider=_external_provider_name(provider)), "warning")
        return redirect(url_for("accounts.manage_account"))

    state_value = secrets.token_urlsafe(24)
    session[f"ext_oauth_state_{provider}"] = state_value
    authorize_url = _external_build_authorize_url(provider, state_value)
    if not authorize_url:
        flash(tr("flash.accounts.integration_not_configured", provider=_external_provider_name(provider)), "warning")
        return redirect(url_for("accounts.manage_account"))
    return redirect(authorize_url)


@bp.route("/account/integrations/callback/<provider>")
@login_required
def external_provider_callback(provider):
    provider = (provider or "").strip().lower()
    if provider not in SUPPORTED_EXTERNAL_PROVIDERS:
        flash(tr("flash.songs.invalid_request"), "danger")
        return redirect(url_for("accounts.manage_account"))
    if provider == "youtube" and not is_youtube_integration_enabled(True):
        flash(tr("flash.accounts.integration_disabled_by_admin"), "warning")
        return redirect(url_for("accounts.manage_account"))

    expected_state = session.pop(f"ext_oauth_state_{provider}", "")
    received_state = (request.args.get("state", "") or "").strip()
    if not expected_state or received_state != expected_state:
        flash(tr("flash.accounts.integration_state_invalid"), "danger")
        return redirect(url_for("accounts.manage_account"))

    code = (request.args.get("code", "") or "").strip()
    if not code:
        flash(tr("flash.accounts.integration_connect_failed", provider=_external_provider_name(provider)), "danger")
        return redirect(url_for("accounts.manage_account"))

    token_data = _external_exchange_code(provider, code)
    if not token_data:
        flash(tr("flash.accounts.integration_connect_failed", provider=_external_provider_name(provider)), "danger")
        return redirect(url_for("accounts.manage_account"))

    user_oid = get_session_user_oid()
    access_token = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")
    expires_in = int(token_data.get("expires_in", 0) or 0)
    expires_at = datetime.utcnow() + timedelta(seconds=expires_in) if expires_in > 0 else None
    now = datetime.utcnow()

    extensions.external_integrations_col.update_one(
        {"user_id": user_oid, "provider": provider},
        {
            "$set": {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "scope": str(token_data.get("scope", "") or ""),
                "expires_at": expires_at,
                "updated_at": now,
            },
            "$setOnInsert": {
                "created_at": now,
                "linked_at": now,
            },
        },
        upsert=True,
    )

    ok, _err, synced_count = _sync_external_provider(user_oid, provider)
    if ok:
        flash(tr("flash.accounts.integration_connected", provider=_external_provider_name(provider), count=synced_count), "success")
    else:
        flash(tr("flash.accounts.integration_connected_sync_failed", provider=_external_provider_name(provider)), "warning")
    return redirect(url_for("accounts.manage_account"))


@bp.route("/account/integrations/sync/<provider>", methods=["POST"])
@login_required
def external_provider_sync(provider):
    provider = (provider or "").strip().lower()
    if provider not in SUPPORTED_EXTERNAL_PROVIDERS:
        flash(tr("flash.songs.invalid_request"), "danger")
        return redirect(url_for("accounts.manage_account"))
    if provider == "youtube" and not is_youtube_integration_enabled(True):
        flash(tr("flash.accounts.integration_disabled_by_admin"), "warning")
        return redirect(url_for("accounts.manage_account"))
    user_oid = get_session_user_oid()
    ok, err_msg, synced_count = _sync_external_provider(user_oid, provider)
    if not ok:
        flash(err_msg or tr("flash.accounts.integration_sync_failed", provider=_external_provider_name(provider)), "danger")
        return redirect(url_for("accounts.manage_account"))
    flash(tr("flash.accounts.integration_synced", provider=_external_provider_name(provider), count=synced_count), "success")
    return redirect(url_for("accounts.manage_account"))


@bp.route("/account/integrations/disconnect/<provider>", methods=["POST"])
@login_required
def external_provider_disconnect(provider):
    provider = (provider or "").strip().lower()
    if provider not in SUPPORTED_EXTERNAL_PROVIDERS:
        flash(tr("flash.songs.invalid_request"), "danger")
        return redirect(url_for("accounts.manage_account"))
    user_oid = get_session_user_oid()
    extensions.external_integrations_col.delete_one({"user_id": user_oid, "provider": provider})
    flash(tr("flash.accounts.integration_disconnected", provider=_external_provider_name(provider)), "success")
    return redirect(url_for("accounts.manage_account"))


def _import_external_playlist_into_local(user_oid, provider, external_playlist_id, local_playlist_id):
    try:
        now = datetime.utcnow()
        playlist_doc = extensions.external_playlists_col.find_one(
            {"user_id": user_oid, "provider": provider, "external_playlist_id": str(external_playlist_id)},
        )
        if not playlist_doc:
            extensions.playlists_col.update_one(
                {"_id": local_playlist_id},
                {"$set": {"import_status": "failed", "import_error": "external_playlist_not_found", "import_finished_at": datetime.utcnow()}},
            )
            return 0

        extensions.playlists_col.update_one(
            {"_id": local_playlist_id},
            {"$set": {"import_status": "running", "import_started_at": datetime.utcnow(), "import_error": ""}},
        )

        # Build a fast lookup for public local uploads to reuse instead of creating external duplicates.
        local_public_by_full = {}
        local_public_by_title = {}
        for row in extensions.songs_col.find(
            {"visibility": "public", "source_type": "upload"},
            {"_id": 1, "title": 1, "artist": 1},
        ):
            title_norm = _normalize_track_identity(row.get("title", ""))
            artist_norm = _normalize_track_identity(row.get("artist", ""))
            if not title_norm:
                continue
            if artist_norm:
                local_public_by_full.setdefault((title_norm, artist_norm), row.get("_id"))
            local_public_by_title.setdefault(title_norm, row.get("_id"))

        added_song_ids = []
        for track in playlist_doc.get("tracks", []) or []:
            track_title = (track.get("title") or "").strip()
            track_artist = (track.get("artist") or "").strip()
            title_norm = _normalize_track_identity(track_title)
            artist_norm = _normalize_track_identity(track_artist)

            local_match_id = None
            if title_norm and artist_norm:
                local_match_id = local_public_by_full.get((title_norm, artist_norm))
            if not local_match_id and title_norm:
                local_match_id = local_public_by_title.get(title_norm)
            if local_match_id:
                added_song_ids.append(local_match_id)
                continue

            preview_url = (track.get("preview_url") or "").strip()
            fallback_url = (track.get("url") or "").strip()
            song_source = preview_url or fallback_url
            if not song_source:
                continue
            existing = extensions.songs_col.find_one(
                {
                    "source_type": "external",
                    "source_url": song_source,
                    "created_by": user_oid,
                },
                {"_id": 1},
            )
            if existing:
                added_song_ids.append(existing["_id"])
                continue
            song_id = extensions.songs_col.insert_one(
                {
                    "title": (track_title or tr("defaults.untitled")).strip()[:200],
                    "artist": (track_artist or tr("defaults.unknown_artist")).strip()[:200],
                    "genre": "",
                    "source_type": "external",
                    "source_url": song_source,
                    "file_name": None,
                    "audio_fingerprint": "",
                    "visibility": "private",
                    "shared_with": [],
                    "lyrics_text": "",
                    "lyrics_cues": [],
                    "lyrics_source": "",
                    "lyrics_auto_sync": False,
                    "external_provider": provider,
                    "external_track_id": (track.get("external_track_id") or "").strip(),
                    "is_available": True,
                    "availability_reason": "",
                    "created_at": now,
                    "created_by": user_oid,
                }
            ).inserted_id
            added_song_ids.append(song_id)

        extensions.playlists_col.update_one(
            {"_id": local_playlist_id},
            {
                "$set": {
                    "song_ids": added_song_ids,
                    "updated_at": datetime.utcnow(),
                    "import_status": "completed",
                    "import_finished_at": datetime.utcnow(),
                    "import_added_count": len(added_song_ids),
                    "external_source_provider": provider,
                    "external_source_playlist_id": str(external_playlist_id),
                }
            },
        )
        return len(added_song_ids)
    except Exception:
        extensions.playlists_col.update_one(
            {"_id": local_playlist_id},
            {"$set": {"import_status": "failed", "import_error": "background_import_failed", "import_finished_at": datetime.utcnow()}},
        )
        return 0


@bp.route("/account/integrations/import/<provider>/<external_playlist_id>", methods=["POST"])
@login_required
def external_provider_import_playlist(provider, external_playlist_id):
    provider = (provider or "").strip().lower()
    if provider not in SUPPORTED_EXTERNAL_PROVIDERS:
        flash(tr("flash.songs.invalid_request"), "danger")
        return redirect(url_for("accounts.manage_account"))
    if provider == "youtube" and not is_youtube_integration_enabled(True):
        flash(tr("flash.accounts.integration_disabled_by_admin"), "warning")
        return redirect(url_for("accounts.manage_account"))
    user_oid = get_session_user_oid()
    playlist_doc = extensions.external_playlists_col.find_one(
        {"user_id": user_oid, "provider": provider, "external_playlist_id": str(external_playlist_id)},
    )
    if not playlist_doc:
        flash(tr("flash.accounts.integration_playlist_not_found"), "danger")
        return redirect(url_for("accounts.manage_account"))

    now = datetime.utcnow()
    playlist_name = f"[{_external_provider_name(provider)}] {(playlist_doc.get('name') or '').strip() or tr('defaults.unnamed')}"
    local_playlist_id = extensions.playlists_col.insert_one(
        {
            "name": playlist_name[:120],
            "user_id": user_oid,
            "song_ids": [],
            "visibility": "private",
            "collaborator_ids": [],
            "external_source_provider": provider,
            "external_source_playlist_id": str(external_playlist_id),
            "import_status": "pending",
            "import_started_at": None,
            "import_finished_at": None,
            "import_error": "",
            "import_total_tracks": len(playlist_doc.get("tracks", []) or []),
            "import_added_count": 0,
            "created_at": now,
            "updated_at": now,
        }
    ).inserted_id

    future = IMPORT_EXECUTOR.submit(
        _import_external_playlist_into_local,
        user_oid,
        provider,
        str(external_playlist_id),
        local_playlist_id,
    )
    try:
        added_count = int(future.result(timeout=2.8) or 0)
        flash(tr("flash.accounts.integration_playlist_imported", count=added_count), "success")
    except FutureTimeoutError:
        flash(tr("flash.accounts.integration_playlist_import_started"), "info")
    except Exception:
        extensions.playlists_col.update_one(
            {"_id": local_playlist_id},
            {"$set": {"import_status": "failed", "import_error": "background_import_failed", "import_finished_at": datetime.utcnow()}},
        )
        flash(tr("flash.accounts.integration_sync_failed", provider=_external_provider_name(provider)), "danger")
    return redirect(url_for("playlists.playlist_detail", playlist_id=str(local_playlist_id)))


@bp.route("/account/2fa/request-toggle", methods=["POST"])
@login_required
def request_two_factor_toggle():
    user_oid = get_session_user_oid()
    user = extensions.users_col.find_one({"_id": user_oid})
    if not user:
        session.clear()
        flash(tr("flash.auth.required"), "warning")
        return redirect(url_for("accounts.login"))
    if user.get("auth_provider") == "google":
        flash(tr("flash.accounts.two_factor_not_available_google"), "warning")
        return redirect(url_for("accounts.manage_account"))

    action = (request.form.get("action", "") or "").strip().lower()
    if action not in {"enable", "disable"}:
        flash(tr("flash.songs.invalid_request"), "danger")
        return redirect(url_for("accounts.manage_account"))
    target_enabled = action == "enable"
    if bool(user.get("two_factor_enabled", False)) == target_enabled:
        flash(
            tr("flash.accounts.two_factor_already_enabled" if target_enabled else "flash.accounts.two_factor_already_disabled"),
            "info",
        )
        return redirect(url_for("accounts.manage_account"))

    sent = _send_two_factor_toggle_email(user, action)
    if not sent:
        flash(tr("flash.accounts.two_factor_toggle_email_failed"), "danger")
        return redirect(url_for("accounts.manage_account"))

    extensions.users_col.update_one(
        {"_id": user_oid},
        {
            "$set": {
                "two_factor_toggle_requested_action": action,
                "two_factor_toggle_requested_at": datetime.utcnow(),
            }
        },
    )
    flash(
        tr("flash.accounts.two_factor_toggle_email_sent_enable" if target_enabled else "flash.accounts.two_factor_toggle_email_sent_disable"),
        "success",
    )
    return redirect(url_for("accounts.manage_account"))


@bp.route("/account/2fa/confirm/<token>", methods=["GET", "POST"])
def confirm_two_factor_toggle(token):
    user, action, error = _load_two_factor_toggle_user_from_token(token)
    if not user:
        if error:
            flash(error, "danger")
        return redirect(url_for("accounts.login"))

    target_enabled = action == "enable"
    if request.method == "POST":
        password = request.form.get("password", "")
        if not password:
            flash(tr("flash.accounts.fields_required"), "danger")
            return redirect(url_for("accounts.confirm_two_factor_toggle", token=token))
        if not check_password_hash(user.get("password_hash", ""), password):
            flash(tr("flash.accounts.invalid_credentials"), "danger")
            return redirect(url_for("accounts.confirm_two_factor_toggle", token=token))

        extensions.users_col.update_one(
            {"_id": user.get("_id")},
            {
                "$set": {
                    "two_factor_enabled": target_enabled,
                    "two_factor_prompt_pending": False,
                    "two_factor_updated_at": datetime.utcnow(),
                },
                "$unset": {
                    "two_factor_toggle_requested_action": "",
                    "two_factor_toggle_requested_at": "",
                },
            },
        )
        flash(tr("flash.accounts.two_factor_enabled" if target_enabled else "flash.accounts.two_factor_disabled"), "success")
        if get_session_user_oid() == user.get("_id"):
            return redirect(url_for("accounts.manage_account"))
        return redirect(url_for("accounts.login"))

    return render_template(
        "accounts/two_factor_toggle_confirm.jinja",
        token=token,
        action=action,
        masked_email=_mask_email(user.get("email", "")),
    )


@bp.route("/account/2fa/dismiss-suggestion", methods=["POST"])
@login_required
def dismiss_two_factor_suggestion():
    user_oid = get_session_user_oid()
    extensions.users_col.update_one({"_id": user_oid}, {"$set": {"two_factor_prompt_pending": False}})
    flash(tr("flash.accounts.two_factor_prompt_dismissed"), "info")
    return redirect(url_for("accounts.manage_account"))


@bp.route("/account/manage")
@login_required
def manage_account():
    user_oid = get_session_user_oid()
    user = extensions.users_col.find_one({"_id": user_oid})
    my_songs_count = extensions.songs_col.count_documents({"created_by": user_oid})
    creator_stats = _build_creator_stats(user_oid)

    blocked_song_ids = [sid for sid in (user.get("recommendation_blocked_song_ids", []) or []) if sid]
    songs_map = {
        row.get("_id"): row
        for row in extensions.songs_col.find({"_id": {"$in": blocked_song_ids}}, {"title": 1, "artist": 1})
    } if blocked_song_ids else {}

    blocked_songs = []
    for sid in blocked_song_ids:
        row = songs_map.get(sid)
        if row:
            blocked_songs.append(
                {
                    "id": str(sid),
                    "title": row.get("title", tr("defaults.untitled")),
                    "artist": row.get("artist", tr("defaults.unknown_artist")),
                    "detail_url": url_for("songs.song_detail", song_id=str(sid)),
                }
            )
        else:
            blocked_songs.append(
                {
                    "id": str(sid),
                    "title": tr("defaults.untitled"),
                    "artist": tr("defaults.unknown_artist"),
                    "detail_url": "",
                }
            )

    blocked_artists = [str(a or "").strip() for a in (user.get("recommendation_blocked_artists", []) or [])]
    blocked_artists = sorted([a for a in blocked_artists if a], key=lambda x: x.lower())

    youtube_enabled = is_youtube_integration_enabled(True)
    integration_docs = list(extensions.external_integrations_col.find({"user_id": user_oid}))
    integration_by_provider = {str(doc.get("provider", "")).strip().lower(): doc for doc in integration_docs}
    provider_rows = []
    for provider in ["youtube"]:
        info = integration_by_provider.get(provider)
        provider_rows.append(
            {
                "provider": provider,
                "name": _external_provider_name(provider),
                "configured": _external_provider_is_configured(provider),
                "disabled_by_admin": (provider == "youtube" and not youtube_enabled),
                "connected": bool(info and info.get("access_token")),
                "linked_at": info.get("linked_at") if info else None,
                "updated_at": info.get("updated_at") if info else None,
                "expires_at": info.get("expires_at") if info else None,
            }
        )

    external_playlists = []
    if youtube_enabled:
        for row in extensions.external_playlists_col.find({"user_id": user_oid, "provider": "youtube"}).sort("synced_at", -1).limit(120):
            external_playlists.append(
                {
                    "provider": row.get("provider", ""),
                    "provider_name": _external_provider_name(row.get("provider", "")),
                    "external_playlist_id": str(row.get("external_playlist_id", "")),
                    "name": row.get("name", tr("defaults.unnamed")),
                    "url": row.get("url", ""),
                    "tracks_count": int(row.get("tracks_count", 0) or 0),
                    "synced_at": row.get("synced_at"),
                }
            )

    try:
        two_factor_toggle_url = url_for("accounts.request_two_factor_toggle")
    except BuildError:
        two_factor_toggle_url = ""
    try:
        two_factor_dismiss_url = url_for("accounts.dismiss_two_factor_suggestion")
    except BuildError:
        two_factor_dismiss_url = ""

    return render_template(
        "accounts/manage.jinja",
        me={
            "id": str(user["_id"]),
            "username": user.get("username", "user"),
            "email": user.get("email", ""),
            "is_admin": bool(user.get("is_admin", False)),
            "is_root_admin": bool(user.get("is_root_admin", False)),
            "require_password_change": bool(user.get("require_password_change", False)),
            "email_verified": bool(is_email_verified(user)),
            "auth_provider": user.get("auth_provider", "local"),
            "is_google_account": user.get("auth_provider") == "google",
            "two_factor_enabled": bool(user.get("two_factor_enabled", False)),
            "two_factor_prompt_pending": bool(user.get("two_factor_prompt_pending", False)),
            "profile_url": url_for("accounts.public_profile", username=user.get("username", "user")),
        },
        my_songs_count=my_songs_count,
        creator_stats=creator_stats,
        blocked_songs=blocked_songs,
        blocked_artists=blocked_artists,
        youtube_integration_enabled=youtube_enabled,
        integration_providers=provider_rows,
        external_playlists=external_playlists,
        two_factor_toggle_url=two_factor_toggle_url,
        two_factor_dismiss_url=two_factor_dismiss_url,
        username_update_url=url_for("accounts.update_username"),
        show_two_factor_prompt=bool(
            user.get("auth_provider") != "google"
            and not bool(user.get("two_factor_enabled", False))
            and bool(user.get("two_factor_prompt_pending", False))
        ),
    )


@bp.route("/account/notifications/read-all", methods=["POST"])
@login_required
def mark_all_notifications_read():
    user_oid = get_session_user_oid()
    try:
        mark_notifications_read(user_oid)
        return jsonify({"ok": True, "items": get_user_notifications(user_oid, limit=20), "unread_count": 0})
    except PyMongoError:
        current_app.logger.warning("Unable to mark notifications as read", exc_info=True)
        return jsonify({"ok": False, "message": tr("errors.503.msg")}), 503


@bp.route("/account/update-username", methods=["POST"])
@login_required
def update_username():
    user_oid = get_session_user_oid()
    user = extensions.users_col.find_one({"_id": user_oid}, {"username": 1, "username_normalized": 1})
    if not user:
        session.clear()
        flash(tr("flash.auth.required"), "warning")
        return redirect(url_for("accounts.login"))

    new_username = (request.form.get("username", "") or "").strip()
    normalized = normalize_username(new_username)
    current_normalized = normalize_username(user.get("username", ""))

    if not username_policy_ok(new_username):
        flash(tr("flash.accounts.username_invalid"), "danger")
        return redirect(url_for("accounts.manage_account"))

    if normalized == current_normalized:
        flash(tr("flash.accounts.username_unchanged"), "info")
        return redirect(url_for("accounts.manage_account"))

    existing = extensions.users_col.find_one({"username_normalized": normalized}, {"_id": 1})
    if existing and existing.get("_id") != user_oid:
        flash(tr("flash.accounts.username_exists"), "danger")
        return redirect(url_for("accounts.manage_account"))

    try:
        safe_mongo_update_one(
            extensions.users_col,
            {"_id": user_oid},
            {"$set": {"username": new_username, "username_normalized": normalized}},
        )
    except DuplicateKeyError:
        flash(tr("flash.accounts.username_exists"), "danger")
        return redirect(url_for("accounts.manage_account"))
    except PyMongoError:
        current_app.logger.warning("Unable to update username", exc_info=True)
        flash(tr("flash.accounts.username_update_failed"), "warning")
        return redirect(url_for("accounts.manage_account"))
    flash(tr("flash.accounts.username_updated"), "success")
    return redirect(url_for("accounts.manage_account"))


@bp.route("/account/export/json")
@login_required
def export_account_json():
    user_oid = get_session_user_oid()
    payload = _build_user_export_payload(user_oid)
    if not payload:
        flash(tr("flash.songs.invalid_request"), "danger")
        return redirect(url_for("accounts.manage_account"))

    created_at = datetime.utcnow()
    extensions.data_exports_col.insert_one(
        {
            "user_id": user_oid,
            "format": "json",
            "created_at": created_at,
            "items_count": sum(len(payload.get(k, [])) for k in ["songs", "playlists", "history", "comments", "votes"]),
        }
    )

    filename = f"pulsebeat-export-{str(user_oid)}-{created_at.strftime('%Y%m%d%H%M%S')}.json"
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    return Response(
        body,
        status=200,
        mimetype="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@bp.route("/account/export/csv")
@login_required
def export_account_csv():
    user_oid = get_session_user_oid()
    payload = _build_user_export_payload(user_oid)
    if not payload:
        flash(tr("flash.songs.invalid_request"), "danger")
        return redirect(url_for("accounts.manage_account"))

    created_at = datetime.utcnow()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["entity", "entity_id", "field", "value"])

    def write_entity(entity_name, entity_id, data):
        for key, value in (data or {}).items():
            if isinstance(value, (list, dict)):
                value = json.dumps(value, ensure_ascii=False)
            writer.writerow([entity_name, entity_id, key, value])

    write_entity("user", payload.get("user", {}).get("id", ""), payload.get("user", {}))
    write_entity("preferences", payload.get("user", {}).get("id", ""), payload.get("preferences", {}))
    for row in payload.get("songs", []):
        write_entity("song", row.get("id", ""), row)
    for row in payload.get("playlists", []):
        write_entity("playlist", row.get("id", ""), row)
    for row in payload.get("history", []):
        write_entity("history", row.get("song_id", ""), row)
    for row in payload.get("comments", []):
        write_entity("comment", row.get("id", ""), row)
    for row in payload.get("votes", []):
        write_entity("vote", row.get("song_id", ""), row)

    extensions.data_exports_col.insert_one(
        {
            "user_id": user_oid,
            "format": "csv",
            "created_at": created_at,
            "items_count": sum(len(payload.get(k, [])) for k in ["songs", "playlists", "history", "comments", "votes"]),
        }
    )

    filename = f"pulsebeat-export-{str(user_oid)}-{created_at.strftime('%Y%m%d%H%M%S')}.csv"
    return Response(
        output.getvalue(),
        status=200,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@bp.route("/account/preferences/unblock-song", methods=["POST"])
@login_required
def unblock_recommendation_song():
    user_oid = get_session_user_oid()
    song_oid = parse_object_id(request.form.get("song_id", ""))
    if not song_oid:
        flash(tr("flash.songs.invalid_request"), "danger")
        return redirect(url_for("accounts.manage_account"))

    extensions.users_col.update_one(
        {"_id": user_oid},
        {"$pull": {"recommendation_blocked_song_ids": song_oid}},
    )
    flash(tr("flash.accounts.preferences_updated"), "success")
    return redirect(url_for("accounts.manage_account"))


@bp.route("/account/preferences/unblock-artist", methods=["POST"])
@login_required
def unblock_recommendation_artist():
    user_oid = get_session_user_oid()
    artist = (request.form.get("artist", "") or "").strip()
    if not artist:
        flash(tr("flash.songs.invalid_request"), "danger")
        return redirect(url_for("accounts.manage_account"))

    user = extensions.users_col.find_one({"_id": user_oid}, {"recommendation_blocked_artists": 1}) or {}
    artists = [str(item or "").strip() for item in (user.get("recommendation_blocked_artists", []) or [])]
    target = artist.lower()
    artists = [item for item in artists if item and item.lower() != target]

    extensions.users_col.update_one(
        {"_id": user_oid},
        {"$set": {"recommendation_blocked_artists": artists}},
    )
    flash(tr("flash.accounts.preferences_updated"), "success")
    return redirect(url_for("accounts.manage_account"))


@bp.route("/account/history")
@login_required
def listening_history():
    user_oid = get_session_user_oid()
    page_raw = request.args.get("page", "1").strip()
    page = max(1, int(page_raw)) if page_raw.isdigit() else 1
    per_page = int(current_app.config.get("PAGE_SIZE", 50))

    total = extensions.listening_history_col.count_documents({"user_id": user_oid})
    pages = max(1, ceil(total / per_page)) if total else 1
    page = min(page, pages)

    rows = list(
        extensions.listening_history_col.find({"user_id": user_oid})
        .sort("updated_at", -1)
        .skip((page - 1) * per_page)
        .limit(per_page)
    )

    items = []
    for row in rows:
        song = extensions.songs_col.find_one({"_id": row.get("song_id")})
        if not song or not can_access_song(song, user_oid):
            continue
        item = serialize_song(song, user_oid)
        item["url"] = song_stream_url(item["id"]) if item.get("is_audio_playable", True) else ""
        item["detail_url"] = url_for("songs.song_detail", song_id=item["id"])
        item["external_url"] = item.get("source_url", "")
        item["last_position"] = float(row.get("last_position", 0) or 0)
        item["last_duration"] = float(row.get("last_duration", 0) or 0)
        item["play_count"] = int(row.get("play_count", 0) or 0)
        items.append(item)

    return render_template(
        "accounts/history.jinja",
        items=items,
        page=page,
        pages=pages,
    )


@bp.route("/account/change-password", methods=["POST"])
@login_required
def change_password():
    user_oid = get_session_user_oid()
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")
    user = extensions.users_col.find_one({"_id": user_oid})

    if user.get("auth_provider") == "google":
        flash(tr("flash.accounts.google_password_managed"), "warning")
        return redirect(url_for("accounts.manage_account"))

    force_change = bool(user.get("require_password_change", False))

    if not new_password or not confirm_password:
        flash(tr("flash.accounts.fields_required"), "danger")
        return redirect(url_for("accounts.manage_account"))

    if not force_change and user.get("auth_provider") != "google":
        if not current_password:
            flash(tr("flash.accounts.fields_required"), "danger")
            return redirect(url_for("accounts.manage_account"))
        if not check_password_hash(user.get("password_hash", ""), current_password):
            flash(tr("flash.accounts.old_password_invalid"), "danger")
            return redirect(url_for("accounts.manage_account"))

    ok, msg = validate_password_for_set(new_password, confirm_password, allow_unavailable=True)
    if not ok:
        flash(msg, "danger")
        return redirect(url_for("accounts.manage_account"))

    try:
        safe_mongo_update_one(
            extensions.users_col,
            {"_id": user_oid},
            {
                "$set": {
                    "password_hash": generate_password_hash(new_password),
                    "require_password_change": False,
                    "auth_provider": "local",
                    "active_sessions": [],
                    "pending_device_approvals": [],
                }
            },
        )
        _bump_session_version(user_oid)
    except PyMongoError:
        current_app.logger.warning("Unable to change password securely", exc_info=True)
        flash(tr("flash.accounts.session_security_retry"), "warning")
        return redirect(url_for("accounts.manage_account"))
    refreshed = extensions.users_col.find_one({"_id": user_oid}) or {}
    try:
        begin_authenticated_session(refreshed)
    except PyMongoError:
        current_app.logger.warning("Unable to recreate session after password change", exc_info=True)
        session.clear()
        flash(tr("flash.accounts.session_security_retry"), "warning")
        return redirect(url_for("accounts.login"))
    flash(tr("flash.accounts.password_changed"), "success")
    return redirect(url_for("accounts.manage_account"))


@bp.route("/account/delete-songs", methods=["POST"])
@login_required
def delete_my_songs():
    user_oid = get_session_user_oid()
    songs = list(extensions.songs_col.find({"created_by": user_oid}))
    for song in songs:
        cleanup_song(song)
    flash(tr("flash.accounts.songs_deleted"), "success")
    return redirect(url_for("accounts.manage_account"))


@bp.route("/account/delete", methods=["POST"])
@login_required
def delete_account():
    user_oid = get_session_user_oid()
    password = request.form.get("password", "")
    delete_songs = request.form.get("delete_songs", "no") == "yes"
    user = extensions.users_col.find_one({"_id": user_oid})
    if not user:
        session.clear()
        return redirect(url_for("accounts.login"))

    if user.get("is_root_admin", False):
        flash(tr("flash.accounts.root_admin_delete_forbidden"), "danger")
        return redirect(url_for("accounts.manage_account"))

    if user.get("auth_provider") != "google":
        valid = check_password_hash(user.get("password_hash", ""), password)
        if not valid:
            flash(tr("flash.accounts.invalid_credentials"), "danger")
            return redirect(url_for("accounts.manage_account"))

    cleanup_user(user_oid, delete_songs=delete_songs)
    session.clear()
    flash(tr("flash.accounts.deleted"), "success")
    return redirect(url_for("accounts.register"))


@bp.route("/users/check-availability")
def check_availability():
    field = request.args.get("field", "").strip().lower()
    value = request.args.get("value", "")
    if field == "email":
        available = bool(normalize_email(value)) and find_user_by_email(value) is None
        return jsonify({"available": available, "message": "" if available else tr("flash.accounts.email_exists")})
    if field == "username":
        if not username_policy_ok(value):
            return jsonify({"available": False, "message": tr("flash.accounts.username_invalid")})
        normalized = normalize_username(value)
        existing = find_user_by_username(value)
        current_user_oid = get_session_user_oid()
        available = bool(normalized) and (
            existing is None or (current_user_oid is not None and existing.get("_id") == current_user_oid)
        )
        return jsonify({"available": available, "message": "" if available else tr("flash.accounts.username_exists")})
    return jsonify({"available": False, "message": tr("flash.songs.invalid_request")}), 400


@bp.route("/users/<username>")
def public_profile(username):
    from blueprints.playlists import normalize_playlist_visibility

    viewer_oid = get_session_user_oid()
    target = extensions.users_col.find_one(
        {"username_normalized": normalize_username(username)},
        {"username": 1, "created_at": 1, "is_admin": 1, "is_root_admin": 1},
    )
    if not target:
        abort(404)

    songs_query = compose_and_filters({"created_by": target["_id"]}, visible_song_filter(viewer_oid))
    songs_projection = {
        "title": 1,
        "artist": 1,
        "genre": 1,
        "visibility": 1,
        "shared_with": 1,
        "created_by": 1,
        "source_type": 1,
        "source_url": 1,
        "url": 1,
        "external_provider": 1,
        "is_available": 1,
        "availability_reason": 1,
    }
    songs = []
    for song in extensions.songs_col.find(songs_query, songs_projection).sort("created_at", -1).limit(50):
        item = serialize_song(song, viewer_oid)
        item["url"] = song_stream_url(item["id"]) if item.get("is_audio_playable", True) else ""
        item["detail_url"] = url_for("songs.song_detail", song_id=item["id"])
        item["external_url"] = item.get("source_url", "")
        songs.append(item)

    playlist_query = compose_and_filters({"user_id": target["_id"]}, youtube_playlist_visibility_clause())
    if not (viewer_oid and str(viewer_oid) == str(target["_id"])):
        access_clause = [{"visibility": {"$in": ["public", "unlisted"]}}]
        if viewer_oid:
            access_clause.append({"collaborator_ids": viewer_oid})
        playlist_query = compose_and_filters(playlist_query, {"$or": access_clause})

    playlist_projection = {"name": 1, "song_ids": 1, "visibility": 1, "collaborator_ids": 1, "user_id": 1}
    playlists = []
    for playlist in extensions.playlists_col.find(playlist_query, playlist_projection).sort("updated_at", -1).limit(50):
        playlists.append({
            "id": str(playlist["_id"]),
            "name": playlist.get("name") or tr("defaults.unnamed"),
            "song_count": len(playlist.get("song_ids", [])),
            "visibility": normalize_playlist_visibility(playlist),
            "detail_url": url_for("playlists.playlist_detail", playlist_id=str(playlist["_id"])),
        })

    subscriber_count = count_creator_subscribers(target["_id"])
    viewer_subscription = get_creator_subscription(target["_id"], viewer_oid) if viewer_oid and str(viewer_oid) != str(target["_id"]) else None
    subscriber_list = list_creator_subscribers(target["_id"]) if viewer_oid and str(viewer_oid) == str(target["_id"]) else []

    return render_template(
        "accounts/public_profile.jinja",
        profile={
            "id": str(target["_id"]),
            "username": target.get("username", "user"),
            "created_at": target.get("created_at"),
            "is_admin": bool(target.get("is_admin", False)),
            "is_root_admin": bool(target.get("is_root_admin", False)),
            "is_self": bool(viewer_oid and str(viewer_oid) == str(target["_id"])),
            "manage_url": url_for("accounts.manage_account") if viewer_oid and str(viewer_oid) == str(target["_id"]) else "",
            "subscriber_count": subscriber_count,
            "viewer_subscription": {
                "notifications_enabled": bool(viewer_subscription.get("notifications_enabled", False)),
            } if viewer_subscription else None,
        },
        songs=songs,
        playlists=playlists,
        subscriber_list=subscriber_list,
        visible_song_count=len(songs),
        visible_playlist_count=len(playlists),
        comment_count=extensions.song_comments_col.count_documents({"user_id": target["_id"]}),
    )


@bp.route("/users/<username>/subscribe", methods=["POST"])
@login_required
def subscribe_to_creator(username):
    viewer_oid = get_session_user_oid()
    target = extensions.users_col.find_one({"username_normalized": normalize_username(username)}, {"username": 1})
    if not target:
        abort(404)
    if str(target["_id"]) == str(viewer_oid):
        flash(tr("flash.songs.invalid_request"), "warning")
        return redirect(url_for("accounts.public_profile", username=target.get("username", username)))

    notifications_enabled = request.form.get("notifications_enabled") == "1"
    now = datetime.utcnow()
    try:
        result = safe_mongo_update_one(
            extensions.creator_subscriptions_col,
            {"creator_id": target["_id"], "subscriber_id": viewer_oid},
            {
                "$set": {"notifications_enabled": notifications_enabled, "updated_at": now},
                "$setOnInsert": {
                    "creator_id": target["_id"],
                    "subscriber_id": viewer_oid,
                    "created_at": now,
                },
            },
            upsert=True,
        )
    except DuplicateKeyError:
        current_app.logger.info("Duplicate creator subscription resolved by retry path", exc_info=True)
        result = safe_mongo_update_one(
            extensions.creator_subscriptions_col,
            {"creator_id": target["_id"], "subscriber_id": viewer_oid},
            {"$set": {"notifications_enabled": notifications_enabled, "updated_at": now}},
        )
    except PyMongoError:
        current_app.logger.warning("Unable to subscribe to creator", exc_info=True)
        flash(tr("flash.accounts.subscription_failed"), "warning")
        return redirect(url_for("accounts.public_profile", username=target.get("username", username)))

    if getattr(result, "upserted_id", None):
        flash(tr("flash.accounts.subscription_created"), "success")
    else:
        flash(tr("flash.accounts.subscription_updated"), "success")
    return redirect(url_for("accounts.public_profile", username=target.get("username", username)))


@bp.route("/users/<username>/unsubscribe", methods=["POST"])
@login_required
def unsubscribe_from_creator(username):
    viewer_oid = get_session_user_oid()
    target = extensions.users_col.find_one({"username_normalized": normalize_username(username)}, {"username": 1})
    if not target:
        abort(404)
    try:
        extensions.creator_subscriptions_col.delete_one({"creator_id": target["_id"], "subscriber_id": viewer_oid})
    except PyMongoError:
        current_app.logger.warning("Unable to unsubscribe from creator", exc_info=True)
        flash(tr("flash.accounts.subscription_failed"), "warning")
        return redirect(url_for("accounts.public_profile", username=target.get("username", username)))
    flash(tr("flash.accounts.subscription_removed"), "success")
    return redirect(url_for("accounts.public_profile", username=target.get("username", username)))


@bp.route("/users/suggest")
@login_required
def users_suggest():
    q = request.args.get("q", "").strip()
    if not q:
        return {"items": []}
    user_oid = get_session_user_oid()
    regex = {"$regex": re.escape(q[:80]), "$options": "i"}
    rows = list(
        extensions.users_col.find(
            {"_id": {"$ne": user_oid}, "$or": [{"username": regex}, {"email": regex}]},
            {"username": 1, "email": 1},
        ).sort("username", 1).limit(20)
    )
    return {
        "items": [
            {"id": str(u["_id"]), "username": u.get("username", "user"), "email": u.get("email", "")}
            for u in rows
        ]
    }
