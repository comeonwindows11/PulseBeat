from datetime import datetime
from math import ceil
from flask import Blueprint, flash, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

import extensions
from auth_helpers import admin_required, cleanup_user, parse_object_id
from i18n import tr

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.route("")
@admin_required
def dashboard():
    per_page = 50
    users_page_raw = request.args.get("users_page", "1").strip()
    users_page = max(1, int(users_page_raw)) if users_page_raw.isdigit() else 1
    songs_page_raw = request.args.get("songs_page", "1").strip()
    songs_page = max(1, int(songs_page_raw)) if songs_page_raw.isdigit() else 1
    comments_page_raw = request.args.get("comments_page", "1").strip()
    comments_page = max(1, int(comments_page_raw)) if comments_page_raw.isdigit() else 1

    users_total = extensions.users_col.count_documents({})
    users_pages = max(1, ceil(users_total / per_page)) if users_total else 1
    users_page = min(users_page, users_pages)
    users = list(
        extensions.users_col.find().sort("created_at", -1).skip((users_page - 1) * per_page).limit(per_page)
    )

    songs_total = extensions.songs_col.count_documents({})
    songs_pages = max(1, ceil(songs_total / per_page)) if songs_total else 1
    songs_page = min(songs_page, songs_pages)
    songs = list(
        extensions.songs_col.find().sort("created_at", -1).skip((songs_page - 1) * per_page).limit(per_page)
    )

    comments_total = extensions.song_comments_col.count_documents({})
    comments_pages = max(1, ceil(comments_total / per_page)) if comments_total else 1
    comments_page = min(comments_page, comments_pages)
    comments = list(
        extensions.song_comments_col.find()
        .sort("created_at", -1)
        .skip((comments_page - 1) * per_page)
        .limit(per_page)
    )
    return render_template(
        "admin/dashboard.jinja",
        users=users,
        songs=songs,
        comments=comments,
        users_page=users_page,
        users_pages=users_pages,
        songs_page=songs_page,
        songs_pages=songs_pages,
        comments_page=comments_page,
        comments_pages=comments_pages,
    )


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
    if password != confirm_password:
        flash(tr("flash.accounts.password_mismatch"), "danger")
        return redirect(url_for("admin.dashboard"))
    if extensions.users_col.find_one({"email": email}):
        flash(tr("flash.accounts.email_exists"), "danger")
        return redirect(url_for("admin.dashboard"))

    extensions.users_col.insert_one(
        {
            "username": username,
            "email": email,
            "password_hash": generate_password_hash(password),
            "is_admin": True,
            "created_at": datetime.utcnow(),
        }
    )
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
    cleanup_user(user_oid, delete_songs=delete_songs)
    flash(tr("flash.admin.user_deleted"), "success")
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
        extensions.song_comments_col.delete_many(
            {"$or": [{"_id": comment_oid}, {"parent_comment_id": comment_oid}]}
        )
    flash(tr("flash.admin.comment_deleted"), "success")
    return redirect(url_for("admin.dashboard"))
