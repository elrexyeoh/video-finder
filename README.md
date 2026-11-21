# 🎬 Video Finder

A team website for finding videos by describing what's in them.

> "find me the videos with premium blue sofa beds with flowery patterns"

You get a ranked list of matching videos, with thumbnails of the exact moments that match.
Click a thumbnail and the video plays from that moment.

## What it does

- **Ask like you'd ask a colleague:** type or **speak** "find me the videos with a blue sofa bed with
  flower patterns". The assistant searches every scene, answers in plain language, and shows the
  matching videos with the exact moments. Tap a moment and the video plays from there.
- **Voice search** in English, Bahasa Melayu and Chinese (tap the language chip next to the mic).
  When you ask by voice, it also answers out loud in the same language.
- **Honest results:** if nothing in the library matches, it says so instead of showing random videos.
  Matches are labelled *Strong match* or *Possible match*.
- **Upload any video:** MP4, MOV, AVI, MKV, WMV, iPhone (HEVC) and more. Videos a browser can't play
  are converted to standard MP4 automatically.
- **Team access, mobile-first:** one shared team password, works on phones and desktops, and the
  first screen is always the assistant.

## How the AI search works

1. When a video is uploaded, ffmpeg takes one snapshot every 2 seconds.
2. A vision AI model, Google's **SigLIP** (multilingual), looks at each snapshot and stores a
   numeric "fingerprint" of what it shows. Near-identical snapshots are skipped.
3. Your request is cleaned up ("find me the videos where there are..." becomes "...") and turned
   into a fingerprint the same way.
4. SigLIP scores how likely each snapshot is to show what you asked for. Only snapshots above a
   calibrated confidence level count as matches, and results are grouped per video.

The model runs on your own server. Videos are never sent to an outside AI service, and there is no
per-search cost.

## Optional: OpenAI for smarter search and a natural voice

Add an `OPENAI_API_KEY` variable (Railway: service → Variables) and the app automatically:

- **Understands requests better:** an OpenAI model rewrites what was said, in Chinese, English,
  Malay or a mix, into a precise English scene description before searching. Without a key, a free
  local Chinese→English translator is used instead.
- **Speaks naturally:** replies use OpenAI's text-to-speech voice instead of the browser's built-in
  voice. Replies are cached, so repeated sentences cost nothing.

Only the short request text and reply sentence are sent to OpenAI, never videos or images. If
OpenAI is slow or unreachable, the app silently falls back to the free local behaviour.
Optional: `OPENAI_CHAT_MODEL`, `OPENAI_TTS_MODEL`, `OPENAI_TTS_VOICE` (default `coral`).

## Optional: import videos from Lark Base (多维表格)

Admins can paste a Lark Base link on the Upload page. The app imports every video attachment,
keeps the row's other columns (product name, category, notes…) as searchable details, and
re-syncs every hour (`LARK_SYNC_MINUTES`). It only reads from Lark; nothing in Lark is changed.
Deleting an imported video in the app keeps it from being re-imported.

One-time setup in the Lark developer console (open.larksuite.com → Developer Console):
1. **Create Custom App** (企业自建应用). Name it e.g. "Video Finder".
2. **Permissions & Scopes:** add `bitable:app:readonly` (read Base), `docs:document.media:download`
   (download attachments) and, if your Base lives inside a Wiki, `wiki:wiki:readonly`.
3. **Version Management & Release:** create a version and publish it. Your Lark admin may need to approve it.
4. Copy the **App ID** and **App Secret** (Credentials & Basic Info) into Railway Variables as
   `LARK_APP_ID` and `LARK_APP_SECRET`.
5. Open the Base in Lark → **···** (top right) → **More** → **Add document app** (添加文档应用) →
   choose the app. If the Base uses advanced permissions, also give the app a role that can view the table.
6. In Video Finder: Upload → *Import from Lark Base* → paste the Base link → *Connect & import*.

## Settings (environment variables)

| Variable | What it's for |
|---|---|
| `APP_PASSWORD` | **Required in the cloud.** The team password. Without it, anyone with the link gets in. |
| `SECRET_KEY` | Any long random string. Keeps people signed in across restarts. |
| `DATA_DIR` | Where videos and the index are stored (`/data` in Docker; mount a persistent disk there). |
| `SAMPLE_EVERY_SEC` | How often to grab a frame (default `2`). Lower means more precise but slower. |
| `MATCH_MINIMUM` / `MATCH_STRONG` | Confidence cut-offs (defaults `-10` / `-7.5`). Raise them to show fewer, surer results. |

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
2. **About 3 GB of RAM and 2 or more CPUs.** Analysing a 5-minute video takes roughly 20–60 s on CPU.
3. `APP_PASSWORD` and `SECRET_KEY` set.

## Limits and ideas for later

- Search uses **what's visible**, not what's said. Speech search (auto-transcribing with
  Whisper) would be a good next addition.
- It understands visual concepts well (sofa, colours, patterns, factory, beach, people presenting).
  It's weaker on fine detail like brand names, tiny text or exact counts.
- Voice search uses the browser's built-in speech recognition (Chrome, Edge and Safari; not Firefox).
- One shared password suits a small team. For individual accounts or Google/Microsoft sign-in,
  put it behind a login service such as Cloudflare Access.
- For very large libraries (tens of thousands of videos or several TB), move video storage to
  an S3-style bucket.
