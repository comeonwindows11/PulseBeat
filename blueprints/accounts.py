from datetime import datetime
from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import extensions
from auth_helpers import cleanup_song, cleanup_user, get_session_user_oid, login_required
from i18n import tr

bp = Blueprint("accounts", __name__)

ROOT_ADMIN_EMAIL = "admin@mail.com"
ROOT_ADMIN_PASSWORD = "Password123!"


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not username or not email or not password:
            flash(tr("flash.accounts.fields_required"), "danger")
            return redirect(url_for("accounts.register"))
        if password != confirm_password:
            flash(tr("flash.accounts.password_mismatch"), "danger")
            return redirect(url_for("accounts.register"))

        if extensions.users_col.find_one({"email": email}):
            flash(tr("flash.accounts.email_exists"), "danger")
            return redirect(url_for("accounts.register"))

        user_id = extensions.users_col.insert_one(
            {
                "username": username,
                "email": email,
                "password_hash": generate_password_hash(password),
                "is_admin": False,
                "created_at": datetime.utcnow(),
            }
        ).inserted_id
        session["user_id"] = str(user_id)
        flash(tr("flash.accounts.created"), "success")
        return redirect(url_for("main.index"))

    return render_template("accounts/register.jinja")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if email == ROOT_ADMIN_EMAIL and password == ROOT_ADMIN_PASSWORD:
            admin = extensions.users_col.find_one({"email": ROOT_ADMIN_EMAIL})
            if not admin:
                admin_id = extensions.users_col.insert_one(
                    {
                        "username": "RootAdmin",
                        "email": ROOT_ADMIN_EMAIL,
                        "password_hash": generate_password_hash(ROOT_ADMIN_PASSWORD),
                        "is_admin": True,
                        "created_at": datetime.utcnow(),
                    }
                ).inserted_id
                session["user_id"] = str(admin_id)
            else:
                extensions.users_col.update_one({"_id": admin["_id"]}, {"$set": {"is_admin": True}})
                session["user_id"] = str(admin["_id"])
            flash(tr("flash.accounts.logged_in"), "success")
            return redirect(url_for("main.index"))
        if email == ROOT_ADMIN_EMAIL and password != ROOT_ADMIN_PASSWORD:
            flash(tr("flash.accounts.invalid_credentials"), "danger")
            return redirect(url_for("accounts.login"))

        user = extensions.users_col.find_one({"email": email})
        if not user or not check_password_hash(user.get("password_hash", ""), password):
            flash(tr("flash.accounts.invalid_credentials"), "danger")
            return redirect(url_for("accounts.login"))

        session["user_id"] = str(user["_id"])
        flash(tr("flash.accounts.logged_in"), "success")
        return redirect(url_for("main.index"))

    return render_template("accounts/login.jinja")


@bp.route("/logout")
def logout():
    session.clear()
    flash(tr("flash.accounts.logged_out"), "success")
    return redirect(url_for("accounts.login"))


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
        },
        my_songs_count=my_songs_count,
    )


@bp.route("/account/change-password", methods=["POST"])
@login_required
def change_password():
    user_oid = get_session_user_oid()
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")
    user = extensions.users_col.find_one({"_id": user_oid})
    if user.get("email") == ROOT_ADMIN_EMAIL:
        flash(tr("flash.accounts.root_password_locked"), "danger")
        return redirect(url_for("accounts.manage_account"))

    if not current_password or not new_password or not confirm_password:
        flash(tr("flash.accounts.fields_required"), "danger")
        return redirect(url_for("accounts.manage_account"))
    if new_password != confirm_password:
        flash(tr("flash.accounts.password_mismatch"), "danger")
        return redirect(url_for("accounts.manage_account"))
    if not check_password_hash(user.get("password_hash", ""), current_password):
        flash(tr("flash.accounts.old_password_invalid"), "danger")
        return redirect(url_for("accounts.manage_account"))

    extensions.users_col.update_one(
        {"_id": user_oid},
        {"$set": {"password_hash": generate_password_hash(new_password)}},
    )
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

    valid = False
    if user.get("email") == ROOT_ADMIN_EMAIL and password == ROOT_ADMIN_PASSWORD:
        valid = True
    elif check_password_hash(user.get("password_hash", ""), password):
        valid = True
    if not valid:
        flash(tr("flash.accounts.invalid_credentials"), "danger")
        return redirect(url_for("accounts.manage_account"))

    cleanup_user(user_oid, delete_songs=delete_songs)
    session.clear()
    flash(tr("flash.accounts.deleted"), "success")
    return redirect(url_for("accounts.register"))
