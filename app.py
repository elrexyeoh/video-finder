"""Video Finder web app: upload videos, then search them by describing what you see."""
import hmac
import os
import secrets
import time
import uuid

from flask import (Flask, abort, jsonify, redirect, render_template, request,
                   send_file, session, url_for)
from werkzeug.utils import secure_filename

import openai_helper
from indexer import DATA_DIR, THUMB_DIR, VIDEO_DIR, db, engine

APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
ALLOWED_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".wmv", ".mpg", ".mpeg", ".3gp", ".3g2",
               ".flv", ".mts", ".m2ts", ".ts", ".vob", ".ogv", ".hevc", ".mxf", ".dv", ".asf", ".f4v"}

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30,
)
engine.start()
import lark_sync  # noqa: E402  (needs the database set up by engine.start)

lark_sync.start()


@app.before_request
def require_login():
    if request.endpoint in ("login", "static", "health"):
        return
    if not APP_PASSWORD:
        return  # no password configured (local testing)
    if not session.get("ok"):
        if request.path.startswith("/api/"):
            return jsonify(error="login required"), 401
        return redirect(url_for("login", next=request.path))


@app.route("/login", methods=["GET", "POST"])
def login():
    error, name = False, ""
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()[:60]
        if APP_PASSWORD and hmac.compare_digest(request.form.get("password", ""), APP_PASSWORD):
            session.permanent = True
            session["ok"] = True
            session["name"] = name or "Someone"
            nxt = request.args.get("next", "/")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else "/")
        time.sleep(1)
        error = True
    return render_template("login.html", error=error, name=name)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/health")
def health():
    return "ok"


@app.route("/")
def index():
    return render_template("index.html", name=session.get("name", ""))


@app.post("/api/upload")
def upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify(error="no file"), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_EXT and not (f.mimetype or "").startswith("video/"):
        return jsonify(error=f"{ext or 'this file type'} is not a supported video type"), 400
    stored = f"{uuid.uuid4().hex}{ext if ext.isascii() and len(ext) <= 6 else '.bin'}"
    path = os.path.join(VIDEO_DIR, stored)
    f.save(path)
    with db() as c:
        cur = c.execute(
            "INSERT INTO videos (filename, stored_name, size, status, uploaded_by, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (secure_filename(f.filename) or f.filename[:200], stored, os.path.getsize(path), "queued",
             session.get("name", ""), time.time()),
        )
        vid = cur.lastrowid
    engine.enqueue(vid)
    return jsonify(id=vid)


@app.get("/api/videos")
def videos():
    with db() as c:
        rows = c.execute(
            "SELECT id, filename, title, source, size, duration, status, progress, error, uploaded_by, created_at, "
            "(SELECT id FROM frames WHERE video_id=videos.id ORDER BY t LIMIT 1) AS cover "
            "FROM videos ORDER BY id DESC"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.delete("/api/videos/<int:vid>")
def delete_video(vid):
    with db() as c:
        row = c.execute("SELECT stored_name, source, source_id FROM videos WHERE id=?", (vid,)).fetchone()
        if not row:
            abort(404)
        if c.execute("SELECT status FROM videos WHERE id=?", (vid,)).fetchone()["status"] in ("indexing", "converting"):
            return jsonify(error="This video is being indexed right now, try again in a moment"), 409
        frame_ids = [r["id"] for r in c.execute("SELECT id FROM frames WHERE video_id=?", (vid,))]
        c.execute("DELETE FROM frames WHERE video_id=?", (vid,))
        c.execute("DELETE FROM videos WHERE id=?", (vid,))
    if row["source"] == "lark" and row["source_id"]:
        lark_sync.skip_file(row["source_id"])
    for fid in frame_ids:
        try:
            os.remove(os.path.join(THUMB_DIR, f"{fid}.jpg"))
        except OSError:
            pass
    try:
        os.remove(os.path.join(VIDEO_DIR, row["stored_name"]))
    except OSError:
        pass
    engine.reload_matrix()
    return jsonify(ok=True)


@app.get("/api/config")
def config():
    st = openai_helper.status()
    ok = st.get("enabled") and not st.get("error")
    return jsonify(natural_voice=bool(ok and st.get("tts_model")), smart_search=bool(ok and st.get("chat_model")), openai=st)


@app.post("/api/tts")
def tts():
    body = request.get_json(silent=True) or {}
    path = openai_helper.speak(str(body.get("text", ""))[:600], str(body.get("lang", "en")), os.path.join(DATA_DIR, "tts"))
    if not path:
        return ("", 204)
    resp = send_file(path, mimetype="audio/mpeg")
    resp.headers["Cache-Control"] = "private, max-age=86400"
    return resp


@app.get("/api/lark")
def lark_list():
    return jsonify(configured=lark_sync.configured(), sync_minutes=lark_sync.SYNC_MINUTES, sources=lark_sync.sources())


@app.post("/api/lark")
def lark_add():
    if not lark_sync.configured():
        return jsonify(error="not_configured"), 400
    url = str((request.get_json(silent=True) or {}).get("url", ""))[:1000]
    try:
        sid = lark_sync.add_source(url, session.get("name", ""))
    except ValueError:
        return jsonify(error="bad_link"), 400
    return jsonify(id=sid)


@app.post("/api/lark/<int:sid>/sync")
def lark_sync_now(sid):
    lark_sync.request_sync(sid)
    return jsonify(ok=True)


@app.delete("/api/lark/<int:sid>")
def lark_remove(sid):
    lark_sync.remove_source(sid)
    return jsonify(ok=True)


@app.get("/api/stats")
def stats():
    return jsonify(engine.stats())


@app.get("/api/search")
def search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"query": "", "looking_for": "", "results": [], **engine.stats()})
    return jsonify(engine.search(q[:300]))


@app.get("/media/<int:vid>")
def media(vid):
    with db() as c:
        row = c.execute("SELECT stored_name, filename FROM videos WHERE id=?", (vid,)).fetchone()
    if not row:
        abort(404)
    return send_file(
        os.path.join(VIDEO_DIR, row["stored_name"]),
        conditional=True,  # supports seeking (HTTP range requests)
        download_name=row["filename"],
        as_attachment=request.args.get("download") == "1",
    )


@app.get("/thumb/<int:fid>")
def thumb(fid):
    p = os.path.join(THUMB_DIR, f"{fid}.jpg")
    if not os.path.exists(p):
        abort(404)
    resp = send_file(p, mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "private, max-age=86400"
    return resp


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), threaded=True)
