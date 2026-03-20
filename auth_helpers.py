import hashlib
import os
import re
import secrets
import smtplib
import threading
import time
import errno
from collections import deque
from datetime import datetime, timedelta
from email.message import EmailMessage
from functools import wraps
from urllib.parse import parse_qs, urlparse

import requests
from bson import ObjectId
from flask import current_app, flash, g, jsonify, redirect, render_template, request, session, url_for
from pymongo.errors import AutoReconnect, BulkWriteError, DuplicateKeyError, NetworkTimeout, OperationFailure, WriteError
from werkzeug.exceptions import Conflict, HTTPException
from werkzeug.utils import secure_filename

import extensions
from i18n import tr
from server_cache import (
    bump_popular_public_songs_cache,
    bump_public_playlist_cache,
    bump_public_profile_cache,
    has_cached_youtube_audio,
)
from recap_helpers import ensure_yearly_recap_notification, RECAP_NOTIFICATION_TYPE

ALLOWED_EXTENSIONS = {"mp3", "wav", "ogg", "m4a"}
VISIBILITY_VALUES = {"public", "private", "unlisted"}
PASSWORD_POLICY_RE = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{6,}$")
USERNAME_POLICY_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")

KNOWN_EMAIL_PROVIDER_DOMAINS = {
    "gmail.com", "googlemail.com",
    "outlook.com", "hotmail.com", "live.com", "msn.com",
    "icloud.com", "me.com", "mac.com",
    "yahoo.com", "yahoo.ca", "yahoo.fr", "ymail.com",
    "aol.com",
    "proton.me", "protonmail.com",
    "mail.com", "gmx.com", "gmx.net",
    "zoho.com", "yandex.com", "yandex.ru",
    "qq.com",
}

DISPOSABLE_EMAIL_DOMAINS = {
    "10minutemail.com",
    "10minutemail.net",
    "guerrillamail.com",
    "mailinator.com",
    "temp-mail.org",
    "tempmail.dev",
    "tempmailo.com",
    "yopmail.com",
    "dispostable.com",
    "sharklasers.com",
    "getnada.com",
    "trashmail.com",
}

PROFANITY_TERMS = {
    "fuck",
    "fucking",
    "shit",
    "bitch",
    "asshole",
    "bastard",
    "dick",
    "motherfucker",
    "fuk",
    "f*ck",
    "merde",
    "putain",
    "connard",
    "connasse",
    "encule",
    "enculé",
    "enculee",
    "enculée",
    "salope",
    "batard",
    "bâtard",
    "nique",
    "niquer",
}

AUTO_MODERATION_BAN_THRESHOLD = 3
AUTO_MODERATION_BAN_DAYS = 36500

FEATURE_DEFAULTS_FULL = {
    "usage_mode": "full",
    "enable_password_reset": True,
    "enable_advanced_moderation": True,
    "enable_google_oauth": True,
    "enable_email_notifications": True,
    "enable_youtube_integration": True,
    "enable_database_audio_storage": False,
    "database_audio_storage_allowed_user_ids": [],
}
APP_SETTINGS_DOC_ID = "global"
YOUTUBE_URL_RE = re.compile(r"(youtube\.com|youtu\.be)", re.IGNORECASE)
DEVICE_COOKIE_DEFAULT_NAME = "pulsebeat_device_id"
MAX_TRACKED_DEVICES = 10
MAX_TRACKED_ACTIVE_SESSIONS = 10
ROBOT_WATCHDOG_SESSION_KEY = "pulsebeat_robot_watchdog"
ROBOT_CHALLENGE_SESSION_KEY = "pulsebeat_robot_challenge"
ROBOT_WATCHDOG_SKIP_ENDPOINTS = {
    "favicon",
    "dino_easter_egg",
    "dino_leaderboard_api",
    "accounts.robot_check",
    "songs.stream_song",
    "songs.playback_meta",
    "songs.update_progress",
    "songs.recover_audio",
    "main.live_songs",
}


class InvalidStoredDocumentError(Exception):
    def __init__(self, collection_name: str, reason: str, document_id=None):
        self.collection_name = str(collection_name or "unknown")
        self.reason = str(reason or "invalid_document")
        self.document_id = document_id
        super().__init__(f"Invalid stored document in {self.collection_name}: {self.reason}")


class ConflictRequestError(Conflict):
    description = "Conflict"


class InsufficientStorageError(HTTPException):
    code = 507
    description = "Insufficient Storage"


def parse_object_id(value: str):
    try:
        return ObjectId(value)
    except Exception:
        return None


def _flatten_pymongo_error_message(exc) -> str:
    parts = [str(exc or "")]
    details = getattr(exc, "details", None)
    if isinstance(details, dict):
        errmsg = details.get("errmsg")
        if errmsg:
            parts.append(str(errmsg))
        write_errors = details.get("writeErrors") or []
        if isinstance(write_errors, list):
            for item in write_errors[:3]:
                if isinstance(item, dict) and item.get("errmsg"):
                    parts.append(str(item.get("errmsg")))
    return " | ".join(part for part in parts if str(part).strip())


def is_mongo_conflict_error(exc) -> bool:
    if isinstance(exc, DuplicateKeyError):
        return True
    lowered = _flatten_pymongo_error_message(exc).lower()
    return "e11000" in lowered or "duplicate key error" in lowered


def is_storage_related_mongo_error(exc) -> bool:
    lowered = _flatten_pymongo_error_message(exc).lower()
    needles = (
        "quota",
        "storage",
        "disk full",
        "no space left",
        "insufficient storage",
        "exceeded storage",
        "space quota",
        "maximum storage",
        "data size limit",
        "cannot allocate space",
        "not enough disk space",
    )
    return any(needle in lowered for needle in needles)


def is_local_storage_os_error(exc) -> bool:
    error_no = getattr(exc, "errno", None)
    if error_no == errno.ENOSPC:
        return True
    lowered = str(exc or "").lower()
    return "no space left on device" in lowered or "not enough space on the disk" in lowered


def mark_storage_full_latch(source: str, detail: str = ""):
    app = current_app._get_current_object()
    state = dict(app.config.get("STORAGE_FULL_STATE") or {})
    details = list(state.get("details") or [])
    normalized_source = "database" if str(source or "").strip().lower() == "database" else "server"
    state[normalized_source] = True
    if detail:
        trimmed = str(detail).strip()[:400]
        if trimmed and trimmed not in details:
            details.append(trimmed)
    state["details"] = details
    app.config["STORAGE_FULL_STATE"] = state
    app.config["STORAGE_FULL_LATCHED"] = True


def raise_http_error_for_mongo_failure(exc):
    if is_storage_related_mongo_error(exc):
        mark_storage_full_latch("database", _flatten_pymongo_error_message(exc))
        raise InsufficientStorageError()
    if is_mongo_conflict_error(exc):
        raise ConflictRequestError()


def _collection_for_invalid_document_watchdog(collection_name: str):
    mapping = {
        "users": getattr(extensions, "users_col", None),
        "songs": getattr(extensions, "songs_col", None),
        "playlists": getattr(extensions, "playlists_col", None),
        "external_integrations": getattr(extensions, "external_integrations_col", None),
        "external_playlists": getattr(extensions, "external_playlists_col", None),
        "external_import_jobs": getattr(extensions, "external_import_jobs_col", None),
        "data_exports": getattr(extensions, "data_exports_col", None),
        "song_votes": getattr(extensions, "song_votes_col", None),
        "song_comments": getattr(extensions, "song_comments_col", None),
        "comment_votes": getattr(extensions, "comment_votes_col", None),
        "song_reports": getattr(extensions, "song_reports_col", None),
        "listening_history": getattr(extensions, "listening_history_col", None),
        "admin_audit": getattr(extensions, "admin_audit_col", None),
        "system_status": getattr(extensions, "system_status_col", None),
        "app_settings": getattr(extensions, "app_settings_col", None),
        "user_notifications": getattr(extensions, "user_notifications_col", None),
        "creator_subscriptions": getattr(extensions, "creator_subscriptions_col", None),
        "dino_leaderboard": getattr(extensions, "dino_leaderboard_col", None),
    }
    return mapping.get(str(collection_name or "").strip(), None)


def _document_type_error(field_name: str, expected: str):
    return f"field '{field_name}' must be {expected}"


def _validate_user_document_shape(user):
    if not isinstance(user, dict):
        return False, "document is not an object"
    if not user.get("_id"):
        return False, "missing _id"
    if "username" in user and user.get("username") is not None and not isinstance(user.get("username"), str):
        return False, _document_type_error("username", "a string")
    if "email" in user and user.get("email") is not None and not isinstance(user.get("email"), str):
        return False, _document_type_error("email", "a string")
    if "trusted_devices" in user and user.get("trusted_devices") is not None and not isinstance(user.get("trusted_devices"), list):
        return False, _document_type_error("trusted_devices", "a list")
    if "active_sessions" in user and user.get("active_sessions") is not None and not isinstance(user.get("active_sessions"), list):
        return False, _document_type_error("active_sessions", "a list")
    if "dismissed_admin_alerts" in user and user.get("dismissed_admin_alerts") is not None and not isinstance(user.get("dismissed_admin_alerts"), list):
        return False, _document_type_error("dismissed_admin_alerts", "a list")
    return True, ""


def _validate_song_document_shape(song):
    if not isinstance(song, dict):
        return False, "document is not an object"
    if not song.get("_id"):
        return False, "missing _id"
    if "title" in song and song.get("title") is not None and not isinstance(song.get("title"), str):
        return False, _document_type_error("title", "a string")
    if "artist" in song and song.get("artist") is not None and not isinstance(song.get("artist"), str):
        return False, _document_type_error("artist", "a string")
    if "genre" in song and song.get("genre") is not None and not isinstance(song.get("genre"), str):
        return False, _document_type_error("genre", "a string")
    if "visibility" in song and song.get("visibility") is not None and not isinstance(song.get("visibility"), str):
        return False, _document_type_error("visibility", "a string")
    if "shared_with" in song and song.get("shared_with") is not None and not isinstance(song.get("shared_with"), list):
        return False, _document_type_error("shared_with", "a list")
    if "source_type" in song and song.get("source_type") is not None and not isinstance(song.get("source_type"), str):
        return False, _document_type_error("source_type", "a string")
    if "source_url" in song and song.get("source_url") is not None and not isinstance(song.get("source_url"), str):
        return False, _document_type_error("source_url", "a string")
    if "external_provider" in song and song.get("external_provider") is not None and not isinstance(song.get("external_provider"), str):
        return False, _document_type_error("external_provider", "a string")
    return True, ""


def _validate_playlist_document_shape(playlist):
    if not isinstance(playlist, dict):
        return False, "document is not an object"
    if not playlist.get("_id"):
        return False, "missing _id"
    if "name" in playlist and playlist.get("name") is not None and not isinstance(playlist.get("name"), str):
        return False, _document_type_error("name", "a string")
    if "song_ids" in playlist and playlist.get("song_ids") is not None and not isinstance(playlist.get("song_ids"), list):
        return False, _document_type_error("song_ids", "a list")
    if "collaborator_ids" in playlist and playlist.get("collaborator_ids") is not None and not isinstance(playlist.get("collaborator_ids"), list):
        return False, _document_type_error("collaborator_ids", "a list")
    if "visibility" in playlist and playlist.get("visibility") is not None and not isinstance(playlist.get("visibility"), str):
        return False, _document_type_error("visibility", "a string")
    return True, ""


def _validate_comment_document_shape(comment):
    if not isinstance(comment, dict):
        return False, "document is not an object"
    if not comment.get("_id"):
        return False, "missing _id"
    if "content" in comment and comment.get("content") is not None and not isinstance(comment.get("content"), str):
        return False, _document_type_error("content", "a string")
    return True, ""


def _validate_vote_document_shape(vote, target_key: str):
    if not isinstance(vote, dict):
        return False, "document is not an object"
    if not vote.get("_id"):
        return False, "missing _id"
    if target_key in vote and not vote.get(target_key):
        return False, f"missing {target_key}"
    if "user_id" in vote and not vote.get("user_id"):
        return False, "missing user_id"
    vote_value = vote.get("vote")
    if "vote" in vote and (not isinstance(vote_value, int) or vote_value not in {-1, 1}):
        return False, _document_type_error("vote", "an integer equal to -1 or 1")
    return True, ""


def _validate_listening_history_document_shape(row):
    if not isinstance(row, dict):
        return False, "document is not an object"
    if not row.get("_id"):
        return False, "missing _id"
    if "user_id" in row and not row.get("user_id"):
        return False, "missing user_id"
    if "song_id" in row and not row.get("song_id"):
        return False, "missing song_id"
    if "play_count" in row and row.get("play_count") is not None and not isinstance(row.get("play_count"), int):
        return False, _document_type_error("play_count", "an integer")
    return True, ""


def _validate_song_report_document_shape(report):
    if not isinstance(report, dict):
        return False, "document is not an object"
    if not report.get("_id"):
        return False, "missing _id"
    if "reporter_id" in report and report.get("reporter_id") is None:
        return False, "missing reporter_id"
    target_type = report.get("target_type")
    if "target_type" in report and (not isinstance(target_type, str) or target_type.strip().lower() not in {"song", "comment"}):
        return False, _document_type_error("target_type", "a string equal to 'song' or 'comment'")
    status = report.get("status")
    if status is not None and (not isinstance(status, str) or status.strip().lower() not in {"open", "resolved", "dismissed"}):
        return False, _document_type_error("status", "a string equal to open, resolved or dismissed")
    return True, ""


def _validate_admin_audit_document_shape(row):
    if not isinstance(row, dict):
        return False, "document is not an object"
    if not row.get("_id"):
        return False, "missing _id"
    if not isinstance(row.get("action"), str) or not row.get("action", "").strip():
        return False, _document_type_error("action", "a non-empty string")
    if not isinstance(row.get("target_type"), str) or not row.get("target_type", "").strip():
        return False, _document_type_error("target_type", "a non-empty string")
    if "details" in row and row.get("details") is not None and not isinstance(row.get("details"), dict):
        return False, _document_type_error("details", "an object")
    return True, ""


def _validate_creator_subscription_document_shape(row):
    if not isinstance(row, dict):
        return False, "document is not an object"
    if not row.get("_id"):
        return False, "missing _id"
    if "creator_id" in row and not row.get("creator_id"):
        return False, "missing creator_id"
    if "subscriber_id" in row and not row.get("subscriber_id"):
        return False, "missing subscriber_id"
    if "notifications_enabled" in row and row.get("notifications_enabled") is not None and not isinstance(row.get("notifications_enabled"), bool):
        return False, _document_type_error("notifications_enabled", "a boolean")
    return True, ""


def _validate_user_notification_document_shape(row):
    if not isinstance(row, dict):
        return False, "document is not an object"
    if not row.get("_id"):
        return False, "missing _id"
    if "recipient_user_id" in row and not row.get("recipient_user_id"):
        return False, "missing recipient_user_id"
    if "notification_type" in row and row.get("notification_type") is not None and not isinstance(row.get("notification_type"), str):
        return False, _document_type_error("notification_type", "a string")
    if "content_type" in row and row.get("content_type") is not None and not isinstance(row.get("content_type"), str):
        return False, _document_type_error("content_type", "a string")
    if "content_title" in row and row.get("content_title") is not None and not isinstance(row.get("content_title"), str):
        return False, _document_type_error("content_title", "a string")
    if "is_read" in row and row.get("is_read") is not None and not isinstance(row.get("is_read"), bool):
        return False, _document_type_error("is_read", "a boolean")
    return True, ""


def _validate_external_import_job_document_shape(row):
    if not isinstance(row, dict):
        return False, "document is not an object"
    if not row.get("_id"):
        return False, "missing _id"
    if "user_id" in row and not row.get("user_id"):
        return False, "missing user_id"
    if "status" in row and row.get("status") is not None and not isinstance(row.get("status"), str):
        return False, _document_type_error("status", "a string")
    return True, ""


def _validate_external_playlist_document_shape(row):
    if not isinstance(row, dict):
        return False, "document is not an object"
    if not row.get("_id"):
        return False, "missing _id"
    if "name" in row and row.get("name") is not None and not isinstance(row.get("name"), str):
        return False, _document_type_error("name", "a string")
    return True, ""


def _validate_external_integration_document_shape(row):
    if not isinstance(row, dict):
        return False, "document is not an object"
    if not row.get("_id"):
        return False, "missing _id"
    if "user_id" in row and not row.get("user_id"):
        return False, "missing user_id"
    if "provider" in row and row.get("provider") is not None and not isinstance(row.get("provider"), str):
        return False, _document_type_error("provider", "a string")
    return True, ""


def _validate_data_export_document_shape(row):
    if not isinstance(row, dict):
        return False, "document is not an object"
    if not row.get("_id"):
        return False, "missing _id"
    if "user_id" in row and not row.get("user_id"):
        return False, "missing user_id"
    if "status" in row and row.get("status") is not None and not isinstance(row.get("status"), str):
        return False, _document_type_error("status", "a string")
    return True, ""


def _validate_system_status_document_shape(row):
    if not isinstance(row, dict):
        return False, "document is not an object"
    if not row.get("_id"):
        return False, "missing _id"
    if not isinstance(row.get("key"), str) or not row.get("key", "").strip():
        return False, _document_type_error("key", "a non-empty string")
    if "status" in row and row.get("status") is not None and not isinstance(row.get("status"), str):
        return False, _document_type_error("status", "a string")
    if "message" in row and row.get("message") is not None and not isinstance(row.get("message"), str):
        return False, _document_type_error("message", "a string")
    return True, ""


def _validate_app_settings_document_shape(row):
    if not isinstance(row, dict):
        return False, "document is not an object"
    if "_id" not in row:
        return False, "missing _id"
    return True, ""


def _validate_dino_leaderboard_document_shape(row):
    if not isinstance(row, dict):
        return False, "document is not an object"
    if not row.get("_id"):
        return False, "missing _id"
    if "owner_key" in row and (not isinstance(row.get("owner_key"), str) or not row.get("owner_key", "").strip()):
        return False, _document_type_error("owner_key", "a non-empty string")
    if "best_score" in row and row.get("best_score") is not None and not isinstance(row.get("best_score"), int):
        return False, _document_type_error("best_score", "an integer")
    if "is_robot" in row and row.get("is_robot") is not None and not isinstance(row.get("is_robot"), bool):
        return False, _document_type_error("is_robot", "a boolean")
    return True, ""


def validate_document_shape(collection_name: str, document):
    collection_key = str(collection_name or "").strip()
    if collection_key == "users":
        return _validate_user_document_shape(document)
    if collection_key == "songs":
        return _validate_song_document_shape(document)
    if collection_key == "playlists":
        return _validate_playlist_document_shape(document)
    if collection_key == "song_comments":
        return _validate_comment_document_shape(document)
    if collection_key == "song_votes":
        return _validate_vote_document_shape(document, "song_id")
    if collection_key == "comment_votes":
        return _validate_vote_document_shape(document, "comment_id")
    if collection_key == "listening_history":
        return _validate_listening_history_document_shape(document)
    if collection_key == "song_reports":
        return _validate_song_report_document_shape(document)
    if collection_key == "admin_audit":
        return _validate_admin_audit_document_shape(document)
    if collection_key == "creator_subscriptions":
        return _validate_creator_subscription_document_shape(document)
    if collection_key == "user_notifications":
        return _validate_user_notification_document_shape(document)
    if collection_key == "external_import_jobs":
        return _validate_external_import_job_document_shape(document)
    if collection_key == "external_playlists":
        return _validate_external_playlist_document_shape(document)
    if collection_key == "external_integrations":
        return _validate_external_integration_document_shape(document)
    if collection_key == "data_exports":
        return _validate_data_export_document_shape(document)
    if collection_key == "system_status":
        return _validate_system_status_document_shape(document)
    if collection_key == "app_settings":
        return _validate_app_settings_document_shape(document)
    if collection_key == "dino_leaderboard":
        return _validate_dino_leaderboard_document_shape(document)
    if not isinstance(document, dict):
        return False, "document is not an object"
    if not document.get("_id"):
        return False, "missing _id"
    return True, ""


def _persist_repaired_document(collection_name: str, document_id, update_fields: dict):
    if not document_id or not isinstance(update_fields, dict) or not update_fields:
        return False
    collection = _collection_for_invalid_document_watchdog(collection_name)
    if collection is None:
        return False
    try:
        safe_mongo_update_one(
            collection,
            {"_id": document_id},
            {"$set": update_fields},
        )
        return True
    except Exception:
        current_app.logger.warning(
            "Unable to persist repaired document fields for %s (%s)",
            collection_name,
            document_id,
            exc_info=True,
        )
        return False


def _recover_user_document(user):
    if not isinstance(user, dict) or not user.get("_id"):
        return None, {}
    repaired = dict(user)
    updates = {}
    for field_name in ("trusted_devices", "active_sessions", "dismissed_admin_alerts", "pending_device_approvals"):
        if field_name in repaired and repaired.get(field_name) is not None and not isinstance(repaired.get(field_name), list):
            repaired[field_name] = []
            updates[field_name] = []
    return repaired, updates


def _recover_song_document(song):
    if not isinstance(song, dict) or not song.get("_id"):
        return None, {}
    repaired = dict(song)
    updates = {}

    if not isinstance(repaired.get("title"), str) or not (repaired.get("title") or "").strip():
        repaired["title"] = "Untitled"
        updates["title"] = "Untitled"
    else:
        repaired["title"] = repaired.get("title", "").strip()
        if repaired["title"] != song.get("title"):
            updates["title"] = repaired["title"]

    if not isinstance(repaired.get("artist"), str) or not (repaired.get("artist") or "").strip():
        repaired["artist"] = "Unknown artist"
        updates["artist"] = "Unknown artist"
    else:
        repaired["artist"] = repaired.get("artist", "").strip()
        if repaired["artist"] != song.get("artist"):
            updates["artist"] = repaired["artist"]

    if not isinstance(repaired.get("genre"), str):
        repaired["genre"] = ""
        updates["genre"] = ""
    if not isinstance(repaired.get("source_type"), str):
        repaired["source_type"] = ""
        updates["source_type"] = ""
    if not isinstance(repaired.get("source_url"), str):
        repaired["source_url"] = ""
        updates["source_url"] = ""
    if not isinstance(repaired.get("external_provider"), str):
        repaired["external_provider"] = ""
        updates["external_provider"] = ""
    if not isinstance(repaired.get("availability_reason"), str):
        repaired["availability_reason"] = ""
        updates["availability_reason"] = ""
    if repaired.get("shared_with") is not None and not isinstance(repaired.get("shared_with"), list):
        repaired["shared_with"] = []
        updates["shared_with"] = []

    visibility = repaired.get("visibility")
    if not isinstance(visibility, str) or visibility.strip().lower() not in VISIBILITY_VALUES:
        repaired["visibility"] = "public"
        updates["visibility"] = "public"
    else:
        normalized_visibility = visibility.strip().lower()
        if normalized_visibility != visibility:
            repaired["visibility"] = normalized_visibility
            updates["visibility"] = normalized_visibility

    return repaired, updates


def _recover_playlist_document(playlist):
    if not isinstance(playlist, dict) or not playlist.get("_id"):
        return None, {}
    repaired = dict(playlist)
    updates = {}

    if not isinstance(repaired.get("name"), str) or not (repaired.get("name") or "").strip():
        repaired["name"] = "Playlist"
        updates["name"] = "Playlist"
    else:
        trimmed_name = repaired.get("name", "").strip()
        if trimmed_name != repaired.get("name"):
            repaired["name"] = trimmed_name
            updates["name"] = trimmed_name

    if repaired.get("song_ids") is not None and not isinstance(repaired.get("song_ids"), list):
        repaired["song_ids"] = []
        updates["song_ids"] = []
    if repaired.get("collaborator_ids") is not None and not isinstance(repaired.get("collaborator_ids"), list):
        repaired["collaborator_ids"] = []
        updates["collaborator_ids"] = []

    visibility = repaired.get("visibility")
    allowed_values = {"public", "private", "unlisted"}
    if not isinstance(visibility, str) or visibility.strip().lower() not in allowed_values:
        repaired["visibility"] = "private"
        updates["visibility"] = "private"
    else:
        normalized_visibility = visibility.strip().lower()
        if normalized_visibility != visibility:
            repaired["visibility"] = normalized_visibility
            updates["visibility"] = normalized_visibility

    return repaired, updates


def _recover_comment_document(comment):
    if not isinstance(comment, dict) or not comment.get("_id"):
        return None, {}
    repaired = dict(comment)
    updates = {}
    content = repaired.get("content")
    if not isinstance(content, str):
        if isinstance(content, (int, float, bool)):
            repaired["content"] = str(content)
        else:
            repaired["content"] = "[message unavailable]"
        updates["content"] = repaired["content"]
    return repaired, updates


def _recover_vote_document(vote, target_key: str):
    if not isinstance(vote, dict) or not vote.get("_id"):
        return None, {}
    repaired = dict(vote)
    updates = {}
    raw_vote = repaired.get("vote")
    if "vote" not in repaired:
        return repaired, updates
    if isinstance(raw_vote, bool):
        repaired["vote"] = 1 if raw_vote else -1
        updates["vote"] = repaired["vote"]
    elif isinstance(raw_vote, (int, float)):
        repaired["vote"] = 1 if float(raw_vote) >= 0 else -1
        updates["vote"] = repaired["vote"]
    else:
        return None, {}
    return repaired, updates


def _recover_listening_history_document(row):
    if not isinstance(row, dict) or not row.get("_id"):
        return None, {}
    repaired = dict(row)
    updates = {}
    if "play_count" in repaired and not isinstance(repaired.get("play_count"), int):
        try:
            repaired["play_count"] = max(0, int(repaired.get("play_count", 0) or 0))
        except Exception:
            repaired["play_count"] = 0
        updates["play_count"] = repaired["play_count"]
    for field_name in ("last_position", "last_duration"):
        value = repaired.get(field_name, 0)
        if not isinstance(value, (int, float)):
            try:
                repaired[field_name] = max(0.0, float(value or 0))
            except Exception:
                repaired[field_name] = 0.0
            updates[field_name] = repaired[field_name]
    return repaired, updates


def _recover_song_report_document(report):
    if not isinstance(report, dict) or not report.get("_id"):
        return None, {}
    repaired = dict(report)
    updates = {}
    target_type = repaired.get("target_type")
    if "target_type" in repaired and (not isinstance(target_type, str) or target_type.strip().lower() not in {"song", "comment"}):
        if repaired.get("target_comment_id"):
            repaired["target_type"] = "comment"
        elif repaired.get("target_song_id") or repaired.get("song_id"):
            repaired["target_type"] = "song"
        else:
            return None, {}
        updates["target_type"] = repaired["target_type"]
    status = repaired.get("status")
    if "status" in repaired and (not isinstance(status, str) or status.strip().lower() not in {"open", "resolved", "dismissed"}):
        repaired["status"] = "open"
        updates["status"] = "open"
    if "reason" in repaired and repaired.get("reason") is not None and not isinstance(repaired.get("reason"), str):
        repaired["reason"] = str(repaired.get("reason") or "")
        updates["reason"] = repaired["reason"]
    return repaired, updates


def _recover_admin_audit_document(row):
    if not isinstance(row, dict) or not row.get("_id"):
        return None, {}
    repaired = dict(row)
    updates = {}
    if not isinstance(repaired.get("action"), str) or not repaired.get("action", "").strip():
        repaired["action"] = "unknown_action"
        updates["action"] = "unknown_action"
    if not isinstance(repaired.get("target_type"), str) or not repaired.get("target_type", "").strip():
        repaired["target_type"] = "unknown_target"
        updates["target_type"] = "unknown_target"
    if "details" in repaired and repaired.get("details") is not None and not isinstance(repaired.get("details"), dict):
        repaired["details"] = {"raw": str(repaired.get("details"))}
        updates["details"] = repaired["details"]
    return repaired, updates


def _recover_creator_subscription_document(row):
    if not isinstance(row, dict) or not row.get("_id"):
        return None, {}
    repaired = dict(row)
    updates = {}
    if "notifications_enabled" in repaired and not isinstance(repaired.get("notifications_enabled"), bool):
        repaired["notifications_enabled"] = bool(repaired.get("notifications_enabled"))
        updates["notifications_enabled"] = repaired["notifications_enabled"]
    return repaired, updates


def _recover_user_notification_document(row):
    if not isinstance(row, dict) or not row.get("_id"):
        return None, {}
    repaired = dict(row)
    updates = {}
    if "notification_type" in repaired and not isinstance(repaired.get("notification_type"), str):
        repaired["notification_type"] = "generic"
        updates["notification_type"] = "generic"
    if "content_type" in repaired and not isinstance(repaired.get("content_type"), str):
        repaired["content_type"] = ""
        updates["content_type"] = ""
    if "content_title" in repaired and not isinstance(repaired.get("content_title"), str):
        repaired["content_title"] = tr("defaults.untitled")
        updates["content_title"] = repaired["content_title"]
    if "creator_username_snapshot" in repaired and not isinstance(repaired.get("creator_username_snapshot"), str):
        repaired["creator_username_snapshot"] = ""
        updates["creator_username_snapshot"] = ""
    if "is_read" in repaired and not isinstance(repaired.get("is_read"), bool):
        repaired["is_read"] = bool(repaired.get("is_read"))
        updates["is_read"] = repaired["is_read"]
    return repaired, updates


def _recover_external_import_job_document(row):
    if not isinstance(row, dict) or not row.get("_id"):
        return None, {}
    repaired = dict(row)
    updates = {}
    if "status" in repaired and not isinstance(repaired.get("status"), str):
        repaired["status"] = "queued"
        updates["status"] = "queued"
    if "error_message" in repaired and repaired.get("error_message") is not None and not isinstance(repaired.get("error_message"), str):
        repaired["error_message"] = str(repaired.get("error_message") or "")
        updates["error_message"] = repaired["error_message"]
    return repaired, updates


def _recover_external_playlist_document(row):
    if not isinstance(row, dict) or not row.get("_id"):
        return None, {}
    repaired = dict(row)
    updates = {}
    if not isinstance(repaired.get("name"), str):
        repaired["name"] = tr("defaults.unnamed")
        updates["name"] = repaired["name"]
    return repaired, updates


def _recover_external_integration_document(row):
    if not isinstance(row, dict) or not row.get("_id"):
        return None, {}
    repaired = dict(row)
    updates = {}
    if "provider" in repaired and not isinstance(repaired.get("provider"), str):
        repaired["provider"] = ""
        updates["provider"] = ""
    return repaired, updates


def _recover_data_export_document(row):
    if not isinstance(row, dict) or not row.get("_id"):
        return None, {}
    repaired = dict(row)
    updates = {}
    if "status" in repaired and not isinstance(repaired.get("status"), str):
        repaired["status"] = "unknown"
        updates["status"] = "unknown"
    return repaired, updates


def _recover_system_status_document(row):
    if not isinstance(row, dict) or "_id" not in row:
        return None, {}
    repaired = dict(row)
    updates = {}
    if not isinstance(repaired.get("key"), str) or not repaired.get("key", "").strip():
        return None, {}
    if "status" in repaired and repaired.get("status") is not None and not isinstance(repaired.get("status"), str):
        repaired["status"] = "unknown"
        updates["status"] = "unknown"
    if "message" in repaired and repaired.get("message") is not None and not isinstance(repaired.get("message"), str):
        repaired["message"] = str(repaired.get("message") or "")
        updates["message"] = repaired["message"]
    return repaired, updates


def _recover_dino_leaderboard_document(row):
    if not isinstance(row, dict) or not row.get("_id"):
        return None, {}
    repaired = dict(row)
    updates = {}
    if "best_score" in repaired and not isinstance(repaired.get("best_score"), int):
        try:
            repaired["best_score"] = max(0, int(repaired.get("best_score", 0) or 0))
        except Exception:
            repaired["best_score"] = 0
        updates["best_score"] = repaired["best_score"]
    if "is_robot" in repaired and not isinstance(repaired.get("is_robot"), bool):
        repaired["is_robot"] = bool(repaired.get("is_robot"))
        updates["is_robot"] = repaired["is_robot"]
    if "actor_type" in repaired and not isinstance(repaired.get("actor_type"), str):
        repaired["actor_type"] = "guest"
        updates["actor_type"] = "guest"
    if "display_name" in repaired and not isinstance(repaired.get("display_name"), str):
        repaired["display_name"] = ""
        updates["display_name"] = ""
    if "guest_code" in repaired and not isinstance(repaired.get("guest_code"), str):
        repaired["guest_code"] = ""
        updates["guest_code"] = ""
    return repaired, updates


def attempt_recover_invalid_document(collection_name: str, document, context: str = ""):
    collection_key = str(collection_name or "").strip()
    repaired = None
    updates = {}
    if collection_key == "users":
        repaired, updates = _recover_user_document(document)
    elif collection_key == "songs":
        repaired, updates = _recover_song_document(document)
    elif collection_key == "playlists":
        repaired, updates = _recover_playlist_document(document)
    elif collection_key == "song_comments":
        repaired, updates = _recover_comment_document(document)
    elif collection_key == "song_votes":
        repaired, updates = _recover_vote_document(document, "song_id")
    elif collection_key == "comment_votes":
        repaired, updates = _recover_vote_document(document, "comment_id")
    elif collection_key == "listening_history":
        repaired, updates = _recover_listening_history_document(document)
    elif collection_key == "song_reports":
        repaired, updates = _recover_song_report_document(document)
    elif collection_key == "admin_audit":
        repaired, updates = _recover_admin_audit_document(document)
    elif collection_key == "creator_subscriptions":
        repaired, updates = _recover_creator_subscription_document(document)
    elif collection_key == "user_notifications":
        repaired, updates = _recover_user_notification_document(document)
    elif collection_key == "external_import_jobs":
        repaired, updates = _recover_external_import_job_document(document)
    elif collection_key == "external_playlists":
        repaired, updates = _recover_external_playlist_document(document)
    elif collection_key == "external_integrations":
        repaired, updates = _recover_external_integration_document(document)
    elif collection_key == "data_exports":
        repaired, updates = _recover_data_export_document(document)
    elif collection_key == "system_status":
        repaired, updates = _recover_system_status_document(document)
    elif collection_key == "dino_leaderboard":
        repaired, updates = _recover_dino_leaderboard_document(document)

    if not repaired:
        return None

    is_valid, _reason = validate_document_shape(collection_name, repaired)
    if not is_valid:
        return None

    if updates:
        _persist_repaired_document(collection_name, repaired.get("_id"), updates)
        current_app.logger.warning(
            "Recovered invalid document in %s (%s) during %s with updates: %s",
            collection_name,
            repaired.get("_id"),
            context or "server operation",
            ", ".join(sorted(updates.keys())),
        )
    return repaired


def report_invalid_document(collection_name: str, document, reason: str, context: str = ""):
    collection_name = str(collection_name or "unknown").strip() or "unknown"
    reason_text = str(reason or "invalid_document").strip() or "invalid_document"
    context_text = str(context or "").strip()
    document_id = ""
    if isinstance(document, dict) and document.get("_id"):
        document_id = str(document.get("_id"))

    alert_message = tr(
        "admin.invalid_document_alert_message",
        collection=collection_name,
        document_id=document_id or "?",
        reason=reason_text,
        context=context_text or tr("admin.invalid_document_context_default"),
    )

    collection = _collection_for_invalid_document_watchdog(collection_name)
    deleted = False
    if collection is not None and document_id:
        try:
            result = collection.delete_one({"_id": document.get("_id")})
            deleted = bool(getattr(result, "deleted_count", 0))
        except Exception:
            current_app.logger.warning(
                "Failed to delete invalid document from %s (%s)",
                collection_name,
                document_id,
                exc_info=True,
            )

    now = datetime.utcnow()
    if extensions.system_status_col is not None:
        try:
            extensions.system_status_col.update_one(
                {"key": "invalid_document_watchdog"},
                {
                    "$set": {
                        "key": "invalid_document_watchdog",
                        "status": "alert",
                        "message": alert_message,
                        "updated_at": now,
                        "collection": collection_name,
                        "document_id": document_id,
                        "reason": reason_text,
                        "context": context_text,
                        "deleted": deleted,
                    }
                },
                upsert=True,
            )
        except Exception:
            current_app.logger.warning("Unable to persist invalid document watchdog status", exc_info=True)

    if getattr(extensions, "admin_audit_col", None) is not None:
        try:
            extensions.admin_audit_col.insert_one(
                {
                    "admin_user_id": None,
                    "action": "auto_delete_invalid_document",
                    "target_type": collection_name,
                    "target_id": document_id or None,
                    "details": {
                        "reason": reason_text,
                        "context": context_text,
                        "deleted": deleted,
                    },
                    "created_at": now,
                }
            )
        except Exception:
            current_app.logger.warning("Unable to write audit log for invalid document watchdog", exc_info=True)

    try:
        notify_admins(
            "email.admin_alert_subject",
            "email.admin_alert_body",
            message=alert_message,
        )
    except Exception:
        current_app.logger.warning("Unable to notify admins about invalid document watchdog event", exc_info=True)

    current_app.logger.warning(
        "Invalid document watchdog triggered for %s (document=%s, deleted=%s, context=%s): %s",
        collection_name,
        document_id or "?",
        deleted,
        context_text or "-",
        reason_text,
    )
    return InvalidStoredDocumentError(collection_name, reason_text, document_id=document_id or None)


def validate_or_purge_document(collection_name: str, document, context: str = "", fatal: bool = False):
    if document is None:
        return None
    is_valid, reason = validate_document_shape(collection_name, document)
    if is_valid:
        return document
    recovered = attempt_recover_invalid_document(collection_name, document, context=context)
    if recovered is not None:
        return recovered
    if not fatal:
        if not isinstance(document, dict) or not document.get("_id"):
            current_app.logger.warning(
                "Skipping structurally invalid document from %s during %s without deleting it",
                collection_name,
                context or "server operation",
            )
            return None
        current_app.logger.warning(
            "Keeping potentially invalid document from %s during %s because no fatal failure occurred yet: %s",
            collection_name,
            context or "server operation",
            reason,
        )
        return document
    error = report_invalid_document(collection_name, document, reason, context=context)
    if fatal:
        raise error
    return None


def get_session_user_oid():
    return parse_object_id(session.get("user_id", ""))


def _hash_text(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def _session_device_cookie_name() -> str:
    return str(current_app.config.get("DEVICE_COOKIE_NAME", DEVICE_COOKIE_DEFAULT_NAME) or DEVICE_COOKIE_DEFAULT_NAME)


def _session_device_cookie_max_age() -> int:
    return max(3600, int(current_app.config.get("DEVICE_COOKIE_MAX_AGE", 31536000) or 31536000))


def _request_wants_json() -> bool:
    requested_with = (request.headers.get("X-Requested-With", "") or "").strip().lower()
    accept = (request.headers.get("Accept", "") or "").lower()
    content_type = (request.content_type or "").lower()
    return bool(request.is_json or requested_with == "xmlhttprequest" or "application/json" in accept or "application/json" in content_type)


def _client_ip_address() -> str:
    forwarded = (request.headers.get("X-Forwarded-For", "") or "").split(",")[0].strip()
    if forwarded:
        return forwarded
    return (request.headers.get("X-Real-IP", "") or request.remote_addr or "").strip()


def _coarse_ip_prefix(ip_address: str) -> str:
    raw = (ip_address or "").strip()
    if not raw:
        return ""
    if ":" in raw:
        return ":".join([part for part in raw.split(":") if part][:4])
    if "." in raw:
        return ".".join(raw.split(".")[:3])
    return raw[:32]


def _browser_family(user_agent: str) -> str:
    ua = (user_agent or "").lower()
    if "edg/" in ua:
        return "Edge"
    if "opr/" in ua or "opera" in ua:
        return "Opera"
    if "firefox/" in ua:
        return "Firefox"
    if "chrome/" in ua or "chromium/" in ua:
        return "Chrome"
    if "safari/" in ua:
        return "Safari"
    return "Browser"


def _os_family(user_agent: str) -> str:
    ua = (user_agent or "").lower()
    if "windows" in ua:
        return "Windows"
    if "android" in ua:
        return "Android"
    if "iphone" in ua or "ipad" in ua or "ios" in ua:
        return "iOS"
    if "mac os" in ua or "macintosh" in ua:
        return "macOS"
    if "linux" in ua:
        return "Linux"
    return "Device"


def _user_agent_signature(user_agent: str) -> str:
    return f"{_os_family(user_agent)}|{_browser_family(user_agent)}"


def _device_label(user_agent: str) -> str:
    return f"{_os_family(user_agent)} / {_browser_family(user_agent)}"


def ensure_request_device_id() -> str:
    cached = getattr(g, "_pulsebeat_device_id", "")
    if cached:
        return cached

    cookie_name = _session_device_cookie_name()
    raw_value = (request.cookies.get(cookie_name, "") or "").strip()
    if raw_value:
        g._pulsebeat_device_id = raw_value
        return raw_value

    raw_value = secrets.token_urlsafe(32)
    g._pulsebeat_device_id = raw_value
    g._pulsebeat_device_cookie_needs_set = True
    return raw_value


def get_request_device_context():
    raw_device_id = ensure_request_device_id()
    user_agent = (request.headers.get("User-Agent", "") or "").strip()
    ua_signature = _user_agent_signature(user_agent)
    ip_address = _client_ip_address()
    return {
        "device_id": raw_device_id,
        "device_hash": _hash_text(raw_device_id),
        "ua_hash": _hash_text(ua_signature),
        "ua_signature": ua_signature,
        "label": _device_label(user_agent),
        "ip_prefix": _coarse_ip_prefix(ip_address),
    }


def device_summary_text(context: dict | None) -> str:
    data = context or {}
    label = str(data.get("label", "") or "").strip()
    ip_prefix = str(data.get("ip_prefix", "") or "").strip()
    if label and ip_prefix:
        return f"{label} ({ip_prefix})"
    return label or ip_prefix or "unknown"


def apply_session_security_cookies(response):
    if not getattr(g, "_pulsebeat_device_cookie_needs_set", False):
        return response

    cookie_name = _session_device_cookie_name()
    raw_value = getattr(g, "_pulsebeat_device_id", "")
    if not raw_value:
        return response

    response.set_cookie(
        cookie_name,
        raw_value,
        max_age=_session_device_cookie_max_age(),
        httponly=True,
        secure=bool(current_app.config.get("SESSION_COOKIE_SECURE", False)),
        samesite=str(current_app.config.get("SESSION_COOKIE_SAMESITE", "Lax") or "Lax"),
        path="/",
    )
    return response


def _trusted_devices_list(user) -> list:
    return list((user or {}).get("trusted_devices", []) or [])


def is_trusted_device(user, context: dict | None) -> bool:
    data = context or {}
    device_hash = str(data.get("device_hash", "") or "")
    ua_hash = str(data.get("ua_hash", "") or "")
    if not device_hash:
        return False
    for entry in _trusted_devices_list(user):
        if str(entry.get("device_hash", "") or "") != device_hash:
            continue
        entry_ua_hash = str(entry.get("ua_hash", "") or "")
        if not entry_ua_hash or not ua_hash or entry_ua_hash == ua_hash:
            return True
    return False


def remember_trusted_device(user_oid, context: dict | None):
    if not user_oid or not context:
        return
    now = datetime.utcnow()
    entry = {
        "device_hash": str(context.get("device_hash", "") or ""),
        "ua_hash": str(context.get("ua_hash", "") or ""),
        "label": str(context.get("label", "") or ""),
        "last_ip_prefix": str(context.get("ip_prefix", "") or ""),
        "first_seen_at": now,
        "last_seen_at": now,
    }
    if not entry["device_hash"]:
        return
    result = safe_mongo_update_one(
        extensions.users_col,
        {"_id": user_oid, "trusted_devices.device_hash": entry["device_hash"]},
        {
            "$set": {
                "trusted_devices.$.ua_hash": entry["ua_hash"],
                "trusted_devices.$.label": entry["label"],
                "trusted_devices.$.last_ip_prefix": entry["last_ip_prefix"],
                "trusted_devices.$.last_seen_at": now,
            }
        },
    )
    if result.matched_count:
        return

    inserted = safe_mongo_update_one(
        extensions.users_col,
        {"_id": user_oid, "trusted_devices.device_hash": {"$ne": entry["device_hash"]}},
        {"$push": {"trusted_devices": {"$each": [entry], "$slice": -MAX_TRACKED_DEVICES}}},
    )
    if not inserted.matched_count:
        safe_mongo_update_one(
            extensions.users_col,
            {"_id": user_oid, "trusted_devices.device_hash": entry["device_hash"]},
            {
                "$set": {
                    "trusted_devices.$.ua_hash": entry["ua_hash"],
                    "trusted_devices.$.label": entry["label"],
                    "trusted_devices.$.last_ip_prefix": entry["last_ip_prefix"],
                    "trusted_devices.$.last_seen_at": now,
                }
            },
        )


def touch_trusted_device(user_oid, context: dict | None):
    if not user_oid or not context or not context.get("device_hash"):
        return
    now = datetime.utcnow()
    result = safe_mongo_update_one(
        extensions.users_col,
        {"_id": user_oid, "trusted_devices.device_hash": context["device_hash"]},
        {
            "$set": {
                "trusted_devices.$.ua_hash": str(context.get("ua_hash", "") or ""),
                "trusted_devices.$.label": str(context.get("label", "") or ""),
                "trusted_devices.$.last_ip_prefix": str(context.get("ip_prefix", "") or ""),
                "trusted_devices.$.last_seen_at": now,
            }
        },
    )
    if result.matched_count == 0:
        remember_trusted_device(user_oid, context)


def _register_active_session(user_oid, context: dict | None) -> str:
    if not user_oid or not context:
        return ""
    session_id = secrets.token_urlsafe(32)
    now = datetime.utcnow()
    entry = {
        "session_id": session_id,
        "device_hash": str(context.get("device_hash", "") or ""),
        "ua_hash": str(context.get("ua_hash", "") or ""),
        "label": str(context.get("label", "") or ""),
        "last_ip_prefix": str(context.get("ip_prefix", "") or ""),
        "created_at": now,
        "last_seen_at": now,
    }
    device_hash = entry["device_hash"]
    if device_hash:
        result = safe_mongo_update_one(
            extensions.users_col,
            {"_id": user_oid, "active_sessions.device_hash": device_hash},
            {
                "$set": {
                    "active_sessions.$.session_id": session_id,
                    "active_sessions.$.ua_hash": entry["ua_hash"],
                    "active_sessions.$.label": entry["label"],
                    "active_sessions.$.last_ip_prefix": entry["last_ip_prefix"],
                    "active_sessions.$.created_at": now,
                    "active_sessions.$.last_seen_at": now,
                }
            },
        )
        if not result.matched_count:
            inserted = safe_mongo_update_one(
                extensions.users_col,
                {"_id": user_oid, "active_sessions.device_hash": {"$ne": device_hash}},
                {"$push": {"active_sessions": {"$each": [entry], "$slice": -MAX_TRACKED_ACTIVE_SESSIONS}}},
            )
            if not inserted.matched_count:
                safe_mongo_update_one(
                    extensions.users_col,
                    {"_id": user_oid, "active_sessions.device_hash": device_hash},
                    {
                        "$set": {
                            "active_sessions.$.session_id": session_id,
                            "active_sessions.$.ua_hash": entry["ua_hash"],
                            "active_sessions.$.label": entry["label"],
                            "active_sessions.$.last_ip_prefix": entry["last_ip_prefix"],
                            "active_sessions.$.created_at": now,
                            "active_sessions.$.last_seen_at": now,
                        }
                    },
                )
    else:
        safe_mongo_update_one(
            extensions.users_col,
            {"_id": user_oid},
            {"$push": {"active_sessions": {"$each": [entry], "$slice": -MAX_TRACKED_ACTIVE_SESSIONS}}},
        )
    return session_id


def begin_authenticated_session(user):
    if not user:
        return ""
    user_oid = user.get("_id")
    context = get_request_device_context()
    remember_trusted_device(user_oid, context)
    session.clear()
    session["user_id"] = str(user_oid)
    session["session_token_version"] = int(user.get("session_token_version", 0) or 0)
    session["active_session_id"] = _register_active_session(user_oid, context)
    return session.get("active_session_id", "")


def clear_current_session_binding(user_oid=None):
    session_id = str(session.get("active_session_id", "") or "").strip()
    if user_oid and session_id:
        safe_mongo_update_one(
            extensions.users_col,
            {"_id": user_oid},
            {"$pull": {"active_sessions": {"session_id": session_id}}},
        )
    session.pop("active_session_id", None)


def _build_session_invalid_response():
    message = tr("flash.accounts.session_invalidated")
    if _request_wants_json():
        return jsonify({"ok": False, "message": message}), 401
    flash(message, "warning")
    return redirect(url_for("accounts.login"))


def _send_suspicious_session_alert(user, context: dict | None):
    if not user:
        return False
    summary = device_summary_text(context)
    plain_text = tr("auth.suspicious_session_plain_body", username=user.get("username", "user"), device=summary)
    html_body = f"""
<html>
  <body style="margin:0;padding:0;background:#f4f6fb;font-family:Segoe UI,Arial,sans-serif;color:#101828;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f4f6fb;padding:24px 0;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:640px;background:#ffffff;border-radius:18px;overflow:hidden;border:1px solid #d9e1f2;">
            <tr>
              <td style="padding:24px;background:#0f172a;color:#f8fafc;">
                <h1 style="margin:0;font-size:24px;">PulseBeat</h1>
              </td>
            </tr>
            <tr>
              <td style="padding:24px;">
                <h2 style="margin:0 0 14px 0;font-size:22px;color:#101828;">{tr("auth.suspicious_session_heading")}</h2>
                <p style="margin:0 0 12px 0;line-height:1.6;">{tr("auth.suspicious_session_html_greeting", username=user.get("username", "user"))}</p>
                <p style="margin:0 0 12px 0;line-height:1.6;">{tr("auth.suspicious_session_html_intro", device=summary)}</p>
                <p style="margin:0;line-height:1.6;color:#5b6472;">{tr("auth.suspicious_session_ignore")}</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""
    return send_email_message(user.get("email", ""), tr("auth.suspicious_session_subject"), plain_text, html_body)


def _build_suspicious_session_response(user, context: dict | None):
    _send_suspicious_session_alert(user, context)
    message = tr("flash.accounts.session_suspicious")
    if _request_wants_json():
        return jsonify({"ok": False, "message": message}), 403
    return (
        render_template(
            "accounts/session_blocked.jinja",
            blocked_title=tr("account.session_blocked_title"),
            blocked_body=tr("account.session_blocked_body"),
            blocked_note=tr("account.session_blocked_note"),
            blocked_login_label=tr("account.session_blocked_cta"),
        ),
        403,
    )


def validate_bound_session_request(user):
    if not user:
        return None

    user_oid = user.get("_id")
    if not user_oid:
        session.clear()
        return _build_session_invalid_response()

    context = get_request_device_context()
    session_id = str(session.get("active_session_id", "") or "").strip()
    if not session_id:
        touch_trusted_device(user_oid, context)
        session["active_session_id"] = _register_active_session(user_oid, context)
        return None

    active_sessions = list(user.get("active_sessions", []) or [])
    active_entry = next((row for row in active_sessions if str(row.get("session_id", "") or "") == session_id), None)
    if not active_entry:
        clear_current_session_binding(user_oid)
        session.clear()
        return _build_session_invalid_response()

    expected_device_hash = str(active_entry.get("device_hash", "") or "")
    expected_ua_hash = str(active_entry.get("ua_hash", "") or "")
    current_device_hash = str(context.get("device_hash", "") or "")
    current_ua_hash = str(context.get("ua_hash", "") or "")
    if expected_device_hash != current_device_hash or (expected_ua_hash and expected_ua_hash != current_ua_hash):
        clear_current_session_binding(user_oid)
        session.clear()
        return _build_suspicious_session_response(user, context)

    now = datetime.utcnow()
    result = safe_mongo_update_one(
        extensions.users_col,
        {"_id": user_oid, "active_sessions.session_id": session_id},
        {
            "$set": {
                "active_sessions.$.last_seen_at": now,
                "active_sessions.$.label": str(context.get("label", "") or ""),
                "active_sessions.$.last_ip_prefix": str(context.get("ip_prefix", "") or ""),
                "active_sessions.$.ua_hash": current_ua_hash,
            }
        },
    )
    if result.matched_count == 0:
        clear_current_session_binding(user_oid)
        session.clear()
        return _build_session_invalid_response()
    touch_trusted_device(user_oid, context)
    return None


def get_app_settings():
    settings = dict(FEATURE_DEFAULTS_FULL)
    settings_col = getattr(extensions, "app_settings_col", None)
    if settings_col is None:
        return settings

    doc = settings_col.find_one({"_id": APP_SETTINGS_DOC_ID}) or {}
    doc = validate_or_purge_document("app_settings", doc, context="auth.get_app_settings") or {}
    for key, default_value in FEATURE_DEFAULTS_FULL.items():
        if key not in doc:
            continue
        raw_value = doc.get(key)
        if isinstance(default_value, bool):
            if isinstance(raw_value, str):
                settings[key] = raw_value.strip().lower() in {"1", "true", "yes", "on"}
            else:
                settings[key] = bool(raw_value)
        else:
            settings[key] = raw_value
    return settings


def save_app_settings(settings: dict):
    if not isinstance(settings, dict):
        return

    settings_col = getattr(extensions, "app_settings_col", None)
    if settings_col is None:
        return

    update_set = {}
    for key, default_value in FEATURE_DEFAULTS_FULL.items():
        if key not in settings:
            continue
        raw_value = settings.get(key)
        if isinstance(default_value, bool):
            if isinstance(raw_value, str):
                update_set[key] = raw_value.strip().lower() in {"1", "true", "yes", "on"}
            else:
                update_set[key] = bool(raw_value)
        else:
            update_set[key] = raw_value

    if not update_set:
        return

    now = datetime.utcnow()
    settings_col.update_one(
        {"_id": APP_SETTINGS_DOC_ID},
        {"$set": {**update_set, "updated_at": now}, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )


def is_feature_enabled(flag_name: str, default=True):
    # Most legacy feature flags are intentionally always-on.
    # Only YouTube integration is admin-toggleable globally.
    if flag_name == "enable_youtube_integration":
        settings = get_app_settings()
        raw_value = settings.get(flag_name, default)
        if isinstance(raw_value, str):
            return raw_value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(raw_value)
    return bool(default)


def is_youtube_integration_enabled(default=True):
    return is_feature_enabled("enable_youtube_integration", default=default)


def get_database_audio_storage_settings():
    settings = get_app_settings()
    enabled_raw = settings.get("enable_database_audio_storage", False)
    if isinstance(enabled_raw, str):
        enabled = enabled_raw.strip().lower() in {"1", "true", "yes", "on"}
    else:
        enabled = bool(enabled_raw)

    raw_ids = settings.get("database_audio_storage_allowed_user_ids", [])
    if isinstance(raw_ids, str):
        raw_ids = [part.strip() for part in raw_ids.split(",") if part.strip()]
    elif not isinstance(raw_ids, (list, tuple, set)):
        raw_ids = []

    normalized_ids = []
    for value in raw_ids:
        text = str(value or "").strip()
        if text:
            normalized_ids.append(text)

    return {"enabled": enabled, "allowed_user_ids": normalized_ids}


def is_database_audio_storage_enabled(default=False):
    settings = get_database_audio_storage_settings()
    if settings:
        return bool(settings.get("enabled", False))
    return bool(default)


def can_user_use_database_audio_storage(user) -> bool:
    if not user or not is_database_audio_storage_enabled(False):
        return False
    if bool((user or {}).get("is_admin", False)):
        return True
    user_id = str((user or {}).get("_id", "") or "").strip()
    if not user_id:
        return False
    settings = get_database_audio_storage_settings()
    allowed_ids = set(settings.get("allowed_user_ids", []))
    return user_id in allowed_ids


def song_has_database_audio(song) -> bool:
    if not song:
        return False
    if str((song or {}).get("storage_mode", "server") or "server").strip().lower() != "database":
        return False
    gridfs_id = (song or {}).get("gridfs_file_id")
    if isinstance(gridfs_id, ObjectId):
        return True
    return parse_object_id(str(gridfs_id or "")) is not None


def song_gridfs_file_id(song):
    if not song:
        return None
    gridfs_id = song.get("gridfs_file_id")
    if isinstance(gridfs_id, ObjectId):
        return gridfs_id
    return parse_object_id(str(gridfs_id or ""))


def is_youtube_song(song) -> bool:
    if not song:
        return False
    provider = (song.get("external_provider") or "").strip().lower()
    if provider == "youtube":
        return True
    source_url = (song.get("source_url") or song.get("url") or "").strip()
    return bool(source_url and YOUTUBE_URL_RE.search(source_url))


def youtube_song_visibility_clause():
    if is_youtube_integration_enabled(True):
        return {}
    return {
        "$nor": [
            {"external_provider": "youtube"},
            {"source_url": {"$regex": YOUTUBE_URL_RE.pattern, "$options": "i"}},
            {"url": {"$regex": YOUTUBE_URL_RE.pattern, "$options": "i"}},
        ]
    }


def compose_and_filters(*clauses):
    parts = [part for part in clauses if isinstance(part, dict) and part]
    if not parts:
        return {}
    if len(parts) == 1:
        return parts[0]
    return {"$and": parts}


def sanitize_update_document(update_doc):
    if not isinstance(update_doc, dict):
        return update_doc

    normalized = {}
    for op, payload in update_doc.items():
        if isinstance(payload, dict):
            normalized[op] = dict(payload)
        else:
            normalized[op] = payload

    set_doc = normalized.get("$set") if isinstance(normalized.get("$set"), dict) else {}
    set_on_insert = normalized.get("$setOnInsert") if isinstance(normalized.get("$setOnInsert"), dict) else {}
    if set_doc and set_on_insert:
        for field in list(set(set_doc.keys()) & set(set_on_insert.keys())):
            set_on_insert.pop(field, None)
        if set_on_insert:
            normalized["$setOnInsert"] = set_on_insert
        else:
            normalized.pop("$setOnInsert", None)
    return normalized


def _is_retryable_operation_failure(exc: OperationFailure) -> bool:
    details = getattr(exc, "details", {}) or {}
    labels = details.get("errorLabels") or []
    if isinstance(labels, list) and any(label in {"RetryableWriteError", "TransientTransactionError"} for label in labels):
        return True
    code = int(getattr(exc, "code", 0) or 0)
    return code in {6, 7, 89, 91, 112, 11600, 11602, 10107, 13435}


def safe_mongo_update_one(collection, filter_doc, update_doc, upsert=False, max_retries=2):
    prepared = sanitize_update_document(update_doc)
    retries = max(0, int(max_retries or 0))

    for attempt in range(retries + 1):
        try:
            return collection.update_one(filter_doc, prepared, upsert=upsert)
        except WriteError as exc:
            message = str(exc)
            is_conflict = "would create a conflict at" in message.lower()
            if is_conflict and attempt < retries:
                prepared = sanitize_update_document(prepared)
                time.sleep(0.02 * (attempt + 1))
                continue
            raise
        except DuplicateKeyError:
            if upsert and attempt < retries:
                time.sleep(0.02 * (attempt + 1))
                continue
            raise
        except (AutoReconnect, NetworkTimeout):
            if attempt < retries:
                time.sleep(0.05 * (attempt + 1))
                continue
            raise
        except OperationFailure as exc:
            if _is_retryable_operation_failure(exc) and attempt < retries:
                time.sleep(0.05 * (attempt + 1))
                continue
            raise

    return collection.update_one(filter_doc, prepared, upsert=upsert)


def is_youtube_linked_playlist(playlist) -> bool:
    if not playlist:
        return False
    provider = (playlist.get("external_source_provider") or "").strip().lower()
    if provider == "youtube":
        return True
    name = (playlist.get("name") or "").strip().lower()
    return name.startswith("[youtube]")


def youtube_playlist_visibility_clause():
    if is_youtube_integration_enabled(True):
        return {}
    return {
        "$and": [
            {"$or": [{"external_source_provider": {"$exists": False}}, {"external_source_provider": {"$ne": "youtube"}}]},
            {"name": {"$not": {"$regex": r"^\s*\[youtube\]", "$options": "i"}}},
        ]
    }


def password_policy_ok(password: str) -> bool:
    return bool(PASSWORD_POLICY_RE.match(password or ""))


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def normalize_username(username: str) -> str:
    return (username or "").strip().lower()


def is_disposable_email(email: str) -> bool:
    normalized = normalize_email(email)
    if "@" not in normalized:
        return False

    domain = normalized.split("@", 1)[1].strip().lower()
    if not domain or "." not in domain:
        return True

    if domain in DISPOSABLE_EMAIL_DOMAINS or any(domain.endswith(f".{d}") for d in DISPOSABLE_EMAIL_DOMAINS):
        return True

    if domain in KNOWN_EMAIL_PROVIDER_DOMAINS:
        return False

    # Heuristique: certains patterns de domaines temporaires sont très fréquents.
    disposable_markers = ("temp", "trash", "10min", "minute", "mailinator", "guerrilla", "disposable", "throwaway")
    if any(marker in domain for marker in disposable_markers):
        return True

    # Dans ce projet, un domaine non reconnu est considéré à risque/jetable.
    return True


def contains_profanity(text_value: str) -> bool:
    value = (text_value or "").lower()
    if not value:
        return False
    compact = re.sub(r"\s+", " ", value)
    return any(term in compact for term in PROFANITY_TERMS)


def register_auto_moderation_violation(user_oid, source: str):
    user = extensions.users_col.find_one({"_id": user_oid}, {"username": 1, "auto_moderation_strikes": 1, "is_root_admin": 1})
    if not user:
        return {"strikes": 0, "remaining": AUTO_MODERATION_BAN_THRESHOLD, "banned": False, "exempt": False}

    if user.get("is_root_admin", False):
        return {
            "strikes": int(user.get("auto_moderation_strikes", 0) or 0),
            "remaining": AUTO_MODERATION_BAN_THRESHOLD,
            "banned": False,
            "exempt": True,
        }

    now = datetime.utcnow()
    current = int(user.get("auto_moderation_strikes", 0) or 0)
    strikes = current + 1
    remaining = max(0, AUTO_MODERATION_BAN_THRESHOLD - strikes)

    set_payload = {
        "auto_moderation_strikes": strikes,
        "auto_moderation_last_source": source,
        "auto_moderation_last_at": now,
    }

    banned = False
    if strikes >= AUTO_MODERATION_BAN_THRESHOLD:
        set_payload["banned_until"] = now + timedelta(days=AUTO_MODERATION_BAN_DAYS)
        set_payload["auto_banned"] = True
        banned = True

    extensions.users_col.update_one({"_id": user_oid}, {"$set": set_payload})

    username = user.get("username", "user")
    alert_message = tr(
        "moderation.admin_alert_message",
        username=username,
        source=source,
        strikes=strikes,
        remaining=remaining,
    )

    if extensions.system_status_col is not None:
        extensions.system_status_col.update_one(
            {"key": "auto_moderation"},
            {
                "$set": {
                    "key": "auto_moderation",
                    "status": "alert",
                    "message": alert_message,
                    "updated_at": now,
                    "username": username,
                    "source": source,
                    "strikes": strikes,
                    "remaining": remaining,
                    "banned": banned,
                }
            },
            upsert=True,
        )

    notify_admins(
        "email.admin_alert_subject",
        "email.admin_alert_body",
        message=alert_message,
    )

    return {"strikes": strikes, "remaining": remaining, "banned": banned, "exempt": False}


def username_policy_ok(username: str) -> bool:
    return bool(USERNAME_POLICY_RE.match((username or "").strip()))


def _mail_configured():
    host = current_app.config.get("MAIL_HOST", "")
    sender = current_app.config.get("MAIL_FROM", "")
    return bool(current_app.config.get("MAIL_ENABLED", False) and host and sender)


def send_email_message(to_email: str, subject: str, text_body: str, html_body: str | None = None):
    if not to_email or not _mail_configured() or not is_feature_enabled("enable_email_notifications", True):
        return False

    host = current_app.config.get("MAIL_HOST", "")
    port = int(current_app.config.get("MAIL_PORT", 587))
    mail_from = current_app.config.get("MAIL_FROM", "")
    mail_user = current_app.config.get("MAIL_USERNAME", "")
    mail_pass = current_app.config.get("MAIL_PASSWORD", "")
    use_tls = bool(current_app.config.get("MAIL_USE_TLS", True))
    use_ssl = bool(current_app.config.get("MAIL_USE_SSL", False))

    msg = EmailMessage()
    msg["From"] = mail_from
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(text_body or "")
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=10) as server:
                if mail_user and mail_pass:
                    server.login(mail_user, mail_pass)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=10) as server:
                server.ehlo()
                if use_tls:
                    server.starttls()
                    server.ehlo()
                if mail_user and mail_pass:
                    server.login(mail_user, mail_pass)
                server.send_message(msg)
        return True
    except Exception:
        return False


def notify_admins(subject_key: str, body_key: str, **kwargs):
    if not is_feature_enabled("enable_email_notifications", True):
        return

    admins = list(extensions.users_col.find({"is_admin": True}, {"email": 1, "username": 1}))
    for admin in admins:
        email = admin.get("email", "")
        if not email:
            continue
        text_body = tr(body_key, **kwargs)
        send_email_message(email, tr(subject_key), text_body)


def set_password_check_status(ok: bool, message: str | None = None):
    if extensions.system_status_col is None:
        return
    now = datetime.utcnow()
    if ok:
        extensions.system_status_col.update_one(
            {"key": "password_leak_service"},
            {
                "$set": {
                    "key": "password_leak_service",
                    "status": "up",
                    "last_ok_at": now,
                    "message": "",
                }
            },
            upsert=True,
        )
    else:
        doc = extensions.system_status_col.find_one({"key": "password_leak_service"}) or {}
        doc = validate_or_purge_document("system_status", doc, context="auth.set_password_check_status") or {}
        last_notified_at = doc.get("last_notified_at")
        should_notify = not last_notified_at or (now - last_notified_at) > timedelta(minutes=30)

        update_payload = {
            "key": "password_leak_service",
            "status": "down",
            "last_failed_at": now,
            "message": message or "Password leak check unavailable",
        }
        if should_notify:
            update_payload["last_notified_at"] = now

        extensions.system_status_col.update_one(
            {"key": "password_leak_service"},
            {"$set": update_payload},
            upsert=True,
        )

        if should_notify:
            notify_admins(
                "email.admin_alert_subject",
                "email.admin_alert_body",
                message=update_payload["message"],
            )


def password_pwned_status(password: str, timeout_seconds: int = 10):
    sha1 = hashlib.sha1((password or "").encode("utf-8")).hexdigest().upper()
    prefix = sha1[:5]
    suffix = sha1[5:]
    url = f"https://api.pwnedpasswords.com/range/{prefix}"
    try:
        response = requests.get(
            url,
            timeout=timeout_seconds,
            headers={"User-Agent": "PulseBeat/1.0", "Add-Padding": "true"},
        )
        if response.status_code != 200:
            set_password_check_status(False, f"HTTP {response.status_code}")
            return "unavailable", 0

        set_password_check_status(True)
        for line in response.text.splitlines():
            parts = line.strip().split(":")
            if len(parts) != 2:
                continue
            if parts[0].upper() == suffix:
                try:
                    count = int(parts[1].strip())
                except Exception:
                    count = 1
                return "pwned", count
        return "safe", 0
    except Exception:
        set_password_check_status(False, "timeout_or_network_error")
        return "unavailable", 0


def is_user_banned(user):
    if not user:
        return False
    if user.get("is_root_admin", False):
        return False
    banned_until = user.get("banned_until")
    if not banned_until:
        return False
    return banned_until > datetime.utcnow()


def is_email_verified(user):
    if not user:
        return False
    if user.get("auth_provider") == "google":
        return True
    return bool(user.get("email_verified", False))


def count_creator_subscribers(creator_oid):
    if not creator_oid or extensions.creator_subscriptions_col is None:
        return 0
    return extensions.creator_subscriptions_col.count_documents({"creator_id": creator_oid})


def get_creator_subscription(creator_oid, subscriber_oid):
    if not creator_oid or not subscriber_oid or extensions.creator_subscriptions_col is None:
        return None
    row = extensions.creator_subscriptions_col.find_one({"creator_id": creator_oid, "subscriber_id": subscriber_oid})
    return validate_or_purge_document("creator_subscriptions", row, context="auth.get_creator_subscription")


def list_creator_subscribers(creator_oid):
    if not creator_oid or extensions.creator_subscriptions_col is None:
        return []

    rows = list(
        extensions.creator_subscriptions_col.find(
            {"creator_id": creator_oid},
            {"subscriber_id": 1, "notifications_enabled": 1, "created_at": 1},
        ).sort("created_at", -1)
    )
    rows = [
        row
        for row in (
            validate_or_purge_document("creator_subscriptions", item, context="auth.list_creator_subscribers.subscription")
            for item in rows
        )
        if row
    ]
    user_ids = [row.get("subscriber_id") for row in rows if row.get("subscriber_id")]
    if not user_ids:
        return []

    user_map = {
        row.get("_id"): row
        for row in (
            validate_or_purge_document("users", item, context="auth.list_creator_subscribers.user")
            for item in extensions.users_col.find({"_id": {"$in": user_ids}}, {"username": 1})
        )
        if row
    }
    items = []
    for row in rows:
        subscriber_oid = row.get("subscriber_id")
        user = user_map.get(subscriber_oid)
        if not user:
            continue
        username = user.get("username", "user")
        items.append(
            {
                "id": str(user.get("_id")),
                "username": username,
                "profile_url": url_for("accounts.public_profile", username=username),
                "notifications_enabled": bool(row.get("notifications_enabled", False)),
                "created_at": row.get("created_at"),
            }
        )
    items.sort(key=lambda item: item.get("username", "").lower())
    return items


def invalidate_public_profile_cache(user_oid):
    if user_oid:
        bump_public_profile_cache(current_app, user_oid)


def invalidate_playlist_cache(playlist_id):
    if playlist_id:
        bump_public_playlist_cache(current_app, playlist_id)


def invalidate_song_related_caches(song):
    if not song:
        return
    creator_oid = song.get("created_by")
    if creator_oid:
        invalidate_public_profile_cache(creator_oid)
    bump_popular_public_songs_cache(current_app)
    song_oid = song.get("_id")
    if not song_oid:
        return
    try:
        linked_playlists = extensions.playlists_col.find({"song_ids": song_oid}, {"_id": 1}).limit(400)
        for row in linked_playlists:
            playlist_id = row.get("_id")
            if playlist_id:
                invalidate_playlist_cache(playlist_id)
    except Exception:
        current_app.logger.warning("Unable to invalidate linked playlist caches for song %s", song_oid, exc_info=True)


def invalidate_playlist_related_caches(playlist):
    if not playlist:
        return
    playlist_id = playlist.get("_id") if isinstance(playlist, dict) else playlist
    if playlist_id:
        invalidate_playlist_cache(playlist_id)
    if isinstance(playlist, dict):
        owner_oid = playlist.get("user_id")
        if owner_oid:
            invalidate_public_profile_cache(owner_oid)


def create_creator_publication_notifications(creator_oid, content_type: str, content_id, content_title: str):
    if not creator_oid or not content_id or content_type not in {"song", "playlist"}:
        return 0
    if extensions.creator_subscriptions_col is None or extensions.user_notifications_col is None:
        return 0

    creator = extensions.users_col.find_one({"_id": creator_oid}, {"username": 1})
    creator = validate_or_purge_document("users", creator, context="auth.create_creator_publication_notifications.creator")
    if not creator:
        return 0

    creator_username = creator.get("username", "user")
    subscribers = list(
        extensions.creator_subscriptions_col.find(
            {"creator_id": creator_oid, "notifications_enabled": True},
            {"subscriber_id": 1},
        )
    )
    subscribers = [
        row
        for row in (
            validate_or_purge_document("creator_subscriptions", item, context="auth.create_creator_publication_notifications.subscription")
            for item in subscribers
        )
        if row
    ]
    docs = []
    now = datetime.utcnow()
    for row in subscribers:
        subscriber_oid = row.get("subscriber_id")
        if not subscriber_oid or str(subscriber_oid) == str(creator_oid):
            continue
        docs.append(
            {
                "recipient_user_id": subscriber_oid,
                "notification_type": "creator_publication",
                "creator_id": creator_oid,
                "creator_username_snapshot": creator_username,
                "content_type": content_type,
                "content_id": content_id,
                "content_title": (content_title or "").strip() or tr("defaults.untitled"),
                "created_at": now,
                "is_read": False,
                "read_at": None,
            }
        )

    if not docs:
        return 0

    try:
        result = extensions.user_notifications_col.insert_many(docs, ordered=False)
        return len(getattr(result, "inserted_ids", []) or [])
    except DuplicateKeyError:
        return 0
    except BulkWriteError as exc:
        details = getattr(exc, "details", {}) or {}
        write_errors = details.get("writeErrors") or []
        if write_errors and all(int((row or {}).get("code", 0) or 0) == 11000 for row in write_errors):
            return max(0, len(docs) - len(write_errors))
        raise


def count_unread_notifications(user_oid):
    if not user_oid or extensions.user_notifications_col is None:
        return 0
    ensure_yearly_recap_notification(user_oid)
    return extensions.user_notifications_col.count_documents({"recipient_user_id": user_oid, "is_read": False})


def mark_notifications_read(user_oid):
    if not user_oid or extensions.user_notifications_col is None:
        return 0
    result = extensions.user_notifications_col.update_many(
        {"recipient_user_id": user_oid, "is_read": False},
        {"$set": {"is_read": True, "read_at": datetime.utcnow()}},
    )
    return int(getattr(result, "modified_count", 0) or 0)


def get_user_notifications(user_oid, limit=20):
    if not user_oid or extensions.user_notifications_col is None:
        return []
    ensure_yearly_recap_notification(user_oid)

    rows = list(
        extensions.user_notifications_col.find({"recipient_user_id": user_oid}).sort("created_at", -1).limit(max(1, int(limit or 20)))
    )
    rows = [
        row
        for row in (
            validate_or_purge_document("user_notifications", item, context="auth.get_user_notifications.notification")
            for item in rows
        )
        if row
    ]
    if not rows:
        return []

    creator_ids = [row.get("creator_id") for row in rows if row.get("creator_id")]
    creator_map = {
        row.get("_id"): row
        for row in (
            validate_or_purge_document("users", item, context="auth.get_user_notifications.creator")
            for item in extensions.users_col.find({"_id": {"$in": creator_ids}}, {"username": 1})
        )
        if row
    } if creator_ids else {}

    items = []
    for row in rows:
        notification_type = str(row.get("notification_type") or "generic").strip().lower()
        creator_oid = row.get("creator_id")
        creator = creator_map.get(creator_oid)
        creator_username = (
            creator.get("username", "user")
            if creator
            else (row.get("creator_username_snapshot") or "user")
        )
        creator_url = url_for("accounts.public_profile", username=creator_username) if creator_username else ""
        content_id = row.get("content_id")
        content_type = (row.get("content_type") or "").strip().lower()
        if notification_type == RECAP_NOTIFICATION_TYPE:
            recap_id = row.get("recap_id")
            content_type = "recap"
            creator_username = current_app.config.get("APP_NAME", "PulseBeat")
            creator_url = ""
            content_url = url_for("accounts.view_recap", recap_id=str(recap_id)) if recap_id else ""
        elif content_type == "playlist" and content_id:
            content_url = url_for("playlists.playlist_detail", playlist_id=str(content_id))
        elif content_type == "song" and content_id:
            content_url = url_for("songs.song_detail", song_id=str(content_id))
        else:
            content_url = ""

        items.append(
            {
                "id": str(row.get("_id")),
                "notification_type": notification_type,
                "creator_username": creator_username,
                "creator_url": creator_url,
                "content_type": content_type,
                "content_title": row.get("content_title") or tr("defaults.untitled"),
                "content_url": content_url,
                "is_read": bool(row.get("is_read", False)),
                "created_at": row.get("created_at"),
            }
        )
    return items


def get_form_honeypot_name() -> str:
    name = str(session.get("form_honeypot_name", "") or "").strip()
    if not name:
        name = f"pb_extra_{secrets.token_hex(8)}"
        session["form_honeypot_name"] = name
    return name


def _safe_internal_next_path(raw_value: str) -> str:
    candidate = str(raw_value or "").strip()
    if not candidate:
        return ""
    parsed = urlparse(candidate)
    if parsed.scheme or parsed.netloc:
        return ""
    if not candidate.startswith("/"):
        return ""
    return candidate


def get_robot_watchdog_runtime():
    runtime = current_app.extensions.get("robot_watchdog_runtime")
    if runtime is None:
        runtime = {"lock": threading.Lock(), "actors": {}}
        current_app.extensions["robot_watchdog_runtime"] = runtime
    return runtime


def get_robot_watchdog_actor():
    user_oid = get_session_user_oid()
    if user_oid:
        return {
            "actor_key": f"user:{user_oid}",
            "actor_type": "user",
            "user_oid": user_oid,
            "label": f"user:{user_oid}",
        }

    device_id = ensure_request_device_id()
    digest = hashlib.sha256((device_id or "").encode("utf-8")).hexdigest()
    guest_code = digest[:6].upper() or "GUEST"
    return {
        "actor_key": f"guest:{digest}",
        "actor_type": "guest",
        "user_oid": None,
        "guest_code": guest_code,
        "label": f"guest:{guest_code}",
    }


def robot_watchdog_should_skip(endpoint: str | None = None) -> bool:
    endpoint_name = str(endpoint or request.endpoint or "").strip()
    if not endpoint_name:
        return False
    if endpoint_name == "static" or endpoint_name.startswith("static"):
        return True
    if endpoint_name.startswith("debug_") or request.path.startswith("/debug/test/"):
        return True
    return endpoint_name in ROBOT_WATCHDOG_SKIP_ENDPOINTS


def _guest_robot_watchdog_state():
    raw = session.get(ROBOT_WATCHDOG_SESSION_KEY)
    if not isinstance(raw, dict):
        raw = {}
    return {
        "hits": max(0, int(raw.get("hits", 0) or 0)),
        "challenge_required": bool(raw.get("challenge_required", False)),
        "last_hit_at": raw.get("last_hit_at"),
    }


def _save_guest_robot_watchdog_state(state: dict):
    session[ROBOT_WATCHDOG_SESSION_KEY] = {
        "hits": max(0, int((state or {}).get("hits", 0) or 0)),
        "challenge_required": bool((state or {}).get("challenge_required", False)),
        "last_hit_at": (state or {}).get("last_hit_at"),
    }


def robot_challenge_required_for_actor(actor=None) -> bool:
    actor = actor or get_robot_watchdog_actor()
    if actor.get("actor_type") == "user" and actor.get("user_oid"):
        row = extensions.users_col.find_one(
            {"_id": actor["user_oid"]},
            {"robot_challenge_required": 1},
        )
        row = validate_or_purge_document("users", row, context="auth.robot_challenge_required_for_actor")
        return bool((row or {}).get("robot_challenge_required", False))
    return bool(_guest_robot_watchdog_state().get("challenge_required", False))


def _log_robot_watchdog_event(actor: dict, reason: str, require_challenge: bool):
    now = datetime.utcnow()
    details = {
        "actor_key": actor.get("actor_key", ""),
        "actor_type": actor.get("actor_type", "guest"),
        "endpoint": request.endpoint or "",
        "path": request.path,
        "method": request.method,
        "reason": str(reason or "").strip(),
        "challenge_required": bool(require_challenge),
        "ip_prefix": get_request_device_context().get("ip_prefix", ""),
    }
    if getattr(extensions, "admin_audit_col", None) is not None:
        try:
            extensions.admin_audit_col.insert_one(
                {
                    "admin_user_id": None,
                    "action": "robot_watchdog_detected",
                    "target_type": actor.get("actor_type", "guest"),
                    "target_id": actor.get("user_oid") or actor.get("actor_key"),
                    "details": details,
                    "created_at": now,
                }
            )
        except Exception:
            current_app.logger.warning("Unable to write robot watchdog audit log", exc_info=True)
    if getattr(extensions, "system_status_col", None) is not None:
        try:
            extensions.system_status_col.update_one(
                {"key": "robot_watchdog"},
                {
                    "$set": {
                        "key": "robot_watchdog",
                        "status": "alert",
                        "message": f"{actor.get('label', 'actor')} flagged for suspicious automation on {request.endpoint or request.path}",
                        "updated_at": now,
                        "actor_key": actor.get("actor_key", ""),
                        "reason": str(reason or "").strip(),
                        "challenge_required": bool(require_challenge),
                    }
                },
                upsert=True,
            )
        except Exception:
            current_app.logger.warning("Unable to update robot watchdog system status", exc_info=True)


def mark_robot_watchdog_detection(actor: dict, reason: str, require_challenge: bool = False) -> int:
    now = datetime.utcnow()
    hits = 1
    if actor.get("actor_type") == "user" and actor.get("user_oid"):
        row = extensions.users_col.find_one(
            {"_id": actor["user_oid"]},
            {"robot_watchdog_hits": 1},
        )
        row = validate_or_purge_document("users", row, context="auth.mark_robot_watchdog_detection")
        hits = max(0, int((row or {}).get("robot_watchdog_hits", 0) or 0)) + 1
        safe_mongo_update_one(
            extensions.users_col,
            {"_id": actor["user_oid"]},
            {
                "$set": {
                    "robot_watchdog_hits": hits,
                    "robot_watchdog_last_hit_at": now,
                    "robot_watchdog_last_reason": str(reason or "").strip(),
                    "robot_challenge_required": bool(require_challenge or hits >= 2),
                    "robot_challenge_required_at": now if (require_challenge or hits >= 2) else None,
                }
            },
        )
    else:
        state = _guest_robot_watchdog_state()
        hits = max(0, int(state.get("hits", 0) or 0)) + 1
        state["hits"] = hits
        state["last_hit_at"] = now.isoformat()
        state["challenge_required"] = bool(require_challenge or hits >= 2)
        _save_guest_robot_watchdog_state(state)

    _log_robot_watchdog_event(actor, reason, require_challenge or hits >= 2)
    return hits


def clear_robot_watchdog_restrictions(actor=None):
    actor = actor or get_robot_watchdog_actor()
    runtime = get_robot_watchdog_runtime()
    with runtime["lock"]:
        runtime["actors"].pop(actor.get("actor_key", ""), None)

    if actor.get("actor_type") == "user" and actor.get("user_oid"):
        safe_mongo_update_one(
            extensions.users_col,
            {"_id": actor["user_oid"]},
            {
                "$set": {
                    "robot_watchdog_hits": 1,
                    "robot_challenge_required": False,
                    "robot_challenge_required_at": None,
                }
            },
        )
    else:
        state = _guest_robot_watchdog_state()
        state["hits"] = 1
        state["challenge_required"] = False
        _save_guest_robot_watchdog_state(state)

    session.pop(ROBOT_CHALLENGE_SESSION_KEY, None)


def _robot_challenge_hash(answer: str, nonce: str) -> str:
    raw = "|".join([str(current_app.secret_key or ""), str(nonce or ""), str(answer or "").strip()])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_or_issue_robot_challenge(next_path: str = "", rotate: bool = False):
    payload = session.get(ROBOT_CHALLENGE_SESSION_KEY)
    if isinstance(payload, dict) and not rotate:
        expires_at = int(payload.get("expires_at", 0) or 0)
        if expires_at > int(time.time()):
            if next_path:
                payload["next_path"] = _safe_internal_next_path(next_path)
                session[ROBOT_CHALLENGE_SESSION_KEY] = payload
            return payload

    a = 3 + secrets.randbelow(9)
    b = 2 + secrets.randbelow(8)
    if secrets.randbelow(2):
        question = tr("auth.robot_check_question_add", a=a, b=b)
        answer = str(a + b)
    else:
        big = max(a, b)
        small = min(a, b)
        question = tr("auth.robot_check_question_sub", a=big, b=small)
        answer = str(big - small)

    nonce = secrets.token_urlsafe(12)
    payload = {
        "question": question,
        "nonce": nonce,
        "expected_hash": _robot_challenge_hash(answer, nonce),
        "expires_at": int(time.time()) + 600,
        "next_path": _safe_internal_next_path(next_path),
    }
    session[ROBOT_CHALLENGE_SESSION_KEY] = payload
    return payload


def verify_robot_challenge_answer(answer: str):
    payload = session.get(ROBOT_CHALLENGE_SESSION_KEY)
    if not isinstance(payload, dict):
        return False, ""
    expires_at = int(payload.get("expires_at", 0) or 0)
    if expires_at <= int(time.time()):
        session.pop(ROBOT_CHALLENGE_SESSION_KEY, None)
        return False, ""
    expected_hash = str(payload.get("expected_hash", "") or "").strip()
    nonce = str(payload.get("nonce", "") or "").strip()
    if not expected_hash or not nonce:
        session.pop(ROBOT_CHALLENGE_SESSION_KEY, None)
        return False, ""
    if expected_hash != _robot_challenge_hash(str(answer or "").strip(), nonce):
        return False, _safe_internal_next_path(payload.get("next_path", ""))

    next_path = _safe_internal_next_path(payload.get("next_path", ""))
    clear_robot_watchdog_restrictions()
    return True, next_path


def ban_user_for_robot_honeypot(user_oid):
    if not user_oid:
        return False
    user = extensions.users_col.find_one({"_id": user_oid}, {"is_root_admin": 1})
    user = validate_or_purge_document("users", user, context="auth.ban_user_for_robot_honeypot") or {}
    if user.get("is_root_admin", False):
        _log_robot_watchdog_event(
            {"actor_key": f"user:{user_oid}", "actor_type": "user", "user_oid": user_oid, "label": f"user:{user_oid}"},
            "honeypot_root_admin_exempt",
            False,
        )
        return False
    now = datetime.utcnow()
    ban_reason = "Utilisation de scripts automatisé ou d'un robot suspectée"
    safe_mongo_update_one(
        extensions.users_col,
        {"_id": user_oid},
        {
            "$set": {
                "banned_until": now + timedelta(days=36500),
                "auto_banned": True,
                "ban_reason": ban_reason,
                "robot_watchdog_hits": 2,
                "robot_challenge_required": True,
                "robot_challenge_required_at": now,
            }
        },
    )
    actor = {
        "actor_key": f"user:{user_oid}",
        "actor_type": "user",
        "user_oid": user_oid,
        "label": f"user:{user_oid}",
    }
    _log_robot_watchdog_event(actor, "honeypot_triggered", True)
    try:
        notify_admins(
            "email.admin_alert_subject",
            "email.admin_alert_body",
            message=f"Autobanned account after honeypot form trigger: {user_oid}",
        )
    except Exception:
        current_app.logger.warning("Unable to notify admins after honeypot autoban", exc_info=True)
    return True


def current_user():
    user_oid = get_session_user_oid()
    if not user_oid:
        return None
    user = extensions.users_col.find_one({"_id": user_oid})
    user = validate_or_purge_document("users", user, context="current_user")
    if not user:
        session.clear()
        return None
    if is_user_banned(user):
        session.clear()
        return None
    if not is_email_verified(user):
        session.clear()
        return None
    return {
        "id": str(user["_id"]),
        "username": user.get("username", "user"),
        "email": user.get("email", ""),
        "is_admin": bool(user.get("is_admin", False)),
        "is_root_admin": bool(user.get("is_root_admin", False)),
        "require_password_change": bool(user.get("require_password_change", False)),
        "email_verified": bool(is_email_verified(user)),
    }


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        user_oid = get_session_user_oid()
        if not user_oid:
            session.clear()
            flash(tr("flash.auth.required"), "warning")
            return redirect(url_for("accounts.login"))

        user = extensions.users_col.find_one({"_id": user_oid})
        user = validate_or_purge_document("users", user, context=f"login_required:{request.endpoint or ''}")
        if not user:
            session.clear()
            flash(tr("flash.auth.required"), "warning")
            return redirect(url_for("accounts.login"))
        if is_user_banned(user):
            session.clear()
            flash(tr("flash.accounts.banned"), "danger")
            return redirect(url_for("accounts.login"))
        if not is_email_verified(user):
            session.clear()
            session["pending_verification_email"] = user.get("email", "")
            flash(tr("flash.accounts.email_not_verified"), "warning")
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
        user = validate_or_purge_document("users", user, context=f"admin_required:{request.endpoint or ''}")
        if not user or not user.get("is_admin", False):
            flash(tr("flash.admin.forbidden"), "danger")
            return redirect(url_for("main.index"))
        if is_user_banned(user):
            session.clear()
            flash(tr("flash.accounts.banned"), "danger")
            return redirect(url_for("accounts.login"))
        if not is_email_verified(user):
            session.clear()
            session["pending_verification_email"] = user.get("email", "")
            flash(tr("flash.accounts.email_not_verified"), "warning")
            return redirect(url_for("accounts.login"))
        return fn(*args, **kwargs)

    return wrapped


def allowed_file(filename: str) -> bool:
    if "." not in filename:
        return False
    return filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def audio_upload_signature_ok(file_storage, filename: str) -> bool:
    if not file_storage or not filename or "." not in filename:
        return False

    ext = filename.rsplit(".", 1)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False

    stream = getattr(file_storage, "stream", None)
    if stream is None:
        return False

    try:
        pos = stream.tell()
    except Exception:
        pos = None

    try:
        head = stream.read(64) or b""
    except Exception:
        head = b""
    finally:
        try:
            if pos is not None:
                stream.seek(pos)
            else:
                stream.seek(0)
        except Exception:
            pass

    if not head:
        return False

    if ext == "mp3":
        return head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0)
    if ext == "wav":
        return len(head) >= 12 and head[0:4] == b"RIFF" and head[8:12] == b"WAVE"
    if ext == "ogg":
        return head.startswith(b"OggS")
    if ext == "m4a":
        return len(head) >= 12 and head[4:8] == b"ftyp"
    return False


def song_owner_matches(song, user_oid):
    if not user_oid:
        return False
    created_by = song.get("created_by")
    if not created_by:
        return False
    return str(created_by) == str(user_oid)


def cleanup_song(song):
    song_oid = song["_id"]
    linked_playlist_ids = [row.get("_id") for row in extensions.playlists_col.find({"song_ids": song_oid}, {"_id": 1}) if row.get("_id")]
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

    gridfs_id = song_gridfs_file_id(song)
    bucket = getattr(extensions, "audio_files_bucket", None)
    if gridfs_id is not None and bucket is not None:
        try:
            bucket.delete(gridfs_id)
        except Exception:
            pass

    extensions.playlists_col.update_many({}, {"$pull": {"song_ids": song_oid}})
    extensions.song_votes_col.delete_many({"song_id": song_oid})
    if getattr(extensions, "comment_votes_col", None) is not None:
        comment_ids = [c["_id"] for c in extensions.song_comments_col.find({"song_id": song_oid}, {"_id": 1})]
        if comment_ids:
            extensions.comment_votes_col.delete_many({"comment_id": {"$in": comment_ids}})
    extensions.song_comments_col.delete_many({"song_id": song_oid})
    extensions.listening_history_col.delete_many({"song_id": song_oid})
    extensions.song_reports_col.delete_many({"$or": [{"target_song_id": song_oid}, {"song_id": song_oid}]})
    extensions.songs_col.delete_one({"_id": song_oid})
    invalidate_song_related_caches(song)
    for playlist_id in linked_playlist_ids:
        invalidate_playlist_cache(playlist_id)


def cleanup_user(user_oid, delete_songs=False):
    user = extensions.users_col.find_one({"_id": user_oid})
    if user and user.get("is_root_admin", False):
        return False

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
    if getattr(extensions, "comment_votes_col", None) is not None:
        user_comment_ids = [c["_id"] for c in extensions.song_comments_col.find({"user_id": user_oid}, {"_id": 1})]
        if user_comment_ids:
            extensions.comment_votes_col.delete_many({"comment_id": {"$in": user_comment_ids}})
        extensions.comment_votes_col.delete_many({"user_id": user_oid})
    extensions.song_comments_col.delete_many({"user_id": user_oid})
    extensions.listening_history_col.delete_many({"user_id": user_oid})
    extensions.song_reports_col.delete_many({"reporter_id": user_oid})
    extensions.playlists_col.delete_many({"user_id": user_oid})
    extensions.users_col.delete_one({"_id": user_oid})
    return True


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
    song = validate_or_purge_document("songs", song, context="can_access_song")
    if not song:
        return False
    if is_youtube_song(song) and not is_youtube_integration_enabled(True):
        return False
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
    youtube_clause = youtube_song_visibility_clause()
    if not user_oid:
        return compose_and_filters(public_clause, youtube_clause)

    base_clause = {
        "$or": [
            public_clause,
            {"created_by": user_oid},
            {"$and": [{"visibility": "private"}, {"shared_with": user_oid}]},
        ]
    }
    return compose_and_filters(base_clause, youtube_clause)


def serialize_song(song, user_oid):
    song = validate_or_purge_document("songs", song, context="serialize_song", fatal=True)
    source_type = (song.get("source_type") or "").strip().lower()
    source_url = (song.get("source_url") or song.get("url") or "").strip()
    external_provider = (song.get("external_provider") or "").strip().lower()
    youtube_video_id = ""
    if source_url:
        parsed = urlparse(source_url)
        host = (parsed.netloc or "").lower()
        path = parsed.path or ""
        if "youtube.com" in host:
            video_id = (parse_qs(parsed.query).get("v") or [""])[0].strip()
            if not video_id and path.startswith("/shorts/"):
                video_id = path.replace("/shorts/", "", 1).strip("/ ")
            youtube_video_id = video_id
        elif "youtu.be" in host:
            youtube_video_id = path.strip("/ ")

    is_youtube_source = external_provider == "youtube" or bool(youtube_video_id)
    is_available = bool(song.get("is_available", True))
    has_youtube_cache = is_youtube_source and has_cached_youtube_audio(current_app, song)
    is_audio_playable = is_available and (not is_youtube_source or has_youtube_cache)
    playback_mode = "audio"
    if is_youtube_source:
        playback_mode = "audio" if has_youtube_cache else "youtube"
    if not is_available:
        playback_mode = "disabled"

    return {
        "id": str(song["_id"]),
        "title": song.get("title") or tr("defaults.untitled"),
        "artist": song.get("artist") or tr("defaults.unknown_artist"),
        "genre": song.get("genre", "").strip(),
        "visibility": normalize_visibility(song),
        "shared_count": len(song.get("shared_with", [])),
        "can_delete": song_owner_matches(song, user_oid),
        "source_type": source_type,
        "source_url": source_url,
        "external_provider": external_provider,
        "youtube_video_id": youtube_video_id,
        "playback_mode": playback_mode,
        "is_available": is_available,
        "is_audio_playable": is_audio_playable,
        "availability_reason": (song.get("availability_reason") or "").strip(),
    }


def song_stream_url(song_id: str):
    return url_for("songs.stream_song", song_id=song_id)


def user_choice_list(exclude_user_oid=None):
    query = {}
    if exclude_user_oid:
        query = {"_id": {"$ne": exclude_user_oid}}
    items = []
    for user in extensions.users_col.find(query).sort("username", 1):
        valid_user = validate_or_purge_document("users", user, context="user_choice_list")
        if not valid_user:
            continue
        items.append(
            {
                "id": str(valid_user["_id"]),
                "username": valid_user.get("username", "user"),
                "email": valid_user.get("email", ""),
            }
        )
    return items


def save_uploaded_file(file_storage):
    safe_name = secure_filename(file_storage.filename)
    stamped_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{safe_name}"
    upload_dir = current_app.config["UPLOAD_DIR"]
    file_path = os.path.join(upload_dir, stamped_name)
    file_storage.save(file_path)
    return stamped_name


def compute_audio_fingerprint(file_path: str, chunk_size: int = 1024 * 1024):
    if not file_path or not os.path.isfile(file_path):
        return ""
    hasher = hashlib.sha256()
    try:
        with open(file_path, "rb") as fh:
            while True:
                chunk = fh.read(chunk_size)
                if not chunk:
                    break
                hasher.update(chunk)
    except Exception:
        return ""
    return hasher.hexdigest()


