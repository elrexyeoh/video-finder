"""Import videos from Lark Base (多维表格) tables into the Video Finder library.

An admin pastes a Base link once. The app then reads every row, downloads video attachments,
and keeps the row's other columns (product name, category, notes...) as searchable details.
It re-syncs on a schedule and only downloads attachments it hasn't imported before.
Nothing is ever changed or deleted in Lark: the app only needs read access.

Setup (Lark developer console): create a custom app, give it read-only Base and Drive-media
scopes, publish it, then add the app to the Base from the Base's "···" menu. Put the app's
credentials in the LARK_APP_ID and LARK_APP_SECRET environment variables.
"""
import json
import os
import re
import shutil
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid

from indexer import DATA_DIR, VIDEO_DIR, db, engine

API = os.environ.get("LARK_API_BASE", "https://open.larksuite.com").rstrip("/")
APP_ID = os.environ.get("LARK_APP_ID", "").strip()
APP_SECRET = os.environ.get("LARK_APP_SECRET", "").strip()
SYNC_MINUTES = float(os.environ.get("LARK_SYNC_MINUTES", "60"))
KEEP_FREE_MB = float(os.environ.get("KEEP_FREE_MB", "400"))  # stop importing before the disk is full

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".wmv", ".mpg", ".mpeg", ".3gp", ".3g2", ".flv",
             ".mts", ".m2ts", ".ts", ".vob", ".ogv", ".hevc", ".mxf", ".dv", ".asf", ".f4v"}
ATTACHMENT = 17  # Base field type for attachments


def configured():
    return bool(APP_ID and APP_SECRET)


class LarkError(Exception):
    def __init__(self, code, msg, http=None):
        super().__init__(f"{code}: {msg}")
        self.code, self.msg, self.http = code, msg, http


# ---------------------------------------------------------------- API client
_tok = {"value": None, "exp": 0.0}
_tok_lock = threading.Lock()


def _token():
    with _tok_lock:
        if _tok["value"] and time.time() < _tok["exp"] - 120:
            return _tok["value"]
        body = json.dumps({"app_id": APP_ID, "app_secret": APP_SECRET}).encode()
        r = urllib.request.Request(API + "/open-apis/auth/v3/tenant_access_token/internal", data=body, method="POST",
                                   headers={"Content-Type": "application/json; charset=utf-8"})
        with urllib.request.urlopen(r, timeout=20) as resp:
            d = json.loads(resp.read())
        if d.get("code") != 0:
            raise LarkError(d.get("code"), d.get("msg", "could not get access token"))
        _tok["value"], _tok["exp"] = d["tenant_access_token"], time.time() + int(d.get("expire", 7200))
        return _tok["value"]


def _open(method, path, params=None, body=None, timeout=30):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(6):
        r = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {_token()}", "Content-Type": "application/json; charset=utf-8"})
        try:
            return urllib.request.urlopen(r, timeout=timeout)
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                d = json.loads(raw)
            except Exception:
                d = {}
            code = d.get("code")
            if e.code in (429, 500, 502, 503, 504) or code in (99991400, 1254290, 1254607, 1255040):  # busy: retry
                time.sleep(min(30, 2 ** attempt))
                continue
            if code in (99991663, 99991664, 99991661):  # token expired/invalid
                _tok["value"] = None
                continue
            raise LarkError(code or e.code, d.get("msg") or f"HTTP {e.code}", http=e.code)
    raise LarkError(429, "Lark kept rate-limiting the requests")


def _get(path, params=None):
    with _open("GET", path, params) as resp:
        d = json.loads(resp.read())
    if d.get("code") != 0:
        raise LarkError(d.get("code"), d.get("msg"))
    return d.get("data") or {}


def _paged(path, params=None, key="items"):
    params = dict(params or {})
    while True:
        d = _get(path, params)
        yield from d.get(key) or []
        if not d.get("has_more") or not d.get("page_token"):
            break
        params["page_token"] = d["page_token"]


# ---------------------------------------------------------------- Base helpers
def parse_link(url):
    """https://xxx.larksuite.com/base/<app_token>?table=tbl...  or  .../wiki/<node>?table=tbl..."""
    u = urllib.parse.urlparse(url.strip())
    q = urllib.parse.parse_qs(u.query)
    table = (q.get("table") or [None])[0]
    m = re.search(r"/(base|wiki)/([A-Za-z0-9]+)", u.path)
    if not m:
        raise ValueError("bad_link")
    return m.group(1), m.group(2), table


def resolve_app_token(kind, token):
    if kind == "base":
        return token
    node = _get("/open-apis/wiki/v2/spaces/get_node", {"token": token}).get("node") or {}
    if node.get("obj_type") != "bitable":
        raise ValueError("not_base")
    return node["obj_token"]


def cell_text(v):
    """Turn any Base cell value into plain text."""
    if v is None:
        return ""
    if isinstance(v, (str, int, float, bool)):
        return str(v)
    if isinstance(v, list):
        parts = [t for t in (cell_text(x) for x in v) if t]
        if v and all(isinstance(x, dict) and "type" in x and "text" in x for x in v):
            return "".join(parts)  # rich-text segments
        return ", ".join(parts)  # multi-select, people, links...
    if isinstance(v, dict):
        for k in ("text", "name", "en_name", "full_name", "link", "value"):
            if k in v and v[k] not in (None, ""):
                return cell_text(v[k])
    return ""


def is_video(att):
    ext = os.path.splitext(att.get("name") or "")[1].lower()
    return (att.get("type") or "").startswith("video/") or ext in VIDEO_EXT


def download(file_token, dest, extra=None):
    params = {"extra": json.dumps(extra, separators=(",", ":"))} if extra else None
    tmp = dest + ".part"
    with _open("GET", f"/open-apis/drive/v1/medias/{file_token}/download", params, timeout=120) as resp, open(tmp, "wb") as f:
        shutil.copyfileobj(resp, f, 1024 * 1024)
    os.replace(tmp, dest)


# ---------------------------------------------------------------- sync
_run_lock = threading.Lock()
_wake = threading.Event()
_pending = set()


def _set_src(sid, **fields):
    keys = ", ".join(f"{k}=?" for k in fields)
    with db() as c:
        c.execute(f"UPDATE lark_sources SET {keys} WHERE id=?", (*fields.values(), sid))


FRIENDLY = {
    "no_access": "The Lark app can't open this Base yet. In the Base, open ··· → Add document app, and add the Video Finder app.",
    "bad_creds": "Lark rejected the app credentials. Check LARK_APP_ID and LARK_APP_SECRET in Railway.",
    "storage_full": "Storage is full, so the import paused. Increase the Railway volume size, then sync again.",
}


def _friendly(e):
    if isinstance(e, LarkError):
        if e.code in (10003, 10014, 99991663, 99991664, 99991661):
            return FRIENDLY["bad_creds"]
        if e.http == 403 or e.code in (1254302, 1254303, 91403, 131006, 99991672, 99991679):
            return FRIENDLY["no_access"] + f" (Lark: {e.msg})"
        if e.code in (1254003, 1254040, 1254004, 1254041):
            return "Lark can't find that Base or table. Check the link."
        return f"Lark error {e.code}: {e.msg}"
    if isinstance(e, ValueError):
        return {"bad_link": "That doesn't look like a Lark Base link.", "not_base": "That Wiki page is not a Base table."}.get(str(e), str(e))
    return str(e)[:300]


def sync_source(sid):
    with db() as c:
        src = c.execute("SELECT * FROM lark_sources WHERE id=?", (sid,)).fetchone()
        skip = {r["file_token"] for r in c.execute("SELECT file_token FROM lark_skip")}
    if not src:
        return
    found = imported = 0
    _set_src(sid, status="syncing", message="Reading the Base…")
    try:
        app_token = src["app_token"]
        if not app_token:
            kind, token, _ = parse_link(src["url"])
            app_token = resolve_app_token(kind, token)
            _set_src(sid, app_token=app_token)
        tables = list(_paged(f"/open-apis/bitable/v1/apps/{app_token}/tables", {"page_size": 100}))
        if src["table_id"]:
            tables = [t for t in tables if t.get("table_id") == src["table_id"]] or [{"table_id": src["table_id"], "name": ""}]
        if not src["name"]:
            _set_src(sid, name=", ".join(t.get("name", "") for t in tables if t.get("name"))[:120] or None)

        for tb in tables:
            tid = tb["table_id"]
            fields = list(_paged(f"/open-apis/bitable/v1/apps/{app_token}/tables/{tid}/fields", {"page_size": 100}))
            att_fields = {f["field_name"]: f["field_id"] for f in fields if f.get("type") == ATTACHMENT}
            if not att_fields:
                continue
            primary = next((f["field_name"] for f in fields if f.get("is_primary")), None)
            names = {f["field_name"] for f in fields}
            for rec in _paged(f"/open-apis/bitable/v1/apps/{app_token}/tables/{tid}/records", {"page_size": 500}):
                cells = rec.get("fields") or {}
                meta = {}
                for k in [f["field_name"] for f in fields] + [k for k in cells if k not in names]:  # table column order
                    if k in att_fields or k not in cells:
                        continue
                    txt = cell_text(cells[k]).strip()
                    if txt:
                        meta[k] = txt[:500]
                title = meta.get(primary) if primary else None
                meta_text = " ".join(f"{k} {v}" for k, v in meta.items())[:4000]
                for fname, fid in att_fields.items():
                    for att in cells.get(fname) or []:
                        if not isinstance(att, dict) or not is_video(att) or not att.get("file_token"):
                            continue
                        ft = att["file_token"]
                        found += 1
                        with db() as c:
                            row = c.execute("SELECT id FROM videos WHERE source='lark' AND source_id=?", (ft,)).fetchone()
                            if row:  # already imported: refresh its details from the table
                                c.execute("UPDATE videos SET title=?, meta=?, meta_text=? WHERE id=?",
                                          (title, json.dumps(meta, ensure_ascii=False), meta_text, row["id"]))
                                continue
                        if ft in skip:
                            continue
                        size = int(att.get("size") or 0)
                        if shutil.disk_usage(DATA_DIR).free - size < KEEP_FREE_MB * 1e6:
                            raise RuntimeError("storage_full")
                        name = att.get("name") or "video.mp4"
                        ext = os.path.splitext(name)[1].lower()
                        stored = f"{uuid.uuid4().hex}{ext if ext.isascii() and 1 < len(ext) <= 6 else '.mp4'}"
                        dest = os.path.join(VIDEO_DIR, stored)
                        _set_src(sid, message=f"Downloading {name}…", found=found, imported=imported)
                        # Lark asks Base attachment downloads to say which table/record the file is in.
                        extra = {"bitablePerm": {"tableId": tid, "attachments": {fid: {rec["record_id"]: [ft]}}}}
                        try:
                            download(ft, dest, extra)
                        except LarkError as e:
                            if e.http not in (400, 403):
                                raise
                            download(ft, dest)  # some Bases only accept the plain form
                        ref = json.dumps({"app": app_token, "table": tid, "record": rec.get("record_id"), "field": fid})
                        with db() as c:
                            cur = c.execute(
                                "INSERT INTO videos (filename, stored_name, size, status, uploaded_by, created_at, source, "
                                "source_id, source_ref, title, meta, meta_text) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                                (name, stored, os.path.getsize(dest), "queued", "Lark", time.time(), "lark", ft, ref,
                                 title, json.dumps(meta, ensure_ascii=False), meta_text))
                            engine.enqueue(cur.lastrowid)
                        imported += 1
        msg = f"{found} videos found in Lark, {imported} new imported."
        _set_src(sid, status="ok", message=msg, found=found, imported=(src["imported"] or 0) + imported, last_sync=time.time())
    except Exception as e:
        if not isinstance(e, (LarkError, ValueError)) and str(e) != "storage_full":
            traceback.print_exc()
        msg = FRIENDLY["storage_full"] if str(e) == "storage_full" else _friendly(e)
        _set_src(sid, status="error", message=msg, found=found, imported=(src["imported"] or 0) + imported, last_sync=time.time())


def request_sync(sid):
    _pending.add(sid)
    _wake.set()


def _loop():
    while True:
        _wake.wait(timeout=60)
        _wake.clear()
        if not configured():
            continue
        with db() as c:
            due = [r["id"] for r in c.execute(
                "SELECT id FROM lark_sources WHERE last_sync IS NULL OR last_sync < ?", (time.time() - SYNC_MINUTES * 60,))]
        for sid in list(_pending) + [d for d in due if d not in _pending]:
            _pending.discard(sid)
            with _run_lock:
                sync_source(sid)


def start():
    with db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS lark_skip (file_token TEXT PRIMARY KEY)")
        c.execute("UPDATE lark_sources SET status='ok' WHERE status='syncing'")
    threading.Thread(target=_loop, daemon=True).start()


def sources():
    with db() as c:
        return [dict(r) for r in c.execute("SELECT id, url, name, status, message, found, imported, last_sync, added_by "
                                           "FROM lark_sources ORDER BY id")]


def add_source(url, added_by=""):
    kind, token, table = parse_link(url)  # validates the link
    with db() as c:
        cur = c.execute("INSERT INTO lark_sources (url, app_token, table_id, status, message, created_at, added_by) "
                        "VALUES (?,?,?,?,?,?,?)", (url.strip(), token if kind == "base" else None, table, "queued",
                                                   "Waiting to sync…", time.time(), added_by))
        sid = cur.lastrowid
    request_sync(sid)
    return sid


def remove_source(sid):
    with db() as c:
        c.execute("DELETE FROM lark_sources WHERE id=?", (sid,))


def skip_file(file_token):
    """Remember a deleted Lark video so the next sync doesn't bring it back."""
    with db() as c:
        c.execute("INSERT OR IGNORE INTO lark_skip (file_token) VALUES (?)", (file_token,))
