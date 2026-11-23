"""Video Finder web app: upload videos, then search them by describing what you see."""
import hmac
import json
import mimetypes
import re
import os
import secrets
import threading
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

mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("image/svg+xml", ".svg")

app = Flask(__name__)
from werkzeug.middleware.proxy_fix import ProxyFix  # noqa: E402

app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.json.sort_keys = False  # keep Lark columns in table order
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
    if request.endpoint in ("login", "static", "health", "manifest", "service_worker", "offline", "public_frame"):
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


@app.get("/manifest.webmanifest")
def manifest():
    resp = send_file(os.path.join(app.static_folder, "manifest.webmanifest"), mimetype="application/manifest+json")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.get("/sw.js")
def service_worker():
    resp = send_file(os.path.join(app.static_folder, "sw.js"), mimetype="text/javascript")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp


@app.get("/offline")
def offline():
    return render_template("offline.html")


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


@app.get("/api/videos/<int:vid>")
def video_detail(vid):
    with db() as c:
        r = c.execute("SELECT id, filename, title, source, meta, duration, uploaded_by, created_at FROM videos WHERE id=?",
                      (vid,)).fetchone()
    if not r:
        abort(404)
    d = dict(r)
    d["meta"] = json.loads(d["meta"]) if d.get("meta") else None
    return jsonify(d)


# ------------------------------------------------------------------ find the same product / suppliers
def _video_rows(ids):
    if not ids:
        return {}
    with db() as c:
        rows = c.execute(f"SELECT id, filename, title, source, meta, duration, uploaded_by, created_at, ai_product FROM videos "
                         f"WHERE id IN ({','.join('?' * len(ids))})", list(ids)).fetchall()
    out = {}
    for r in rows:
        d = dict(r)
        d["meta"] = json.loads(d["meta"]) if d.get("meta") else None
        d["ai_product"] = json.loads(d["ai_product"]) if d.get("ai_product") else None
        out[d["id"]] = d
    return out


SAME_SCORE = float(os.environ.get("SIMILAR_SAME_SCORE", "0.90"))
SIMILAR_SCORE = float(os.environ.get("SIMILAR_SCORE", "0.80"))


def _levels(meta):
    """Category columns from the Lark table, e.g. {1: '餐饮', 2: '餐饮设备', 3: '商用电器'}."""
    out = {}
    for k, v in (meta or {}).items():
        m = re.match(r"^\s*([一二三四五]|\d)\s*级", k)
        if m and v:
            out["一二三四五".index(m.group(1)) + 1 if m.group(1) in "一二三四五" else int(m.group(1))] = v.strip()
    return out


@app.get("/api/videos/<int:vid>/similar")
def similar_videos(vid):
    """Visual match, adjusted by the Lark categories: many showroom videos look alike, so the same
    category raises the score and a different top-level category lowers it."""
    sims = engine.similar(vid, limit=60, minimum=0.70)
    rows = _video_rows([vid] + [x["id"] for x in sims])
    if vid not in rows:
        abort(404)
    mine = _levels(rows[vid]["meta"])
    items = []
    for x in sims:
        if x["id"] not in rows:
            continue
        theirs, adj = _levels(rows[x["id"]]["meta"]), 0.0
        if mine and theirs:
            if mine.get(1) and theirs.get(1) and mine[1] != theirs[1]:
                adj -= 0.06
            else:
                adj += sum(w for lvl, w in ((1, .02), (2, .03), (3, .04)) if mine.get(lvl) and mine.get(lvl) == theirs.get(lvl))
        score = x["similarity"] + adj
        if score < SIMILAR_SCORE:
            continue
        items.append({**rows[x["id"]], **x, "score": round(score, 3), "level": "same" if score >= SAME_SCORE else "similar"})
    items.sort(key=lambda it: -it["score"])
    items = items[:12]
    for it in items:
        it.pop("ai_product", None)
    me = rows[vid]
    me.pop("ai_product", None)
    kf = engine.key_frames(vid, 3)
    me["cover"] = kf[len(kf) // 2] if kf else None
    return jsonify(video=me, similar=items)


def _sign(fid, exp):
    return hmac.new(app.secret_key.encode(), f"{fid}.{exp}".encode(), "sha256").hexdigest()[:24]


@app.get("/pub/frame/<int:fid>")
def public_frame(fid):
    """Time-limited public link to one still frame, so Google Lens can open it without logging in."""
    exp = request.args.get("e", "0")
    if not exp.isdigit() or int(exp) < time.time() or not hmac.compare_digest(_sign(fid, exp), request.args.get("s", "")):
        abort(403)
    p = os.path.join(THUMB_DIR, f"{fid}.jpg")
    if not os.path.exists(p):
        abort(404)
    return send_file(p, mimetype="image/jpeg")


def _search_links(product, frame_id):
    from urllib.parse import quote, quote_plus
    zh = (product.get("keywords_zh") or [product.get("name_zh", "")])[0] or product.get("name_zh", "")
    en = (product.get("keywords_en") or [product.get("name_en", "")])[0] or product.get("name_en", "")
    links = []
    if zh:
        links += [{"key": "1688", "url": "https://s.1688.com/selloffer/offer_search.htm?keywords=" + quote(zh.encode("gbk", "ignore"))},
                  {"key": "taobao", "url": "https://s.taobao.com/search?q=" + quote(zh)}]
    if en:
        slug = re.sub(r"[^A-Za-z0-9]+", "-", en).strip("-")
        links += [{"key": "alibaba", "url": "https://www.alibaba.com/trade/search?SearchText=" + quote_plus(en)},
                  {"key": "mic", "url": f"https://www.made-in-china.com/multi-search/{slug}/F1/1.html"}]
    if frame_id:
        exp = str(int(time.time()) + 7 * 86400)
        img = request.url_root.rstrip("/") + f"/pub/frame/{frame_id}?e={exp}&s={_sign(frame_id, exp)}"
        links.append({"key": "lens", "url": "https://lens.google.com/uploadbyurl?url=" + quote(img, safe="")})
    if zh or en:
        links.append({"key": "google", "url": "https://www.google.com/search?q=" + quote(f"{zh or en} 厂家 供应商")})
    return links


def _product_for(vid):
    """AI description of the product in a video (cached in the database)."""
    rows = _video_rows([vid])
    if vid not in rows:
        abort(404)
    v = rows[vid]
    frames = engine.key_frames(vid, 3)
    if v["ai_product"]:
        return v, v["ai_product"], frames
    images = []
    for fid in frames:
        p = os.path.join(THUMB_DIR, f"{fid}.jpg")
        if os.path.exists(p):
            with open(p, "rb") as fh:
                images.append(fh.read())
    info = {k: val for k, val in (v["meta"] or {}).items() if not re.search(r"联系|电话|微信|网站|日期", k)}
    if v["title"]:
        info.setdefault("名称", v["title"])
    product = openai_helper.describe_product(images, info) if images else None
    if product:
        with db() as c:
            c.execute("UPDATE videos SET ai_product=? WHERE id=?", (json.dumps(product, ensure_ascii=False), vid))
    return v, product, frames


@app.get("/api/videos/<int:vid>/product")
def product_info(vid):
    v, product, frames = _product_for(vid)
    if not product:  # no OpenAI: still offer searches with the table name
        name = v["title"] or ""
        product = {"name_zh": name, "name_en": "", "keywords_zh": [name] if name else [], "keywords_en": [], "fallback": True}
    return jsonify(product=product, links=_search_links(product, frames[len(frames) // 2] if frames else None),
                   ai=bool(openai_helper.enabled()))


_research_lock = threading.Lock()


def _run_research(vid, who):
    try:
        _, product, _ = _product_for(vid)
        if not product:
            raise RuntimeError("no_product")
        result = openai_helper.research_suppliers(product)
        result["product"] = product
        with db() as c:
            c.execute("UPDATE supplier_research SET status='done', result=?, error=NULL, updated_at=? WHERE video_id=?",
                      (json.dumps(result, ensure_ascii=False), time.time(), vid))
    except Exception as e:
        print("research failed:", e, flush=True)
        with db() as c:
            c.execute("UPDATE supplier_research SET status='error', error=?, updated_at=? WHERE video_id=?",
                      (str(e)[:300], time.time(), vid))


@app.post("/api/videos/<int:vid>/research")
def research_start(vid):
    if not openai_helper.enabled():
        return jsonify(error="no_ai"), 400
    with _research_lock, db() as c:
        row = c.execute("SELECT status, updated_at FROM supplier_research WHERE video_id=?", (vid,)).fetchone()
        if row and row["status"] == "running" and time.time() - (row["updated_at"] or 0) < 600:
            return jsonify(status="running")
        c.execute("INSERT OR REPLACE INTO supplier_research (video_id, status, result, error, updated_at, requested_by) "
                  "VALUES (?,?,?,?,?,?)", (vid, "running", None, None, time.time(), session.get("name", "")))
    threading.Thread(target=_run_research, args=(vid, session.get("name", "")), daemon=True).start()
    return jsonify(status="running")


@app.get("/api/videos/<int:vid>/research")
def research_get(vid):
    with db() as c:
        row = c.execute("SELECT * FROM supplier_research WHERE video_id=?", (vid,)).fetchone()
    if not row:
        return jsonify(status="none")
    d = dict(row)
    d["result"] = json.loads(d["result"]) if d.get("result") else None
    if d["status"] == "running" and time.time() - (d["updated_at"] or 0) > 600:
        d["status"], d["error"] = "error", "timeout"
    return jsonify(d)


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
    return jsonify(natural_voice=bool(ok and st.get("tts_model")), smart_search=bool(ok and st.get("chat_model")),
                   voice_input=bool(ok and st.get("stt_model")), openai=st)


@app.post("/api/transcribe")
def transcribe():
    f = request.files.get("audio")
    if not f:
        return jsonify(error="no audio"), 400
    audio = f.read(8 * 1024 * 1024)
    mime = (f.mimetype or "audio/webm").split(";")[0]
    ext = {"audio/mp4": "m4a", "audio/x-m4a": "m4a", "audio/aac": "m4a", "audio/mpeg": "mp3", "audio/wav": "wav",
           "audio/ogg": "ogg", "audio/webm": "webm"}.get(mime, "webm")
    text = openai_helper.transcribe(audio, f"speech.{ext}", mime, request.form.get("lang", "zh"))
    if text is None:
        return jsonify(error="unavailable"), 503
    return jsonify(text=text)


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
    body = request.get_json(silent=True) or {}
    url = str(body.get("url", ""))[:1000]
    try:
        sid = lark_sync.add_source(url, session.get("name", ""), body.get("row_from"), body.get("row_to"))
    except ValueError as e:
        return jsonify(error=str(e) if str(e) == "bad_range" else "bad_link"), 400
    return jsonify(id=sid)


@app.patch("/api/lark/<int:sid>")
def lark_range(sid):
    body = request.get_json(silent=True) or {}
    try:
        lark_sync.set_range(sid, body.get("row_from"), body.get("row_to"))
    except ValueError:
        return jsonify(error="bad_range"), 400
    return jsonify(ok=True)


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
