"""Optional OpenAI features. Everything here is skipped when OPENAI_API_KEY is not set,
and every caller falls back to the free local behaviour if a request fails.

- understand(): turns a spoken/typed request (Chinese, English, Malay or mixed) into a precise
  English visual description for the vision model, plus a short version in the user's language.
- speak(): natural-sounding spoken replies (text-to-speech), cached on disk.

Only short text is sent to OpenAI (the request and the reply sentence), never videos or images.
"""
import hashlib
import json
import os
import threading
import time
import traceback
import urllib.error
import urllib.request

API = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
KEY = os.environ.get("OPENAI_API_KEY", "").strip()
CHAT_PREFS = [m for m in [os.environ.get("OPENAI_CHAT_MODEL")] if m] + ["gpt-4.1-mini", "gpt-4o-mini", "gpt-5-mini", "gpt-5-nano"]
TTS_PREFS = [m for m in [os.environ.get("OPENAI_TTS_MODEL")] if m] + ["gpt-4o-mini-tts", "tts-1"]
TTS_VOICE = os.environ.get("OPENAI_TTS_VOICE", "coral")
TIMEOUT = float(os.environ.get("OPENAI_TIMEOUT", "5"))
_down_until = [0.0]  # after a failure, skip OpenAI briefly so searches stay fast

_lock = threading.Lock()
_models = {"chat": None, "tts": None, "checked": 0.0, "error": None}
_cache = {}


def enabled():
    return bool(KEY) and time.time() >= _down_until[0]


def _failed(e, what):
    print(f"openai {what} failed:", _describe(e), flush=True)
    if not isinstance(e, urllib.error.HTTPError) or e.code >= 429:
        _down_until[0] = time.time() + 60


def _req(path, payload=None, method="POST", timeout=TIMEOUT, raw=False):
    data = json.dumps(payload).encode() if payload is not None else None
    r = urllib.request.Request(API + path, data=data, method=method, headers={
        "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        body = resp.read()
    return body if raw else json.loads(body)


def _pick_models():
    """Choose the first preferred model this account can use (checked at most every 6 hours)."""
    with _lock:
        if _models["checked"] and time.time() - _models["checked"] < 6 * 3600:
            return _models
        try:
            ids = {m["id"] for m in _req("/models", method="GET").get("data", [])}
            _models["chat"] = next((m for m in CHAT_PREFS if m in ids), None)
            _models["tts"] = next((m for m in TTS_PREFS if m in ids), None)
            _models["error"] = None if _models["chat"] else "no suitable chat model on this account"
        except Exception as e:  # bad key, network, ...
            _models["chat"] = _models["tts"] = None
            _models["error"] = _describe(e)
        _models["checked"] = time.time()
        return _models


def _describe(e):
    if isinstance(e, urllib.error.HTTPError):
        try:
            return f"HTTP {e.code}: " + json.loads(e.read()).get("error", {}).get("message", "")[:200]
        except Exception:
            return f"HTTP {e.code}"
    return str(e)[:200]


def status():
    if not KEY:
        return {"enabled": False}
    m = _pick_models()
    return {"enabled": True, "chat_model": m["chat"], "tts_model": m["tts"], "voice": TTS_VOICE, "error": m["error"]}


SYSTEM = """You help a company search its video library. A search engine compares an English text
description against video frames, so it needs a short description of what should be VISIBLE.

The user speaks Chinese, English or Malay, often mixed (Malaysian style), sometimes via imperfect
speech recognition. Reply with JSON only: {"visual": "...", "display": "...", "lang": "zh|en|ms"}

visual: natural English, only the things the user asked to see (objects, colours, patterns,
  materials, setting, people, actions, camera angle). Keep it as short as the request.
  NEVER add details the user did not say: no extra colours, settings, weather, adjectives or quality
  words. Drop filler such as "find me the video", "tolong cari", "帮我找", "老板要看", "lah".
  Fix obvious speech-recognition mistakes. If the request is not about visual content, use "".
display: the same subject in the user's own language, short, without words like video/视频/clip.
lang: the main language the user spoke.

Examples:
帮我找有沙发的视频 -> {"visual": "a sofa", "display": "沙发", "lang": "zh"}
老板要看那个有高楼大厦的video lah -> {"visual": "tall buildings", "display": "高楼大厦", "lang": "zh"}
tolong cari video lukisan air terjun -> {"visual": "a painting of a waterfall", "display": "lukisan air terjun", "lang": "ms"}
find me the clip with the blue velvet sofa bed with flowers -> {"visual": "a blue velvet sofa bed with a floral pattern", "display": "blue velvet sofa bed with a floral pattern", "lang": "en"}
仓库里堆着钢管的画面 -> {"visual": "steel pipes stacked in a warehouse", "display": "仓库里堆放的钢管", "lang": "zh"}"""


def understand(text):
    """-> {"visual": English description, "display": short native phrase, "lang": ...} or None."""
    if not enabled() or not text.strip():
        return None
    if text in _cache:
        return _cache[text]
    model = _pick_models()["chat"]
    if not model:
        return None
    payload = {"model": model, "response_format": {"type": "json_object"}, "max_completion_tokens": 300,
               "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text[:500]}]}
    if model.startswith("gpt-5"):
        payload["reasoning_effort"] = "minimal"
    try:
        out = _req("/chat/completions", payload)
        data = json.loads(out["choices"][0]["message"]["content"])
        res = {"visual": str(data.get("visual") or "").strip()[:300],
               "display": str(data.get("display") or "").strip()[:120],
               "lang": str(data.get("lang") or "")[:5]}
    except Exception as e:
        _failed(e, "understand")
        return None
    if len(_cache) > 2000:
        _cache.clear()
    _cache[text] = res
    return res


TTS_STYLE = {
    "zh": "用自然、亲切、专业的普通话说，像一位得力的私人助理。语速适中。",
    "ms": "Cakap dalam Bahasa Melayu Malaysia dengan nada mesra dan profesional, seperti pembantu peribadi.",
    "en": "Speak warmly and professionally, like a capable personal assistant. Natural, unhurried pace.",
}


def speak(text, lang, cache_dir):
    """-> path to an mp3 file, or None."""
    if not enabled() or not text.strip():
        return None
    model = _pick_models()["tts"]
    if not model:
        return None
    lang = (lang or "en")[:2]
    key = hashlib.sha256(f"{model}|{TTS_VOICE}|{lang}|{text}".encode()).hexdigest()[:32]
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, key + ".mp3")
    if os.path.exists(path):
        return path
    payload = {"model": model, "voice": TTS_VOICE, "input": text[:600], "response_format": "mp3"}
    if model != "tts-1":
        payload["instructions"] = TTS_STYLE.get(lang, TTS_STYLE["en"])
    try:
        audio = _req("/audio/speech", payload, raw=True, timeout=20)
    except Exception as e:
        _failed(e, "speech")
        return None
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(audio)
    os.replace(tmp, path)
    return path
