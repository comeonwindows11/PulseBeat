import os
from datetime import datetime
from flask import Flask, flash, redirect, render_template, request, url_for
from dotenv import load_dotenv

import extensions
from auth_helpers import current_user, get_session_user_oid
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

    handled_codes = [400, 401, 403, 404, 405, 408, 413, 429, 500, 502, 503, 504]
    for code in handled_codes:
        app.register_error_handler(code, make_handler(code))


def root_admin_exists():
    return extensions.users_col.count_documents({"is_admin": True, "is_root_admin": True}, limit=1) > 0


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
    app.config["GOOGLE_CLIENT_ID"] = os.getenv("GOOGLE_CLIENT_ID", "")
    app.config["GOOGLE_CLIENT_SECRET"] = os.getenv("GOOGLE_CLIENT_SECRET", "")
    app.config["GOOGLE_REDIRECT_URI"] = os.getenv("GOOGLE_REDIRECT_URI", "")

    extensions.init_mongo(app)
    now = datetime.utcnow()
    extensions.users_col.update_many({"email_verified": {"$exists": False}}, {"$set": {"email_verified": True, "email_verified_at": now}})
    extensions.users_col.update_many({"email_verification_sent_at": {"$exists": False}}, {"$set": {"email_verification_sent_at": None}})
    extensions.users_col.update_many({"auth_provider": {"$exists": False}}, {"$set": {"auth_provider": "local"}})
    os.makedirs(app.config["UPLOAD_DIR"], exist_ok=True)

    app.register_blueprint(accounts_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(songs_bp)
    app.register_blueprint(playlists_bp)
    register_error_handlers(app)

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
        user = extensions.users_col.find_one({"_id": user_oid}, {"require_password_change": 1})
        if not user or not user.get("require_password_change", False):
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

    @app.context_processor
    def inject_global_data():
        user = current_user()
        nav_playlists = []
        if user:
            user_oid = get_session_user_oid()
            raw = list(extensions.playlists_col.find({"user_id": user_oid}).sort("created_at", -1).limit(6))
            nav_playlists = [{"id": str(p["_id"]), "name": p.get("name") or t("defaults.unnamed")} for p in raw]
        return {
            "app_name": app.config["APP_NAME"],
            "current_user": user,
            "nav_playlists": nav_playlists,
            "current_lang": get_lang(),
            "t": t,
            "setup_required": not root_admin_exists(),
        }

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)

