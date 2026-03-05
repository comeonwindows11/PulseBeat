import hashlib
import html
import secrets
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from math import ceil

import re

import requests
from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, session, url_for
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


def root_admin_exists():
    return extensions.users_col.count_documents({"is_admin": True, "is_root_admin": True}, limit=1) > 0


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
        session.pop("pending_verification_email", None)
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
        session["user_id"] = str(user_id)
        session["session_token_version"] = int(created_user.get("session_token_version", 0) or 0)
    else:
        extensions.users_col.update_one(
            {"_id": existing["_id"]},
            {"$set": {"email_verified": True, "email_verified_at": existing.get("email_verified_at") or datetime.utcnow(), "auth_provider": "google", "require_password_change": False}, "$unset": {"password_compromised_at": ""}},
        )
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


@bp.route("/account/manage")
@login_required
def manage_account():
    user_oid = get_session_user_oid()
    user = extensions.users_col.find_one({"_id": user_oid})
    my_songs_count = extensions.songs_col.count_documents({"created_by": user_oid})
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
    )


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
        item["url"] = song_stream_url(item["id"])
        item["detail_url"] = url_for("songs.song_detail", song_id=item["id"])
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
        item["url"] = song_stream_url(item["id"])
        item["detail_url"] = url_for("songs.song_detail", song_id=item["id"])
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
    regex = {"$regex": q, "$options": "i"}
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
