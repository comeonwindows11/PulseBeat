import os
from flask import Flask, render_template
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

    extensions.init_mongo(app)
    os.makedirs(app.config["UPLOAD_DIR"], exist_ok=True)

    app.register_blueprint(accounts_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(songs_bp)
    app.register_blueprint(playlists_bp)
    register_error_handlers(app)

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
        }

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
