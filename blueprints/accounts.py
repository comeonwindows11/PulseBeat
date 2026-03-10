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
from werkzeug.security import check_password_hash, generate_password_hash

import extensions
from auth_helpers import (
    can_access_song,
    cleanup_song,
    cleanup_user,
    is_disposable_email,
    get_session_user_oid,
    is_email_verified,
    is_youtube_integration_enabled,
    is_user_banned,
    login_required,
    normalize_email,
    normalize_username,
    parse_object_id,
    password_policy_ok,
    password_pwned_status,
    send_email_message,
    serialize_song,
    song_stream_url,
    username_policy_ok,
)
from i18n import tr

bp = Blueprint("accounts", __name__)
IMPORT_EXECUTOR = ThreadPoolExecutor(max_workers=2)


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
        extensions.users_col.update_one(
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
    extensions.users_col.update_one(
        {"_id": user["_id"]},
        {"$set": {"login_failure_count": failures}},
    )
    return {"locked": False, "minutes": 0, "remaining_attempts": remaining}


def _reset_login_lock(user_oid):
    extensions.users_col.update_one(
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
    extensions.users_col.update_one({"_id": user_oid}, {"$inc": {"session_token_version": 1}})


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
        session.clear()
        session["user_id"] = str(user["_id"])
        session["session_token_version"] = _session_version(user)
        flash(tr("flash.accounts.logged_in"), "success")
        return redirect(url_for("main.index"))

    return render_template("accounts/login.jinja", pending_verification_email=session.get("pending_verification_email", ""))


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
                "created_at": datetime.utcnow(),
            }
        ).inserted_id
        created_user = extensions.users_col.find_one({"_id": user_id}, {"session_token_version": 1}) or {}
        session.clear()
        session["user_id"] = str(user_id)
        session["session_token_version"] = int(created_user.get("session_token_version", 0) or 0)
    else:
        extensions.users_col.update_one(
            {"_id": existing["_id"]},
            {"$set": {"email_verified": True, "email_verified_at": existing.get("email_verified_at") or datetime.utcnow(), "auth_provider": "google", "require_password_change": False}, "$unset": {"password_compromised_at": ""}},
        )
        session.clear()
        session["user_id"] = str(existing["_id"])
        session["session_token_version"] = _session_version(existing)

    flash(tr("flash.accounts.logged_in"), "success")
    return redirect(url_for("main.index"))


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
    session.clear()
    session["user_id"] = str(user["_id"])
    session["session_token_version"] = _session_version(refreshed)
    flash(tr("flash.accounts.unlock_success"), "success")
    return redirect(url_for("main.index"))


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
            "profile_url": url_for("accounts.public_profile", username=user.get("username", "user")),
        },
        my_songs_count=my_songs_count,
        creator_stats=creator_stats,
        blocked_songs=blocked_songs,
        blocked_artists=blocked_artists,
        youtube_integration_enabled=youtube_enabled,
        integration_providers=provider_rows,
        external_playlists=external_playlists,
    )


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

    extensions.users_col.update_one(
        {"_id": user_oid},
        {"$set": {"password_hash": generate_password_hash(new_password), "require_password_change": False, "auth_provider": "local"}},
    )
    _bump_session_version(user_oid)
    refreshed = extensions.users_col.find_one({"_id": user_oid}, {"session_token_version": 1}) or {}
    session["session_token_version"] = int(refreshed.get("session_token_version", 0) or 0)
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
        available = bool(normalize_username(value)) and find_user_by_username(value) is None
        return jsonify({"available": available, "message": "" if available else tr("flash.accounts.username_exists")})
    return jsonify({"available": False, "message": tr("flash.songs.invalid_request")}), 400


@bp.route("/users/<username>")
def public_profile(username):
    from blueprints.playlists import can_access_playlist, normalize_playlist_visibility

    viewer_oid = get_session_user_oid()
    target = extensions.users_col.find_one({"username_normalized": normalize_username(username)})
    if not target:
        abort(404)

    songs = []
    for song in extensions.songs_col.find({"created_by": target["_id"]}).sort("created_at", -1).limit(250):
        if not can_access_song(song, viewer_oid):
            continue
        item = serialize_song(song, viewer_oid)
        item["url"] = song_stream_url(item["id"]) if item.get("is_audio_playable", True) else ""
        item["detail_url"] = url_for("songs.song_detail", song_id=item["id"])
        item["external_url"] = item.get("source_url", "")
        songs.append(item)
        if len(songs) >= 50:
            break

    playlists = []
    for playlist in extensions.playlists_col.find({"user_id": target["_id"]}).sort("updated_at", -1).limit(250):
        if not can_access_playlist(playlist, viewer_oid):
            continue
        playlists.append({
            "id": str(playlist["_id"]),
            "name": playlist.get("name") or tr("defaults.unnamed"),
            "song_count": len(playlist.get("song_ids", [])),
            "visibility": normalize_playlist_visibility(playlist),
            "detail_url": url_for("playlists.playlist_detail", playlist_id=str(playlist["_id"])),
        })
        if len(playlists) >= 50:
            break

    return render_template(
        "accounts/public_profile.jinja",
        profile={
            "username": target.get("username", "user"),
            "created_at": target.get("created_at"),
            "is_admin": bool(target.get("is_admin", False)),
            "is_root_admin": bool(target.get("is_root_admin", False)),
            "is_self": bool(viewer_oid and str(viewer_oid) == str(target["_id"])),
            "manage_url": url_for("accounts.manage_account") if viewer_oid and str(viewer_oid) == str(target["_id"]) else "",
        },
        songs=songs,
        playlists=playlists,
        visible_song_count=len(songs),
        visible_playlist_count=len(playlists),
        comment_count=extensions.song_comments_col.count_documents({"user_id": target["_id"]}),
    )


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
