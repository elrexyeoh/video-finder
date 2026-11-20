# 🎬 Video Finder

A team website for finding videos by describing what's in them.

> "find me the videos with premium blue sofa beds with flowery patterns"

You get a ranked list of matching videos, with thumbnails of the exact moments that match.
Click a thumbnail and the video plays from that moment.

## What it does

- **Upload any video:** MP4, MOV, AVI, MKV, WMV, iPhone (HEVC) and more. Drag in hundreds at once.
  Videos a browser can't play are converted to standard MP4 automatically.
- **Search by description:** objects, colours, patterns, places, people, scenes.
  You can search in English, Bahasa Melayu, Chinese and 50+ other languages.
- **Team access:** everyone signs in with one shared team password and their name, so the
  library shows who uploaded what. It works on phones too.
- **No tagging needed:** the app "looks" at a frame every 2 seconds using an AI vision model
  (CLIP) that runs on the server. No per-search AI fees, and videos aren't sent to any AI company.

## How it works

1. When a video is uploaded, ffmpeg pulls out one frame every 2 seconds.
2. The CLIP model turns each frame into a list of numbers (an "embedding") describing what it shows.
   Near-identical frames are skipped.
3. When you search, your sentence is turned into numbers the same way. The frames whose numbers
   are closest to your sentence are the best matches. Results are grouped per video.

## Settings (environment variables)

| Variable | What it's for |
|---|---|
| `APP_PASSWORD` | **Required in the cloud.** The team password. Without it, anyone with the link gets in. |
| `SECRET_KEY` | Any long random string. Keeps people signed in across restarts. |
| `DATA_DIR` | Where videos and the index are stored (`/data` in Docker; mount a persistent disk there). |
| `SAMPLE_EVERY_SEC` | How often to grab a frame (default `2`). Lower means more precise but slower. |

## Run it on a computer (for testing)

Needs Python 3.10+ and ffmpeg.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
APP_PASSWORD=changeme python app.py
```

Then open http://localhost:8000.

## Put it in the cloud

The included `Dockerfile` works on any host that runs containers (Railway, Render, Fly.io,
Google Cloud Run with a volume, a VPS, ...). You need:

1. **A persistent volume mounted at `/data`.** This is where the videos live, so size it for
   your library (e.g. 1,000 videos × 200 MB ≈ 200 GB).
2. **About 2 GB of RAM and 1 or more CPUs.** Indexing a 5-minute video takes about 10–30 s on CPU.
3. `APP_PASSWORD` and `SECRET_KEY` set.

## Limits and ideas for later

- Search uses **what's visible**, not what's said. Speech search (auto-transcribing with
  Whisper) would be a good next addition.
- It understands broad visual concepts well (blue sofa, flower pattern, beach, office, car).
  It's weaker on fine detail like brand names or tiny text.
- One shared password suits a small team. For individual accounts or Google/Microsoft sign-in,
  put it behind a login service such as Cloudflare Access.
- For very large libraries (tens of thousands of videos or several TB), move video storage to
  an S3-style bucket.
