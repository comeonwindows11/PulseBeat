import os
from datetime import datetime
from functools import wraps
from bson import ObjectId
from flask import current_app, flash, redirect, session, url_for
from werkzeug.utils import secure_filename

import extensions
from i18n import tr

ALLOWED_EXTENSIONS = {"mp3", "wav", "ogg", "m4a"}
VISIBILITY_VALUES = {"public", "private", "unlisted"}


def parse_object_id(value: str):
    try:
        return ObjectId(value)
    except Exception:
        return None


def get_session_user_oid():
    return parse_object_id(session.get("user_id", ""))


def current_user():
    user_oid = get_session_user_oid()
    if not user_oid:
        return None
    user = extensions.users_col.find_one({"_id": user_oid})
    if not user:
        session.clear()
        return None
    return {
        "id": str(user["_id"]),
        "username": user.get("username", "user"),
        "email": user.get("email", ""),
        "is_admin": bool(user.get("is_admin", False)),
    }


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not get_session_user_oid():
            session.clear()
            flash(tr("flash.auth.required"), "warning")
            return redirect(url_for("accounts.login"))
        return fn(*args, **kwargs)

    return wrapped


def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        user_oid = get_session_user_oid()
        if not user_oid:
            session.clear()
            flash(tr("flash.auth.required"), "warning")
            return redirect(url_for("accounts.login"))
        user = extensions.users_col.find_one({"_id": user_oid})
        if not user or not user.get("is_admin", False):
            flash(tr("flash.admin.forbidden"), "danger")
            return redirect(url_for("main.index"))
        return fn(*args, **kwargs)

    return wrapped


def allowed_file(filename: str) -> bool:
    if "." not in filename:
        return False
    return filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def song_owner_matches(song, user_oid):
    if not user_oid:
        return False
    created_by = song.get("created_by")
    if not created_by:
        return False
    return str(created_by) == str(user_oid)


def cleanup_song(song):
    song_oid = song["_id"]
    file_name = song.get("file_name")
    if file_name:
        local_path = os.path.join(current_app.config["UPLOAD_DIR"], file_name)
        if os.path.exists(local_path):
            os.remove(local_path)
    else:
        legacy_url = song.get("url", "")
        uploads_prefix = url_for("static", filename="uploads/")
        if legacy_url.startswith(uploads_prefix):
            legacy_file = os.path.basename(legacy_url.replace(uploads_prefix, "", 1))
            legacy_path = os.path.join(current_app.config["UPLOAD_DIR"], legacy_file)
            if os.path.exists(legacy_path):
                os.remove(legacy_path)

    extensions.playlists_col.update_many({}, {"$pull": {"song_ids": song_oid}})
    extensions.song_votes_col.delete_many({"song_id": song_oid})
    extensions.song_comments_col.delete_many({"song_id": song_oid})
    extensions.songs_col.delete_one({"_id": song_oid})


def cleanup_user(user_oid, delete_songs=False):
    if delete_songs:
        songs = list(extensions.songs_col.find({"created_by": user_oid}))
        for song in songs:
            cleanup_song(song)
    else:
        extensions.songs_col.update_many(
            {"created_by": user_oid},
            {"$set": {"created_by": None, "visibility": "public"}, "$pull": {"shared_with": user_oid}},
        )

    extensions.songs_col.update_many({}, {"$pull": {"shared_with": user_oid}})
    extensions.song_votes_col.delete_many({"user_id": user_oid})
    extensions.song_comments_col.delete_many({"user_id": user_oid})
    extensions.playlists_col.delete_many({"user_id": user_oid})
    extensions.users_col.delete_one({"_id": user_oid})


def normalize_visibility(song):
    visibility = song.get("visibility", "public")
    if visibility not in VISIBILITY_VALUES:
        visibility = "public"
    return visibility


def user_in_shared(song, user_oid):
    if not user_oid:
        return False
    return any(str(shared_id) == str(user_oid) for shared_id in song.get("shared_with", []))


def can_access_song(song, user_oid):
    visibility = normalize_visibility(song)
    if song_owner_matches(song, user_oid):
        return True
    if visibility == "public":
        return True
    if visibility == "unlisted":
        return True
    if visibility == "private" and user_in_shared(song, user_oid):
        return True
    return False


def visible_song_filter(user_oid):
    public_clause = {"$or": [{"visibility": "public"}, {"visibility": {"$exists": False}}]}
    if not user_oid:
        return public_clause

    return {
        "$or": [
            public_clause,
            {"created_by": user_oid},
            {"$and": [{"visibility": "private"}, {"shared_with": user_oid}]},
        ]
    }


def serialize_song(song, user_oid):
    return {
        "id": str(song["_id"]),
        "title": song.get("title") or tr("defaults.untitled"),
        "artist": song.get("artist") or tr("defaults.unknown_artist"),
        "visibility": normalize_visibility(song),
        "shared_count": len(song.get("shared_with", [])),
        "can_delete": song_owner_matches(song, user_oid),
    }


def song_stream_url(song_id: str):
    return url_for("songs.stream_song", song_id=song_id)


def user_choice_list(exclude_user_oid=None):
    query = {}
    if exclude_user_oid:
        query = {"_id": {"$ne": exclude_user_oid}}
    users = list(extensions.users_col.find(query).sort("username", 1))
    return [
        {
            "id": str(user["_id"]),
            "username": user.get("username", "user"),
            "email": user.get("email", ""),
        }
        for user in users
    ]


def save_uploaded_file(file_storage):
    safe_name = secure_filename(file_storage.filename)
    stamped_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{safe_name}"
    upload_dir = current_app.config["UPLOAD_DIR"]
    file_path = os.path.join(upload_dir, stamped_name)
    file_storage.save(file_path)
    return stamped_name
