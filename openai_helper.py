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
import re
import threading
import time
import traceback
import urllib.error
import urllib.request

API = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
KEY = os.environ.get("OPENAI_API_KEY", "").strip()
CHAT_PREFS = [m for m in [os.environ.get("OPENAI_CHAT_MODEL")] if m] + ["gpt-4.1-mini", "gpt-4o-mini", "gpt-5-mini", "gpt-5-nano"]
TTS_PREFS = [m for m in [os.environ.get("OPENAI_TTS_MODEL")] if m] + ["gpt-4o-mini-tts", "tts-1"]
STT_PREFS = [m for m in [os.environ.get("OPENAI_STT_MODEL")] if m] + ["gpt-4o-transcribe", "gpt-4o-mini-transcribe", "whisper-1"]
TTS_VOICE = os.environ.get("OPENAI_TTS_VOICE", "coral")
TIMEOUT = float(os.environ.get("OPENAI_TIMEOUT", "5"))
_down_until = [0.0]  # after a failure, skip OpenAI briefly so searches stay fast

_lock = threading.Lock()
_models = {"chat": None, "tts": None, "stt": None, "checked": 0.0, "error": None}
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
            _models["stt"] = next((m for m in STT_PREFS if m in ids), None)
            _models["error"] = None if _models["chat"] else "no suitable chat model on this account"
        except Exception as e:  # bad key, network, ...
            _models["chat"] = _models["tts"] = _models["stt"] = None
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
    return {"enabled": True, "chat_model": m["chat"], "tts_model": m["tts"], "stt_model": m["stt"], "voice": TTS_VOICE,
            "error": m["error"]}


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


STT_PROMPT = {
    "zh": "这是马来西亚同事在视频库里找视频的语音，可能夹杂中文、英文和马来语，例如：帮我找浮雕壁画室内设计的视频、不锈钢厨房、星空房。",
    "ms": "Permintaan suara untuk mencari video, mungkin bercampur Bahasa Melayu, Inggeris dan Cina.",
    "en": "A spoken request to find a video in a company library; may mix English, Chinese and Malay.",
}


def transcribe(audio, filename, mime, lang):
    """Speech -> text with OpenAI. Returns the text ('' if nothing was said) or None on failure."""
    if not enabled() or not audio:
        return None
    model = _pick_models()["stt"]
    if not model:
        return None
    boundary = "----vf" + hashlib.sha1(os.urandom(8)).hexdigest()
    fields = {"model": model, "prompt": STT_PROMPT.get((lang or "zh")[:2], STT_PROMPT["zh"]), "response_format": "json"}
    body = b""
    for k, v in fields.items():
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
             f"Content-Type: {mime}\r\n\r\n").encode() + audio + f"\r\n--{boundary}--\r\n".encode()
    r = urllib.request.Request(API + "/audio/transcriptions", data=body, method="POST", headers={
        "Authorization": f"Bearer {KEY}", "Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            return (json.loads(resp.read()).get("text") or "").strip()
    except Exception as e:
        _failed(e, "transcribe")
        return None


PRODUCT_SYSTEM = """You identify products in short supplier/marketing videos for a Malaysian company's sourcing team.
You get a few frames from one video and, if available, the row from their product table.
Reply with JSON only:
{"name_zh": "...", "name_en": "...", "keywords_zh": ["..."], "keywords_en": ["..."], "category_zh": "...",
 "material": "...", "features_zh": "...", "summary_zh": "..."}
name_*: the product as a buyer would search for it on 1688 / Alibaba (specific, no brand unless clearly shown).
keywords_*: 3-6 search phrases, most specific first (type + material + key feature), as used on 1688 (zh) and Alibaba.com (en).
features_zh: notable specs/features visible or stated (size, material, function), one short sentence. "" if unknown.
summary_zh: one sentence describing the product for the boss.
Base it on what is visible plus the table info; don't invent specs."""


def describe_product(images, table_info):
    """images: list of JPEG bytes. -> dict or None."""
    import base64
    if not enabled():
        return None
    model = _pick_models()["chat"]
    if not model:
        return None
    content = [{"type": "text", "text": "Product table info: " + (json.dumps(table_info, ensure_ascii=False) if table_info else "(none)")}]
    for im in images[:4]:
        content.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(im).decode(), "detail": "low"}})
    payload = {"model": model, "response_format": {"type": "json_object"}, "max_completion_tokens": 600,
               "messages": [{"role": "system", "content": PRODUCT_SYSTEM}, {"role": "user", "content": content}]}
    if model.startswith("gpt-5"):
        payload["reasoning_effort"] = "minimal"
    try:
        out = _req("/chat/completions", payload, timeout=40)
        data = json.loads(out["choices"][0]["message"]["content"])
    except Exception as e:
        _failed(e, "describe")
        return None
    clean = lambda v, n: [str(x).strip()[:60] for x in (v or []) if str(x).strip()][:n]
    return {"name_zh": str(data.get("name_zh", ""))[:80], "name_en": str(data.get("name_en", ""))[:80],
            "keywords_zh": clean(data.get("keywords_zh"), 6), "keywords_en": clean(data.get("keywords_en"), 6),
            "category_zh": str(data.get("category_zh", ""))[:60], "material": str(data.get("material", ""))[:80],
            "features_zh": str(data.get("features_zh", ""))[:200], "summary_zh": str(data.get("summary_zh", ""))[:200]}


RESEARCH_MODEL_PREFS = [m for m in [os.environ.get("OPENAI_RESEARCH_MODEL")] if m] + ["gpt-4.1", "gpt-4o", "gpt-4.1-mini", "gpt-4o-mini"]
RESEARCH_PROMPT = """Find real suppliers / manufacturers for this product so a Malaysian buyer can contact them.
Product: {name_zh} / {name_en}
Details: {details}
Search terms to try: {keywords}

Search the web (1688, Alibaba.com, Made-in-China, Global Sources, manufacturers' own sites, Malaysian suppliers).
Prefer manufacturers/factories and suppliers that sell this exact kind of product. Return 5-10 of the best.
Reply with ONLY a JSON object (no markdown):
{{"summary_zh": "<2 sentences in Chinese for the boss: what you found, e.g. 主要产地、大致价格区间>",
  "suppliers": [{{"name": "<company name, original language>", "location": "<city, country>",
    "type": "<厂家/贸易商/平台店铺/manufacturer...>", "products": "<what they sell, short>",
    "price": "<price hint with currency and unit if published, else empty>", "moq": "<minimum order if published>",
    "url": "<the page you found them on>", "contact": "<public phone/email/WeChat if shown, else empty>",
    "why_zh": "<one short Chinese sentence: why this matches>"}}]}}
Only include suppliers you actually found in search results, with their real URL. Never invent contact details."""


def research_suppliers(product):
    """Web research with OpenAI's web search tool. -> dict {summary_zh, suppliers[], sources[]} or raises."""
    if not enabled():
        raise RuntimeError("OpenAI is not configured")
    ids = None
    try:
        ids = {m["id"] for m in _req("/models", method="GET").get("data", [])}
    except Exception:
        pass
    model = next((m for m in RESEARCH_MODEL_PREFS if not ids or m in ids), "gpt-4.1-mini")
    prompt = RESEARCH_PROMPT.format(
        name_zh=product.get("name_zh", ""), name_en=product.get("name_en", ""),
        details="; ".join(x for x in [product.get("category_zh"), product.get("material"), product.get("features_zh")] if x) or "-",
        keywords=", ".join((product.get("keywords_zh") or [])[:3] + (product.get("keywords_en") or [])[:3]))
    last = None
    for tool in ("web_search", "web_search_preview"):
        try:
            out = _req("/responses", {"model": model, "tools": [{"type": tool}], "input": prompt,
                                      "max_output_tokens": 3000}, timeout=150)
            break
        except urllib.error.HTTPError as e:
            last = e
            if e.code != 400:
                raise RuntimeError(_describe(e))
    else:
        raise RuntimeError(_describe(last) if last else "web search unavailable")
    text, sources = "", []
    for item in out.get("output", []):
        for c in item.get("content", []) or []:
            if c.get("type") == "output_text":
                text += c.get("text", "")
                for a in c.get("annotations", []) or []:
                    if a.get("type") == "url_citation" and a.get("url"):
                        sources.append({"title": a.get("title", "")[:120], "url": a["url"]})
    m = re.search(r"\{.*\}", text, re.S)
    data = {}
    if m:
        try:
            data = json.loads(m.group(0))
        except ValueError:
            data = {}
    sups = []
    for x in data.get("suppliers", []) if isinstance(data.get("suppliers"), list) else []:
        if not isinstance(x, dict) or not x.get("name"):
            continue
        url = str(x.get("url", ""))
        sups.append({k: str(x.get(k, ""))[:300] for k in ("name", "location", "type", "products", "price", "moq", "contact", "why_zh")}
                    | {"url": url if url.startswith("http") else ""})
    seen, uniq = set(), []
    for s_ in sources:
        if s_["url"] not in seen:
            seen.add(s_["url"]); uniq.append(s_)
    return {"summary_zh": str(data.get("summary_zh", ""))[:400] or (text[:400] if not sups else ""),
            "suppliers": sups[:10], "sources": uniq[:12], "model": model}
