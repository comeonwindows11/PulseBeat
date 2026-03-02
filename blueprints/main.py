import re
from math import ceil
from flask import Blueprint, current_app, make_response, redirect, render_template, request, url_for

from auth_helpers import (
    get_session_user_oid,
    serialize_song,
    song_stream_url,
    user_choice_list,
    visible_song_filter,
)
import extensions

bp = Blueprint("main", __name__)

SORT_MAP = {
    "date": [("created_at", -1), ("_id", -1)],
    "title": [("title", 1), ("created_at", -1)],
    "artist": [("artist", 1), ("created_at", -1)],
}


def song_to_public(song, user_oid):
    item = serialize_song(song, user_oid)
    item["url"] = song_stream_url(item["id"])
    item["detail_url"] = url_for("songs.song_detail", song_id=item["id"])
    return item


def build_recommendations(user_oid, exclude_song_ids=None, limit=20):
    exclude_song_ids = exclude_song_ids or set()
    if not user_oid:
        return []

    artist_scores = {}

    votes = list(extensions.song_votes_col.find({"user_id": user_oid, "vote": 1}, {"song_id": 1}).limit(200))
    vote_song_ids = [row.get("song_id") for row in votes if row.get("song_id")]
    for song in extensions.songs_col.find({"_id": {"$in": vote_song_ids}}, {"artist": 1}):
        artist = (song.get("artist") or "").strip()
        if artist:
            artist_scores[artist] = artist_scores.get(artist, 0) + 3

    history = list(
        extensions.listening_history_col.find({"user_id": user_oid}, {"song_id": 1, "play_count": 1})
        .sort("updated_at", -1)
        .limit(250)
    )
    history_song_ids = [row.get("song_id") for row in history if row.get("song_id")]
    history_map = {row.get("song_id"): int(row.get("play_count", 0) or 0) for row in history if row.get("song_id")}
    for song in extensions.songs_col.find({"_id": {"$in": history_song_ids}}, {"artist": 1}):
        song_id = song.get("_id")
        artist = (song.get("artist") or "").strip()
        if artist:
            artist_scores[artist] = artist_scores.get(artist, 0) + max(1, history_map.get(song_id, 0))

    top_artists = [k for k, _ in sorted(artist_scores.items(), key=lambda x: x[1], reverse=True)[:6]]

    recs = []
    picked = set(exclude_song_ids)
    if top_artists:
        query = {"$and": [visible_song_filter(user_oid), {"artist": {"$in": top_artists}}]}
        for song in extensions.songs_col.find(query).sort("created_at", -1).limit(200):
            sid = str(song["_id"])
            if sid in picked:
                continue
            recs.append(song_to_public(song, user_oid))
            picked.add(sid)
            if len(recs) >= limit:
                return recs

    query = visible_song_filter(user_oid)
    for song in extensions.songs_col.find(query).sort("created_at", -1).limit(300):
        sid = str(song["_id"])
        if sid in picked:
            continue
        recs.append(song_to_public(song, user_oid))
        picked.add(sid)
        if len(recs) >= limit:
            break

    return recs


@bp.route("/")
def index():
    q = request.args.get("q", "").strip()
    sort = request.args.get("sort", "date").strip().lower()
    if sort not in SORT_MAP:
        sort = "date"

    page_raw = request.args.get("page", "1").strip()
    page = 1
    if page_raw.isdigit():
        page = max(1, int(page_raw))

    user_oid = get_session_user_oid()
    query_parts = [visible_song_filter(user_oid)]

    if q:
        escaped = re.escape(q)
        query_parts.append(
            {
                "$or": [
                    {"title": {"$regex": escaped, "$options": "i"}},
                    {"artist": {"$regex": escaped, "$options": "i"}},
                ]
            }
        )

    query = {"$and": query_parts} if len(query_parts) > 1 else query_parts[0]
    per_page = int(current_app.config.get("PAGE_SIZE", 50))
    total = extensions.songs_col.count_documents(query)
    pages = max(1, ceil(total / per_page)) if total else 1
    if page > pages:
        page = pages

    skip = (page - 1) * per_page
    cursor = extensions.songs_col.find(query).sort(SORT_MAP[sort])
    raw_songs = list(cursor.skip(skip).limit(per_page))

    songs = [song_to_public(song, user_oid) for song in raw_songs]

    exclude_ids = {song["id"] for song in songs}
    recommended_songs = build_recommendations(user_oid, exclude_ids, limit=20)

    shareable_users = user_choice_list(user_oid) if user_oid else []

    return render_template(
        "main/index.jinja",
        songs=songs,
        recommended_songs=recommended_songs,
        shareable_users=shareable_users,
        q=q,
        sort=sort,
        page=page,
        pages=pages,
        total=total,
    )


@bp.route("/set-language", methods=["POST"])
def set_language():
    chosen = request.form.get("lang", "fr").strip().lower()
    next_url = request.form.get("next", "").strip() or request.referrer or url_for("main.index")
    if not next_url.startswith("/"):
        next_url = url_for("main.index")
    response = make_response(redirect(next_url))
    if chosen not in {"fr", "en"}:
        chosen = "fr"
    response.set_cookie("lang", chosen, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return response
