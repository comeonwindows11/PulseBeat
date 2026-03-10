import re
from math import ceil
from flask import Blueprint, current_app, make_response, redirect, render_template, request, url_for

from auth_helpers import (
    get_session_user_oid,
    parse_object_id,
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
    item["url"] = song_stream_url(item["id"]) if item.get("is_audio_playable", True) else ""
    item["detail_url"] = url_for("songs.song_detail", song_id=item["id"])
    item["external_url"] = item.get("source_url", "")
    created_at = song.get("created_at")
    if created_at:
        try:
            item["created_ts"] = float(created_at.timestamp())
        except Exception:
            item["created_ts"] = 0.0
    else:
        item["created_ts"] = 0.0
    return item


def recommendation_filters_for_user(user_oid):
    blocked_song_ids = set()
    blocked_artists = set()
    if not user_oid:
        return blocked_song_ids, blocked_artists

    user = extensions.users_col.find_one(
        {"_id": user_oid},
        {"recommendation_blocked_song_ids": 1, "recommendation_blocked_artists": 1},
    ) or {}

    for sid in user.get("recommendation_blocked_song_ids", []) or []:
        if sid:
            blocked_song_ids.add(str(sid))

    for artist in user.get("recommendation_blocked_artists", []) or []:
        value = str(artist or "").strip().lower()
        if value:
            blocked_artists.add(value)

    return blocked_song_ids, blocked_artists


def song_blocked_for_recommendations(song, blocked_song_ids, blocked_artists):
    if not song:
        return True
    sid = str(song.get("_id", ""))
    if sid and sid in blocked_song_ids:
        return True
    artist = (song.get("artist") or "").strip().lower()
    if artist and artist in blocked_artists:
        return True
    return False


def _top_artists_for_user(user_oid):
    if not user_oid:
        return []

    artist_scores = {}

    votes = list(extensions.song_votes_col.find({"user_id": user_oid, "vote": 1}, {"song_id": 1}).limit(200))
    vote_song_ids = [row.get("song_id") for row in votes if row.get("song_id")]
    if vote_song_ids:
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
    if history_song_ids:
        for song in extensions.songs_col.find({"_id": {"$in": history_song_ids}}, {"artist": 1}):
            song_id = song.get("_id")
            artist = (song.get("artist") or "").strip()
            if artist:
                artist_scores[artist] = artist_scores.get(artist, 0) + max(1, history_map.get(song_id, 0))

    return [k for k, _ in sorted(artist_scores.items(), key=lambda x: x[1], reverse=True)[:6]]


def _popular_song_ids(limit=400):
    rows = list(
        extensions.listening_history_col.aggregate(
            [
                {"$match": {"song_id": {"$exists": True}}},
                {
                    "$group": {
                        "_id": "$song_id",
                        "plays": {"$sum": {"$ifNull": ["$play_count", 0]}},
                        "updated_at": {"$max": "$updated_at"},
                    }
                },
                {"$sort": {"plays": -1, "updated_at": -1}},
                {"$limit": int(limit)},
            ]
        )
    )
    return [row.get("_id") for row in rows if row.get("_id")]


def _discovery_song_ids(limit=400, max_plays=3):
    rows = list(
        extensions.listening_history_col.aggregate(
            [
                {"$match": {"song_id": {"$exists": True}}},
                {"$group": {"_id": "$song_id", "plays": {"$sum": {"$ifNull": ["$play_count", 0]}}}},
                {"$match": {"plays": {"$lte": int(max_plays)}}},
                {"$sort": {"plays": 1}},
                {"$limit": int(limit)},
            ]
        )
    )
    return [row.get("_id") for row in rows if row.get("_id")]


def _append_rec_song(song, user_oid, picked, recs, blocked_song_ids, blocked_artists):
    if not song:
        return False
    sid = str(song.get("_id", ""))
    if not sid or sid in picked:
        return False
    if song_blocked_for_recommendations(song, blocked_song_ids, blocked_artists):
        return False
    recs.append(song_to_public(song, user_oid))
    picked.add(sid)
    return True


def build_recommendations(user_oid, exclude_song_ids=None, limit=20):
    limit = max(1, int(limit or 20))
    exclude_song_ids = set(exclude_song_ids or set())

    blocked_song_ids, blocked_artists = recommendation_filters_for_user(user_oid)
    top_artists = _top_artists_for_user(user_oid)
    popular_ids = _popular_song_ids(limit=max(200, limit * 20))
    discovery_ids = _discovery_song_ids(limit=max(200, limit * 20), max_plays=3)

    recs = []
    picked = set(exclude_song_ids)

    if user_oid:
        target_personal = max(1, int(round(limit * 0.4)))
        target_popular = max(1, int(round(limit * 0.4)))
        target_discovery = max(0, limit - target_personal - target_popular)
    else:
        target_personal = 0
        target_popular = max(1, int(round(limit * 0.6)))
        target_discovery = max(0, limit - target_popular)

    # Part 1: personalized picks from the user's strongest artist signals.
    if top_artists and target_personal > 0:
        query = {"$and": [visible_song_filter(user_oid), {"artist": {"$in": top_artists}}]}
        for song in extensions.songs_col.find(query).sort("created_at", -1).limit(300):
            if _append_rec_song(song, user_oid, picked, recs, blocked_song_ids, blocked_artists):
                if len(recs) >= target_personal:
                    break

    # Part 2: popularity picks from global listening history.
    if popular_ids and target_popular > 0:
        query = {"$and": [visible_song_filter(user_oid), {"_id": {"$in": popular_ids}}]}
        by_id = {row["_id"]: row for row in extensions.songs_col.find(query).limit(500)}
        added_popular = 0
        for sid in popular_ids:
            song = by_id.get(sid)
            if _append_rec_song(song, user_oid, picked, recs, blocked_song_ids, blocked_artists):
                added_popular += 1
                if added_popular >= target_popular or len(recs) >= limit:
                    break

    # Part 3: discovery picks (less played catalog).
    if discovery_ids and target_discovery > 0 and len(recs) < limit:
        query = {"$and": [visible_song_filter(user_oid), {"_id": {"$in": discovery_ids}}]}
        by_id = {row["_id"]: row for row in extensions.songs_col.find(query).sort("created_at", -1).limit(500)}
        added_discovery = 0
        for sid in discovery_ids:
            song = by_id.get(sid)
            if _append_rec_song(song, user_oid, picked, recs, blocked_song_ids, blocked_artists):
                added_discovery += 1
                if added_discovery >= target_discovery or len(recs) >= limit:
                    break

    # Part 4: fill remaining slots with freshest accessible songs.
    if len(recs) < limit:
        query = visible_song_filter(user_oid)
        for song in extensions.songs_col.find(query).sort("created_at", -1).limit(400):
            if _append_rec_song(song, user_oid, picked, recs, blocked_song_ids, blocked_artists):
                if len(recs) >= limit:
                    break

    return recs[:limit]


@bp.route("/")
def index():
    q = request.args.get("q", "").strip()
    selected_song_id = request.args.get("song_id", "").strip()
    sort = request.args.get("sort", "date").strip().lower()
    if sort not in SORT_MAP:
        sort = "date"

    page_raw = request.args.get("page", "1").strip()
    page = 1
    if page_raw.isdigit():
        page = max(1, int(page_raw))

    user_oid = get_session_user_oid()
    selected_song_oid = parse_object_id(selected_song_id)
    query_parts = [visible_song_filter(user_oid)]
    text_filters = []

    if q:
        escaped = re.escape(q)
        text_filters = [
            {"title": {"$regex": escaped, "$options": "i"}},
            {"artist": {"$regex": escaped, "$options": "i"}},
            {"genre": {"$regex": escaped, "$options": "i"}},
            {"lyrics_text": {"$regex": escaped, "$options": "i"}},
        ]

    if selected_song_oid and text_filters:
        query_parts.append({"$or": [{"_id": selected_song_oid}, *text_filters]})
    elif selected_song_oid:
        query_parts.append({"_id": selected_song_oid})
    elif text_filters:
        query_parts.append({"$or": text_filters})

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

    live_enabled = (not q) and sort == "date" and page == 1
    live_since = songs[0].get("created_ts", 0.0) if songs else 0.0

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
        live_enabled=live_enabled,
        live_since=live_since,
    )


@bp.route("/live-songs")
def live_songs():
    user_oid = get_session_user_oid()
    q = request.args.get("q", "").strip()
    sort = request.args.get("sort", "date").strip().lower()
    page_raw = request.args.get("page", "1").strip()
    page = max(1, int(page_raw)) if page_raw.isdigit() else 1
    since_raw = request.args.get("since", "0").strip()

    if q or sort != "date" or page != 1:
        return {"ok": True, "items": [], "next_since": float(since_raw or 0)}

    try:
        since_ts = float(since_raw or 0)
    except Exception:
        since_ts = 0.0

    query_parts = [visible_song_filter(user_oid)]
    if since_ts > 0:
        from datetime import datetime
        since_dt = datetime.utcfromtimestamp(since_ts)
        query_parts.append({"created_at": {"$gt": since_dt}})

    query = {"$and": query_parts} if len(query_parts) > 1 else query_parts[0]
    raw = list(extensions.songs_col.find(query).sort("created_at", -1).limit(50))
    items = [song_to_public(song, user_oid) for song in raw]
    items.sort(key=lambda s: s.get("created_ts", 0.0))
    next_since = since_ts
    for item in items:
        try:
            next_since = max(next_since, float(item.get("created_ts", 0.0) or 0.0))
        except Exception:
            continue
    return {"ok": True, "items": items, "next_since": next_since}


@bp.route("/set-language", methods=["POST"])
def set_language():
    chosen = request.form.get("lang", "fr").strip().lower()
    next_url = request.form.get("next", "").strip() or request.referrer or url_for("main.index")
    # Reject absolute and scheme-relative URLs to avoid open redirects.
    if (
        not next_url.startswith("/")
        or next_url.startswith("//")
        or next_url.startswith("/\\")
        or "\n" in next_url
        or "\r" in next_url
    ):
        next_url = url_for("main.index")
    response = make_response(redirect(next_url))
    if chosen not in {"fr", "en"}:
        chosen = "fr"
    response.set_cookie("lang", chosen, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return response
