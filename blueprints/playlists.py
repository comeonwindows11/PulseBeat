from datetime import datetime
from html import escape
import re
from math import ceil
from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for

from auth_helpers import (
    can_access_song,
    get_session_user_oid,
    login_required,
    parse_object_id,
    register_auto_moderation_violation,
    serialize_song,
    song_stream_url,
    send_email_message,
    visible_song_filter,
)
import extensions
from i18n import tr

bp = Blueprint("playlists", __name__, url_prefix="/playlists")

PLAYLIST_VISIBILITY_VALUES = {"public", "private", "unlisted"}


def normalize_playlist_visibility(playlist):
    value = (playlist.get("visibility") or "private").strip().lower()
    if value not in PLAYLIST_VISIBILITY_VALUES:
        value = "private"
    return value


def is_playlist_owner(playlist, user_oid):
    if not user_oid:
        return False
    return str(playlist.get("user_id")) == str(user_oid)


def is_playlist_collaborator(playlist, user_oid):
    if not user_oid:
        return False
    return any(str(uid) == str(user_oid) for uid in playlist.get("collaborator_ids", []))


def can_access_playlist(playlist, user_oid):
    if is_playlist_owner(playlist, user_oid) or is_playlist_collaborator(playlist, user_oid):
        return True
    visibility = normalize_playlist_visibility(playlist)
    return visibility in {"public", "unlisted"}


def can_edit_playlist(playlist, user_oid):
    return is_playlist_owner(playlist, user_oid) or is_playlist_collaborator(playlist, user_oid)


def playlist_public_data(playlist, user_oid):
    return {
        "id": str(playlist["_id"]),
        "name": playlist.get("name") or tr("defaults.unnamed"),
        "visibility": normalize_playlist_visibility(playlist),
        "is_owner": is_playlist_owner(playlist, user_oid),
        "is_collaborator": is_playlist_collaborator(playlist, user_oid),
        "song_count": len(playlist.get("song_ids", [])),
    }


def send_playlist_share_email(target_user, owner_name, playlist_name, playlist_link):
    text_body = tr(
        "email.playlist_shared_body",
        username=target_user.get("username", "user"),
        owner=owner_name,
        playlist=playlist_name,
        link=playlist_link,
    )
    html_message = tr(
        "email.playlist_shared_body",
        username=target_user.get("username", "user"),
        owner=owner_name,
        playlist=playlist_name,
        link=playlist_link,
    )
    html_message = escape(html_message).replace("\\n", "<br>").replace("\n", "<br>")
    html_body = f"""
<!doctype html>
<html>
  <body style=\"margin:0;padding:0;background:#f3f6fb;font-family:Arial,Helvetica,sans-serif;color:#1b2430;\">
    <table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" style=\"background:#f3f6fb;padding:24px 0;\">
      <tr>
        <td align=\"center\">
          <table role=\"presentation\" width=\"640\" cellspacing=\"0\" cellpadding=\"0\" style=\"max-width:640px;width:100%;background:#ffffff;border-radius:14px;overflow:hidden;border:1px solid #e3eaf3;\">
            <tr>
              <td style=\"background:linear-gradient(135deg,#ff8a1f,#ff4f4f);padding:20px 28px;color:#fff;font-size:22px;font-weight:700;\">PulseBeat</td>
            </tr>
            <tr>
              <td style=\"padding:28px;\">
                <h1 style=\"margin:0 0 14px 0;font-size:22px;line-height:1.3;color:#101828;\">{escape(tr('email.playlist_shared_subject'))}</h1>
                <p style=\"margin:0 0 12px 0;font-size:15px;line-height:1.6;\">{escape(tr('auth.verification_email_plain_greeting', username=target_user.get('username', 'user')))}</p>
                <p style=\"margin:0 0 18px 0;font-size:15px;line-height:1.6;\">{html_message}</p>
                <p style=\"margin:0 0 22px 0;\">
                  <a href=\"{escape(playlist_link)}\" style=\"display:inline-block;background:#2563eb;color:#ffffff;text-decoration:none;padding:12px 18px;border-radius:10px;font-size:14px;font-weight:700;\">{escape(tr('song.details'))}</a>
                </p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""
    return send_email_message(target_user.get("email", ""), tr("email.playlist_shared_subject"), text_body, html_body)


def parse_collaborator_ids(values, owner_oid):
    items = []
    for raw in values:
        oid = parse_object_id(raw)
        if oid and str(oid) != str(owner_oid):
            items.append(oid)
    if not items:
        return []
    return [u["_id"] for u in extensions.users_col.find({"_id": {"$in": items}}, {"_id": 1})]


@bp.route("", methods=["GET", "POST"])
@login_required
def list_playlists():
    user_oid = get_session_user_oid()
    page_raw = request.args.get("page", "1").strip()
    page = max(1, int(page_raw)) if page_raw.isdigit() else 1
    per_page = int(current_app.config.get("PAGE_SIZE", 50))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        visibility = request.form.get("visibility", "private").strip().lower()
        collaborator_ids = parse_collaborator_ids(request.form.getlist("collaborator_ids"), user_oid)
        if not name:
            flash(tr("flash.playlists.name_required"), "danger")
            return redirect(url_for("playlists.list_playlists"))
        if contains_profanity(name):
            moderation = register_auto_moderation_violation(user_oid, "playlist_create")
            flash(tr("flash.moderation.blocked", remaining=moderation.get("remaining", 0)), "danger")
            if moderation.get("banned"):
                flash(tr("flash.moderation.auto_banned"), "danger")
            return redirect(url_for("playlists.list_playlists"))
        if visibility not in PLAYLIST_VISIBILITY_VALUES:
            visibility = "private"

        playlist_id = extensions.playlists_col.insert_one(
            {
                "name": name,
                "user_id": user_oid,
                "song_ids": [],
                "visibility": visibility,
                "collaborator_ids": collaborator_ids,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
        ).inserted_id
        if collaborator_ids:
            owner = extensions.users_col.find_one({"_id": user_oid}, {"username": 1}) or {"username": "user"}
            link = url_for("playlists.playlist_detail", playlist_id=str(playlist_id), _external=True)
            for target in extensions.users_col.find({"_id": {"$in": collaborator_ids}}, {"email": 1, "username": 1}):
                send_playlist_share_email(target, owner.get("username", "user"), name, link)
        flash(tr("flash.playlists.created"), "success")
        return redirect(url_for("playlists.playlist_detail", playlist_id=str(playlist_id)))

    query = {
        "$or": [
            {"user_id": user_oid},
            {"collaborator_ids": user_oid},
            {"visibility": "public"},
        ]
    }

    total = extensions.playlists_col.count_documents(query)
    pages = max(1, ceil(total / per_page)) if total else 1
    if page > pages:
        page = pages
    skip = (page - 1) * per_page
    raw = list(extensions.playlists_col.find(query).sort("updated_at", -1).skip(skip).limit(per_page))
    playlists = [playlist_public_data(p, user_oid) for p in raw]
    return render_template("playlists/list.jinja", playlists=playlists, page=page, pages=pages)


@bp.route("/suggest")
@login_required
def suggest_playlists():
    user_oid = get_session_user_oid()
    q = request.args.get("q", "").strip()

    query = {"$or": [{"user_id": user_oid}, {"collaborator_ids": user_oid}]}
    if q:
        query = {
            "$and": [
                query,
                {"name": {"$regex": q, "$options": "i"}},
            ]
        }

    rows = list(extensions.playlists_col.find(query, {"name": 1, "visibility": 1}).sort("updated_at", -1).limit(20))
    return jsonify(
        {
            "items": [
                {
                    "id": str(p["_id"]),
                    "name": p.get("name") or tr("defaults.unnamed"),
                    "visibility": normalize_playlist_visibility(p),
                    "value": p.get("name") or tr("defaults.unnamed"),
                }
                for p in rows
            ]
        }
    )


@bp.route("/quick-add", methods=["POST"])
@login_required
def quick_add_song_to_playlist():
    user_oid = get_session_user_oid()
    payload = request.get_json(silent=True) or {}
    playlist_oid = parse_object_id(payload.get("playlist_id", ""))
    song_oid = parse_object_id(payload.get("song_id", ""))

    if not playlist_oid or not song_oid:
        return jsonify({"ok": False, "message": tr("flash.songs.invalid_request")}), 400

    playlist = extensions.playlists_col.find_one({"_id": playlist_oid})
    if not playlist or not can_edit_playlist(playlist, user_oid):
        return jsonify({"ok": False, "message": tr("flash.playlists.not_found")}), 403

    song = extensions.songs_col.find_one({"_id": song_oid})
    if not song or not can_access_song(song, user_oid):
        return jsonify({"ok": False, "message": tr("flash.playlists.song_inaccessible")}), 404

    if song_oid in playlist.get("song_ids", []):
        return jsonify({"ok": True, "already_exists": True, "message": tr("flash.playlists.song_exists")})

    extensions.playlists_col.update_one(
        {"_id": playlist_oid},
        {"$push": {"song_ids": song_oid}, "$set": {"updated_at": datetime.utcnow()}},
    )
    return jsonify({"ok": True, "already_exists": False, "message": tr("flash.playlists.song_added")})



@bp.route("/<playlist_id>/search-suggest")
@login_required
def playlist_search_suggest(playlist_id):
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"items": []})

    user_oid = get_session_user_oid()
    playlist_oid = parse_object_id(playlist_id)
    if not playlist_oid:
        return jsonify({"items": []})

    playlist = extensions.playlists_col.find_one({"_id": playlist_oid}, {"song_ids": 1, "visibility": 1, "user_id": 1, "collaborator_ids": 1})
    if not playlist or not can_access_playlist(playlist, user_oid):
        return jsonify({"items": []})

    song_ids = playlist.get("song_ids", [])
    if not song_ids:
        return jsonify({"items": []})

    regex = {"$regex": re.escape(q), "$options": "i"}
    query = {
        "_id": {"$in": song_ids},
        "$or": [{"title": regex}, {"artist": regex}, {"genre": regex}],
    }
    rows = list(extensions.songs_col.find(query, {"title": 1, "artist": 1, "genre": 1}).limit(50))
    by_id = {row["_id"]: row for row in rows}

    items = []
    for sid in song_ids:
        song = by_id.get(sid)
        if not song or not can_access_song(song, user_oid):
            continue
        items.append(
            {
                "song_id": str(song["_id"]),
                "title": song.get("title", ""),
                "artist": song.get("artist", ""),
                "value": f"{song.get('title', '')} - {song.get('artist', '')}".strip(" -"),
                "detail_url": url_for("songs.song_detail", song_id=str(song["_id"])),
            }
        )
        if len(items) >= 15:
            break

    return jsonify({"items": items})

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
    songs_q = request.args.get("songs_q", "").strip()
    per_page = int(current_app.config.get("PAGE_SIZE", 50))

    playlist = extensions.playlists_col.find_one({"_id": playlist_oid})
    if not playlist:
        flash(tr("flash.playlists.not_found"), "danger")
        return redirect(url_for("playlists.list_playlists"))
    if not can_access_playlist(playlist, user_oid):
        flash(tr("flash.playlists.not_found"), "danger")
        return redirect(url_for("playlists.list_playlists"))

    song_ids = playlist.get("song_ids", [])
    songs = []
    if song_ids:
        raw_songs = list(extensions.songs_col.find({"_id": {"$in": song_ids}}))
        songs_by_id = {song["_id"]: song for song in raw_songs}
        ordered = [songs_by_id[sid] for sid in song_ids if sid in songs_by_id]
        if songs_q:
            needle = re.escape(songs_q)
            pattern = re.compile(needle, re.IGNORECASE)
            ordered = [
                song
                for song in ordered
                if pattern.search(song.get("title", ""))
                or pattern.search(song.get("artist", ""))
                or pattern.search(song.get("genre", ""))
            ]
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

    all_songs = []

    collaborators = []
    for u in extensions.users_col.find({"_id": {"$in": playlist.get("collaborator_ids", [])}}, {"username": 1, "email": 1}):
        collaborators.append({"id": str(u["_id"]), "username": u.get("username", "user"), "email": u.get("email", "")})

    return render_template(
        "playlists/detail.jinja",
        playlist=playlist_public_data(playlist, user_oid),
        songs=songs,
        all_songs=all_songs,
        collaborators=collaborators,
        songs_page=songs_page,
        songs_pages=songs_pages,
        add_page=add_page,
        add_pages=add_pages,
        songs_q=songs_q,
    )


@bp.route("/<playlist_id>/update", methods=["POST"])
@login_required
def update_playlist(playlist_id):
    user_oid = get_session_user_oid()
    playlist_oid = parse_object_id(playlist_id)
    if not playlist_oid:
        flash(tr("flash.playlists.invalid"), "danger")
        return redirect(url_for("playlists.list_playlists"))

    playlist = extensions.playlists_col.find_one({"_id": playlist_oid})
    if not playlist or not is_playlist_owner(playlist, user_oid):
        flash(tr("flash.playlists.not_found"), "danger")
        return redirect(url_for("playlists.list_playlists"))

    name = request.form.get("name", "").strip()
    visibility = request.form.get("visibility", "private").strip().lower()
    if not name:
        flash(tr("flash.playlists.name_required"), "danger")
        return redirect(url_for("playlists.playlist_detail", playlist_id=playlist_id))
    if contains_profanity(name):
        moderation = register_auto_moderation_violation(user_oid, "playlist_edit")
        flash(tr("flash.moderation.blocked", remaining=moderation.get("remaining", 0)), "danger")
        if moderation.get("banned"):
            flash(tr("flash.moderation.auto_banned"), "danger")
        return redirect(url_for("playlists.playlist_detail", playlist_id=playlist_id))
    if visibility not in PLAYLIST_VISIBILITY_VALUES:
        visibility = "private"

    extensions.playlists_col.update_one(
        {"_id": playlist_oid},
        {"$set": {"name": name, "visibility": visibility, "updated_at": datetime.utcnow()}},
    )
    flash(tr("flash.playlists.updated"), "success")
    return redirect(url_for("playlists.playlist_detail", playlist_id=playlist_id))


@bp.route("/<playlist_id>/collaborators", methods=["POST"])
@login_required
def update_playlist_collaborators(playlist_id):
    user_oid = get_session_user_oid()
    playlist_oid = parse_object_id(playlist_id)
    if not playlist_oid:
        flash(tr("flash.playlists.invalid"), "danger")
        return redirect(url_for("playlists.list_playlists"))

    playlist = extensions.playlists_col.find_one({"_id": playlist_oid})
    if not playlist or not is_playlist_owner(playlist, user_oid):
        flash(tr("flash.playlists.not_found"), "danger")
        return redirect(url_for("playlists.list_playlists"))

    old_ids = {str(cid) for cid in playlist.get("collaborator_ids", [])}
    collaborator_ids = parse_collaborator_ids(request.form.getlist("collaborator_ids"), user_oid)
    extensions.playlists_col.update_one(
        {"_id": playlist_oid},
        {"$set": {"collaborator_ids": collaborator_ids, "updated_at": datetime.utcnow()}},
    )
    if collaborator_ids:
        owner = extensions.users_col.find_one({"_id": user_oid}, {"username": 1}) or {"username": "user"}
        new_ids = [cid for cid in collaborator_ids if str(cid) not in old_ids]
        link = url_for("playlists.playlist_detail", playlist_id=playlist_id, _external=True)
        for target in extensions.users_col.find({"_id": {"$in": new_ids}}, {"email": 1, "username": 1}):
            send_playlist_share_email(target, owner.get("username", "user"), playlist.get("name", tr("defaults.unnamed")), link)

    flash(tr("flash.playlists.collaborators_updated"), "success")
    return redirect(url_for("playlists.playlist_detail", playlist_id=playlist_id))


@bp.route("/<playlist_id>/add-song", methods=["POST"])
@login_required
def add_song_to_playlist(playlist_id):
    user_oid = get_session_user_oid()
    playlist_oid = parse_object_id(playlist_id)
    song_oid = parse_object_id(request.form.get("song_id", ""))
    if not playlist_oid or not song_oid:
        flash(tr("flash.songs.invalid_request"), "danger")
        return redirect(url_for("playlists.list_playlists"))

    playlist = extensions.playlists_col.find_one({"_id": playlist_oid})
    if not playlist or not can_edit_playlist(playlist, user_oid):
        flash(tr("flash.playlists.not_found"), "danger")
        return redirect(url_for("playlists.list_playlists"))

    song = extensions.songs_col.find_one({"_id": song_oid})
    if not song or not can_access_song(song, user_oid):
        flash(tr("flash.playlists.song_inaccessible"), "danger")
        return redirect(url_for("playlists.playlist_detail", playlist_id=playlist_id))

    if song_oid in playlist.get("song_ids", []):
        flash(tr("flash.playlists.song_exists"), "warning")
        return redirect(url_for("playlists.playlist_detail", playlist_id=playlist_id))

    extensions.playlists_col.update_one(
        {"_id": playlist_oid},
        {"$push": {"song_ids": song_oid}, "$set": {"updated_at": datetime.utcnow()}},
    )
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

    playlist = extensions.playlists_col.find_one({"_id": playlist_oid})
    if not playlist or not can_edit_playlist(playlist, user_oid):
        flash(tr("flash.playlists.not_found"), "danger")
        return redirect(url_for("playlists.list_playlists"))

    extensions.playlists_col.update_one(
        {"_id": playlist_oid},
        {"$pull": {"song_ids": song_oid}, "$set": {"updated_at": datetime.utcnow()}},
    )
    flash(tr("flash.playlists.song_removed"), "success")
    return redirect(url_for("playlists.playlist_detail", playlist_id=playlist_id))















