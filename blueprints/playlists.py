from datetime import datetime
from math import ceil
from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from auth_helpers import (
    can_access_song,
    get_session_user_oid,
    login_required,
    parse_object_id,
    serialize_song,
    song_stream_url,
    visible_song_filter,
)
import extensions
from i18n import tr

bp = Blueprint("playlists", __name__, url_prefix="/playlists")


@bp.route("", methods=["GET", "POST"])
@login_required
def list_playlists():
    user_oid = get_session_user_oid()
    page_raw = request.args.get("page", "1").strip()
    page = max(1, int(page_raw)) if page_raw.isdigit() else 1
    per_page = int(current_app.config.get("PAGE_SIZE", 50))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash(tr("flash.playlists.name_required"), "danger")
            return redirect(url_for("playlists.list_playlists"))

        playlist_id = extensions.playlists_col.insert_one(
            {
                "name": name,
                "user_id": user_oid,
                "song_ids": [],
                "created_at": datetime.utcnow(),
            }
        ).inserted_id
        flash(tr("flash.playlists.created"), "success")
        return redirect(url_for("playlists.playlist_detail", playlist_id=str(playlist_id)))

    total = extensions.playlists_col.count_documents({"user_id": user_oid})
    pages = max(1, ceil(total / per_page)) if total else 1
    if page > pages:
        page = pages
    skip = (page - 1) * per_page
    raw = list(
        extensions.playlists_col.find({"user_id": user_oid}).sort("created_at", -1).skip(skip).limit(per_page)
    )
    playlists = [{"id": str(p["_id"]), "name": p.get("name") or tr("defaults.unnamed")} for p in raw]
    return render_template("playlists/list.jinja", playlists=playlists, page=page, pages=pages)


@bp.route("/<playlist_id>")
@login_required
def playlist_detail(playlist_id):
    user_oid = get_session_user_oid()
    playlist_oid = parse_object_id(playlist_id)
    if not playlist_oid:
        flash(tr("flash.playlists.invalid"), "danger")
        return redirect(url_for("playlists.list_playlists"))

    songs_page_raw = request.args.get("songs_page", "1").strip()
    songs_page = max(1, int(songs_page_raw)) if songs_page_raw.isdigit() else 1
    add_page_raw = request.args.get("add_page", "1").strip()
    add_page = max(1, int(add_page_raw)) if add_page_raw.isdigit() else 1
    per_page = int(current_app.config.get("PAGE_SIZE", 50))

    playlist = extensions.playlists_col.find_one({"_id": playlist_oid, "user_id": user_oid})
    if not playlist:
        flash(tr("flash.playlists.not_found"), "danger")
        return redirect(url_for("playlists.list_playlists"))

    song_ids = playlist.get("song_ids", [])
    songs = []
    if song_ids:
        raw_songs = list(extensions.songs_col.find({"_id": {"$in": song_ids}}))
        songs_by_id = {song["_id"]: song for song in raw_songs}
        ordered = [songs_by_id[sid] for sid in song_ids if sid in songs_by_id]
        total_playlist_songs = len(ordered)
        songs_pages = max(1, ceil(total_playlist_songs / per_page)) if total_playlist_songs else 1
        if songs_page > songs_pages:
            songs_page = songs_pages
        start = (songs_page - 1) * per_page
        end = start + per_page
        ordered = ordered[start:end]
        for song in ordered:
            if can_access_song(song, user_oid):
                item = serialize_song(song, user_oid)
                item["url"] = song_stream_url(item["id"])
                songs.append(item)
    else:
        songs_pages = 1

    add_total = extensions.songs_col.count_documents(visible_song_filter(user_oid))
    add_pages = max(1, ceil(add_total / per_page)) if add_total else 1
    if add_page > add_pages:
        add_page = add_pages
    add_skip = (add_page - 1) * per_page
    addable_raw = list(
        extensions.songs_col.find(visible_song_filter(user_oid))
        .sort("created_at", -1)
        .skip(add_skip)
        .limit(per_page)
    )
    all_songs = [
        {
            "id": str(song["_id"]),
            "title": song.get("title") or tr("defaults.untitled"),
            "artist": song.get("artist") or tr("defaults.unknown_artist"),
        }
        for song in addable_raw
        if can_access_song(song, user_oid)
    ]

    return render_template(
        "playlists/detail.jinja",
        playlist={"id": str(playlist["_id"]), "name": playlist.get("name") or tr("defaults.unnamed")},
        songs=songs,
        all_songs=all_songs,
        songs_page=songs_page,
        songs_pages=songs_pages,
        add_page=add_page,
        add_pages=add_pages,
    )


@bp.route("/<playlist_id>/add-song", methods=["POST"])
@login_required
def add_song_to_playlist(playlist_id):
    user_oid = get_session_user_oid()
    playlist_oid = parse_object_id(playlist_id)
    song_oid = parse_object_id(request.form.get("song_id", ""))
    if not playlist_oid or not song_oid:
        flash(tr("flash.songs.invalid_request"), "danger")
        return redirect(url_for("playlists.list_playlists"))

    playlist = extensions.playlists_col.find_one({"_id": playlist_oid, "user_id": user_oid})
    if not playlist:
        flash(tr("flash.playlists.not_found"), "danger")
        return redirect(url_for("playlists.list_playlists"))

    song = extensions.songs_col.find_one({"_id": song_oid})
    if not song or not can_access_song(song, user_oid):
        flash(tr("flash.playlists.song_inaccessible"), "danger")
        return redirect(url_for("playlists.playlist_detail", playlist_id=playlist_id))

    if song_oid in playlist.get("song_ids", []):
        flash(tr("flash.playlists.song_exists"), "warning")
        return redirect(url_for("playlists.playlist_detail", playlist_id=playlist_id))

    extensions.playlists_col.update_one({"_id": playlist_oid}, {"$push": {"song_ids": song_oid}})
    flash(tr("flash.playlists.song_added"), "success")
    return redirect(url_for("playlists.playlist_detail", playlist_id=playlist_id))


@bp.route("/<playlist_id>/remove-song/<song_id>", methods=["POST"])
@login_required
def remove_song_from_playlist(playlist_id, song_id):
    user_oid = get_session_user_oid()
    playlist_oid = parse_object_id(playlist_id)
    song_oid = parse_object_id(song_id)
    if not playlist_oid or not song_oid:
        flash(tr("flash.songs.invalid_request"), "danger")
        return redirect(url_for("playlists.list_playlists"))

    playlist = extensions.playlists_col.find_one({"_id": playlist_oid, "user_id": user_oid})
    if not playlist:
        flash(tr("flash.playlists.not_found"), "danger")
        return redirect(url_for("playlists.list_playlists"))

    extensions.playlists_col.update_one({"_id": playlist_oid}, {"$pull": {"song_ids": song_oid}})
    flash(tr("flash.playlists.song_removed"), "success")
    return redirect(url_for("playlists.playlist_detail", playlist_id=playlist_id))
