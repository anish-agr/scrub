"""Reading engine (OCR): count sheets, tray tags and sterile pack labels.

Each reader returns structured JSON plus "method" ("qr", "perceptron", "gemini" or null), "latency_ms", "ok",
"error" and "attempts" (one entry per backend tried). Order: QR (tray tags only), then Perceptron OCR
(chat completions on perceptron-mk1.5 with a strict json_schema), then Gemini structured output. A backend
that errors, times out, or returns JSON that does not validate hands over to the next one.

Item ids always come from the setting: the schemas only allow the setting's ids (plus "other"), and every
answer is matched again here against ids, names and aliases. Anything that does not match is dropped.
"""

from __future__ import annotations

import base64
import calendar
import datetime as dt
import difflib
import json
import os
import re
import time
from pathlib import Path

import cv2
import httpx
import numpy as np

from vision.geometry import normalize_label
from vision.tray import item_labels

ROOT = Path(__file__).resolve().parent.parent
PERCEPTRON_CHAT_URL = "https://api.perceptron.inc/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
QR_PREFIX = "scrub:tray:"
OTHER = "other"  # schema value for "not one of the listed ids"; never returned as an item or tray


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


# ---------------------------------------------------------------- settings

def known_settings(repo: Path = ROOT) -> list[str]:
    """Setting ids from settings/*.json, without the *.local.json alias overlays."""
    return sorted(p.stem for p in (repo / "settings").glob("*.json") if not p.name.endswith(".local.json"))


def load_setting_merged(repo: Path, setting_id: str) -> dict:
    """settings/<id>.json with <id>.local.json aliases merged in (the controller does the same)."""
    doc = json.loads((repo / "settings" / f"{setting_id}.json").read_text(encoding="utf-8"))
    local = repo / "settings" / f"{setting_id}.local.json"
    if local.exists():
        try:
            extra = json.loads(local.read_text(encoding="utf-8")).get("aliases") or {}
        except (OSError, ValueError):
            extra = {}
        for item in doc.get("items") or []:
            words = [w.lower() for w in extra.get(item["id"]) or [] if isinstance(w, str)]
            item["aliases"] = list(dict.fromkeys((item.get("aliases") or []) + words))
    return doc


def setting_labels(repo: Path, settings: list[str]) -> dict[str, str]:
    """{setting id: its "label"}, e.g. {"surgical": "Operating room"}, for matching a printed tray name."""
    labels = {}
    for sid in settings:
        try:
            labels[sid] = json.loads((repo / "settings" / f"{sid}.json").read_text(encoding="utf-8")).get("label", "")
        except (OSError, ValueError):
            pass
    return labels


def item_ids(setting: dict) -> list[str]:
    return [i["id"] for i in setting.get("items") or []]


# ---------------------------------------------------------------- matching and parsing (pure)

def _clean(text: str) -> str:
    text = re.sub(r"\(.*?\)|\[.*?\]", " ", str(text or ""))
    text = re.sub(r"[^a-z0-9 _-]", " ", text.lower())
    return normalize_label(text)


def match_name(text: str, setting: dict) -> str | None:
    """Printed or handwritten name -> item id from this setting, or None. Never invents an id.

    Exact id, name or alias first (case, spaces, underscores and hyphens ignored; also without a trailing "s"),
    then the longest label found as whole words inside the text ("Kelly hemostat 14 cm"), then a close spelling
    (difflib ratio 0.85, for OCR slips like "hemostatt").
    """
    raw = normalize_label(str(text or ""))
    key = _clean(text)
    if not key and not raw:
        return None
    labels = [(label, item["id"]) for item in setting.get("items") or [] for label in item_labels(item) if label]
    for candidate in (raw, key, key.rstrip("s")):
        for label, iid in labels:
            if candidate and (candidate == label or candidate == label.rstrip("s")):
                return iid
    padded = f" {key} "
    inside = [(len(label), iid) for label, iid in labels if len(label) >= 4 and f" {label} " in padded]
    if inside:
        best = max(inside)[0]
        ids = {iid for n, iid in inside if n == best}
        if len(ids) == 1:
            return ids.pop()
    close = difflib.get_close_matches(key, [label for label, _ in labels], n=2, cutoff=0.85)
    if close:
        ids = {iid for label, iid in labels if label == close[0]}
        if len(ids) == 1:
            return ids.pop()
    return None


def match_tray(text: str, settings: list[str], labels: dict[str, str] | None = None) -> str | None:
    """Tray tag text or QR payload -> a known setting id ("scrub:tray:bench", "BENCH", "Robotics bench")."""
    words = _clean(str(text or "").replace(":", " "))
    if not words:
        return None
    padded = f" {words} "
    for sid in settings:
        if f" {sid} " in padded:
            return sid
    for sid, label in (labels or {}).items():
        lab = _clean(label)
        if sid in settings and lab and f" {lab} " in padded:
            return sid
    return None


def qr_payload_tray(payload: str, settings: list[str]) -> str | None:
    text = str(payload or "").strip()
    if text.lower().startswith(QR_PREFIX):
        sid = text[len(QR_PREFIX):].strip().lower()
        return sid if sid in settings else None
    return text.lower() if text.lower() in settings else None


MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_name) if m})
MONTHS["sept"] = 9


def _ymd(y: int, m: int, d: int | None) -> str | None:
    if y < 100:
        y += 2000
    if not (2000 <= y <= 2100 and 1 <= m <= 12):
        return None
    last = calendar.monthrange(y, m)[1]
    d = last if d is None else d  # a month-only expiry ("2026-11", "11/2026") runs to the end of that month
    if not 1 <= d <= last:
        return None
    return f"{y:04d}-{m:02d}-{d:02d}"


def parse_date(text) -> str | None:
    """A printed date -> "YYYY-MM-DD", or None. Numeric dates are read US style (MM/DD) unless the first
    number is over 12. Handles 2026-10-18, 2026/10/18, 10/18/2026, 10/18/26, 18 Oct 2026, Oct 18, 2026,
    OCT-18-2026, 2026-11 and 11/2026."""
    if text is None:
        return None
    s = str(text).strip().lower().replace(",", " ").replace(".", "/")
    if not s:
        return None
    m = re.search(r"\b(\d{4})[-/ ](\d{1,2})[-/ ](\d{1,2})\b", s)
    if m:
        return _ymd(int(m[1]), int(m[2]), int(m[3]))
    m = re.search(r"\b(\d{1,2})[-/ ](\d{1,2})[-/ ](\d{4}|\d{2})\b", s)
    if m:
        a, b, y = int(m[1]), int(m[2]), int(m[3])
        mon, day = (b, a) if a > 12 else (a, b)
        return _ymd(y, mon, day)
    m = re.search(r"\b(\d{1,2})[-/ ]+([a-z]{3,9})[-/ ]+(\d{4}|\d{2})\b", s)
    if m and m[2] in MONTHS:
        return _ymd(int(m[3]), MONTHS[m[2]], int(m[1]))
    m = re.search(r"\b([a-z]{3,9})[-/ ]+(\d{1,2})[-/ ]+(\d{4})\b", s)
    if m and m[1] in MONTHS:
        return _ymd(int(m[3]), MONTHS[m[1]], int(m[2]))
    m = re.search(r"\b(\d{4})[-/](\d{1,2})\b", s)
    if m:
        return _ymd(int(m[1]), int(m[2]), None)
    m = re.search(r"\b(\d{1,2})[-/](\d{4})\b", s)
    if m:
        return _ymd(int(m[2]), int(m[1]), None)
    m = re.search(r"\b([a-z]{3,9})[-/ ]+(\d{4})\b", s)
    if m and m[1] in MONTHS:
        return _ymd(int(m[2]), MONTHS[m[1]], None)
    return None


def is_expired(expires: str | None, today: dt.date | str) -> bool:
    """True when the expiry date is before today. A pack is still good on its expiry date."""
    if not expires:
        return False
    if isinstance(today, str):
        today = dt.date.fromisoformat(today)
    return dt.date.fromisoformat(expires) < today


def parse_count(value) -> int | None:
    """A count cell -> int 0..999, or None when blank or unreadable."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        n = int(value)
        return n if float(value) == n and 0 <= n <= 999 else None
    m = re.fullmatch(r"\s*(\d{1,3})\s*", str(value))
    return int(m[1]) if m else None


# ---------------------------------------------------------------- images

def to_bgr(img) -> np.ndarray:
    """JPEG or PNG bytes, or a BGR array -> BGR array."""
    if isinstance(img, np.ndarray):
        return img
    data = np.frombuffer(bytes(img), np.uint8)
    bgr = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
    if bgr is None:
        raise ValueError("not a readable image")
    return bgr


def downscale(bgr: np.ndarray, long_side: int) -> np.ndarray:
    h, w = bgr.shape[:2]
    if long_side and max(h, w) > long_side:
        s = long_side / float(max(h, w))
        bgr = cv2.resize(bgr, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA)
    return bgr


def jpeg_for_upload(img, long_side: int | None = None) -> bytes:
    long_side = int(_env_float("READ_MAX_SIDE", 1600)) if long_side is None else long_side
    ok, buf = cv2.imencode(".jpg", downscale(to_bgr(img), long_side), [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    if not ok:
        raise ValueError("could not encode image")
    return buf.tobytes()


def decode_qr(bgr: np.ndarray) -> list[str]:
    """Every QR payload OpenCV finds, trying the image as is and then a 1600 px copy."""
    det = cv2.QRCodeDetector()
    found: list[str] = []
    for img in (bgr, downscale(bgr, 1600)):
        try:
            ok, texts, _pts, _ = det.detectAndDecodeMulti(img)
        except cv2.error:
            ok, texts = False, ()
        if ok:
            found.extend(t for t in texts if t)
        if not found:
            try:
                text, _pts, _ = det.detectAndDecode(img)
            except cv2.error:
                text = ""
            if text:
                found.append(text)
        if found:
            break
    return list(dict.fromkeys(found))


# ---------------------------------------------------------------- backends

class PerceptronOCR:
    """Perceptron OCR: POST /v1/chat/completions on perceptron-mk1.5 with response_format json_schema, strict.

    This is the request docs.perceptron.inc/perceptron-mk1.5/capabilities/ocr documents (checked Oct 18, 2026);
    there is no separate OCR endpoint. The image goes in as an image_url data URL.
    """

    name = "perceptron"

    def __init__(self, api_key: str, timeout: float | None = None, model: str | None = None,
                 reasoning: str | None = None, client=None, url: str = PERCEPTRON_CHAT_URL):
        self.api_key = api_key
        # Measured Oct 18 on 1100 to 1540 px renders: 0.5 to 1.1 s at reasoning "none", 1.0 to 2.2 s at "low".
        self.timeout = timeout if timeout is not None else _env_float("READ_PERCEPTRON_TIMEOUT_S", 8.0)
        self.model = model or os.environ.get("PERCEPTRON_OCR_MODEL") or "perceptron-mk1.5"
        self.reasoning = reasoning or os.environ.get("READ_PERCEPTRON_REASONING") or "low"
        self.url = url
        self.client = client

    def extract(self, jpeg: bytes, prompt: str, schema: dict, schema_name: str) -> dict:
        if not self.api_key:
            raise RuntimeError("PERCEPTRON_API_KEY is empty")
        data_url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": data_url}},
                {"type": "text", "text": prompt},
            ]}],
            "reasoning_effort": self.reasoning,
            "max_completion_tokens": 2048,
            "temperature": 0,
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": schema_name, "strict": True, "schema": schema}},
        }
        client = self.client or httpx
        r = client.post(self.url, json=payload, headers={"Authorization": f"Bearer {self.api_key}"}, timeout=self.timeout)
        if r.status_code != 200:
            raise RuntimeError(f"Perceptron HTTP {r.status_code}")
        body = r.json()
        if body.get("error"):
            raise RuntimeError("Perceptron error: " + str((body["error"] or {}).get("message", ""))[:120])
        choice = (body.get("choices") or [{}])[0]
        if choice.get("finish_reason") not in (None, "stop"):
            raise RuntimeError(f"Perceptron finish_reason {choice.get('finish_reason')}")
        content = (choice.get("message") or {}).get("content") or ""
        if isinstance(content, list):  # content parts
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        return _loads(content)


def gemini_schema(schema: dict) -> dict:
    """JSON Schema (as sent to Perceptron) -> Gemini responseSchema (OpenAPI subset, upper-case types)."""
    out: dict = {}
    typ = schema.get("type")
    nullable = False
    if isinstance(typ, list):
        nullable = "null" in typ
        typ = next(t for t in typ if t != "null")
    if typ:
        out["type"] = typ.upper()
    if nullable:
        out["nullable"] = True
    if "enum" in schema:
        out["enum"] = [v for v in schema["enum"] if v is not None]
    if "description" in schema:
        out["description"] = schema["description"]
    if "properties" in schema:
        out["properties"] = {k: gemini_schema(v) for k, v in schema["properties"].items()}
        out["required"] = list(schema.get("required") or [])
        out["propertyOrdering"] = list(schema["properties"])
    if "items" in schema:
        out["items"] = gemini_schema(schema["items"])
    return out


class GeminiOCR:
    """Gemini generateContent with responseMimeType application/json and a responseSchema (enums for ids)."""

    name = "gemini"

    def __init__(self, api_key: str, timeout: float | None = None, model: str | None = None, client=None):
        self.api_key = api_key
        # Measured Oct 18: 1.7 to 2.9 s, one call 12.1 s.
        self.timeout = timeout if timeout is not None else _env_float("READ_GEMINI_TIMEOUT_S", 15.0)
        self.model = model or os.environ.get("GEMINI_MODEL") or "gemini-3.5-flash-lite"
        self.client = client

    def extract(self, jpeg: bytes, prompt: str, schema: dict, schema_name: str) -> dict:
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY is empty")
        body = {
            "contents": [{"parts": [
                {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(jpeg).decode("ascii")}},
                {"text": prompt},
            ]}],
            "generationConfig": {"responseMimeType": "application/json", "responseSchema": gemini_schema(schema),
                                 "temperature": 0},
        }
        client = self.client or httpx
        r = client.post(GEMINI_URL.format(model=self.model), json=body,
                        headers={"x-goog-api-key": self.api_key}, timeout=self.timeout)
        if r.status_code != 200:
            raise RuntimeError(f"Gemini HTTP {r.status_code}")
        try:
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            raise RuntimeError("Gemini returned no text") from None
        return _loads(text)


def _loads(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\s*|\s*```$", "", text)
    try:
        data = json.loads(text)
    except ValueError:
        raise ValueError("answer is not JSON") from None
    if not isinstance(data, dict):
        raise ValueError("answer is not a JSON object")
    return data


def default_backends() -> list:
    """Perceptron then Gemini, each only when its key is set (keys come from the environment / .env)."""
    out = []
    if os.environ.get("PERCEPTRON_API_KEY", "").strip():
        out.append(PerceptronOCR(os.environ["PERCEPTRON_API_KEY"].strip()))
    if os.environ.get("GEMINI_API_KEY", "").strip():
        out.append(GeminiOCR(os.environ["GEMINI_API_KEY"].strip()))
    return out


def _short(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    return f"{type(exc).__name__}: {str(exc)[:120]}"


def run_backends(backends, jpeg: bytes, prompt: str, schema: dict, schema_name: str, validate) -> dict:
    """Try each backend in order. validate(raw) returns the result fields or raises ValueError.
    The first one that answers and validates wins."""
    attempts = []
    for b in backends:
        started = time.perf_counter()
        try:
            fields = validate(b.extract(jpeg, prompt, schema, schema_name))
            ms = round((time.perf_counter() - started) * 1000)
            attempts.append({"method": b.name, "ok": True, "latency_ms": ms, "error": None})
            total = sum(a["latency_ms"] for a in attempts)  # the whole read; each method's time is in attempts
            return {**fields, "method": b.name, "latency_ms": total, "ok": True, "error": None, "attempts": attempts}
        except Exception as exc:  # noqa: BLE001 - any failure hands over to the next backend
            ms = round((time.perf_counter() - started) * 1000)
            attempts.append({"method": b.name, "ok": False, "latency_ms": ms, "error": _short(exc)})
    error = "; ".join(f"{a['method']}: {a['error']}" for a in attempts) if attempts else "no OCR backend (no API key set)"
    return {"method": None, "latency_ms": sum(a["latency_ms"] for a in attempts), "ok": False, "error": error,
            "attempts": attempts}


# ---------------------------------------------------------------- count sheet

def _id_enum(ids: list[str]) -> dict:
    return {"type": "string", "enum": list(ids) + [OTHER]}


def count_sheet_schema(setting: dict, settings: list[str]) -> dict:
    row = {"type": "object", "properties": {
        "item": _id_enum(item_ids(setting)),
        "printed_name": {"type": "string"},
        "expected": {"type": ["integer", "null"]},
        "initial": {"type": ["integer", "null"]},
        "closing": {"type": ["integer", "null"]},
    }, "required": ["item", "printed_name", "expected", "initial", "closing"], "additionalProperties": False}
    return {"type": "object", "properties": {
        "tray": _id_enum(settings),
        "tray_text": {"type": "string"},
        "items": {"type": "array", "items": row},
    }, "required": ["tray", "tray_text", "items"], "additionalProperties": False}


def count_sheet_prompt(setting: dict, settings: list[str]) -> str:
    names = "; ".join(f"{i['id']} = {i.get('name', i['id'])}" + (f" (also: {', '.join(i.get('aliases') or [])})" if i.get("aliases") else "")
                      for i in setting.get("items") or [])
    return (
        "This is a printed surgical instrument count sheet. Some numbers are handwritten. "
        f"Read the tray name at the top. tray must be one of: {', '.join(settings)}; use \"other\" if none fits. "
        "tray_text is the tray name exactly as printed. "
        "Return one entry per instrument row in reading order. item must be one of these ids, matching the "
        f"printed name: {names}. Use \"other\" for a row that is none of them. printed_name is the row's name "
        "exactly as printed. expected is the printed expected quantity. initial and closing are the numbers "
        "written in the initial count and closing count columns, usually by hand. Use null for an empty or "
        "unreadable cell. Do not guess numbers and do not add rows that are not on the sheet. If the image is "
        "not a count sheet, return an empty items array and tray \"other\"."
    )


def validate_count_sheet(raw: dict, setting: dict, settings: list[str], labels: dict | None = None) -> dict:
    rows = raw.get("items")
    if not isinstance(rows, list):
        raise ValueError("items is not a list")
    by_id = {i["id"]: i for i in setting.get("items") or []}
    items, dropped, seen = [], [], set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        printed = str(row.get("printed_name") or "")
        # The printed name decides. The model's id is used only when it printed no name.
        iid = match_name(printed, setting) if printed.strip() else (row.get("item") if row.get("item") in by_id else None)
        if iid is None or iid in seen:
            dropped.append(printed or str(row.get("item")))
            continue
        seen.add(iid)
        items.append({"item": iid, "name": by_id[iid].get("name", iid), "printed_name": printed or None,
                      "expected": parse_count(row.get("expected")), "initial": parse_count(row.get("initial")),
                      "closing": parse_count(row.get("closing"))})
    if not items:
        raise ValueError("no row matched an item of this setting")
    tray = raw.get("tray") if raw.get("tray") in settings else None
    tray = match_tray(raw.get("tray_text") or "", settings, labels) or tray
    return {"tray": tray, "tray_text": raw.get("tray_text") or None, "items": items, "dropped": dropped}


def read_count_sheet(img, setting: dict, backends=None, repo: Path = ROOT) -> dict:
    """Photo of a count sheet -> {"tray", "items": [{"item", "name", "expected", "initial", "closing"}], ...}."""
    settings = known_settings(repo)
    labels = setting_labels(repo, settings)
    jpeg = jpeg_for_upload(img)
    result = run_backends(default_backends() if backends is None else backends, jpeg,
                          count_sheet_prompt(setting, settings), count_sheet_schema(setting, settings), "count_sheet",
                          lambda raw: validate_count_sheet(raw, setting, settings, labels))
    result.setdefault("tray", None)
    result.setdefault("items", [])
    result["setting"] = setting.get("id")
    return result


# ---------------------------------------------------------------- tray tag

def tray_tag_schema(settings: list[str]) -> dict:
    return {"type": "object", "properties": {"tray": _id_enum(settings), "text": {"type": "string"}},
            "required": ["tray", "text"], "additionalProperties": False}


def read_tray_tag(img, backends=None, repo: Path = ROOT) -> dict:
    """QR first (payload "scrub:tray:<id>"), then OCR of the printed tag. Only known setting ids."""
    settings = known_settings(repo)
    labels = setting_labels(repo, settings)
    bgr = to_bgr(img)
    started = time.perf_counter()
    payloads = decode_qr(bgr)
    qr_ms = round((time.perf_counter() - started) * 1000)
    for p in payloads:
        sid = qr_payload_tray(p, settings)
        if sid:
            return {"tray": sid, "text": p, "qr": payloads, "method": "qr", "latency_ms": qr_ms, "ok": True,
                    "error": None, "attempts": [{"method": "qr", "ok": True, "latency_ms": qr_ms, "error": None}]}

    def validate(raw: dict) -> dict:
        # The tray comes only from the verbatim text, matched here, and the text must say "tray". Live, Oct 18: with
        # the tray names in the prompt, a frame with instruments and no tag came back "Surgical", then "Surgical Tray".
        text = str(raw.get("text") or "")
        if not re.search(r"\btray\b", text, re.I):
            raise ValueError("no tray tag text")
        tray = match_tray(text, settings, labels)
        if tray is None:
            raise ValueError("no known tray on the tag")
        return {"tray": tray, "text": text}

    # A plain transcription: the prompt names no trays, so the model has nothing to echo.
    prompt = ("Transcribe all printed text visible in the image exactly as it appears, as text. If there is no "
              "printed text, return an empty string. Do not describe the image. Set tray to \"other\".")
    result = run_backends(default_backends() if backends is None else backends, jpeg_for_upload(bgr), prompt,
                          tray_tag_schema(settings), "tray_tag", validate)
    result["attempts"].insert(0, {"method": "qr", "ok": False, "latency_ms": qr_ms,
                                  "error": "unknown payload" if payloads else "no QR code"})
    result["latency_ms"] += qr_ms
    result.setdefault("tray", None)
    result.setdefault("text", None)
    result["qr"] = payloads
    return result


# ---------------------------------------------------------------- pack label

def pack_label_schema(setting: dict) -> dict:
    s_or_null = {"type": ["string", "null"]}
    label = {"type": "object", "properties": {
        "item": _id_enum(item_ids(setting)),
        "item_text": {"type": "string"},
        "lot": s_or_null, "sterilized": s_or_null, "expires": s_or_null, "indicator_text": s_or_null,
    }, "required": ["item", "item_text", "lot", "sterilized", "expires", "indicator_text"], "additionalProperties": False}
    return {"type": "object", "properties": {"labels": {"type": "array", "items": label}},
            "required": ["labels"], "additionalProperties": False}


def pack_label_prompt(setting: dict) -> str:
    names = "; ".join(f"{i['id']} = {i.get('name', i['id'])}" for i in setting.get("items") or [])
    return (
        "This is a sterile instrument pack label. Return one entry per label in the image. item_text is the "
        f"instrument name exactly as printed. item is its id, one of: {names}; use \"other\" if it is none of "
        "them. lot is the lot or load number as printed. sterilized is the sterilization or processed date and "
        "expires the expiry or use-by date, each exactly as printed. indicator_text is the printed text on or "
        "next to the sterilization indicator (for example \"STERILIZED\" or \"CHANGES COLOR WHEN PROCESSED\"). "
        "Use null for a field that is missing or unreadable. Do not guess. If there is no printed pack label in "
        "the image, return an empty labels array; never make up text."
    )


def validate_pack_label(raw: dict, setting: dict, today) -> dict:
    rows = raw.get("labels")
    if not isinstance(rows, list):
        raise ValueError("labels is not a list")
    labels = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        # A label must name its contents. On a frame with no label at all, Perceptron once answered
        # item_text "null" with a made-up lot and dates; requiring a printed name drops that.
        text = _s(row.get("item_text"))
        if not text:
            continue
        exp = parse_date(row.get("expires"))
        labels.append({"item": match_name(text, setting), "item_text": text, "lot": _s(row.get("lot")),
                       "sterilized": parse_date(row.get("sterilized")), "expires": exp,
                       "sterilized_text": _s(row.get("sterilized")), "expires_text": _s(row.get("expires")),
                       "indicator_text": _s(row.get("indicator_text")), "expired": is_expired(exp, today)})
    if not labels:
        raise ValueError("no label read")
    return {"labels": labels, "expired": any(lab["expired"] for lab in labels)}


NULL_WORDS = {"", "null", "none", "n/a", "na", "unknown", "unreadable", "-", "--"}


def _s(value) -> str | None:
    """Text, or None for empty and null-like answers ("null", "N/A", "unknown")."""
    text = str(value).strip() if value is not None else ""
    return None if text.lower() in NULL_WORDS else text


def read_pack_label(img, setting: dict, today=None, backends=None) -> dict:
    """Photo of sterile pack labels -> {"labels": [{"item", "item_text", "lot", "sterilized", "expires",
    "indicator_text", "expired"}], "expired": any}. Dates come back as YYYY-MM-DD."""
    today = today or dt.date.today()
    if isinstance(today, str):
        today = dt.date.fromisoformat(today)
    result = run_backends(default_backends() if backends is None else backends, jpeg_for_upload(img),
                          pack_label_prompt(setting), pack_label_schema(setting), "pack_label",
                          lambda raw: validate_pack_label(raw, setting, today))
    result.setdefault("labels", [])
    result.setdefault("expired", False)
    result["today"] = today.isoformat()
    result["setting"] = setting.get("id")
    return result


def main(argv: list[str] | None = None) -> None:
    """python -m vision.reading count_sheet|tray_tag|pack_label IMAGE [--setting surgical] [--today YYYY-MM-DD]"""
    import argparse

    from dotenv import load_dotenv

    ap = argparse.ArgumentParser(description="Read a count sheet, tray tag or pack label photo (prints JSON, never keys)")
    ap.add_argument("kind", choices=["count_sheet", "tray_tag", "pack_label"])
    ap.add_argument("image")
    ap.add_argument("--setting", default=os.environ.get("VISION_SETTING", "surgical"))
    ap.add_argument("--today", default=None)
    a = ap.parse_args(argv)
    load_dotenv(ROOT / ".env")
    img = Path(a.image).read_bytes()
    if a.kind == "tray_tag":
        result = read_tray_tag(img)
    elif a.kind == "count_sheet":
        result = read_count_sheet(img, load_setting_merged(ROOT, a.setting))
    else:
        result = read_pack_label(img, load_setting_merged(ROOT, a.setting), a.today)
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
