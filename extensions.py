from pymongo import MongoClient

mongo_client = None
db = None
users_col = None
songs_col = None
playlists_col = None
song_votes_col = None
song_comments_col = None


def init_mongo(app):
    global mongo_client, db, users_col, songs_col, playlists_col, song_votes_col, song_comments_col

    mongo_client = MongoClient(app.config["MONGO_URI"])
    db = mongo_client[app.config["MONGO_DB_NAME"]]
    users_col = db["users"]
    songs_col = db["songs"]
    playlists_col = db["playlists"]
    song_votes_col = db["song_votes"]
    song_comments_col = db["song_comments"]
