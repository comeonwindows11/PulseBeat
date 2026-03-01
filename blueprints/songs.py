import os
from datetime import datetime
from math import ceil
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_from_directory, url_for

from auth_helpers import (
    VISIBILITY_VALUES,
    admin_required,
    allowed_file,
    can_access_song,
    cleanup_song,
    get_session_user_oid,
    login_required,
    parse_object_id,
    save_uploaded_file,
    serialize_song,
    song_owner_matches,
)
import extensions
from i18n import tr

bp = Blueprint("songs", __name__, url_prefix="/songs")


def song_public_data(song, user_oid):
    item = serialize_song(song, user_oid)
    item["url"] = url_for("songs.stream_song", song_id=item["id"])
    item["detail_url"] = url_for("songs.song_detail", song_id=item["id"])
    return item


def get_vote_stats(song_oid, user_oid):
    likes = extensions.song_votes_col.count_documents({"song_id": song_oid, "vote": 1})
    dislikes = extensions.song_votes_col.count_documents({"song_id": song_oid, "vote": -1})
    user_vote = 0
    if user_oid:
        row = extensions.song_votes_col.find_one({"song_id": song_oid, "user_id": user_oid})
        if row:
            user_vote = int(row.get("vote", 0))
    return likes, dislikes, user_vote


def build_comments(song_oid, user_oid, page=1, per_page=50):
    users = {str(u["_id"]): u.get("username", "user") for u in extensions.users_col.find({}, {"username": 1})}
    raw = list(extensions.song_comments_col.find({"song_id": song_oid}).sort("created_at", 1))
    by_parent = {}
    for row in raw:
        parent = str(row.get("parent_comment_id")) if row.get("parent_comment_id") else ""
        by_parent.setdefault(parent, []).append(row)

    def map_comment(row):
        comment_id = str(row["_id"])
        owner_id = row.get("user_id")
        owner_str = str(owner_id) if owner_id else ""
        is_owner = bool(user_oid and owner_str == str(user_oid))
        item = {
            "id": comment_id,
            "content": row.get("content", ""),
            "created_at": row.get("created_at"),
            "username": users.get(owner_str, tr("defaults.unnamed")),
            "is_owner": is_owner,
            "replies": [],
        }
        for child in by_parent.get(comment_id, []):
            item["replies"].append(map_comment(child))
        return item

    roots = by_parent.get("", [])
    total = len(roots)
    pages = max(1, ceil(total / per_page)) if total else 1
    if page > pages:
        page = pages
    start = (page - 1) * per_page
    end = start + per_page
    roots = roots[start:end]
    comments = [map_comment(row) for row in roots]
    return comments, pages


@bp.route("/add", methods=["POST"])
@login_required
def add_song():
    title = request.form.get("title", "").strip()
    artist = request.form.get("artist", "").strip() or tr("defaults.unknown_artist")
    song_url = request.form.get("song_url", "").strip()
    visibility = request.form.get("visibility", "public").strip().lower()
    file = request.files.get("song_file")
    shared_with_raw = request.form.getlist("shared_with")
    user_oid = get_session_user_oid()

    if not title:
        flash(tr("flash.songs.title_required"), "danger")
        return redirect(url_for("main.index"))

    if not song_url and (not file or not file.filename):
        flash(tr("flash.songs.source_required"), "danger")
        return redirect(url_for("main.index"))

    if visibility not in VISIBILITY_VALUES:
        visibility = "public"

    shared_with = []
    if visibility == "private":
        for raw_id in shared_with_raw:
            oid = parse_object_id(raw_id)
            if oid and str(oid) != str(user_oid):
                shared_with.append(oid)
        if shared_with:
            existing_ids = [
                u["_id"]
                for u in extensions.users_col.find({"_id": {"$in": shared_with}}, {"_id": 1})
            ]
            shared_with = existing_ids
        if not shared_with:
            flash(tr("flash.songs.private_need_users"), "danger")
            return redirect(url_for("main.index"))

    source_type = "external"
    source_url = song_url
    file_name = None

    if file and file.filename:
        if not allowed_file(file.filename):
            flash(tr("flash.songs.invalid_format"), "danger")
            return redirect(url_for("main.index"))
        source_type = "upload"
        source_url = None
        file_name = save_uploaded_file(file)

    extensions.songs_col.insert_one(
        {
            "title": title,
            "artist": artist,
            "source_type": source_type,
            "source_url": source_url,
            "file_name": file_name,
            "visibility": visibility,
            "shared_with": shared_with,
            "created_at": datetime.utcnow(),
            "created_by": user_oid,
        }
    )
    flash(tr("flash.songs.added"), "success")
    return redirect(url_for("main.index"))


@bp.route("/my")
@login_required
def my_songs():
    user_oid = get_session_user_oid()
    page_raw = request.args.get("page", "1").strip()
    page = max(1, int(page_raw)) if page_raw.isdigit() else 1
    per_page = int(current_app.config.get("PAGE_SIZE", 50))
    total = extensions.songs_col.count_documents({"created_by": user_oid})
    pages = max(1, ceil(total / per_page)) if total else 1
    if page > pages:
        page = pages
    skip = (page - 1) * per_page
    raw = list(
        extensions.songs_col.find({"created_by": user_oid}).sort("created_at", -1).skip(skip).limit(per_page)
    )
    songs = [song_public_data(song, user_oid) for song in raw]
    return render_template("songs/my.jinja", songs=songs, page=page, pages=pages)


@bp.route("/<song_id>")
def song_detail(song_id):
    song_oid = parse_object_id(song_id)
    if not song_oid:
        abort(404)
    song = extensions.songs_col.find_one({"_id": song_oid})
    if not song:
        abort(404)
    user_oid = get_session_user_oid()
    comments_page_raw = request.args.get("comments_page", "1").strip()
    comments_page = max(1, int(comments_page_raw)) if comments_page_raw.isdigit() else 1
    per_page = int(current_app.config.get("PAGE_SIZE", 50))
    if not can_access_song(song, user_oid):
        abort(403)

    likes, dislikes, user_vote = get_vote_stats(song_oid, user_oid)
    comments, comments_pages = build_comments(song_oid, user_oid, comments_page, per_page)
    return render_template(
        "songs/detail.jinja",
        song=song_public_data(song, user_oid),
        likes=likes,
        dislikes=dislikes,
        user_vote=user_vote,
        comments=comments,
        comments_page=comments_page,
        comments_pages=comments_pages,
        can_comment=bool(user_oid),
    )


@bp.route("/<song_id>/vote", methods=["POST"])
@login_required
def vote_song(song_id):
    song_oid = parse_object_id(song_id)
    user_oid = get_session_user_oid()
    vote_raw = request.form.get("vote", "0")
    if vote_raw not in {"1", "-1", "0"}:
        flash(tr("flash.songs.invalid_request"), "danger")
        return redirect(url_for("songs.song_detail", song_id=song_id))
    if not song_oid:
        abort(404)
    song = extensions.songs_col.find_one({"_id": song_oid})
    if not song:
        abort(404)
    if not can_access_song(song, user_oid):
        abort(403)

    vote_val = int(vote_raw)
    if vote_val == 0:
        extensions.song_votes_col.delete_one({"song_id": song_oid, "user_id": user_oid})
    else:
        extensions.song_votes_col.update_one(
            {"song_id": song_oid, "user_id": user_oid},
            {"$set": {"vote": vote_val, "updated_at": datetime.utcnow()}},
            upsert=True,
        )
    return redirect(url_for("songs.song_detail", song_id=song_id))


@bp.route("/<song_id>/comment", methods=["POST"])
@login_required
def add_comment(song_id):
    song_oid = parse_object_id(song_id)
    user_oid = get_session_user_oid()
    content = request.form.get("content", "").strip()
    parent_oid = parse_object_id(request.form.get("parent_comment_id", ""))
    if not song_oid or not content:
        flash(tr("flash.songs.invalid_request"), "danger")
        return redirect(url_for("songs.song_detail", song_id=song_id))

    song = extensions.songs_col.find_one({"_id": song_oid})
    if not song:
        abort(404)
    if not can_access_song(song, user_oid):
        abort(403)

    doc = {
        "song_id": song_oid,
        "user_id": user_oid,
        "content": content,
        "created_at": datetime.utcnow(),
    }
    if parent_oid:
        parent = extensions.song_comments_col.find_one({"_id": parent_oid, "song_id": song_oid})
        if parent:
            doc["parent_comment_id"] = parent_oid
    extensions.song_comments_col.insert_one(doc)
    return redirect(url_for("songs.song_detail", song_id=song_id))


@bp.route("/<song_id>/comment/<comment_id>/delete", methods=["POST"])
@login_required
def delete_comment(song_id, comment_id):
    song_oid = parse_object_id(song_id)
    comment_oid = parse_object_id(comment_id)
    user_oid = get_session_user_oid()
    if not song_oid or not comment_oid:
        flash(tr("flash.songs.invalid_request"), "danger")
        return redirect(url_for("songs.song_detail", song_id=song_id))

    comment = extensions.song_comments_col.find_one({"_id": comment_oid, "song_id": song_oid})
    if not comment:
        return redirect(url_for("songs.song_detail", song_id=song_id))

    can_delete = str(comment.get("user_id")) == str(user_oid)
    if not can_delete:
        flash(tr("flash.songs.delete_forbidden"), "danger")
        return redirect(url_for("songs.song_detail", song_id=song_id))

    extensions.song_comments_col.delete_many(
        {
            "$or": [
                {"_id": comment_oid},
                {"parent_comment_id": comment_oid},
            ]
        }
    )
    return redirect(url_for("songs.song_detail", song_id=song_id))


@bp.route("/<song_id>/stream")
def stream_song(song_id):
    song_oid = parse_object_id(song_id)
    if not song_oid:
        abort(404)

    song = extensions.songs_col.find_one({"_id": song_oid})
    if not song:
        abort(404)

    user_oid = get_session_user_oid()
    if not can_access_song(song, user_oid):
        abort(403)

    source_type = song.get("source_type")
    if source_type == "upload" and song.get("file_name"):
        return send_from_directory(current_app.config["UPLOAD_DIR"], song["file_name"], as_attachment=False)
    if source_type == "external" and song.get("source_url"):
        return redirect(song["source_url"])

    legacy_url = song.get("url", "")
    if legacy_url.startswith(url_for("static", filename="uploads/")):
        file_name = os.path.basename(legacy_url)
        return send_from_directory(current_app.config["UPLOAD_DIR"], file_name, as_attachment=False)
    if legacy_url:
        return redirect(legacy_url)

    abort(404)


@bp.route("/<song_id>/delete", methods=["POST"])
@login_required
def delete_song(song_id):
    song_oid = parse_object_id(song_id)
    user_oid = get_session_user_oid()
    if not song_oid or not user_oid:
        flash(tr("flash.songs.invalid_request"), "danger")
        return redirect(url_for("main.index"))

    song = extensions.songs_col.find_one({"_id": song_oid})
    if not song:
        flash(tr("flash.songs.not_found"), "danger")
        return redirect(url_for("main.index"))

    if not song_owner_matches(song, user_oid):
        flash(tr("flash.songs.delete_forbidden"), "danger")
        return redirect(url_for("main.index"))

    cleanup_song(song)
    flash(tr("flash.songs.deleted"), "success")
    return redirect(url_for("main.index"))


@bp.route("/admin/<song_id>/delete", methods=["POST"])
@admin_required
def admin_delete_song(song_id):
    song_oid = parse_object_id(song_id)
    if not song_oid:
        flash(tr("flash.songs.invalid_request"), "danger")
        return redirect(url_for("admin.dashboard"))
    song = extensions.songs_col.find_one({"_id": song_oid})
    if song:
        cleanup_song(song)
    flash(tr("flash.songs.deleted"), "success")
    return redirect(url_for("admin.dashboard"))
