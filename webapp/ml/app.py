import os
import pathlib

import flask
import MySQLdb.cursors
from pymemcache.client.base import Client as MemcacheClient

import pymc_session

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity


_config = None


def config():
    global _config
    if _config is None:
        _config = {
            "db": {
                "host": os.environ.get("ISUCONP_DB_HOST", 'localhost'),
                "port": int(os.environ.get("ISUCONP_DB_PORT", "3306")),
                "user": os.environ.get("ISUCONP_DB_USER", "root"),
                "db": os.environ.get("ISUCONP_DB_NAME", "isuconp"),
            },
        }
        password = os.environ.get("ISUCONP_DB_PASSWORD")
        if password:
            _config['db']['passwd'] = password
    return _config


_db = None


def db():
    global _db
    if _db is None:
        conf = config()["db"].copy()
        conf['charset'] = 'utf8mb4'
        conf['cursorclass'] = MySQLdb.cursors.DictCursor
        conf['autocommit'] = True
        _db = MySQLdb.connect(**conf)
    return _db


def db_initialize():
    cur = db().cursor()
    sqls = [
        'DELETE FROM users WHERE id > 1000',
        'DELETE FROM posts WHERE id > 10000',
        'DELETE FROM comments WHERE id > 100000',
        'UPDATE users SET del_flg = 0',
        'UPDATE users SET del_flg = 1 WHERE id % 50 = 0',
    ]
    for q in sqls:
        cur.execute(q)


_mcclient = None


def memcache():
    global _mcclient
    if _mcclient is None:
        _mcclient = MemcacheClient(('127.0.0.1', 11211), no_delay=True,
                                   default_noreply=False)
    return _mcclient


# load image features
_image_features_dict = {}

npy_fnames = os.listdir("./features")
for fname in npy_fnames:
    npy = np.load(os.path.join("./features", fname))
    npy_no = os.path.splitext(fname)[0]
    _image_features_dict[int(npy_no)] = npy


# app setup
static_path = pathlib.Path(__file__).resolve().parent.parent / 'public'
app = flask.Flask(__name__, static_folder=str(static_path), static_url_path='')
#app.debug = True
app.session_interface = pymc_session.SessionInterface(memcache())


_NUM_SIMILAR_IMAGES = 6


@app.route("/image/<id>/similar", methods=["GET"])
def get_similar_images(id):
    target_feature = _image_features_dict[int(id)]

    cursor = db().cursor()
    query = """
    SELECT p.id, p.mime FROM posts AS p
    JOIN users AS u ON p.user_id = u.id
    WHERE p.searchable = 1 AND u.del_flg = 0
    """
    cursor.execute(query)
    result = cursor.fetchall()

    similarities = []
    for res in result:
        if int(res["id"]) == int(id):
            continue

        feature = _image_features_dict[int(res["id"])]
        sim = cosine_similarity(target_feature, feature)
        similarities.append((res["id"], float(sim[0][0]), res["mime"]))

    similarities.sort(key=lambda x: -x[1])

    ret = [{"id": item[0], "similarity": item[1], "mime": item[2]}
           for item in similarities[:_NUM_SIMILAR_IMAGES]]
    for i, item in enumerate(ret):
        ext = ""
        mime = item['mime']
        if mime == "image/jpeg":
            ext = ".jpg"
        elif mime == "image/png":
            ext = ".png"
        elif mime == "image/gif":
            ext = ".gif"
        item['fname'] = str(item['id']) + ext

    return flask.jsonify(ret)
