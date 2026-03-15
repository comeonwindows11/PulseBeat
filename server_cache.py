import glob
import json
import mimetypes
import os
import threading
import time
from hashlib import sha1
from urllib.parse import parse_qs, urlparse

try:
    import yt_dlp
except Exception:  # pragma: no cover - optional dependency at runtime
    yt_dlp = None


_json_cache_lock = threading.Lock()
_youtube_download_lock = threading.Lock()
_youtube_downloads = {}
_youtube_download_semaphore = threading.Semaphore(1)


def init_server_cache(app):
    root = app.config.get("SERVER_CACHE_DIR", "")
    if not root:
        return
    os.makedirs(root, exist_ok=True)
    os.makedirs(os.path.join(root, "json"), exist_ok=True)
    os.makedirs(os.path.join(root, "versions"), exist_ok=True)
    os.makedirs(os.path.join(root, "audio", "youtube"), exist_ok=True)


def _safe_key(value):
    return sha1(str(value or "").encode("utf-8")).hexdigest()


def _json_default(value):
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return str(value)


def _cache_root(app):
    return app.config.get("SERVER_CACHE_DIR", "")


def _json_cache_path(app, kind, key):
    root = os.path.join(_cache_root(app), "json", str(kind or "generic"))
    os.makedirs(root, exist_ok=True)
    return os.path.join(root, f"{_safe_key(key)}.json")


def _version_path(app, group, key):
    root = os.path.join(_cache_root(app), "versions", str(group or "global"))
    os.makedirs(root, exist_ok=True)
    return os.path.join(root, f"{_safe_key(key)}.ver")


def cache_version(app, group, key="global"):
    path = _version_path(app, group, key)
    if not os.path.isfile(path):
        return "0"
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().strip() or "0"
    except Exception:
        return "0"


def touch_cache_version(app, group, key="global"):
    path = _version_path(app, group, key)
    token = str(time.time_ns())
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(token)
    except Exception:
        return "0"
    return token


def _prune_cache_dir(path, *, max_bytes=0, max_files=0, keep_ext=None):
    if not path or not os.path.isdir(path):
        return

    files = []
    total_bytes = 0
    for root, _dirs, names in os.walk(path):
        for name in names:
            full_path = os.path.join(root, name)
            if keep_ext and not full_path.endswith(keep_ext):
                continue
            try:
                stat = os.stat(full_path)
            except OSError:
                continue
            total_bytes += stat.st_size
            files.append((stat.st_atime, stat.st_size, full_path))

    files.sort(key=lambda row: row[0])

    while files and ((max_bytes and total_bytes > max_bytes) or (max_files and len(files) > max_files)):
        _atime, size, full_path = files.pop(0)
        try:
            os.remove(full_path)
        except OSError:
            continue
        total_bytes = max(0, total_bytes - size)


def load_json_cache(app, kind, key, version, ttl_seconds):
    if not ttl_seconds:
        return None
    path = _json_cache_path(app, kind, key)
    if not os.path.isfile(path):
        return None
    try:
        with _json_cache_lock:
            with open(path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
    except Exception:
        return None

    if str(payload.get("version", "")) != str(version):
        return None
    expires_at = float(payload.get("expires_at", 0) or 0)
    if expires_at and expires_at < time.time():
        return None
    try:
        os.utime(path, None)
    except OSError:
        pass
    return payload.get("payload")


def save_json_cache(app, kind, key, version, ttl_seconds, payload):
    if not ttl_seconds:
        return
    path = _json_cache_path(app, kind, key)
    envelope = {
        "version": str(version),
        "cached_at": time.time(),
        "expires_at": time.time() + max(1, int(ttl_seconds)),
        "payload": payload,
    }
    tmp_path = f"{path}.tmp"
    try:
        with _json_cache_lock:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(envelope, fh, ensure_ascii=False, default=_json_default)
            os.replace(tmp_path, path)
    finally:
        try:
            if os.path.isfile(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass

    _prune_cache_dir(
        os.path.join(_cache_root(app), "json"),
        max_bytes=int(app.config.get("SERVER_CACHE_JSON_MAX_BYTES", 20 * 1024 * 1024) or 0),
        max_files=int(app.config.get("SERVER_CACHE_JSON_MAX_FILES", 500) or 0),
        keep_ext=".json",
    )


def get_or_build_json_cache(app, kind, key, version, ttl_seconds, builder):
    cached = load_json_cache(app, kind, key, version, ttl_seconds)
    if cached is not None:
        return cached, True
    payload = builder() if callable(builder) else None
    if payload is not None:
        save_json_cache(app, kind, key, version, ttl_seconds, payload)
    return payload, False


def invalidate_json_cache(app, kind, key=None):
    base = os.path.join(_cache_root(app), "json", str(kind or "generic"))
    if not os.path.isdir(base):
        return
    if key is None:
        for path in glob.glob(os.path.join(base, "*.json")):
            try:
                os.remove(path)
            except OSError:
                pass
        return
    path = _json_cache_path(app, kind, key)
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def public_profile_cache_version(app, user_id):
    return cache_version(app, "public_profile", str(user_id or ""))


def bump_public_profile_cache(app, user_id):
    touch_cache_version(app, "public_profile", str(user_id or ""))
    touch_cache_version(app, "popular_public_profiles", "global")
    invalidate_json_cache(app, "public_profile", str(user_id or ""))


def public_playlist_cache_version(app, playlist_id):
    return cache_version(app, "public_playlist", str(playlist_id or ""))


def bump_public_playlist_cache(app, playlist_id):
    touch_cache_version(app, "public_playlist", str(playlist_id or ""))
    touch_cache_version(app, "popular_public_playlists", "global")
    invalidate_json_cache(app, "public_playlist", str(playlist_id or ""))


def popular_public_songs_cache_version(app):
    return cache_version(app, "popular_public_songs", "global")


def bump_popular_public_songs_cache(app):
    touch_cache_version(app, "popular_public_songs", "global")
    invalidate_json_cache(app, "popular_public_songs", "global")


def cached_popular_song_ids(app, limit, builder, *, ttl_seconds=None):
    safe_limit = max(1, int(limit or 1))
    version = popular_public_songs_cache_version(app)
    ttl_value = int(ttl_seconds or app.config.get("POPULAR_PUBLIC_SONGS_CACHE_TTL_SECONDS", 180) or 0)
    payload, _cache_hit = get_or_build_json_cache(
        app,
        "popular_public_songs",
        f"limit:{safe_limit}",
        f"{version}:{safe_limit}",
        ttl_value,
        lambda: {"ids": [str(item) for item in list(builder(safe_limit) or [])[:safe_limit]]},
    )
    ids = []
    for raw_value in (payload or {}).get("ids", []):
        value = str(raw_value or "").strip()
        if value:
            ids.append(value)
    return ids


def cached_public_profile_payload(app, user_id, builder, *, ttl_seconds=None):
    cache_key = str(user_id or "")
    version = public_profile_cache_version(app, cache_key)
    ttl_value = int(ttl_seconds or app.config.get("PUBLIC_PROFILE_CACHE_TTL_SECONDS", 180) or 0)
    payload, _cache_hit = get_or_build_json_cache(
        app,
        "public_profile",
        cache_key,
        version,
        ttl_value,
        builder,
    )
    return payload


def cached_public_playlist_payload(app, playlist_id, builder, *, ttl_seconds=None):
    cache_key = str(playlist_id or "")
    version = public_playlist_cache_version(app, cache_key)
    ttl_value = int(ttl_seconds or app.config.get("PUBLIC_PLAYLIST_CACHE_TTL_SECONDS", 180) or 0)
    payload, _cache_hit = get_or_build_json_cache(
        app,
        "public_playlist",
        cache_key,
        version,
        ttl_value,
        builder,
    )
    return payload


def _youtube_video_id(song):
    source_url = str((song or {}).get("source_url") or (song or {}).get("url") or "").strip()
    if not source_url:
        return ""
    try:
        parsed = urlparse(source_url)
        host = (parsed.netloc or "").lower()
        if "youtube.com" in host:
            video_id = (parse_qs(parsed.query).get("v") or [""])[0].strip()
            if not video_id and parsed.path.startswith("/shorts/"):
                video_id = parsed.path.replace("/shorts/", "", 1).strip("/ ")
            return video_id
        if "youtu.be" in host:
            return (parsed.path or "").strip("/ ")
    except Exception:
        return ""
    return ""


def _youtube_audio_dir(app):
    root = os.path.join(_cache_root(app), "audio", "youtube")
    os.makedirs(root, exist_ok=True)
    return root


def _youtube_audio_meta_path(app, cache_key):
    return os.path.join(_youtube_audio_dir(app), f"{cache_key}.json")


def _youtube_audio_sidecar_payload(song, cache_key, file_name, file_size):
    source_url = str((song or {}).get("source_url") or "").strip()
    video_id = _youtube_video_id(song)
    rel_path = os.path.join("audio", "youtube", file_name).replace("\\", "/")
    return {
        "cache_key": cache_key,
        "song_id": str((song or {}).get("_id") or (song or {}).get("id") or ""),
        "video_id": video_id,
        "source_url": source_url,
        "file_name": file_name,
        "rel_path": rel_path,
        "file_size": int(file_size or 0),
        "content_type": mimetypes.guess_type(file_name or "")[0] or "audio/mpeg",
        "cached_at": time.time(),
        "last_accessed_at": time.time(),
    }


def cached_youtube_audio_info(app, song, touch=True):
    if not app or not song:
        return None
    cache_key = _youtube_video_id(song)
    if not cache_key:
        return None
    meta_path = _youtube_audio_meta_path(app, cache_key)
    if not os.path.isfile(meta_path):
        return None
    try:
        with open(meta_path, "r", encoding="utf-8") as fh:
            meta = json.load(fh)
    except Exception:
        return None
    if str(meta.get("source_url", "") or "").strip() != str((song or {}).get("source_url") or "").strip():
        return None
    file_name = str(meta.get("file_name", "") or "").strip()
    file_path = os.path.join(_youtube_audio_dir(app), file_name)
    if not file_name or not os.path.isfile(file_path):
        return None
    if touch:
        now = time.time()
        try:
            os.utime(file_path, None)
        except OSError:
            pass
        if now - float(meta.get("last_accessed_at", 0) or 0) > 30:
            meta["last_accessed_at"] = now
            try:
                with open(meta_path, "w", encoding="utf-8") as fh:
                    json.dump(meta, fh, ensure_ascii=False)
            except Exception:
                pass
    meta["file_path"] = file_path
    return meta


def has_cached_youtube_audio(app, song):
    return cached_youtube_audio_info(app, song, touch=False) is not None


def _find_downloaded_youtube_file(app, cache_key):
    candidates = []
    for path in glob.glob(os.path.join(_youtube_audio_dir(app), f"{cache_key}.*")):
        if path.endswith(".json") or path.endswith(".part") or path.endswith(".ytdl"):
            continue
        candidates.append(path)
    if not candidates:
        return ""
    candidates.sort(key=lambda path: os.path.getmtime(path), reverse=True)
    return candidates[0]


def _prune_youtube_audio_cache(app):
    audio_dir = _youtube_audio_dir(app)
    max_bytes = int(app.config.get("YOUTUBE_AUDIO_CACHE_MAX_BYTES", 512 * 1024 * 1024) or 0)
    max_files = int(app.config.get("YOUTUBE_AUDIO_CACHE_MAX_FILES", 80) or 0)
    entries = []
    total_bytes = 0
    active_keys = set()
    with _youtube_download_lock:
        active_keys.update(_youtube_downloads.keys())

    for path in glob.glob(os.path.join(audio_dir, "*")):
        if path.endswith(".json") or path.endswith(".part") or path.endswith(".ytdl"):
            continue
        try:
            stat = os.stat(path)
        except OSError:
            continue
        cache_key = os.path.basename(path).split(".", 1)[0]
        if cache_key in active_keys:
            continue
        total_bytes += stat.st_size
        entries.append((stat.st_atime, stat.st_size, path, cache_key))

    entries.sort(key=lambda row: row[0])
    while entries and ((max_bytes and total_bytes > max_bytes) or (max_files and len(entries) > max_files)):
        _atime, size, path, cache_key = entries.pop(0)
        try:
            os.remove(path)
        except OSError:
            continue
        total_bytes = max(0, total_bytes - size)
        meta_path = _youtube_audio_meta_path(app, cache_key)
        try:
            if os.path.isfile(meta_path):
                os.remove(meta_path)
        except OSError:
            pass


def _download_youtube_audio(app, song_snapshot):
    cache_key = _youtube_video_id(song_snapshot)
    if not cache_key or yt_dlp is None:
        return

    with _youtube_download_semaphore:
        if cached_youtube_audio_info(app, song_snapshot, touch=False):
            return
        outtmpl = os.path.join(_youtube_audio_dir(app), f"{cache_key}.%(ext)s")
        opts = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "noplaylist": True,
            "format": "bestaudio[ext=m4a]/bestaudio/best",
            "outtmpl": outtmpl,
            "overwrites": True,
            "retries": 1,
            "continuedl": False,
        }
        try:
            downloader = yt_dlp.YoutubeDL(opts)
            info = downloader.extract_info(song_snapshot.get("source_url", ""), download=True)
            final_path = _find_downloaded_youtube_file(app, cache_key)
            if not final_path and info:
                candidate = downloader.prepare_filename(info)
                if os.path.isfile(candidate):
                    final_path = candidate
            if not final_path or not os.path.isfile(final_path):
                return
            file_name = os.path.basename(final_path)
            try:
                file_size = os.path.getsize(final_path)
            except OSError:
                file_size = 0
            meta = _youtube_audio_sidecar_payload(apply_song_id(song_snapshot), cache_key, file_name, file_size)
            with open(_youtube_audio_meta_path(app, cache_key), "w", encoding="utf-8") as fh:
                json.dump(meta, fh, ensure_ascii=False)
            _prune_youtube_audio_cache(app)
        except Exception:
            return


def apply_song_id(song_snapshot):
    result = dict(song_snapshot or {})
    if "_id" in result or "id" in result:
        return result
    return result


def queue_youtube_audio_cache(app, song):
    if not app or not song or yt_dlp is None:
        return False
    if not bool(app.config.get("YOUTUBE_AUDIO_CACHE_ENABLED", True)):
        return False
    cache_key = _youtube_video_id(song)
    if not cache_key:
        return False
    if cached_youtube_audio_info(app, song, touch=False):
        return True

    with _youtube_download_lock:
        thread = _youtube_downloads.get(cache_key)
        if thread and thread.is_alive():
            return True

        song_snapshot = {
            "_id": str((song or {}).get("_id") or (song or {}).get("id") or ""),
            "id": str((song or {}).get("_id") or (song or {}).get("id") or ""),
            "source_url": str((song or {}).get("source_url") or (song or {}).get("url") or "").strip(),
        }

        def runner():
            try:
                _download_youtube_audio(app, song_snapshot)
            finally:
                with _youtube_download_lock:
                    _youtube_downloads.pop(cache_key, None)

        thread = threading.Thread(target=runner, name=f"pb-yt-cache-{cache_key[:8]}", daemon=True)
        _youtube_downloads[cache_key] = thread
        thread.start()
    return True


def prune_server_cache(app):
    if not app:
        return
    root = _cache_root(app)
    if not root:
        return
    _prune_cache_dir(
        os.path.join(root, "json"),
        max_bytes=int(app.config.get("SERVER_CACHE_JSON_MAX_BYTES", 20 * 1024 * 1024) or 0),
        max_files=int(app.config.get("SERVER_CACHE_JSON_MAX_FILES", 500) or 0),
        keep_ext=".json",
    )
    _prune_youtube_audio_cache(app)
