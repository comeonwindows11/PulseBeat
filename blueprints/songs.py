import os
from datetime import datetime
from math import ceil
from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, send_from_directory, url_for

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
    visible_song_filter,
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


def build_basic_recommendations(user_oid, current_song_oid=None, limit=20):
    artist_scores = {}

    if user_oid:
        votes = list(extensions.song_votes_col.find({"user_id": user_oid, "vote": 1}, {"song_id": 1}).limit(200))
        liked_song_ids = [row.get("song_id") for row in votes if row.get("song_id")]
        for song in extensions.songs_col.find({"_id": {"$in": liked_song_ids}}, {"artist": 1}):
            artist = (song.get("artist") or "").strip()
            if artist:
                artist_scores[artist] = artist_scores.get(artist, 0) + 3

        history = list(
            extensions.listening_history_col.find({"user_id": user_oid}, {"song_id": 1, "play_count": 1})
            .sort("updated_at", -1)
            .limit(250)
        )
        history_song_ids = [row.get("song_id") for row in history if row.get("song_id")]
        history_counts = {row.get("song_id"): int(row.get("play_count", 0) or 0) for row in history if row.get("song_id")}
        for song in extensions.songs_col.find({"_id": {"$in": history_song_ids}}, {"artist": 1}):
            artist = (song.get("artist") or "").strip()
            if artist:
                artist_scores[artist] = artist_scores.get(artist, 0) + max(1, history_counts.get(song.get("_id"), 0))

    if current_song_oid:
        current = extensions.songs_col.find_one({"_id": current_song_oid}, {"artist": 1})
        if current and current.get("artist"):
            artist = (current.get("artist") or "").strip()
            if artist:
                artist_scores[artist] = artist_scores.get(artist, 0) + 5

    top_artists = [artist for artist, _score in sorted(artist_scores.items(), key=lambda x: x[1], reverse=True)[:6]]

    recs = []
    picked = set()
    if current_song_oid:
        picked.add(str(current_song_oid))

    if top_artists:
        query = {"$and": [visible_song_filter(user_oid), {"artist": {"$in": top_artists}}]}
        for song in extensions.songs_col.find(query).sort("created_at", -1).limit(200):
            sid = str(song["_id"])
            if sid in picked:
                continue
            recs.append(song_public_data(song, user_oid))
            picked.add(sid)
            if len(recs) >= limit:
                return recs

    for song in extensions.songs_col.find(visible_song_filter(user_oid)).sort("created_at", -1).limit(300):
        sid = str(song["_id"])
        if sid in picked:
            continue
        recs.append(song_public_data(song, user_oid))
        picked.add(sid)
        if len(recs) >= limit:
            break

    return recs


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


@bp.route("/search-suggest")
def search_suggest():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"items": []})
    user_oid = get_session_user_oid()
    regex = {"$regex": q, "$options": "i"}
    query = {"$and": [visible_song_filter(user_oid), {"$or": [{"title": regex}, {"artist": regex}, {"genre": regex}]}]}
    rows = list(extensions.songs_col.find(query, {"title": 1, "artist": 1}).sort("created_at", -1).limit(15))
    return jsonify(
        {
            "items": [
                {
                    "value": f"{r.get('title', '')} - {r.get('artist', '')}".strip(" -"),
                    "title": r.get("title", ""),
                    "artist": r.get("artist", ""),
                    "song_id": str(r["_id"]),
                    "detail_url": url_for("songs.song_detail", song_id=str(r["_id"])),
                }
                for r in rows
            ]
        }
    )


@bp.route("/add", methods=["POST"])
@login_required
def add_song():
    title = request.form.get("title", "").strip()
    artist = request.form.get("artist", "").strip() or tr("defaults.unknown_artist")
    genre = request.form.get("genre", "").strip()
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
            "genre": genre,
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


@bp.route("/<song_id>/edit", methods=["POST"])
@login_required
def edit_song(song_id):
    song_oid = parse_object_id(song_id)
    user_oid = get_session_user_oid()
    if not song_oid:
        flash(tr("flash.songs.invalid_request"), "danger")
        return redirect(url_for("main.index"))

    song = extensions.songs_col.find_one({"_id": song_oid})
    if not song:
        flash(tr("flash.songs.not_found"), "danger")
        return redirect(url_for("main.index"))
    if not song_owner_matches(song, user_oid):
        flash(tr("flash.songs.delete_forbidden"), "danger")
        return redirect(url_for("songs.song_detail", song_id=song_id))

    title = request.form.get("title", "").strip()
    artist = request.form.get("artist", "").strip() or tr("defaults.unknown_artist")
    genre = request.form.get("genre", "").strip()
    if not title:
        flash(tr("flash.songs.title_required"), "danger")
        return redirect(url_for("songs.song_detail", song_id=song_id))

    extensions.songs_col.update_one(
        {"_id": song_oid},
        {"$set": {"title": title, "artist": artist, "genre": genre, "updated_at": datetime.utcnow()}},
    )
    flash(tr("flash.songs.updated"), "success")
    return redirect(url_for("songs.song_detail", song_id=song_id))


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
    recommended_songs = build_basic_recommendations(user_oid, current_song_oid=song_oid, limit=20)
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
        recommended_songs=recommended_songs,
    )


@bp.route("/recommendations")
def recommendations_api():
    user_oid = get_session_user_oid()
    current_song_oid = parse_object_id(request.args.get("song_id", ""))
    limit_raw = request.args.get("limit", "20").strip()
    limit = 20
    if limit_raw.isdigit():
        limit = max(1, min(int(limit_raw), 50))
    items = build_basic_recommendations(user_oid, current_song_oid=current_song_oid, limit=limit)
    return jsonify({"items": items})


@bp.route("/<song_id>/progress", methods=["POST"])
def update_progress(song_id):
    user_oid = get_session_user_oid()
    if not user_oid:
        return jsonify({"ok": False}), 200

    song_oid = parse_object_id(song_id)
    if not song_oid:
        return jsonify({"ok": False}), 400
    song = extensions.songs_col.find_one({"_id": song_oid})
    if not song or not can_access_song(song, user_oid):
        return jsonify({"ok": False}), 404

    payload = request.get_json(silent=True) or {}
    position = float(payload.get("position", 0) or 0)
    duration = float(payload.get("duration", 0) or 0)
    completed = bool(payload.get("completed", False))
    started = bool(payload.get("started", False))

    now = datetime.utcnow()
    existing = extensions.listening_history_col.find_one({"user_id": user_oid, "song_id": song_oid}, {"_id": 1})
    update_doc = {
        "$set": {
            "last_position": max(0.0, position),
            "last_duration": max(0.0, duration),
            "updated_at": now,
        },
        "$setOnInsert": {
            "created_at": now,
            "play_count": 0,
            "last_completed_at": None,
        },
    }

    should_inc = started or existing is None
    if should_inc:
        update_doc.setdefault("$inc", {})["play_count"] = 1
    if completed:
        update_doc["$set"]["last_completed_at"] = now
        update_doc["$set"]["last_position"] = 0

    extensions.listening_history_col.update_one(
        {"user_id": user_oid, "song_id": song_oid},
        update_doc,
        upsert=True,
    )
    return jsonify({"ok": True})


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


@bp.route("/<song_id>/report", methods=["POST"])
@login_required
def report_song(song_id):
    song_oid = parse_object_id(song_id)
    user_oid = get_session_user_oid()
    reason = request.form.get("reason", "").strip()
    if not song_oid or not reason:
        flash(tr("flash.songs.invalid_request"), "danger")
        return redirect(url_for("songs.song_detail", song_id=song_id))

    song = extensions.songs_col.find_one({"_id": song_oid})
    if not song or not can_access_song(song, user_oid):
        abort(404)

    extensions.song_reports_col.insert_one(
        {
            "reporter_id": user_oid,
            "song_id": song_oid,
            "target_type": "song",
            "target_song_id": song_oid,
            "reason": reason,
            "status": "open",
            "created_at": datetime.utcnow(),
        }
    )
    flash(tr("flash.songs.reported"), "success")
    return redirect(url_for("songs.song_detail", song_id=song_id))


@bp.route("/<song_id>/comment/<comment_id>/report", methods=["POST"])
@login_required
def report_comment(song_id, comment_id):
    song_oid = parse_object_id(song_id)
    comment_oid = parse_object_id(comment_id)
    user_oid = get_session_user_oid()
    reason = request.form.get("reason", "").strip()
    if not song_oid or not comment_oid or not reason:
        flash(tr("flash.songs.invalid_request"), "danger")
        return redirect(url_for("songs.song_detail", song_id=song_id))

    comment = extensions.song_comments_col.find_one({"_id": comment_oid, "song_id": song_oid})
    song = extensions.songs_col.find_one({"_id": song_oid})
    if not song or not comment or not can_access_song(song, user_oid):
        abort(404)

    extensions.song_reports_col.insert_one(
        {
            "reporter_id": user_oid,
            "song_id": song_oid,
            "target_type": "comment",
            "target_comment_id": comment_oid,
            "target_song_id": song_oid,
            "reason": reason,
            "status": "open",
            "created_at": datetime.utcnow(),
        }
    )
    flash(tr("flash.songs.reported"), "success")
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
    admin_user_oid = get_session_user_oid()
    if not song_oid:
        flash(tr("flash.songs.invalid_request"), "danger")
        return redirect(url_for("admin.dashboard"))
    song = extensions.songs_col.find_one({"_id": song_oid})
    if song:
        cleanup_song(song)
        create_audit_log(admin_user_oid, "delete_song", "song", song_oid, {"title": song.get("title", "")})
    flash(tr("flash.songs.deleted"), "success")
    return redirect(url_for("admin.dashboard"))



