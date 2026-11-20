"""Video indexing + search engine.

Each uploaded video is sampled every few seconds. Every sampled frame is turned into a
CLIP "image embedding" (a list of numbers that captures what the picture shows). A search
query is turned into a matching "text embedding", and the frames whose embeddings are
closest to the query are the best matches. No tagging or captions needed.
"""
import os
import queue
import sqlite3
import threading
import time
import traceback

import json
import subprocess
import tempfile
from fractions import Fraction

import numpy as np
from PIL import Image

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
VIDEO_DIR = os.path.join(DATA_DIR, "videos")
THUMB_DIR = os.path.join(DATA_DIR, "thumbs")
DB_PATH = os.path.join(DATA_DIR, "index.db")

SAMPLE_EVERY_SEC = float(os.environ.get("SAMPLE_EVERY_SEC", "2"))
# Skip a frame if it looks almost the same as the last kept one (saves memory on static shots).
DEDUPE_SIMILARITY = float(os.environ.get("DEDUPE_SIMILARITY", "0.95"))
IMAGE_MODEL = os.environ.get("IMAGE_MODEL", "clip-ViT-B-32")
# Multilingual text model shares the same embedding space: search in English, Malay, Chinese, ...
TEXT_MODEL = os.environ.get("TEXT_MODEL", "sentence-transformers/clip-ViT-B-32-multilingual-v1")

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
        # Anything interrupted by a restart goes back in the queue.
        c.execute("UPDATE videos SET status='queued', progress=0 WHERE status IN ('indexing','converting')")


class Engine:
    def __init__(self):
        self._img_model = None
        self._txt_model = None
        self._model_lock = threading.Lock()
        self._jobs = queue.Queue()
        self._index_lock = threading.Lock()
        self._frame_ids = np.zeros(0, dtype=np.int64)
        self._frame_video = np.zeros(0, dtype=np.int64)
        self._frame_t = np.zeros(0, dtype=np.float32)
        self._matrix = np.zeros((0, 512), dtype=np.float16)

    # ---------- models ----------
    def _models(self):
        with self._model_lock:
            if self._img_model is None:
                from sentence_transformers import SentenceTransformer

                self._img_model = SentenceTransformer(IMAGE_MODEL, device="cpu")
                self._txt_model = SentenceTransformer(TEXT_MODEL, device="cpu")
        return self._img_model, self._txt_model

    # ---------- lifecycle ----------
    def start(self):
        init_db()
        self.reload_matrix()
        with db() as c:
            for row in c.execute("SELECT id FROM videos WHERE status='queued' ORDER BY id"):
                self._jobs.put(row["id"])
        threading.Thread(target=self._worker, daemon=True).start()
        # Warm the models in the background so the first search is fast.
        threading.Thread(target=self._models, daemon=True).start()

    def enqueue(self, video_id):
        self._jobs.put(video_id)

    def reload_matrix(self):
        with db() as c:
            rows = c.execute(
                "SELECT f.id, f.video_id, f.t, f.emb FROM frames f "
                "JOIN videos v ON v.id=f.video_id WHERE v.status='ready' ORDER BY f.id"
            ).fetchall()
        ids = np.array([r["id"] for r in rows], dtype=np.int64)
        vids = np.array([r["video_id"] for r in rows], dtype=np.int64)
        ts = np.array([r["t"] for r in rows], dtype=np.float32)
        mat = (
            np.stack([np.frombuffer(r["emb"], dtype=np.float16) for r in rows])
            if rows
            else np.zeros((0, 512), dtype=np.float16)
        )
        with self._index_lock:
            self._frame_ids, self._frame_video, self._frame_t, self._matrix = ids, vids, ts, mat

    # ---------- indexing ----------
    def _worker(self):
        while True:
            vid = self._jobs.get()
            try:
                self._index_video(vid)
            except Exception as e:  # keep the worker alive no matter what
                traceback.print_exc()
                with db() as c:
                    c.execute("UPDATE videos SET status='error', error=? WHERE id=?", (str(e)[:500], vid))

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
        img_model, _ = self._models()
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
                        f"fps={Fraction(1 / SAMPLE_EVERY_SEC).limit_denominator(1000)},scale='min(640,iw)':-2", "-q:v", "4",
                        os.path.join(td, "%06d.jpg")])
            files = sorted(f for f in os.listdir(td) if f.endswith(".jpg"))
            if not files:
                raise RuntimeError("No frames could be read from this video")
            samples = []
            for i, fn in enumerate(files):
                with Image.open(os.path.join(td, fn)) as im:
                    samples.append((i * SAMPLE_EVERY_SEC, im.convert("RGB")))
        if not duration:
            duration = samples[-1][0]
        self._set(vid, progress=0.3)

        # Embed in batches.
        embs = []
        B = 32
        for i in range(0, len(samples), B):
            batch = [im for _, im in samples[i : i + B]]
            e = img_model.encode(batch, batch_size=B, convert_to_numpy=True, normalize_embeddings=True)
            embs.append(e)
            self._set(vid, progress=0.3 + 0.7 * min(1.0, (i + B) / len(samples)))
        embs = np.concatenate(embs).astype(np.float32)

        # Drop near-duplicate consecutive frames, save thumbnails, store embeddings.
        with db() as c:
            c.execute("DELETE FROM frames WHERE video_id=?", (vid,))
            last = None
            for (ft, img), e in zip(samples, embs):
                if last is not None and float(e @ last) >= DEDUPE_SIMILARITY:
                    continue
                last = e
                cur = c.execute(
                    "INSERT INTO frames (video_id, t, emb) VALUES (?,?,?)",
                    (vid, ft, e.astype(np.float16).tobytes()),
                )
                thumb = img.copy()
                thumb.thumbnail((360, 360))
                thumb.save(os.path.join(THUMB_DIR, f"{cur.lastrowid}.jpg"), quality=80)
            c.execute(
                "UPDATE videos SET status='ready', progress=1, duration=? WHERE id=?", (duration, vid)
            )
        self.reload_matrix()

    # ---------- search ----------
    def search(self, query, limit=30, frames_per_video=4):
        _, txt_model = self._models()
        q = txt_model.encode([query], convert_to_numpy=True, normalize_embeddings=True)[0].astype(np.float32)
        with self._index_lock:
            mat, fids, fvid, ft = self._matrix, self._frame_ids, self._frame_video, self._frame_t
        if len(fids) == 0:
            return []
        scores = mat.astype(np.float32) @ q

        # Group frame scores per video; rank videos by their best frames.
        order = np.argsort(-scores)
        per_video = {}
        for i in order:
            v = int(fvid[i])
            lst = per_video.setdefault(v, [])
            if len(lst) < frames_per_video:
                # skip frames within 3s of an already-picked frame for variety
                if all(abs(float(ft[i]) - f["t"]) > 3 for f in lst):
                    lst.append({"frame_id": int(fids[i]), "t": float(ft[i]), "score": float(scores[i])})
            if len(per_video) >= limit * 3 and all(len(x) >= frames_per_video for x in per_video.values()):
                break

        ranked = []
        for v, fr in per_video.items():
            top = [f["score"] for f in fr]
            score = 0.7 * top[0] + 0.3 * (sum(top) / len(top))
            ranked.append((score, v, fr))
        ranked.sort(key=lambda x: -x[0])
        ranked = ranked[:limit]
        if not ranked:
            return []

        with db() as c:
            meta = {
                r["id"]: dict(r)
                for r in c.execute(
                    f"SELECT id, filename, duration, uploaded_by, created_at FROM videos WHERE id IN "
                    f"({','.join('?' * len(ranked))})",
                    [v for _, v, _ in ranked],
                )
            }
        # Turn raw CLIP similarity (~0.15-0.35) into a friendlier 0-100 match score relative to the best hit.
        best = ranked[0][0]
        out = []
        for score, v, fr in ranked:
            m = meta.get(v)
            if not m:
                continue
            rel = max(0.0, 1 - (best - score) / 0.08)
            if rel < 0.1:
                continue  # too weak to be a real match
            out.append({**m, "score": round(score, 4), "match": round(100 * rel), "frames": fr})
        return out


engine = Engine()
