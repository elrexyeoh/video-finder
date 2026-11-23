"""Video indexing + search engine.

Each uploaded video is sampled every few seconds. Every sampled frame is looked at by a
vision AI model (Google's SigLIP), which turns it into an "embedding": a list of numbers
capturing what the picture shows. A search sentence is turned into a matching text
embedding, and the model scores how likely each frame is to show what was described.

Unlike older CLIP models, SigLIP gives an absolute yes/no-style score per frame, so we can
tell "nothing in the library matches" apart from "this is the best of a bad bunch".
"""
import json
import os
import queue
import re
import sqlite3
import subprocess
import tempfile
import threading
import traceback
from fractions import Fraction

import numpy as np
from PIL import Image

import openai_helper

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
VIDEO_DIR = os.path.join(DATA_DIR, "videos")
THUMB_DIR = os.path.join(DATA_DIR, "thumbs")
DB_PATH = os.path.join(DATA_DIR, "index.db")

SAMPLE_EVERY_SEC = float(os.environ.get("SAMPLE_EVERY_SEC", "2"))
# Skip a frame if it looks almost the same as the last kept one (saves memory on static shots).
DEDUPE_SIMILARITY = float(os.environ.get("DEDUPE_SIMILARITY", "0.95"))
# Multilingual vision model: search in English, Malay, Chinese and 100+ languages.
MODEL = os.environ.get("MODEL", "google/siglip-base-patch16-256-multilingual")
PROMPT = "a photo of {}"
# Match thresholds on the model's log-odds score. Calibrated on real photos:
#   >= STRONG  -> clearly shows what was asked for
#   >= MINIMUM -> probably shows it
#   below      -> not shown at all
STRONG = float(os.environ.get("MATCH_STRONG", "-7.5"))
MINIMUM = float(os.environ.get("MATCH_MINIMUM", "-10"))
# Chinese requests are also translated to English (locally) and both are scored together:
# the vision model is most precise in English, and averaging guards against bad translations.
TRANSLATE_MODEL = os.environ.get("TRANSLATE_MODEL", "Helsinki-NLP/opus-mt-zh-en")
_CJK = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")
# "Find the same product": video-to-video similarity cut-offs (see Engine.similar).
SIMILAR_SAME = float(os.environ.get("SIMILAR_SAME", "0.80"))
SIMILAR_MIN = float(os.environ.get("SIMILAR_MIN", "0.68"))
# Also drop results far weaker than the best one found.
RELATIVE_GAP = float(os.environ.get("MATCH_GAP", "2.5"))

for d in (VIDEO_DIR, THUMB_DIR):
    os.makedirs(d, exist_ok=True)

BROWSER_CODECS = {"h264", "vp8", "vp9", "av1"}
BROWSER_EXT = {".mp4", ".m4v", ".webm", ".mov"}


def run_ffmpeg(args):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg: " + (r.stderr.strip().splitlines() or ["failed"])[-1][:300])


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("This file isn't a readable video")
    data = json.loads(r.stdout or "{}")
    vstreams = [s for s in data.get("streams", []) if s.get("codec_type") == "video"
                and not s.get("disposition", {}).get("attached_pic")]
    if not vstreams:
        raise RuntimeError("This file has no video track")
    v = vstreams[0]
    astreams = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
    audio_ok = all(s.get("codec_name") in ("aac", "mp3", "opus", "vorbis") for s in astreams)
    ext = os.path.splitext(path)[1].lower()
    try:
        duration = float(data.get("format", {}).get("duration") or v.get("duration") or 0)
    except ValueError:
        duration = 0.0
    return {
        "duration": duration,
        "browser_ok": v.get("codec_name") in BROWSER_CODECS and ext in BROWSER_EXT and audio_ok
        and v.get("pix_fmt", "yuv420p") == "yuv420p",
    }


# ---------- turning a spoken/typed request into a visual description ----------
_FILLER = [
    # English
    r"(?:hey|hi|ok(?:ay)?|please|pls|can you|could you|would you|i want(?: to)?|i need(?: to)?|i'm looking for|im looking for|"
    r"help me|let me|kindly)\b",
    r"(?:find|search(?: for)?|show|get|give|bring|look(?: for)?|look up|pull up|retrieve|fetch|locate|play|open)(?: me| us)?\b",
    r"(?:all|any|some|the|a|an)?\s*(?:videos?|clips?|footage|recordings?|files?|shots?|scenes?|vids?)\b",
    r"(?:where|which|that|in which|with)\s+(?:there\s+(?:is|are)|we\s+(?:see|can see)|you\s+(?:see|can see)|(?:it\s+)?(?:shows?|has|have|contains?|features?))\b",
    r"(?:of|about|showing|featuring|containing|having|with)\b(?=\s)",
    # Malay
    r"(?:tolong|sila|boleh|saya nak|saya mahu|saya perlukan|nak|mahu)\b",
    r"(?:cari(?:kan)?|tunjuk(?:kan)?|tunjukkan|dapatkan|beri)(?: saya| kami)?\b",
    r"(?:semua|mana-mana)?\s*(?:video|klip|rakaman|fail)\b",
    r"(?:yang|di mana|dimana)\s+(?:ada|terdapat|menunjukkan|mempunyai)\b",
    r"(?:tentang|mengenai|berkenaan)\b",
    # Chinese
    r"(?:请|帮我|给我看|给我|我要看|我要|我想看|我想|找一下|找|搜索|搜|查找|显示|看一下|看看)",
    r"(?:所有|一些)?(?:的)?(?:视频|影片|片段)(?:里|中)?(?:有|是)?",
]
_FILLER_RE = re.compile(r"^\s*(?:" + "|".join(_FILLER) + r")[\s,.:;!?]*", re.IGNORECASE)
# Words that come at the end: "...的视频", "... video please"
_TAIL_RE = re.compile(r"(?:[\s,]*(?:please|pls|tolong)|(?:的)?(?:视频|影片|片段)(?:吗)?|[\s,]+(?:videos?|clips?|footage))\s*$",
                      re.IGNORECASE)


def clean_query(q):
    """'Find me the videos where there are blue sofas' -> 'blue sofas'."""
    q = q.strip().strip(" .?!。？！")
    prev = None
    while prev != q:
        prev = q
        q = _FILLER_RE.sub("", q, count=1).strip()
        q = _TAIL_RE.sub("", q).strip()
        q = re.sub(r"^(?:有|是)(?=\S)", "", q)
    return q or prev


def db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                stored_name TEXT NOT NULL,
                size INTEGER,
                duration REAL,
                status TEXT NOT NULL DEFAULT 'queued',   -- queued | converting | indexing | ready | error
                progress REAL DEFAULT 0,
                error TEXT,
                uploaded_by TEXT,
                created_at REAL
            );
            CREATE TABLE IF NOT EXISTS frames (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
                t REAL NOT NULL,
                emb BLOB NOT NULL
            );
            CREATE INDEX IF NOT EXISTS frames_video ON frames(video_id);
            """
        )
        cols = [r["name"] for r in c.execute("PRAGMA table_info(frames)")]
        if "model" not in cols:
            c.execute("ALTER TABLE frames ADD COLUMN model TEXT")
        vcols = [r["name"] for r in c.execute("PRAGMA table_info(videos)")]
        for col in ("source TEXT", "source_id TEXT", "source_ref TEXT", "title TEXT", "meta TEXT", "meta_text TEXT"):
            if col.split()[0] not in vcols:
                c.execute(f"ALTER TABLE videos ADD COLUMN {col}")
        c.execute("CREATE INDEX IF NOT EXISTS videos_source ON videos(source, source_id)")
        if "ai_product" not in [r["name"] for r in c.execute("PRAGMA table_info(videos)")]:
            c.execute("ALTER TABLE videos ADD COLUMN ai_product TEXT")
        c.execute("""CREATE TABLE IF NOT EXISTS supplier_research (
            video_id INTEGER PRIMARY KEY, status TEXT, result TEXT, error TEXT, updated_at REAL, requested_by TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS lark_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT NOT NULL, app_token TEXT, table_id TEXT, name TEXT,
            status TEXT DEFAULT 'new', message TEXT, found INTEGER DEFAULT 0, imported INTEGER DEFAULT 0,
            last_sync REAL, created_at REAL, added_by TEXT)""")
        scols = [r["name"] for r in c.execute("PRAGMA table_info(lark_sources)")]
        for col in ("view_id TEXT", "row_from INTEGER", "row_to INTEGER"):
            if col.split()[0] not in scols:
                c.execute(f"ALTER TABLE lark_sources ADD COLUMN {col}")
        # Anything interrupted by a restart goes back in the queue.
        c.execute("UPDATE videos SET status='queued', progress=0 WHERE status IN ('indexing','converting')")


class Engine:
    def __init__(self):
        self._model = None
        self._proc = None
        self._scale = 1.0
        self._bias = 0.0
        self._model_lock = threading.Lock()
        self._infer_lock = threading.Lock()
        self._mt = None
        self._mt_tok = None
        self._mt_lock = threading.Lock()
        self._mt_cache = {}
        self._jobs = queue.Queue()
        self._index_lock = threading.Lock()
        self._frame_ids = np.zeros(0, dtype=np.int64)
        self._frame_video = np.zeros(0, dtype=np.int64)
        self._frame_t = np.zeros(0, dtype=np.float32)
        self._matrix = np.zeros((0, 1), dtype=np.float16)

    # ---------- model ----------
    def _load(self):
        with self._model_lock:
            if self._model is None:
                import torch
                from transformers import AutoModel, AutoProcessor

                torch.set_num_threads(max(1, os.cpu_count() or 1))
                self._model = AutoModel.from_pretrained(MODEL).eval()
                self._proc = AutoProcessor.from_pretrained(MODEL)
                self._scale = float(self._model.logit_scale.exp())
                self._bias = float(self._model.logit_bias)

    def embed_images(self, images):
        import torch

        self._load()
        out = []
        with self._infer_lock, torch.no_grad():
            for i in range(0, len(images), 16):
                o = self._model.get_image_features(**self._proc(images=images[i:i + 16], return_tensors="pt"))
                o = o if torch.is_tensor(o) else o.pooler_output
                out.append(torch.nn.functional.normalize(o, dim=-1).numpy())
        return np.concatenate(out).astype(np.float32)

    def embed_text(self, text):
        import torch

        self._load()
        with self._infer_lock, torch.no_grad():
            t = self._proc(text=[PROMPT.format(text)], padding="max_length", max_length=64,
                           truncation=True, return_tensors="pt")
            o = self._model.get_text_features(**t)
            o = o if torch.is_tensor(o) else o.pooler_output
            return torch.nn.functional.normalize(o, dim=-1).numpy()[0].astype(np.float32)

    def translate(self, text):
        """Chinese -> English with a small local model. Returns None if unavailable."""
        if not _CJK.search(text) or not TRANSLATE_MODEL:
            return None
        if text in self._mt_cache:
            return self._mt_cache[text]
        try:
            import torch
            from transformers import MarianMTModel, MarianTokenizer

            with self._mt_lock:
                if self._mt is None:
                    self._mt_tok = MarianTokenizer.from_pretrained(TRANSLATE_MODEL)
                    self._mt = MarianMTModel.from_pretrained(TRANSLATE_MODEL).eval()
                with torch.no_grad():
                    out = self._mt.generate(**self._mt_tok([text], return_tensors="pt", truncation=True),
                                            max_new_tokens=48, num_beams=2)
                en = self._mt_tok.decode(out[0], skip_special_tokens=True).strip().rstrip(".。")
        except Exception:
            traceback.print_exc()
            return None
        if len(self._mt_cache) > 2000:
            self._mt_cache.clear()
        self._mt_cache[text] = en or None
        return en or None

    # ---------- lifecycle ----------
    def start(self):
        init_db()
        self.reload_matrix()
        threading.Thread(target=self._worker, daemon=True).start()

    def enqueue(self, video_id):
        self._jobs.put(video_id)

    def stats(self):
        with db() as c:
            r = c.execute("SELECT COUNT(*) n, SUM(status='ready') ready FROM videos").fetchone()
        return {"videos": r["n"] or 0, "searchable": r["ready"] or 0}

    def reload_matrix(self):
        with db() as c:
            rows = c.execute(
                "SELECT f.id, f.video_id, f.t, f.emb FROM frames f JOIN videos v ON v.id=f.video_id "
                "WHERE v.status='ready' AND f.model=? ORDER BY f.id", (MODEL,)
            ).fetchall()
        ids = np.array([r["id"] for r in rows], dtype=np.int64)
        vids = np.array([r["video_id"] for r in rows], dtype=np.int64)
        ts = np.array([r["t"] for r in rows], dtype=np.float32)
        mat = (np.stack([np.frombuffer(r["emb"], dtype=np.float16) for r in rows])
               if rows else np.zeros((0, 1), dtype=np.float16))
        with self._index_lock:
            self._frame_ids, self._frame_video, self._frame_t, self._matrix = ids, vids, ts, mat

    # ---------- background work ----------
    def _worker(self):
        try:
            self._load()  # warm up so the first search is fast
            self.translate("沙发")
            self._upgrade_old_frames()
        except Exception:
            traceback.print_exc()
        with db() as c:
            for row in c.execute("SELECT id FROM videos WHERE status='queued' ORDER BY id"):
                self._jobs.put(row["id"])
        while True:
            vid = self._jobs.get()
            try:
                self._index_video(vid)
            except Exception as e:  # keep the worker alive no matter what
                traceback.print_exc()
                with db() as c:
                    c.execute("UPDATE videos SET status='error', error=? WHERE id=?", (str(e)[:500], vid))

    def _upgrade_old_frames(self):
        """Frames indexed by an older model are re-scored from their saved thumbnails."""
        with db() as c:
            vids = [r["video_id"] for r in c.execute(
                "SELECT DISTINCT video_id FROM frames WHERE model IS NULL OR model != ?", (MODEL,))]
        for vid in vids:
            with db() as c:
                rows = c.execute("SELECT id FROM frames WHERE video_id=? AND (model IS NULL OR model != ?)",
                                 (vid, MODEL)).fetchall()
            ok_ids, imgs = [], []
            for r in rows:
                p = os.path.join(THUMB_DIR, f"{r['id']}.jpg")
                if os.path.exists(p):
                    with Image.open(p) as im:
                        imgs.append(im.convert("RGB"))
                    ok_ids.append(r["id"])
            embs = self.embed_images(imgs) if imgs else []
            with db() as c:
                for fid, e in zip(ok_ids, embs):
                    c.execute("UPDATE frames SET emb=?, model=? WHERE id=?", (e.astype(np.float16).tobytes(), MODEL, fid))
            self.reload_matrix()
            print(f"re-indexed video {vid} with {MODEL}", flush=True)

    def _set(self, vid, **fields):
        keys = ", ".join(f"{k}=?" for k in fields)
        with db() as c:
            c.execute(f"UPDATE videos SET {keys} WHERE id=?", (*fields.values(), vid))

    def _index_video(self, vid):
        with db() as c:
            row = c.execute("SELECT * FROM videos WHERE id=?", (vid,)).fetchone()
        if row is None or row["status"] == "ready":
            return
        path = os.path.join(VIDEO_DIR, row["stored_name"])
        self._set(vid, status="indexing", progress=0, error=None)

        info = probe(path)
        duration = info["duration"]

        # Make sure every video plays in a normal web browser (convert iPhone HEVC, .avi, .wmv, ...).
        if not info["browser_ok"]:
            self._set(vid, status="converting")
            out_name = os.path.splitext(row["stored_name"])[0] + ".mp4"
            tmp = os.path.join(VIDEO_DIR, out_name + ".part.mp4")
            run_ffmpeg(["-i", path, "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "veryfast",
                        "-crf", "23", "-pix_fmt", "yuv420p", "-vf", "scale=trunc(min(iw\\,1920)/2)*2:-2",
                        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", tmp])
            if os.path.abspath(path) != os.path.abspath(os.path.join(VIDEO_DIR, out_name)):
                os.remove(path)
            os.replace(tmp, os.path.join(VIDEO_DIR, out_name))
            path = os.path.join(VIDEO_DIR, out_name)
            self._set(vid, stored_name=out_name, size=os.path.getsize(path), status="indexing")
        self._set(vid, progress=0.2)

        # Pull one frame every SAMPLE_EVERY_SEC seconds.
        with tempfile.TemporaryDirectory() as td:
            run_ffmpeg(["-i", path, "-map", "0:v:0", "-vf",
                        f"fps={Fraction(1 / SAMPLE_EVERY_SEC).limit_denominator(1000)},scale='min(640,iw)':-2",
                        "-q:v", "4", os.path.join(td, "%06d.jpg")])
            files = sorted(f for f in os.listdir(td) if f.endswith(".jpg"))
            if not files:
                raise RuntimeError("No frames could be read from this video")
            samples = []
            for i, fn in enumerate(files):
                with Image.open(os.path.join(td, fn)) as im:
                    # ffmpeg's fps filter picks the frame from the middle of each interval
                    samples.append((round(i * SAMPLE_EVERY_SEC + SAMPLE_EVERY_SEC / 2, 2), im.convert("RGB")))
        if not duration:
            duration = samples[-1][0]
        self._set(vid, progress=0.3)

        embs = []
        B = 32
        for i in range(0, len(samples), B):
            embs.append(self.embed_images([im for _, im in samples[i:i + B]]))
            self._set(vid, progress=0.3 + 0.7 * min(1.0, (i + B) / len(samples)))
        embs = np.concatenate(embs)

        # Drop near-duplicate consecutive frames, save thumbnails, store embeddings.
        with db() as c:
            c.execute("DELETE FROM frames WHERE video_id=?", (vid,))
            last = None
            for (ft, img), e in zip(samples, embs):
                if last is not None and float(e @ last) >= DEDUPE_SIMILARITY:
                    continue
                last = e
                cur = c.execute("INSERT INTO frames (video_id, t, emb, model) VALUES (?,?,?,?)",
                                (vid, ft, e.astype(np.float16).tobytes(), MODEL))
                thumb = img.copy()
                thumb.thumbnail((480, 480))
                thumb.save(os.path.join(THUMB_DIR, f"{cur.lastrowid}.jpg"), quality=82)
            c.execute("UPDATE videos SET status='ready', progress=1, duration=? WHERE id=?", (duration, vid))
        self.reload_matrix()

    # ---------- search ----------
    def search(self, query, limit=30, frames_per_video=4):
        visual = clean_query(query)
        result = {"query": query, "looking_for": visual, "results": [], **self.stats()}
        with self._index_lock:
            mat, fids, fvid, ft = self._matrix, self._frame_ids, self._frame_video, self._frame_t
        if len(fids) == 0:
            return result
        m32 = mat.astype(np.float32)
        score = lambda text: (m32 @ self.embed_text(text)) * self._scale + self._bias
        logits = score(visual)
        # Best: an OpenAI model rewrites the request as a precise English scene description.
        understood = openai_helper.understand(query)
        if understood and understood["visual"]:
            result.update(engine="openai", translated=understood["visual"])
            if understood["display"]:
                result["looking_for"] = understood["display"]
            logits = 0.6 * score(understood["visual"]) + 0.4 * logits
        else:
            # Free fallback: local Chinese->English translation, averaged with the original.
            english = self.translate(visual)
            result["engine"] = "local"
            if english:
                result["translated"] = english
                logits = (logits + score(english)) / 2

        keep = logits >= MINIMUM
        if keep.any():
            keep &= logits >= float(logits[keep].max()) - RELATIVE_GAP

        def top_frames(mask):
            per = {}
            for i in np.argsort(-logits):
                if not mask[i]:
                    continue
                lst = per.setdefault(int(fvid[i]), [])
                # one thumbnail per 4-second stretch, for variety
                if len(lst) < frames_per_video and all(abs(float(ft[i]) - f["t"]) > 4 for f in lst):
                    lst.append({"frame_id": int(fids[i]), "t": float(ft[i]), "score": round(float(logits[i]), 2)})
            return per

        per_video = top_frames(keep) if keep.any() else {}
        # Text match on titles / table columns imported from Lark (e.g. product names).
        text_hits = self._text_matches([visual, result.get("looking_for"), result.get("translated")])
        missing = text_hits - set(per_video)
        if missing:
            extra = top_frames(np.isin(fvid, list(missing)))
            for v in missing:
                if v in extra:
                    per_video[v] = extra[v][:2]

        if text_hits:  # a solid match on the table details beats weak picture guesses
            per_video = {v: f for v, f in per_video.items() if v in text_hits or f[0]["score"] >= STRONG}
        ranked = sorted(per_video.items(), key=lambda kv: (0 if kv[0] in text_hits else 1 if kv[1][0]["score"] >= STRONG else 2,
                                                           -kv[1][0]["score"]))[:limit]
        if not ranked:
            return result
        with db() as c:
            meta = {r["id"]: dict(r) for r in c.execute(
                f"SELECT id, filename, title, meta, source, duration, uploaded_by, created_at FROM videos WHERE id IN "
                f"({','.join('?' * len(ranked))})", [v for v, _ in ranked])}
        for v, frames in ranked:
            if v in meta:
                m = meta[v]
                m["meta"] = json.loads(m["meta"]) if m.get("meta") else None
                top = frames[0]["score"]
                result["results"].append({**m, "score": top, "text_match": v in text_hits,
                                          "strength": "strong" if (top >= STRONG or v in text_hits) else "possible",
                                          "frames": sorted(frames, key=lambda f: f["t"])})
        return result

    def similar(self, vid, limit=12, minimum=SIMILAR_MIN):
        """Videos that look like this one: for each of its frames take the best-matching frame of the
        other video, then average. Same product filmed twice scores ~0.8+, unrelated ~0.5."""
        with self._index_lock:
            mat, fvid, fids, ft = self._matrix, self._frame_video, self._frame_ids, self._frame_t
        mine = fvid == vid
        if not mine.any() or len(fvid) == 0:
            return []
        A = mat[mine].astype(np.float32)
        if len(A) > 24:  # plenty to characterise a video
            A = A[np.linspace(0, len(A) - 1, 24).astype(int)]
        order = np.argsort(fvid, kind="stable")
        vs = fvid[order]
        starts = np.flatnonzero(np.r_[True, vs[1:] != vs[:-1]])
        sims = A @ mat[order].astype(np.float32).T
        best = np.maximum.reduceat(sims, starts, axis=1)            # (frames of A) x (videos)
        score = best.mean(axis=0)
        video_ids = vs[starts]
        best_frame = {}
        col = sims.max(axis=0)
        for k, start in enumerate(starts):
            end = starts[k + 1] if k + 1 < len(starts) else len(vs)
            j = start + int(np.argmax(col[start:end]))
            best_frame[int(video_ids[k])] = (int(fids[order][j]), float(ft[order][j]))
        out = []
        for k in np.argsort(-score):
            v = int(video_ids[k])
            if v == vid:
                continue
            if score[k] < minimum or len(out) >= limit:
                break
            fid, t = best_frame[v]
            out.append({"id": v, "similarity": round(float(score[k]), 3), "frame_id": fid, "t": t,
                        "level": "same" if score[k] >= SIMILAR_SAME else "similar"})
        return out

    def key_frames(self, vid, n=3):
        """Up to n frame ids spread across the video (for describing the product)."""
        with self._index_lock:
            ids = self._frame_ids[self._frame_video == vid]
        if not len(ids):
            return []
        return [int(ids[i]) for i in sorted(set(np.linspace(0, len(ids) - 1, min(n, len(ids))).astype(int)))]

    def _text_matches(self, phrases):
        """Videos whose title or Lark table columns contain the request (e.g. a product name)."""
        phrases = {p.strip().lower() for p in phrases if p and len(p.strip()) >= 2}
        if not phrases:
            return set()
        hits = set()
        with db() as c:
            rows = c.execute("SELECT id, lower(coalesce(title,'') || ' ' || coalesce(meta_text,'')) AS txt FROM videos "
                             "WHERE status='ready' AND (title IS NOT NULL OR meta_text IS NOT NULL)").fetchall()
        for r in rows:
            txt = r["txt"]
            for p in phrases:
                words = [w for w in re.split(r"[\s,，。.!?、/]+", p) if len(w) >= 3]
                # distinctive latin words (product names, codes) inside a Chinese or mixed sentence
                names = re.findall(r"[a-z0-9\u00c0-\u024f][a-z0-9\u00c0-\u024f\-]{3,}", p)
                if p in txt or (len(words) >= 2 and all(w in txt for w in words)) or (names and all(n in txt for n in names)):
                    hits.add(r["id"])
                    break
        return hits


engine = Engine()
