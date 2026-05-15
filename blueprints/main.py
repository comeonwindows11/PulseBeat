import os
import re
import secrets
import string
from datetime import datetime, timedelta
from math import ceil
from flask import Blueprint, abort, current_app, jsonify, make_response, redirect, render_template, request, session, url_for

from auth_helpers import (
    InvalidStoredDocumentError,
    build_special_insensitive_search_pattern,
    get_session_user_oid,
    parse_object_id,
    serialize_song,
    song_stream_url,
    user_choice_list,
    validate_or_purge_document,
    visible_song_filter,
)
from i18n import get_lang
import extensions
from server_cache import cached_popular_song_ids

bp = Blueprint("main", __name__)

SORT_MAP = {
    "date": [("created_at", -1), ("_id", -1)],
    "title": [("title", 1), ("created_at", -1)],
    "artist": [("artist", 1), ("created_at", -1)],
}

QUEUE_ROOM_CODE_CHARS = string.ascii_uppercase + string.digits


def song_to_public(song, user_oid):
    valid_song = validate_or_purge_document("songs", song, context="main.song_to_public")
    if not valid_song:
        return None
    try:
        item = serialize_song(valid_song, user_oid)
    except InvalidStoredDocumentError:
        return None
    item["url"] = song_stream_url(item["id"]) if item.get("is_audio_playable", True) else ""
    item["detail_url"] = url_for("songs.song_detail", song_id=item["id"])
    item["external_url"] = item.get("source_url", "")
    created_at = valid_song.get("created_at")
    if created_at:
        try:
            item["created_ts"] = float(created_at.timestamp())
        except Exception:
            item["created_ts"] = 0.0
    else:
        item["created_ts"] = 0.0
    return item


def _queue_rooms_col():
    return extensions.queue_rooms_col


def _new_queue_room_code():
    for _ in range(12):
        code = "".join(secrets.choice(QUEUE_ROOM_CODE_CHARS) for _ in range(6))
        if not _queue_rooms_col().find_one({"code": code}, {"_id": 1}):
            return code
    return "".join(secrets.choice(QUEUE_ROOM_CODE_CHARS) for _ in range(8))


def _sanitize_queue_item(item):
    if not isinstance(item, dict):
        return None
    song_id = str(item.get("id", "") or "").strip()
    title = str(item.get("title", "") or "").strip()
    if not song_id or not title:
        return None
    return {
        "id": song_id[:80],
        "title": title[:220],
        "artist": str(item.get("artist", "") or "").strip()[:220],
        "url": str(item.get("url", "") or "").strip()[:500],
        "detail_url": str(item.get("detail_url", "") or "").strip()[:500],
        "source_type": str(item.get("source_type", "") or "").strip()[:80],
        "source_url": str(item.get("source_url", "") or "").strip()[:500],
        "external_provider": str(item.get("external_provider", "") or "").strip()[:80],
        "youtube_video_id": str(item.get("youtube_video_id", "") or "").strip()[:120],
        "playback_mode": str(item.get("playback_mode", "") or "").strip()[:80],
        "is_available": item.get("is_available") is not False,
        "is_audio_playable": item.get("is_audio_playable") is not False,
        "visibility": str(item.get("visibility", "") or "").strip()[:80],
    }


def _sanitize_queue_items(items):
    seen = set()
    out = []
    for raw in items if isinstance(items, list) else []:
        item = _sanitize_queue_item(raw)
        if not item:
            continue
        sid = item["id"]
        if sid in seen:
            continue
        seen.add(sid)
        out.append(item)
        if len(out) >= 80:
            break
    return out


def _queue_items_for_viewer(items, user_oid):
    object_ids = []
    order = []
    for item in items if isinstance(items, list) else []:
        song_oid = parse_object_id(str((item or {}).get("id", "") or ""))
        if not song_oid:
            continue
        object_ids.append(song_oid)
        order.append(str(song_oid))
    if not object_ids:
        return []

    query = {"$and": [visible_song_filter(user_oid), {"_id": {"$in": object_ids}}]}
    by_id = {
        str(song["_id"]): song
        for song in extensions.songs_col.find(query)
    }
    visible_items = []
    seen = set()
    for sid in order:
        if sid in seen:
            continue
        seen.add(sid)
        item = song_to_public(by_id.get(sid), user_oid)
        if item:
            visible_items.append(item)
    return visible_items


def _queue_room_actor(user_oid):
    if user_oid:
        user = extensions.users_col.find_one({"_id": user_oid}, {"username": 1, "email": 1}) or {}
        return {
            "id": str(user_oid),
            "name": str(user.get("username") or user.get("email") or "Utilisateur").strip()[:80],
        }

    guest_id = session.get("queue_room_guest_id")
    if not guest_id:
        guest_id = secrets.token_urlsafe(6)
        session["queue_room_guest_id"] = guest_id
    return {"id": f"guest:{guest_id}", "name": "Invité"}


def _serialize_queue_room_timestamp(value):
    return value.isoformat() if value else ""


def _sanitize_queue_room_events(events):
    out = []
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict):
            continue
        out.append(
            {
                "id": str(event.get("id", "") or "")[:40],
                "type": str(event.get("type", "") or "")[:40],
                "actor_id": str(event.get("actor_id", "") or "")[:120],
                "actor_name": str(event.get("actor_name", "") or "Utilisateur")[:80],
                "created_at": _serialize_queue_room_timestamp(event.get("created_at")),
            }
        )
    return out[-40:]


def _sanitize_queue_room_chat(messages):
    out = []
    for message in messages if isinstance(messages, list) else []:
        if not isinstance(message, dict):
            continue
        body = str(message.get("body", "") or "").strip()
        if not body:
            continue
        out.append(
            {
                "id": str(message.get("id", "") or "")[:40],
                "actor_id": str(message.get("actor_id", "") or "")[:120],
                "actor_name": str(message.get("actor_name", "") or "Utilisateur")[:80],
                "body": body[:500],
                "created_at": _serialize_queue_room_timestamp(message.get("created_at")),
            }
        )
    return out[-60:]


def _sanitize_queue_room_typing(typing):
    now = datetime.utcnow()
    out = []
    for item in typing if isinstance(typing, list) else []:
        if not isinstance(item, dict):
            continue
        expires_at = item.get("expires_at")
        if expires_at and expires_at <= now:
            continue
        actor_id = str(item.get("id", "") or "")[:120]
        if not actor_id:
            continue
        out.append(
            {
                "id": actor_id,
                "name": str(item.get("name", "") or "Utilisateur")[:80],
                "expires_at": _serialize_queue_room_timestamp(expires_at),
            }
        )
    return out[-12:]


def _queue_room_participant_count(room):
    participants = room.get("participants", []) if isinstance(room, dict) else []
    if not isinstance(participants, list):
        return 0
    return len({str(item.get("id", "") or "") for item in participants if isinstance(item, dict) and item.get("id")})


def _queue_room_owner_id(room):
    owner_id = str((room or {}).get("owner_actor_id", "") or "").strip()
    if owner_id:
        return owner_id
    created_by = (room or {}).get("created_by")
    return str(created_by) if created_by else ""


def _queue_room_closed_payload(room, actor):
    closed_by = str((room or {}).get("closed_by_name", "") or "Le propriétaire").strip()
    return {
        "ok": False,
        "closed": True,
        "code": (room or {}).get("code", ""),
        "actor_id": actor["id"],
        "message": f"{closed_by} a fermé la file live.",
    }


def _touch_queue_room_participant(clean_code, room, actor, heartbeat=False):
    participants = room.get("participants", []) if isinstance(room, dict) else []
    participant_ids = {
        str(item.get("id", "") or "")
        for item in participants if isinstance(item, dict)
    }
    now = datetime.utcnow()
    if actor["id"] in participant_ids:
        if heartbeat:
            _queue_rooms_col().update_one(
                {"code": clean_code, "participants.id": actor["id"]},
                {"$set": {"participants.$.last_seen_at": now}},
            )
        return

    event = {
        "id": secrets.token_hex(8),
        "type": "join",
        "actor_id": actor["id"],
        "actor_name": actor["name"],
        "created_at": now,
    }
    _queue_rooms_col().update_one(
        {"code": clean_code},
        {
            "$push": {
                "participants": {
                    "id": actor["id"],
                    "name": actor["name"],
                    "joined_at": now,
                    "last_seen_at": now,
                },
                "events": {"$each": [event], "$slice": -40},
            },
            "$set": {"updated_at": now},
        },
    )


def _set_queue_room_typing(clean_code, actor, typing):
    now = datetime.utcnow()
    _queue_rooms_col().update_one(
        {"code": clean_code},
        {
            "$pull": {
                "typing": {
                    "$or": [
                        {"id": actor["id"]},
                        {"expires_at": {"$lte": now}},
                    ]
                }
            },
            "$set": {"updated_at": now},
        },
    )
    if typing:
        _queue_rooms_col().update_one(
            {"code": clean_code},
            {
                "$push": {
                    "typing": {
                        "$each": [
                            {
                                "id": actor["id"],
                                "name": actor["name"],
                                "expires_at": now + timedelta(seconds=5),
                            }
                        ],
                        "$slice": -12,
                    }
                },
                "$set": {"updated_at": now},
            },
        )
    return _queue_rooms_col().find_one({"code": clean_code})


def _queue_room_response(room, user_oid):
    actor = _queue_room_actor(user_oid)
    if room.get("closed"):
        return _queue_room_closed_payload(room, actor)

    queue = _queue_items_for_viewer(room.get("queue", []) or [], user_oid)
    stored_index = int(room.get("index", 0) or 0)
    index = max(0, min(stored_index, len(queue) - 1)) if queue else 0
    updated_at = room.get("updated_at")
    return {
        "ok": True,
        "code": room.get("code", ""),
        "queue": queue,
        "index": index,
        "updated_at": updated_at.isoformat() if updated_at else "",
        "actor_id": actor["id"],
        "is_owner": actor["id"] == _queue_room_owner_id(room),
        "participant_count": _queue_room_participant_count(room),
        "events": _sanitize_queue_room_events(room.get("events", []) or []),
        "chat": _sanitize_queue_room_chat(room.get("chat", []) or []),
        "typing": _sanitize_queue_room_typing(room.get("typing", []) or []),
    }


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

    votes = [
        row
        for row in (
            validate_or_purge_document("song_votes", item, context="main._top_artists_for_user.vote")
            for item in extensions.song_votes_col.find({"user_id": user_oid, "vote": 1}, {"song_id": 1}).limit(200)
        )
        if row
    ]
    vote_song_ids = [row.get("song_id") for row in votes if row.get("song_id")]
    if vote_song_ids:
        for song in extensions.songs_col.find({"_id": {"$in": vote_song_ids}}, {"artist": 1}):
            artist = (song.get("artist") or "").strip()
            if artist:
                artist_scores[artist] = artist_scores.get(artist, 0) + 3

    history = [
        row
        for row in (
            validate_or_purge_document("listening_history", item, context="main._top_artists_for_user.history")
            for item in extensions.listening_history_col.find({"user_id": user_oid}, {"song_id": 1, "play_count": 1})
            .sort("updated_at", -1)
            .limit(250)
        )
        if row
    ]
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
    def builder(safe_limit):
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
                    {"$limit": int(safe_limit)},
                ]
            )
        )
        return [row.get("_id") for row in rows if row.get("_id")]

    ids = cached_popular_song_ids(current_app, limit, builder)
    return [parse_object_id(value) for value in ids if parse_object_id(value)]


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
    item = song_to_public(song, user_oid)
    if not item:
        return False
    recs.append(item)
    picked.add(sid)
    return True


@bp.route("/license")
def license_page():
    preferred_lang = get_lang()
    preferred_filename = "LICENSE.en" if preferred_lang == "en" else "LICENSE"
    fallback_filename = "LICENSE"
    license_path = os.path.join(current_app.root_path, preferred_filename)
    if not os.path.isfile(license_path):
        license_path = os.path.join(current_app.root_path, fallback_filename)
    if not os.path.isfile(license_path):
        abort(404)
    try:
        with open(license_path, "r", encoding="utf-8") as handle:
            license_text = handle.read().strip()
    except OSError:
        abort(404)
    return render_template("main/license.jinja", license_text=license_text, license_lang=preferred_lang)


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


@bp.route("/queue-rooms", methods=["POST"])
def create_queue_room():
    user_oid = get_session_user_oid()
    payload = request.get_json(silent=True) or {}
    items = _sanitize_queue_items(payload.get("queue", []))
    index = int(payload.get("index", 0) or 0)
    index = max(0, min(index, len(items) - 1)) if items else 0
    now = datetime.utcnow()
    code = _new_queue_room_code()
    actor = _queue_room_actor(user_oid)
    _queue_rooms_col().insert_one(
        {
            "code": code,
            "created_by": user_oid,
            "owner_actor_id": actor["id"],
            "created_at": now,
            "updated_at": now,
            "queue": items,
            "index": index,
            "title": str(payload.get("title", "") or "PulseBeat session").strip()[:120],
            "participants": [
                {
                    "id": actor["id"],
                    "name": actor["name"],
                    "joined_at": now,
                    "last_seen_at": now,
                }
            ],
            "events": [],
            "chat": [],
            "typing": [],
        }
    )
    room = _queue_rooms_col().find_one({"code": code}) or {"code": code, "queue": items, "index": index, "updated_at": now}
    return jsonify(_queue_room_response(room, user_oid))


@bp.route("/queue-rooms/<code>", methods=["GET", "POST"])
def queue_room(code):
    user_oid = get_session_user_oid()
    clean_code = re.sub(r"[^A-Z0-9]", "", str(code or "").upper())[:12]
    if not clean_code:
        return jsonify({"ok": False}), 404
    room = _queue_rooms_col().find_one({"code": clean_code})
    if not room:
        return jsonify({"ok": False}), 404
    if room.get("closed"):
        return jsonify(_queue_room_closed_payload(room, _queue_room_actor(user_oid)))
    actor = _queue_room_actor(user_oid)
    _touch_queue_room_participant(clean_code, room, actor)
    room = _queue_rooms_col().find_one({"code": clean_code}) or room

    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
        if room.get("closed"):
            return jsonify(_queue_room_closed_payload(room, actor))
        items = _sanitize_queue_items(payload.get("queue", []))
        index = int(payload.get("index", 0) or 0)
        index = max(0, min(index, len(items) - 1)) if items else 0
        _queue_rooms_col().update_one(
            {"code": clean_code},
            {"$set": {"queue": items, "index": index, "updated_at": datetime.utcnow()}},
        )
        room = _queue_rooms_col().find_one({"code": clean_code}) or {"code": clean_code, "queue": items, "index": index, "updated_at": datetime.utcnow()}
        return jsonify(_queue_room_response(room, user_oid))

    return jsonify(_queue_room_response(room, user_oid))


@bp.route("/queue-rooms/<code>/chat", methods=["POST"])
def queue_room_chat(code):
    user_oid = get_session_user_oid()
    clean_code = re.sub(r"[^A-Z0-9]", "", str(code or "").upper())[:12]
    if not clean_code:
        return jsonify({"ok": False}), 404
    room = _queue_rooms_col().find_one({"code": clean_code})
    if not room:
        return jsonify({"ok": False}), 404
    if room.get("closed"):
        return jsonify(_queue_room_closed_payload(room, _queue_room_actor(user_oid)))

    payload = request.get_json(silent=True) or {}
    body = str(payload.get("message", "") or "").strip()
    if not body:
        return jsonify({"ok": False, "message": "Message vide."}), 400

    actor = _queue_room_actor(user_oid)
    _touch_queue_room_participant(clean_code, room, actor, heartbeat=True)
    now = datetime.utcnow()
    message = {
        "id": secrets.token_hex(8),
        "actor_id": actor["id"],
        "actor_name": actor["name"],
        "body": body[:500],
        "created_at": now,
    }
    _queue_rooms_col().update_one(
        {"code": clean_code},
        {
            "$push": {"chat": {"$each": [message], "$slice": -60}},
            "$set": {"updated_at": now},
        },
    )
    room = _queue_rooms_col().find_one({"code": clean_code}) or room
    return jsonify(_queue_room_response(room, user_oid))


@bp.route("/queue-rooms/<code>/typing", methods=["POST"])
def queue_room_typing(code):
    user_oid = get_session_user_oid()
    clean_code = re.sub(r"[^A-Z0-9]", "", str(code or "").upper())[:12]
    if not clean_code:
        return jsonify({"ok": False}), 404
    room = _queue_rooms_col().find_one({"code": clean_code})
    if not room:
        return jsonify({"ok": False}), 404
    if room.get("closed"):
        return jsonify(_queue_room_closed_payload(room, _queue_room_actor(user_oid)))

    payload = request.get_json(silent=True) or {}
    actor = _queue_room_actor(user_oid)
    _touch_queue_room_participant(clean_code, room, actor, heartbeat=True)
    room = _set_queue_room_typing(clean_code, actor, bool(payload.get("typing")))
    return jsonify(_queue_room_response(room or {}, user_oid))


@bp.route("/queue-rooms/<code>/close", methods=["POST"])
def close_queue_room(code):
    user_oid = get_session_user_oid()
    clean_code = re.sub(r"[^A-Z0-9]", "", str(code or "").upper())[:12]
    if not clean_code:
        return jsonify({"ok": False}), 404
    room = _queue_rooms_col().find_one({"code": clean_code})
    if not room:
        return jsonify({"ok": False}), 404

    actor = _queue_room_actor(user_oid)
    if actor["id"] != _queue_room_owner_id(room):
        return jsonify({"ok": False, "message": "Seul le propriétaire peut fermer cette file live."}), 403

    now = datetime.utcnow()
    _queue_rooms_col().update_one(
        {"code": clean_code},
        {
            "$set": {
                "closed": True,
                "closed_at": now,
                "closed_by_actor_id": actor["id"],
                "closed_by_name": actor["name"],
                "updated_at": now,
            },
            "$unset": {"typing": ""},
        },
    )
    room = _queue_rooms_col().find_one({"code": clean_code}) or room
    return jsonify(_queue_room_closed_payload(room, actor))


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
        escaped = build_special_insensitive_search_pattern(q, max_len=120)
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

    songs = [item for item in (song_to_public(song, user_oid) for song in raw_songs) if item]

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
    items = [item for item in (song_to_public(song, user_oid) for song in raw) if item]
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
