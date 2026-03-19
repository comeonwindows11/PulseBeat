from gridfs import GridFSBucket
from pymongo import MongoClient

mongo_client = None
db = None
audio_files_bucket = None
users_col = None
songs_col = None
playlists_col = None
external_integrations_col = None
external_playlists_col = None
external_import_jobs_col = None
data_exports_col = None
song_votes_col = None
song_comments_col = None
comment_votes_col = None
listening_history_col = None
song_reports_col = None
admin_audit_col = None
system_status_col = None
app_settings_col = None
creator_subscriptions_col = None
user_notifications_col = None
dino_leaderboard_col = None
listening_events_col = None
user_recaps_col = None


def init_mongo(app):
    global mongo_client, db, audio_files_bucket, users_col, songs_col, playlists_col, external_integrations_col, external_playlists_col, external_import_jobs_col
    global data_exports_col, song_votes_col, song_comments_col, comment_votes_col
    global listening_history_col, song_reports_col, admin_audit_col, system_status_col, app_settings_col
    global creator_subscriptions_col, user_notifications_col, dino_leaderboard_col
    global listening_events_col, user_recaps_col

    mongo_client = MongoClient(app.config["MONGO_URI"])
    db = mongo_client[app.config["MONGO_DB_NAME"]]
    audio_files_bucket = GridFSBucket(db, bucket_name="audio_files")
    users_col = db["users"]
    songs_col = db["songs"]
    playlists_col = db["playlists"]
    external_integrations_col = db["external_integrations"]
    external_playlists_col = db["external_playlists"]
    external_import_jobs_col = db["external_import_jobs"]
    data_exports_col = db["data_exports"]
    song_votes_col = db["song_votes"]
    song_comments_col = db["song_comments"]
    comment_votes_col = db["comment_votes"]
    listening_history_col = db["listening_history"]
    song_reports_col = db["song_reports"]
    admin_audit_col = db["admin_audit"]
    system_status_col = db["system_status"]
    app_settings_col = db["app_settings"]
    creator_subscriptions_col = db["creator_subscriptions"]
    user_notifications_col = db["user_notifications"]
    dino_leaderboard_col = db["dino_leaderboard"]
    listening_events_col = db["listening_events"]
    user_recaps_col = db["user_recaps"]
