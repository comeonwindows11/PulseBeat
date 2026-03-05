import hashlib
import os
import re
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from functools import wraps

import requests
from bson import ObjectId
from flask import current_app, flash, redirect, session, url_for
from werkzeug.utils import secure_filename

import extensions
from i18n import tr

ALLOWED_EXTENSIONS = {"mp3", "wav", "ogg", "m4a"}
VISIBILITY_VALUES = {"public", "private", "unlisted"}
PASSWORD_POLICY_RE = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{6,}$")
USERNAME_POLICY_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")

KNOWN_EMAIL_PROVIDER_DOMAINS = {
    "gmail.com", "googlemail.com",
    "outlook.com", "hotmail.com", "live.com", "msn.com",
    "icloud.com", "me.com", "mac.com",
    "yahoo.com", "yahoo.ca", "yahoo.fr", "ymail.com",
    "aol.com",
    "proton.me", "protonmail.com",
    "mail.com", "gmx.com", "gmx.net",
    "zoho.com", "yandex.com", "yandex.ru",
    "qq.com",
}

DISPOSABLE_EMAIL_DOMAINS = {
    "10minutemail.com",
    "10minutemail.net",
    "guerrillamail.com",
    "mailinator.com",
    "temp-mail.org",
    "tempmail.dev",
    "tempmailo.com",
    "yopmail.com",
    "dispostable.com",
    "sharklasers.com",
    "getnada.com",
    "trashmail.com",
}

PROFANITY_TERMS = {
    "fuck",
    "fucking",
    "shit",
    "bitch",
    "asshole",
    "bastard",
    "dick",
    "motherfucker",
    "fuk",
    "f*ck",
    "merde",
    "putain",
    "connard",
    "connasse",
    "encule",
    "enculé",
    "enculee",
    "enculée",
    "salope",
    "batard",
    "bâtard",
    "nique",
    "niquer",
}

AUTO_MODERATION_BAN_THRESHOLD = 3
AUTO_MODERATION_BAN_DAYS = 36500

FEATURE_DEFAULTS_FULL = {
    "usage_mode": "full",
    "enable_password_reset": True,
    "enable_advanced_moderation": True,
    "enable_google_oauth": True,
    "enable_email_notifications": True,
}


def parse_object_id(value: str):
    try:
        return ObjectId(value)
    except Exception:
        return None


def get_session_user_oid():
    return parse_object_id(session.get("user_id", ""))


def get_app_settings():
    return dict(FEATURE_DEFAULTS_FULL)


def save_app_settings(settings: dict):
    return


def is_feature_enabled(flag_name: str, default=True):
    return True


def password_policy_ok(password: str) -> bool:
    return bool(PASSWORD_POLICY_RE.match(password or ""))


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def normalize_username(username: str) -> str:
    return (username or "").strip().lower()


def is_disposable_email(email: str) -> bool:
    normalized = normalize_email(email)
    if "@" not in normalized:
        return False

    domain = normalized.split("@", 1)[1].strip().lower()
    if not domain or "." not in domain:
        return True

    if domain in DISPOSABLE_EMAIL_DOMAINS or any(domain.endswith(f".{d}") for d in DISPOSABLE_EMAIL_DOMAINS):
        return True

    if domain in KNOWN_EMAIL_PROVIDER_DOMAINS:
        return False

    # Heuristique: certains patterns de domaines temporaires sont très fréquents.
    disposable_markers = ("temp", "trash", "10min", "minute", "mailinator", "guerrilla", "disposable", "throwaway")
    if any(marker in domain for marker in disposable_markers):
        return True

    # Dans ce projet, un domaine non reconnu est considéré à risque/jetable.
    return True


def contains_profanity(text_value: str) -> bool:
    value = (text_value or "").lower()
    if not value:
        return False
    compact = re.sub(r"\s+", " ", value)
    return any(term in compact for term in PROFANITY_TERMS)


def register_auto_moderation_violation(user_oid, source: str):
    user = extensions.users_col.find_one({"_id": user_oid}, {"username": 1, "auto_moderation_strikes": 1, "is_root_admin": 1})
    if not user:
        return {"strikes": 0, "remaining": AUTO_MODERATION_BAN_THRESHOLD, "banned": False}

    now = datetime.utcnow()
    current = int(user.get("auto_moderation_strikes", 0) or 0)
    strikes = current + 1
    remaining = max(0, AUTO_MODERATION_BAN_THRESHOLD - strikes)

    set_payload = {
        "auto_moderation_strikes": strikes,
        "auto_moderation_last_source": source,
        "auto_moderation_last_at": now,
    }

    banned = False
    if strikes >= AUTO_MODERATION_BAN_THRESHOLD and not user.get("is_root_admin", False):
        set_payload["banned_until"] = now + timedelta(days=AUTO_MODERATION_BAN_DAYS)
        set_payload["auto_banned"] = True
        banned = True

    extensions.users_col.update_one({"_id": user_oid}, {"$set": set_payload})

    username = user.get("username", "user")
    alert_message = tr(
        "moderation.admin_alert_message",
        username=username,
        source=source,
        strikes=strikes,
        remaining=remaining,
    )

    if extensions.system_status_col is not None:
        extensions.system_status_col.update_one(
            {"key": "auto_moderation"},
            {
                "$set": {
                    "key": "auto_moderation",
                    "status": "alert",
                    "message": alert_message,
                    "updated_at": now,
                    "username": username,
                    "source": source,
                    "strikes": strikes,
                    "remaining": remaining,
                    "banned": banned,
                }
            },
            upsert=True,
        )

    notify_admins(
        "email.admin_alert_subject",
        "email.admin_alert_body",
        message=alert_message,
    )

    return {"strikes": strikes, "remaining": remaining, "banned": banned}


def username_policy_ok(username: str) -> bool:
    return bool(USERNAME_POLICY_RE.match((username or "").strip()))


def _mail_configured():
    host = current_app.config.get("MAIL_HOST", "")
    sender = current_app.config.get("MAIL_FROM", "")
    return bool(current_app.config.get("MAIL_ENABLED", False) and host and sender)


def send_email_message(to_email: str, subject: str, text_body: str, html_body: str | None = None):
    if not to_email or not _mail_configured() or not is_feature_enabled("enable_email_notifications", True):
        return False

    host = current_app.config.get("MAIL_HOST", "")
    port = int(current_app.config.get("MAIL_PORT", 587))
    mail_from = current_app.config.get("MAIL_FROM", "")
    mail_user = current_app.config.get("MAIL_USERNAME", "")
    mail_pass = current_app.config.get("MAIL_PASSWORD", "")
    use_tls = bool(current_app.config.get("MAIL_USE_TLS", True))
    use_ssl = bool(current_app.config.get("MAIL_USE_SSL", False))

    msg = EmailMessage()
    msg["From"] = mail_from
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(text_body or "")
    if html_body:
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


def notify_admins(subject_key: str, body_key: str, **kwargs):
    if not is_feature_enabled("enable_email_notifications", True):
        return

    admins = list(extensions.users_col.find({"is_admin": True}, {"email": 1, "username": 1}))
    for admin in admins:
        email = admin.get("email", "")
        if not email:
            continue
        text_body = tr(body_key, **kwargs)
        send_email_message(email, tr(subject_key), text_body)


def set_password_check_status(ok: bool, message: str | None = None):
    if extensions.system_status_col is None:
        return
    now = datetime.utcnow()
    if ok:
        extensions.system_status_col.update_one(
            {"key": "password_leak_service"},
            {
                "$set": {
                    "key": "password_leak_service",
                    "status": "up",
                    "last_ok_at": now,
                    "message": "",
                }
            },
            upsert=True,
        )
    else:
        doc = extensions.system_status_col.find_one({"key": "password_leak_service"}) or {}
        last_notified_at = doc.get("last_notified_at")
        should_notify = not last_notified_at or (now - last_notified_at) > timedelta(minutes=30)

        update_payload = {
            "key": "password_leak_service",
            "status": "down",
            "last_failed_at": now,
            "message": message or "Password leak check unavailable",
        }
        if should_notify:
            update_payload["last_notified_at"] = now

        extensions.system_status_col.update_one(
            {"key": "password_leak_service"},
            {"$set": update_payload},
            upsert=True,
        )

        if should_notify:
            notify_admins(
                "email.admin_alert_subject",
                "email.admin_alert_body",
                message=update_payload["message"],
            )


def password_pwned_status(password: str, timeout_seconds: int = 10):
    sha1 = hashlib.sha1((password or "").encode("utf-8")).hexdigest().upper()
    prefix = sha1[:5]
    suffix = sha1[5:]
    url = f"https://api.pwnedpasswords.com/range/{prefix}"
    try:
        response = requests.get(
            url,
            timeout=timeout_seconds,
            headers={"User-Agent": "PulseBeat/1.0", "Add-Padding": "true"},
        )
        if response.status_code != 200:
            set_password_check_status(False, f"HTTP {response.status_code}")
            return "unavailable", 0

        set_password_check_status(True)
        for line in response.text.splitlines():
            parts = line.strip().split(":")
            if len(parts) != 2:
                continue
            if parts[0].upper() == suffix:
                try:
                    count = int(parts[1].strip())
                except Exception:
                    count = 1
                return "pwned", count
        return "safe", 0
    except Exception:
        set_password_check_status(False, "timeout_or_network_error")
        return "unavailable", 0


def is_user_banned(user):
    banned_until = user.get("banned_until")
    if not banned_until:
        return False
    return banned_until > datetime.utcnow()


def is_email_verified(user):
    if not user:
        return False
    if user.get("auth_provider") == "google":
        return True
    return bool(user.get("email_verified", False))


def current_user():
    user_oid = get_session_user_oid()
    if not user_oid:
        return None
    user = extensions.users_col.find_one({"_id": user_oid})
    if not user:
        session.clear()
        return None
    if is_user_banned(user):
        session.clear()
        return None
    if not is_email_verified(user):
        session.clear()
        return None
    return {
        "id": str(user["_id"]),
        "username": user.get("username", "user"),
        "email": user.get("email", ""),
        "is_admin": bool(user.get("is_admin", False)),
        "is_root_admin": bool(user.get("is_root_admin", False)),
        "require_password_change": bool(user.get("require_password_change", False)),
        "email_verified": bool(is_email_verified(user)),
    }


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        user_oid = get_session_user_oid()
        if not user_oid:
            session.clear()
            flash(tr("flash.auth.required"), "warning")
            return redirect(url_for("accounts.login"))

        user = extensions.users_col.find_one({"_id": user_oid})
        if not user:
            session.clear()
            flash(tr("flash.auth.required"), "warning")
            return redirect(url_for("accounts.login"))
        if is_user_banned(user):
            session.clear()
            flash(tr("flash.accounts.banned"), "danger")
            return redirect(url_for("accounts.login"))
        if not is_email_verified(user):
            session.clear()
            session["pending_verification_email"] = user.get("email", "")
            flash(tr("flash.accounts.email_not_verified"), "warning")
            return redirect(url_for("accounts.login"))
        return fn(*args, **kwargs)

    return wrapped


def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        user_oid = get_session_user_oid()
        if not user_oid:
            session.clear()
            flash(tr("flash.auth.required"), "warning")
            return redirect(url_for("accounts.login"))
        user = extensions.users_col.find_one({"_id": user_oid})
        if not user or not user.get("is_admin", False):
            flash(tr("flash.admin.forbidden"), "danger")
            return redirect(url_for("main.index"))
        if is_user_banned(user):
            session.clear()
            flash(tr("flash.accounts.banned"), "danger")
            return redirect(url_for("accounts.login"))
        if not is_email_verified(user):
            session.clear()
            session["pending_verification_email"] = user.get("email", "")
            flash(tr("flash.accounts.email_not_verified"), "warning")
            return redirect(url_for("accounts.login"))
        return fn(*args, **kwargs)

    return wrapped


def allowed_file(filename: str) -> bool:
    if "." not in filename:
        return False
    return filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def song_owner_matches(song, user_oid):
    if not user_oid:
        return False
    created_by = song.get("created_by")
    if not created_by:
        return False
    return str(created_by) == str(user_oid)


def cleanup_song(song):
    song_oid = song["_id"]
    file_name = song.get("file_name")
    if file_name:
        local_path = os.path.join(current_app.config["UPLOAD_DIR"], file_name)
        if os.path.exists(local_path):
            os.remove(local_path)
    else:
        legacy_url = song.get("url", "")
        uploads_prefix = url_for("static", filename="uploads/")
        if legacy_url.startswith(uploads_prefix):
            legacy_file = os.path.basename(legacy_url.replace(uploads_prefix, "", 1))
            legacy_path = os.path.join(current_app.config["UPLOAD_DIR"], legacy_file)
            if os.path.exists(legacy_path):
                os.remove(legacy_path)

    extensions.playlists_col.update_many({}, {"$pull": {"song_ids": song_oid}})
    extensions.song_votes_col.delete_many({"song_id": song_oid})
    extensions.song_comments_col.delete_many({"song_id": song_oid})
    extensions.listening_history_col.delete_many({"song_id": song_oid})
    extensions.song_reports_col.delete_many({"$or": [{"target_song_id": song_oid}, {"song_id": song_oid}]})
    extensions.songs_col.delete_one({"_id": song_oid})


def cleanup_user(user_oid, delete_songs=False):
    user = extensions.users_col.find_one({"_id": user_oid})
    if user and user.get("is_root_admin", False):
        return False

    if delete_songs:
        songs = list(extensions.songs_col.find({"created_by": user_oid}))
        for song in songs:
            cleanup_song(song)
    else:
        extensions.songs_col.update_many(
            {"created_by": user_oid},
            {"$set": {"created_by": None, "visibility": "public"}, "$pull": {"shared_with": user_oid}},
        )

    extensions.songs_col.update_many({}, {"$pull": {"shared_with": user_oid}})
    extensions.song_votes_col.delete_many({"user_id": user_oid})
    extensions.song_comments_col.delete_many({"user_id": user_oid})
    extensions.listening_history_col.delete_many({"user_id": user_oid})
    extensions.song_reports_col.delete_many({"reporter_id": user_oid})
    extensions.playlists_col.delete_many({"user_id": user_oid})
    extensions.users_col.delete_one({"_id": user_oid})
    return True


def normalize_visibility(song):
    visibility = song.get("visibility", "public")
    if visibility not in VISIBILITY_VALUES:
        visibility = "public"
    return visibility


def user_in_shared(song, user_oid):
    if not user_oid:
        return False
    return any(str(shared_id) == str(user_oid) for shared_id in song.get("shared_with", []))


def can_access_song(song, user_oid):
    visibility = normalize_visibility(song)
    if song_owner_matches(song, user_oid):
        return True
    if visibility == "public":
        return True
    if visibility == "unlisted":
        return True
    if visibility == "private" and user_in_shared(song, user_oid):
        return True
    return False


def visible_song_filter(user_oid):
    public_clause = {"$or": [{"visibility": "public"}, {"visibility": {"$exists": False}}]}
    if not user_oid:
        return public_clause

    return {
        "$or": [
            public_clause,
            {"created_by": user_oid},
            {"$and": [{"visibility": "private"}, {"shared_with": user_oid}]},
        ]
    }


def serialize_song(song, user_oid):
    return {
        "id": str(song["_id"]),
        "title": song.get("title") or tr("defaults.untitled"),
        "artist": song.get("artist") or tr("defaults.unknown_artist"),
        "genre": song.get("genre", "").strip(),
        "visibility": normalize_visibility(song),
        "shared_count": len(song.get("shared_with", [])),
        "can_delete": song_owner_matches(song, user_oid),
    }


def song_stream_url(song_id: str):
    return url_for("songs.stream_song", song_id=song_id)


def user_choice_list(exclude_user_oid=None):
    query = {}
    if exclude_user_oid:
        query = {"_id": {"$ne": exclude_user_oid}}
    users = list(extensions.users_col.find(query).sort("username", 1))
    return [
        {
            "id": str(user["_id"]),
            "username": user.get("username", "user"),
            "email": user.get("email", ""),
        }
        for user in users
    ]


def save_uploaded_file(file_storage):
    safe_name = secure_filename(file_storage.filename)
    stamped_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{safe_name}"
    upload_dir = current_app.config["UPLOAD_DIR"]
    file_path = os.path.join(upload_dir, stamped_name)
    file_storage.save(file_path)
    return stamped_name
