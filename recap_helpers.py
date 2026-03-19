from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Iterable

from bson import ObjectId
from flask import current_app, g
from pymongo.errors import DuplicateKeyError

import extensions
from i18n import tr

RECAP_NOTIFICATION_TYPE = "yearly_recap"
RECAP_TYPE_ANNUAL = "annual"
RECAP_TYPE_CUSTOM = "custom"
RECAP_MAX_TOP_ITEMS = 5


def _safe_object_id(value):
    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(str(value or ""))
    except Exception:
        return None


def recap_period_key(recap_type: str, year: int | None = None, start_date: str | None = None, end_date: str | None = None):
    recap_type = str(recap_type or RECAP_TYPE_CUSTOM).strip().lower()
    if recap_type == RECAP_TYPE_ANNUAL and year:
        return f"annual:{int(year)}"
    start_value = str(start_date or "").strip() or "na"
    end_value = str(end_date or "").strip() or "na"
    return f"custom:{start_value}:{end_value}"


def _period_bounds_for_year(year: int):
    year = int(year)
    return (
        datetime(year, 1, 1, tzinfo=UTC),
        datetime(year + 1, 1, 1, tzinfo=UTC),
    )


def _coerce_datetime(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return None


def _coerce_date_string(value):
    value = str(value or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=UTC)
    except Exception:
        return None


def recap_period_bounds(recap_type: str, year: int | None = None, start_date: str | None = None, end_date: str | None = None):
    recap_type = str(recap_type or RECAP_TYPE_CUSTOM).strip().lower()
    if recap_type == RECAP_TYPE_ANNUAL and year:
        return _period_bounds_for_year(int(year))
    start_dt = _coerce_date_string(start_date)
    end_dt = _coerce_date_string(end_date)
    if not start_dt or not end_dt:
        return None, None
    end_dt = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
    if end_dt < start_dt:
        return None, None
    return start_dt, end_dt


def _month_bucket_key(dt_value: datetime | None):
    if not dt_value:
        return ""
    normalized = _coerce_datetime(dt_value)
    if not normalized:
        return ""
    return f"{normalized.year:04d}-{normalized.month:02d}"


def _load_song_snapshots(song_ids: Iterable[ObjectId]):
    normalized_ids = [sid for sid in song_ids if isinstance(sid, ObjectId)]
    if not normalized_ids:
        return {}
    rows = extensions.songs_col.find(
        {"_id": {"$in": normalized_ids}},
        {"title": 1, "artist": 1, "genre": 1, "created_by": 1},
    )
    return {
        row["_id"]: {
            "title": (row.get("title") or tr("defaults.untitled")).strip() or tr("defaults.untitled"),
            "artist": (row.get("artist") or tr("defaults.unknown_artist")).strip() or tr("defaults.unknown_artist"),
            "genre": (row.get("genre") or "").strip(),
            "created_by": row.get("created_by"),
        }
        for row in rows
        if row and row.get("_id")
    }


def _available_history_rows(user_oid, start_dt: datetime, end_dt: datetime):
    query = {
        "user_id": user_oid,
        "$or": [
            {"updated_at": {"$gte": start_dt, "$lt": end_dt}},
            {"last_completed_at": {"$gte": start_dt, "$lt": end_dt}},
            {"created_at": {"$gte": start_dt, "$lt": end_dt}},
        ],
    }
    return list(
        extensions.listening_history_col.find(
            query,
            {"song_id": 1, "play_count": 1, "last_duration": 1, "updated_at": 1, "last_completed_at": 1, "created_at": 1},
        )
    )


def _available_event_rows(user_oid, start_dt: datetime, end_dt: datetime):
    collection = getattr(extensions, "listening_events_col", None)
    if collection is None:
        return []
    return list(
        collection.find(
            {
                "user_id": user_oid,
                "created_at": {"$gte": start_dt, "$lt": end_dt},
                "event_type": {"$in": ["started", "completed"]},
            },
            {"song_id": 1, "event_type": 1, "duration": 1, "created_at": 1},
        )
    )


def _build_payload_from_events(user_oid, start_dt: datetime, end_dt: datetime):
    rows = _available_event_rows(user_oid, start_dt, end_dt)
    started_rows = [row for row in rows if str(row.get("event_type") or "") == "started" and row.get("song_id")]
    if not started_rows:
        return None

    song_counts = Counter()
    song_duration_samples = defaultdict(float)
    monthly_counts = Counter()
    completed_count = 0
    for row in rows:
        song_oid = row.get("song_id")
        if not isinstance(song_oid, ObjectId):
            continue
        if str(row.get("event_type") or "") == "started":
            song_counts[song_oid] += 1
            duration = float(row.get("duration", 0) or 0)
            if duration > 0:
                song_duration_samples[song_oid] = max(song_duration_samples[song_oid], duration)
            monthly_counts[_month_bucket_key(row.get("created_at"))] += 1
        elif str(row.get("event_type") or "") == "completed":
            completed_count += 1

    song_map = _load_song_snapshots(song_counts.keys())
    artist_counts = Counter()
    genre_counts = Counter()
    minutes_listened = 0.0
    for song_oid, plays in song_counts.items():
        snapshot = song_map.get(song_oid)
        if not snapshot:
            continue
        artist_counts[snapshot["artist"]] += plays
        if snapshot.get("genre"):
            genre_counts[snapshot["genre"]] += plays
        duration = float(song_duration_samples.get(song_oid, 0) or 0)
        if duration > 0:
            minutes_listened += (duration * plays) / 60.0

    return {
        "basis": "events",
        "plays_total": int(sum(song_counts.values())),
        "songs_distinct": int(len(song_counts)),
        "artists_distinct": int(len([name for name in artist_counts if name])),
        "completed_plays": int(completed_count),
        "minutes_listened": round(minutes_listened, 1),
        "top_songs": _serialize_top_songs(song_counts, song_map),
        "top_artists": _serialize_top_counter(artist_counts),
        "top_genres": _serialize_top_counter(genre_counts),
        "monthly_breakdown": _serialize_monthly_counter(monthly_counts),
        "data_points": int(len(rows)),
    }


def _build_payload_from_history(user_oid, start_dt: datetime, end_dt: datetime):
    rows = _available_history_rows(user_oid, start_dt, end_dt)
    rows = [row for row in rows if isinstance(row.get("song_id"), ObjectId)]
    if not rows:
        return None

    song_counts = Counter()
    song_duration_samples = defaultdict(float)
    monthly_counts = Counter()
    for row in rows:
        song_oid = row.get("song_id")
        plays = max(1, int(row.get("play_count", 0) or 0))
        song_counts[song_oid] += plays
        duration = float(row.get("last_duration", 0) or 0)
        if duration > 0:
            song_duration_samples[song_oid] = max(song_duration_samples[song_oid], duration)
        month_source = row.get("updated_at") or row.get("last_completed_at") or row.get("created_at")
        monthly_counts[_month_bucket_key(month_source)] += plays

    song_map = _load_song_snapshots(song_counts.keys())
    artist_counts = Counter()
    genre_counts = Counter()
    minutes_listened = 0.0
    for song_oid, plays in song_counts.items():
        snapshot = song_map.get(song_oid)
        if not snapshot:
            continue
        artist_counts[snapshot["artist"]] += plays
        if snapshot.get("genre"):
            genre_counts[snapshot["genre"]] += plays
        duration = float(song_duration_samples.get(song_oid, 0) or 0)
        if duration > 0:
            minutes_listened += (duration * plays) / 60.0

    completed_plays = sum(1 for row in rows if row.get("last_completed_at"))
    return {
        "basis": "history_approx",
        "plays_total": int(sum(song_counts.values())),
        "songs_distinct": int(len(song_counts)),
        "artists_distinct": int(len([name for name in artist_counts if name])),
        "completed_plays": int(completed_plays),
        "minutes_listened": round(minutes_listened, 1),
        "top_songs": _serialize_top_songs(song_counts, song_map),
        "top_artists": _serialize_top_counter(artist_counts),
        "top_genres": _serialize_top_counter(genre_counts),
        "monthly_breakdown": _serialize_monthly_counter(monthly_counts),
        "data_points": int(len(rows)),
    }


def _serialize_top_songs(counter: Counter, song_map: dict):
    items = []
    for song_oid, plays in counter.most_common(RECAP_MAX_TOP_ITEMS):
        snapshot = song_map.get(song_oid)
        if not snapshot:
            continue
        items.append(
            {
                "song_id": str(song_oid),
                "title": snapshot["title"],
                "artist": snapshot["artist"],
                "genre": snapshot.get("genre", ""),
                "plays": int(plays),
            }
        )
    return items


def _serialize_top_counter(counter: Counter):
    return [
        {"name": str(name or "").strip(), "plays": int(plays)}
        for name, plays in counter.most_common(RECAP_MAX_TOP_ITEMS)
        if str(name or "").strip()
    ]


def _serialize_monthly_counter(counter: Counter):
    items = []
    for key in sorted([key for key in counter.keys() if key]):
        items.append({"bucket": key, "plays": int(counter.get(key, 0) or 0)})
    return items


def _recap_title(recap_type: str, year: int | None, start_dt: datetime | None, end_dt: datetime | None):
    if recap_type == RECAP_TYPE_ANNUAL and year:
        return f"PulseBeat Recap {int(year)}"
    start_label = start_dt.strftime("%Y-%m-%d") if start_dt else "?"
    end_label = end_dt.strftime("%Y-%m-%d") if end_dt else "?"
    return f"PulseBeat Recap {start_label} -> {end_label}"


def build_recap_payload(user_oid, recap_type: str, year: int | None = None, start_date: str | None = None, end_date: str | None = None):
    start_dt, end_dt = recap_period_bounds(recap_type, year=year, start_date=start_date, end_date=end_date)
    if not start_dt or not end_dt:
        return None

    payload = _build_payload_from_events(user_oid, start_dt, end_dt)
    if not payload:
        payload = _build_payload_from_history(user_oid, start_dt, end_dt)
    if not payload:
        return None

    payload["title"] = _recap_title(recap_type, year, start_dt, end_dt)
    payload["recap_type"] = recap_type
    payload["year"] = int(year) if year else None
    payload["period_start"] = start_dt.isoformat()
    payload["period_end"] = end_dt.isoformat()
    payload["summary"] = {
        "top_song": payload["top_songs"][0] if payload["top_songs"] else None,
        "top_artist": payload["top_artists"][0] if payload["top_artists"] else None,
        "top_genre": payload["top_genres"][0] if payload["top_genres"] else None,
        "best_month": max(payload["monthly_breakdown"], key=lambda item: item.get("plays", 0), default=None),
    }
    return payload


def create_or_refresh_recap(user_oid, recap_type: str, year: int | None = None, start_date: str | None = None, end_date: str | None = None, trigger: str = "manual", force: bool = False):
    collection = getattr(extensions, "user_recaps_col", None)
    if not user_oid or collection is None:
        return None

    period_key = recap_period_key(recap_type, year=year, start_date=start_date, end_date=end_date)
    if not force:
        existing = collection.find_one({"user_id": user_oid, "period_key": period_key})
        if existing:
            return existing

    payload = build_recap_payload(user_oid, recap_type, year=year, start_date=start_date, end_date=end_date)
    if not payload:
        return None

    now = datetime.now(UTC)
    doc = {
        "user_id": user_oid,
        "recap_type": recap_type,
        "year": payload.get("year"),
        "period_key": period_key,
        "period_start": payload.get("period_start"),
        "period_end": payload.get("period_end"),
        "title": payload.get("title", "PulseBeat Recap"),
        "basis": payload.get("basis", "history_approx"),
        "metrics": {
            "plays_total": int(payload.get("plays_total", 0) or 0),
            "songs_distinct": int(payload.get("songs_distinct", 0) or 0),
            "artists_distinct": int(payload.get("artists_distinct", 0) or 0),
            "completed_plays": int(payload.get("completed_plays", 0) or 0),
            "minutes_listened": float(payload.get("minutes_listened", 0) or 0),
            "data_points": int(payload.get("data_points", 0) or 0),
        },
        "top_songs": payload.get("top_songs", []),
        "top_artists": payload.get("top_artists", []),
        "top_genres": payload.get("top_genres", []),
        "monthly_breakdown": payload.get("monthly_breakdown", []),
        "summary": payload.get("summary", {}),
        "trigger": str(trigger or "manual"),
        "updated_at": now,
    }
    update_doc = {"$set": doc, "$setOnInsert": {"created_at": now}}
    try:
        collection.update_one({"user_id": user_oid, "period_key": period_key}, update_doc, upsert=True)
    except DuplicateKeyError:
        pass
    return collection.find_one({"user_id": user_oid, "period_key": period_key})


def list_user_recaps(user_oid, limit: int = 12):
    collection = getattr(extensions, "user_recaps_col", None)
    if not user_oid or collection is None:
        return []
    items = []
    for row in collection.find({"user_id": user_oid}).sort("updated_at", -1).limit(max(1, int(limit or 12))):
        metrics = row.get("metrics", {}) if isinstance(row.get("metrics"), dict) else {}
        items.append(
            {
                "id": str(row.get("_id")),
                "title": row.get("title", "PulseBeat Recap"),
                "recap_type": row.get("recap_type", RECAP_TYPE_CUSTOM),
                "year": row.get("year"),
                "period_start": row.get("period_start", ""),
                "period_end": row.get("period_end", ""),
                "basis": row.get("basis", "history_approx"),
                "basis_label": tr("recap.basis.events") if str(row.get("basis", "")).strip().lower() == "events" else tr("recap.basis.approx"),
                "plays_total": int(metrics.get("plays_total", 0) or 0),
                "minutes_listened": float(metrics.get("minutes_listened", 0) or 0),
                "updated_at": row.get("updated_at") or row.get("created_at"),
            }
        )
    return items


def get_available_recap_years(user_oid):
    years = set()
    collection = getattr(extensions, "listening_events_col", None)
    if user_oid and collection is not None:
        for row in collection.find({"user_id": user_oid}, {"created_at": 1}):
            created_at = _coerce_datetime(row.get("created_at"))
            if created_at:
                years.add(created_at.year)

    for row in _available_history_rows(user_oid, datetime(2020, 1, 1, tzinfo=UTC), datetime.now(UTC) + timedelta(days=1)):
        stamp = _coerce_datetime(row.get("updated_at") or row.get("last_completed_at") or row.get("created_at"))
        if stamp:
            years.add(stamp.year)

    if not years:
        years.add(datetime.now(UTC).year)
    return sorted(years, reverse=True)


def get_recap_document(user_oid, recap_id):
    collection = getattr(extensions, "user_recaps_col", None)
    recap_oid = _safe_object_id(recap_id)
    if not user_oid or collection is None or not recap_oid:
        return None
    return collection.find_one({"_id": recap_oid, "user_id": user_oid})


def ensure_yearly_recap_notification(user_oid, year: int | None = None):
    notifications_col = getattr(extensions, "user_notifications_col", None)
    if not user_oid or notifications_col is None:
        return None

    resolved_year = int(year or (datetime.now(UTC).year - 1))
    if resolved_year < 2020:
        return None

    cache_key = f"annual_recap_checked:{str(user_oid)}:{resolved_year}"
    if getattr(g, cache_key, False):
        return None
    setattr(g, cache_key, True)

    existing = notifications_col.find_one(
        {
            "recipient_user_id": user_oid,
            "notification_type": RECAP_NOTIFICATION_TYPE,
            "content_type": "recap",
            "content_id": f"annual:{resolved_year}",
        },
        {"_id": 1},
    )
    if existing:
        return existing

    recap = create_or_refresh_recap(user_oid, RECAP_TYPE_ANNUAL, year=resolved_year, trigger="automatic", force=False)
    if not recap:
        return None

    metrics = recap.get("metrics", {}) if isinstance(recap.get("metrics"), dict) else {}
    if int(metrics.get("plays_total", 0) or 0) <= 0:
        return None

    now = datetime.now(UTC)
    doc = {
        "recipient_user_id": user_oid,
        "notification_type": RECAP_NOTIFICATION_TYPE,
        "creator_id": None,
        "creator_username_snapshot": current_app.config.get("APP_NAME", "PulseBeat"),
        "content_type": "recap",
        "content_id": f"annual:{resolved_year}",
        "content_title": f"PulseBeat Recap {resolved_year}",
        "recap_id": recap.get("_id"),
        "recap_year": resolved_year,
        "created_at": now,
        "is_read": False,
        "read_at": None,
    }
    try:
        result = notifications_col.insert_one(doc)
        doc["_id"] = result.inserted_id
        return doc
    except DuplicateKeyError:
        return notifications_col.find_one(
            {
                "recipient_user_id": user_oid,
                "notification_type": RECAP_NOTIFICATION_TYPE,
                "content_type": "recap",
                "content_id": f"annual:{resolved_year}",
            }
        )


def record_listening_event(user_oid, song_oid, event_type: str, position: float = 0.0, duration: float = 0.0):
    collection = getattr(extensions, "listening_events_col", None)
    if collection is None or not user_oid or not song_oid:
        return
    normalized_event = str(event_type or "").strip().lower()
    if normalized_event not in {"started", "completed"}:
        return
    collection.insert_one(
        {
            "user_id": user_oid,
            "song_id": song_oid,
            "event_type": normalized_event,
            "position": float(position or 0.0),
            "duration": float(duration or 0.0),
            "created_at": datetime.now(UTC),
        }
    )
