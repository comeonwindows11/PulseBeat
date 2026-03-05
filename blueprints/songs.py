import difflib
import html
import os
import re
import unicodedata
from datetime import UTC, datetime
from math import ceil
from urllib.parse import quote

import requests
from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, send_from_directory, url_for

from auth_helpers import (
    VISIBILITY_VALUES,
    admin_required,
    allowed_file,
    can_access_song,
    cleanup_song,
    contains_profanity,
    get_session_user_oid,
    login_required,
    parse_object_id,
    register_auto_moderation_violation,
    save_uploaded_file,
    serialize_song,
    song_owner_matches,
    visible_song_filter,
)
import extensions
from i18n import tr

bp = Blueprint("songs", __name__, url_prefix="/songs")


LYRICS_MAX_CHARS = 200_000
LYRICS_MAX_CUES = 2_000
LRC_RE = re.compile(r"\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\]")


def _normalize_lyrics_text(raw: str) -> str:
    value = (raw or "").replace("\r\n", "\n").replace("\r", "\n")
    value = "\n".join(line.rstrip() for line in value.split("\n"))
    value = value.strip()
    if len(value) > LYRICS_MAX_CHARS:
        value = value[:LYRICS_MAX_CHARS]
    return value


def _parse_lrc_cues(raw_text: str):
    cues = []
    if not raw_text:
        return cues

    for row in raw_text.split("\n"):
        matches = list(LRC_RE.finditer(row))
        if not matches:
            continue
        lyric_text = LRC_RE.sub("", row).strip()
        if not lyric_text:
            continue
        for match in matches:
            mm = int(match.group(1) or 0)
            ss = int(match.group(2) or 0)
            frac_raw = match.group(3) or "0"
            frac = int(frac_raw)
            if len(frac_raw) == 1:
                frac_sec = frac / 10
            elif len(frac_raw) == 2:
                frac_sec = frac / 100
            else:
                frac_sec = frac / 1000
            ts = (mm * 60) + ss + frac_sec
            cues.append({"time": round(float(ts), 3), "text": lyric_text})

    cues.sort(key=lambda item: item.get("time", 0.0))
    if len(cues) > LYRICS_MAX_CUES:
        cues = cues[:LYRICS_MAX_CUES]
    return cues


def _decode_uploaded_text(raw: bytes) -> str:
    if not raw:
        return ""
    for enc in ("utf-8-sig", "utf-8", "utf-16", "latin-1"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return ""


def _extract_uploaded_lyrics_text(file_storage):
    if not file_storage or not getattr(file_storage, "filename", ""):
        return ""
    raw = file_storage.read()
    try:
        file_storage.stream.seek(0)
    except Exception:
        pass
    return _normalize_lyrics_text(_decode_uploaded_text(raw))


def _lyrics_payload_from_text(raw_text: str):
    text_value = _normalize_lyrics_text(raw_text)
    if not text_value:
        return "", []
    cues = _parse_lrc_cues(text_value)
    return text_value, cues


def _extract_id3_lyrics_from_file(path: str):
    try:
        with open(path, "rb") as fh:
            data = fh.read(min(1024 * 1024, 2 * 1024 * 1024))
    except Exception:
        return "", []

    if len(data) < 10 or data[0:3] != b"ID3":
        return "", []

    tag_size = ((data[6] & 0x7F) << 21) | ((data[7] & 0x7F) << 14) | ((data[8] & 0x7F) << 7) | (data[9] & 0x7F)
    offset = 10
    limit = min(len(data), 10 + tag_size)
    lyrics_chunks = []

    def decode_text(payload: bytes):
        if not payload:
            return ""
        enc = payload[0]
        body = payload[1:]
        for codec in (["latin-1"] if enc == 0 else ["utf-16", "utf-8"]):
            try:
                return body.decode(codec, errors="ignore").replace("\\x00", "").strip()
            except Exception:
                continue
        return body.decode("utf-8", errors="ignore").replace("\\x00", "").strip()

    while offset + 10 <= limit:
        frame_id = data[offset:offset + 4].decode("latin-1", errors="ignore")
        frame_size = int.from_bytes(data[offset + 4:offset + 8], "big", signed=False)
        if not frame_id.strip() or frame_size <= 0:
            break
        start = offset + 10
        end = start + frame_size
        if end > limit:
            break
        payload = data[start:end]
        if frame_id in {"USLT", "SYLT"}:
            text_part = decode_text(payload[4:] if len(payload) > 4 else payload)
            if text_part:
                lyrics_chunks.append(text_part)
        offset = end

    joined = _normalize_lyrics_text("\n".join(lyrics_chunks))
    if not joined:
        return "", []
    return _lyrics_payload_from_text(joined)




def _lyricsify_slug(value: str) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return ""
    raw = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    raw = raw.replace("&", " and ")
    raw = re.sub(r"[^a-z0-9]+", "-", raw)
    raw = re.sub(r"-+", "-", raw).strip("-")
    return raw


def _extract_lyricsify_text(page_html: str) -> str:
    html_value = page_html or ""
    patterns = [
        r'<div[^>]+class="[^"]*(?:lyric-body|lyric-content|lyrics-content|lyrics)[^"]*"[^>]*>([\s\S]*?)</div>',
        r'<pre[^>]+class="[^"]*(?:lyrics|lyric)[^"]*"[^>]*>([\s\S]*?)</pre>',
        r'"lyrics"\s*:\s*"([\s\S]*?)"',
    ]
    for pat in patterns:
        m = re.search(pat, html_value, re.IGNORECASE)
        if not m:
            continue
        raw = m.group(1)
        raw = raw.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
        raw = re.sub(r"<[^>]+>", "", raw)
        raw = html.unescape(raw)
        text_value = _normalize_lyrics_text(raw)
        if text_value and len(text_value) > 30:
            return text_value
    return ""


def _search_title_variants(title: str):
    base = (title or "").strip()
    if not base:
        return []
    variants = [base]
    cleaned = re.sub(r"\s*\(([^)]*)\)", "", base).strip()
    cleaned = re.sub(r"\s*\[([^\]]*)\]", "", cleaned).strip()
    if cleaned and cleaned not in variants:
        variants.append(cleaned)
    no_feat = re.sub(r"\s+(feat\.?|ft\.?)\s+.*$", "", cleaned or base, flags=re.IGNORECASE).strip()
    if no_feat and no_feat not in variants:
        variants.append(no_feat)
    if "-" in no_feat:
        left = no_feat.split("-", 1)[0].strip()
        if left and left not in variants:
            variants.append(left)
    return variants[:4]

def _lyrics_search_online(title: str, artist: str):
    query_title = (title or "").strip()
    query_artist = (artist or "").strip()
    if not query_title:
        return None

    title_variants = _search_title_variants(query_title)
    if not title_variants:
        title_variants = [query_title]

    requests_used = 0
    max_requests = 5
    json_headers = {"Accept": "application/json", "User-Agent": "PulseBeat/1.0"}
    html_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36", "Accept": "text/html,application/xhtml+xml"}

    def fetch_json(url: str, params=None):
        nonlocal requests_used
        if requests_used >= max_requests:
            return None, None
        requests_used += 1
        try:
            resp = requests.get(url, params=params, timeout=8, headers=json_headers)
        except Exception:
            return None, None
        if resp.status_code != 200:
            return resp.status_code, None
        try:
            return 200, resp.json()
        except Exception:
            return 200, None

    def fetch_html(url: str):
        nonlocal requests_used
        if requests_used >= max_requests:
            return None
        requests_used += 1
        try:
            resp = requests.get(url, timeout=8, headers=html_headers)
        except Exception:
            return None
        if resp.status_code != 200:
            return None
        return resp.text

    def build_result(raw_title: str, raw_artist: str, plain_lyrics: str, synced_lyrics: str = ""):
        synced_text = _normalize_lyrics_text(synced_lyrics)
        plain_text = _normalize_lyrics_text(plain_lyrics)
        if synced_text:
            synced_cues = _parse_lrc_cues(synced_text)
            return {
                "artist": raw_artist or query_artist,
                "title": raw_title or query_title,
                "lyrics_text": synced_text,
                "lyrics_cues": synced_cues,
            }
        if plain_text:
            plain_cues = _parse_lrc_cues(plain_text)
            return {
                "artist": raw_artist or query_artist,
                "title": raw_title or query_title,
                "lyrics_text": plain_text,
                "lyrics_cues": plain_cues,
            }
        return None

    # 1) LRCLIB direct lookup
    params_get = {"track_name": title_variants[0]}
    if query_artist:
        params_get["artist_name"] = query_artist
    _, data = fetch_json("https://lrclib.net/api/get", params=params_get)
    if isinstance(data, dict):
        found = build_result(
            data.get("trackName") or data.get("name") or query_title,
            data.get("artistName") or query_artist,
            data.get("plainLyrics") or "",
            data.get("syncedLyrics") or "",
        )
        if found:
            return found

    # 2) LRCLIB search fallback
    for variant in title_variants:
        params_search = {"track_name": variant}
        if query_artist:
            params_search["artist_name"] = query_artist
        _, data = fetch_json("https://lrclib.net/api/search", params=params_search)
        if isinstance(data, list) and data:
            best = None
            best_score = -1.0
            for row in data[:20]:
                cand_title = (row.get("trackName") or row.get("name") or "").strip()
                cand_artist = (row.get("artistName") or "").strip()
                if not cand_title:
                    continue
                title_score = difflib.SequenceMatcher(None, query_title.lower(), cand_title.lower()).ratio()
                artist_score = 0.0
                if query_artist and cand_artist:
                    artist_score = difflib.SequenceMatcher(None, query_artist.lower(), cand_artist.lower()).ratio()
                score = (title_score * 0.8) + (artist_score * 0.2)
                if score > best_score:
                    best_score = score
                    best = row
            if best:
                found = build_result(
                    best.get("trackName") or best.get("name") or query_title,
                    best.get("artistName") or query_artist,
                    best.get("plainLyrics") or "",
                    best.get("syncedLyrics") or "",
                )
                if found:
                    return found
        if requests_used >= max_requests:
            break

    # 3) LRCLIB q-based fallback (often returns synced LRC directly)
    search_q = " ".join(part for part in [query_artist, title_variants[0]] if part).strip()
    if search_q:
        _, data = fetch_json("https://lrclib.net/api/search", params={"q": search_q})
        if isinstance(data, list) and data:
            for row in data[:10]:
                found = build_result(
                    row.get("trackName") or row.get("name") or query_title,
                    row.get("artistName") or query_artist,
                    row.get("plainLyrics") or "",
                    row.get("syncedLyrics") or "",
                )
                if found:
                    return found

    # 4) Lyricsify scrape using normalized slugs
    if query_artist:
        artist_slug = _lyricsify_slug(query_artist)
        title_slug = _lyricsify_slug(title_variants[0])
        if artist_slug and title_slug:
            lyricsify_url = f"https://www.lyricsify.com/lyrics/{artist_slug}/{title_slug}"
            page_html = fetch_html(lyricsify_url)
            if page_html:
                extracted = _extract_lyricsify_text(page_html)
                found = build_result(query_title, query_artist, extracted)
                if found:
                    return found

    # 5) Lyrics.ovh direct
    if query_artist:
        _, data = fetch_json(f"https://api.lyrics.ovh/v1/{quote(query_artist)}/{quote(title_variants[0])}")
        if isinstance(data, dict):
            found = build_result(query_title, query_artist, data.get("lyrics") or "")
            if found:
                return found

    return None


def _lyrics_auto_sync_from_source(song) -> bool:
    source = (song.get("lyrics_source") or "").strip().lower()
    if source in {"metadata", "online_auto", "metadata_edit", "online_auto_edit"}:
        return True
    return bool(song.get("lyrics_auto_sync", False))


def song_public_data(song, user_oid):
    item = serialize_song(song, user_oid)
    item["url"] = url_for("songs.stream_song", song_id=item["id"])
    item["detail_url"] = url_for("songs.song_detail", song_id=item["id"])
    item["has_lyrics"] = bool(song.get("lyrics_text"))
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
    users = {
        str(u["_id"]): {"username": u.get("username", "user"), "profile_url": url_for("accounts.public_profile", username=u.get("username", "user"))}
        for u in extensions.users_col.find({}, {"username": 1})
    }
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
        user_meta = users.get(owner_str, {"username": tr("defaults.unnamed"), "profile_url": ""})
        item = {
            "id": comment_id,
            "content": row.get("content", ""),
            "created_at": row.get("created_at"),
            "username": user_meta.get("username", tr("defaults.unnamed")),
            "profile_url": user_meta.get("profile_url", ""),
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


@bp.route("/metadata-enrich")
@login_required
def metadata_enrich_api():
    title = request.args.get("title", "").strip()
    if not title:
        return jsonify({"ok": False, "message": tr("flash.songs.invalid_request")}), 400

    try:
        resp = requests.get(
            "https://itunes.apple.com/search",
            params={"term": title, "entity": "song", "limit": 10},
            timeout=8,
            headers={"Accept": "application/json", "User-Agent": "PulseBeat/1.0"},
        )
        data = resp.json() if resp.status_code == 200 else {}
    except Exception:
        return jsonify({"ok": False}), 200

    rows = data.get("results") if isinstance(data, dict) else []
    if not isinstance(rows, list) or not rows:
        return jsonify({"ok": False}), 200

    best = None
    best_score = -1.0
    for row in rows[:10]:
        track_name = (row.get("trackName") or "").strip()
        artist_name = (row.get("artistName") or "").strip()
        if not track_name:
            continue
        score = difflib.SequenceMatcher(None, title.lower(), track_name.lower()).ratio()
        if score > best_score:
            best_score = score
            best = row

    if not best:
        return jsonify({"ok": False}), 200

    return jsonify(
        {
            "ok": True,
            "item": {
                "title": best.get("trackName") or title,
                "artist": best.get("artistName") or "",
                "genre": best.get("primaryGenreName") or "",
            },
        }
    )


@bp.route("/lyrics-search")
@login_required
def lyrics_search_api():
    title = request.args.get("title", "").strip()
    artist = request.args.get("artist", "").strip()
    if not title:
        return jsonify({"ok": False, "message": tr("flash.songs.invalid_request")}), 400

    try:
        found = _lyrics_search_online(title, artist)
    except Exception:
        found = None

    if not found or not found.get("lyrics_text"):
        return jsonify({"ok": False, "message": tr("flash.songs.lyrics_search_empty")}), 404

    return jsonify(
        {
            "ok": True,
            "item": {
                "title": found.get("title", title),
                "artist": found.get("artist", artist),
                "lyrics_text": found.get("lyrics_text", ""),
                "lyrics_cues": found.get("lyrics_cues", []),
            },
        }
    )


@bp.route("/<song_id>/lyrics-detect-metadata")
@login_required
def lyrics_detect_metadata(song_id):
    song_oid = parse_object_id(song_id)
    user_oid = get_session_user_oid()
    if not song_oid:
        return jsonify({"ok": False, "message": tr("flash.songs.invalid_request")}), 400

    song = extensions.songs_col.find_one({"_id": song_oid})
    if not song:
        return jsonify({"ok": False, "message": tr("flash.songs.not_found")}), 404
    if not song_owner_matches(song, user_oid):
        return jsonify({"ok": False, "message": tr("flash.songs.delete_forbidden")}), 403

    if song.get("lyrics_text"):
        return jsonify({"ok": False, "has_lyrics": True, "message": tr("flash.songs.lyrics_exists")}), 409

    if song.get("source_type") == "upload" and song.get("file_name"):
        file_path = os.path.join(current_app.config["UPLOAD_DIR"], song.get("file_name"))
        text_value, cues = _extract_id3_lyrics_from_file(file_path)
        if text_value:
            return jsonify(
                {
                    "ok": True,
                    "found": True,
                    "item": {
                        "title": song.get("title", ""),
                        "artist": song.get("artist", ""),
                        "lyrics_text": text_value,
                        "lyrics_cues": cues,
                        "lyrics_source": "metadata_edit",
                    },
                }
            )

    return jsonify({"ok": True, "found": False})


@bp.route("/add", methods=["POST"])
@login_required
def add_song():
    title = request.form.get("title", "").strip()
    artist = request.form.get("artist", "").strip() or tr("defaults.unknown_artist")
    genre = request.form.get("genre", "").strip()
    song_url = request.form.get("song_url", "").strip()
    visibility = request.form.get("visibility", "public").strip().lower()
    file = request.files.get("song_file")
    lyrics_file = request.files.get("lyrics_file")
    lyrics_text_form = request.form.get("lyrics_text", "")
    lyrics_source_form = request.form.get("lyrics_source", "")
    shared_with_raw = request.form.getlist("shared_with")
    user_oid = get_session_user_oid()

    if not title:
        flash(tr("flash.songs.title_required"), "danger")
        return redirect(url_for("songs.new_song"))

    if contains_profanity(" ".join([title, artist, genre])):
        moderation = register_auto_moderation_violation(user_oid, "song_create")
        flash(tr("flash.moderation.blocked", remaining=moderation.get("remaining", 0)), "danger")
        if moderation.get("banned"):
            flash(tr("flash.moderation.auto_banned"), "danger")
        return redirect(url_for("songs.new_song"))

    if not song_url and (not file or not file.filename):
        flash(tr("flash.songs.source_required"), "danger")
        return redirect(url_for("songs.new_song"))

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
            return redirect(url_for("songs.new_song"))

    source_type = "external"
    source_url = song_url
    file_name = None

    lyrics_text = ""
    lyrics_cues = []
    lyrics_source = ""
    lyrics_auto_sync = False

    if file and file.filename:
        if not allowed_file(file.filename):
            flash(tr("flash.songs.invalid_format"), "danger")
            return redirect(url_for("songs.new_song"))
        source_type = "upload"
        source_url = None
        file_name = save_uploaded_file(file)
        extracted_text, extracted_cues = _extract_id3_lyrics_from_file(os.path.join(current_app.config["UPLOAD_DIR"], file_name))
        if extracted_text:
            lyrics_text = extracted_text
            lyrics_cues = extracted_cues
            lyrics_source = "metadata"
            lyrics_auto_sync = True

    form_lyrics_text, form_lyrics_cues = _lyrics_payload_from_text(lyrics_text_form)
    if form_lyrics_text:
        lyrics_text = form_lyrics_text
        lyrics_cues = form_lyrics_cues
        lyrics_source = (lyrics_source_form or "manual").strip() or "manual"
        lyrics_auto_sync = lyrics_source in {"metadata", "online_auto"}

    uploaded_lyrics_text = _extract_uploaded_lyrics_text(lyrics_file)
    if uploaded_lyrics_text:
        uploaded_text, uploaded_cues = _lyrics_payload_from_text(uploaded_lyrics_text)
        if uploaded_text:
            lyrics_text = uploaded_text
            lyrics_cues = uploaded_cues
            is_lrc = bool(lyrics_file and (lyrics_file.filename or "").lower().endswith(".lrc"))
            lyrics_source = "upload_lrc" if is_lrc else "upload_txt"
            lyrics_auto_sync = bool(is_lrc and uploaded_cues)

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
            "lyrics_text": lyrics_text,
            "lyrics_cues": lyrics_cues,
            "lyrics_source": lyrics_source,
            "lyrics_auto_sync": bool(lyrics_auto_sync),
            "created_at": datetime.utcnow(),
            "created_by": user_oid,
        }
    )
    flash(tr("flash.songs.added"), "success")
    return redirect(url_for("songs.my_songs"))


@bp.route("/new")
@login_required
def new_song():
    return render_template("songs/new.jinja")


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

    if contains_profanity(" ".join([title, artist, genre])):
        moderation = register_auto_moderation_violation(user_oid, "song_edit")
        flash(tr("flash.moderation.blocked", remaining=moderation.get("remaining", 0)), "danger")
        if moderation.get("banned"):
            flash(tr("flash.moderation.auto_banned"), "danger")
        return redirect(url_for("songs.song_detail", song_id=song_id))

    update_set = {"title": title, "artist": artist, "genre": genre, "updated_at": datetime.utcnow()}

    if not song.get("lyrics_text"):
        form_lyrics_text = request.form.get("lyrics_text", "")
        form_lyrics_source = (request.form.get("lyrics_source", "") or "").strip() or "manual"
        parsed_form_text, parsed_form_cues = _lyrics_payload_from_text(form_lyrics_text)
        if parsed_form_text:
            update_set["lyrics_text"] = parsed_form_text
            update_set["lyrics_cues"] = parsed_form_cues
            update_set["lyrics_source"] = form_lyrics_source
            update_set["lyrics_auto_sync"] = form_lyrics_source in {"metadata_edit", "online_auto_edit"}

        lyrics_file = request.files.get("lyrics_file")
        if "lyrics_text" not in update_set:
            uploaded_lyrics_text = _extract_uploaded_lyrics_text(lyrics_file)
            if uploaded_lyrics_text:
                parsed_text, parsed_cues = _lyrics_payload_from_text(uploaded_lyrics_text)
                if parsed_text:
                    update_set["lyrics_text"] = parsed_text
                    update_set["lyrics_cues"] = parsed_cues
                    is_lrc = bool(lyrics_file and (lyrics_file.filename or "").lower().endswith(".lrc"))
                    update_set["lyrics_source"] = "upload_lrc_edit" if is_lrc else "upload_txt_edit"
                    update_set["lyrics_auto_sync"] = bool(is_lrc and parsed_cues)
    elif request.files.get("lyrics_file") and request.files.get("lyrics_file").filename:
        flash(tr("flash.songs.lyrics_exists"), "warning")

    extensions.songs_col.update_one(
        {"_id": song_oid},
        {"$set": update_set},
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

    uploader = None
    created_by = song.get("created_by")
    if created_by:
        owner = extensions.users_col.find_one({"_id": created_by}, {"username": 1})
        if owner and owner.get("username"):
            uploader = {
                "username": owner.get("username", "user"),
                "profile_url": url_for("accounts.public_profile", username=owner.get("username", "user")),
            }

    likes, dislikes, user_vote = get_vote_stats(song_oid, user_oid)
    comments, comments_pages = build_comments(song_oid, user_oid, comments_page, per_page)
    recommended_songs = build_basic_recommendations(user_oid, current_song_oid=song_oid, limit=20)
    return render_template(
        "songs/detail.jinja",
        song=song_public_data(song, user_oid),
        uploader=uploader,
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


@bp.route("/<song_id>/lyrics")
def song_lyrics(song_id):
    song_oid = parse_object_id(song_id)
    if not song_oid:
        return jsonify({"ok": False}), 404

    song = extensions.songs_col.find_one({"_id": song_oid})
    if not song:
        return jsonify({"ok": False}), 404

    user_oid = get_session_user_oid()
    if not can_access_song(song, user_oid):
        return jsonify({"ok": False}), 403

    text_value = _normalize_lyrics_text(song.get("lyrics_text", ""))
    auto_sync = _lyrics_auto_sync_from_source(song)
    cues = song.get("lyrics_cues") if isinstance(song.get("lyrics_cues"), list) else []
    return jsonify(
        {
            "ok": True,
            "has_lyrics": bool(text_value),
            "lyrics_text": text_value,
            "lyrics_auto_sync": bool(auto_sync),
            "lyrics_cues": cues[:LYRICS_MAX_CUES] if auto_sync else [],
        }
    )


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

    now = datetime.now(UTC)
    existing = extensions.listening_history_col.find_one({"user_id": user_oid, "song_id": song_oid}, {"_id": 1})
    update_doc = {
        "$set": {
            "last_position": max(0.0, position),
            "last_duration": max(0.0, duration),
            "updated_at": now,
        },
        "$setOnInsert": {
            "created_at": now,
        },
    }

    should_inc = started or existing is None
    if should_inc:
        update_doc.setdefault("$inc", {})["play_count"] = 1
    else:
        update_doc["$setOnInsert"]["play_count"] = 0
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

    if contains_profanity(content):
        moderation = register_auto_moderation_violation(user_oid, "comment_create")
        flash(tr("flash.moderation.blocked", remaining=moderation.get("remaining", 0)), "danger")
        if moderation.get("banned"):
            flash(tr("flash.moderation.auto_banned"), "danger")
        return redirect(url_for("songs.song_detail", song_id=song_id))

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



