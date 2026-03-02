from pymongo import MongoClient

mongo_client = None
db = None
users_col = None
songs_col = None
playlists_col = None
song_votes_col = None
song_comments_col = None
listening_history_col = None
song_reports_col = None
admin_audit_col = None
system_status_col = None
app_settings_col = None


def init_mongo(app):
    global mongo_client, db, users_col, songs_col, playlists_col, song_votes_col, song_comments_col
    global listening_history_col, song_reports_col, admin_audit_col, system_status_col, app_settings_col

    mongo_client = MongoClient(app.config["MONGO_URI"])
    db = mongo_client[app.config["MONGO_DB_NAME"]]
    users_col = db["users"]
    songs_col = db["songs"]
    playlists_col = db["playlists"]
    song_votes_col = db["song_votes"]
    song_comments_col = db["song_comments"]
    listening_history_col = db["listening_history"]
    song_reports_col = db["song_reports"]
    admin_audit_col = db["admin_audit"]
    system_status_col = db["system_status"]
    app_settings_col = db["app_settings"]

