"""Ask Gemini whether the instrument in a camera crop has a sharp end.

The key comes from GEMINI_API_KEY. A missing key, a bad picture, or a failed call
returns None. Nothing here logs the key or the picture.
"""

from __future__ import annotations

import base64
import json
import os

import httpx

from vision.draw import jpeg_bytes

_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash"
_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def names_for(item: str) -> set[str]:
    text = item.replace("_", " ").strip().lower()
    return {text, text.replace(" ", "")}


def _box(detection: dict):
    point = detection.get("point_box") or {}
    top, bottom = point.get("top_left") or {}, point.get("bottom_right") or {}
    if "x" not in top or "x" not in bottom:
        return None
    return int(top["x"]), int(top["y"]), int(bottom["x"]), int(bottom["y"])


def crop_jpeg(frame, detections: list, item: str) -> bytes:
    """The detection box for this instrument, or the whole frame if it was not boxed."""
    wanted = names_for(item)
    height, width = frame.shape[:2]
    for detection in detections or []:
        mention = str(detection.get("mention") or "").replace("_", " ").strip().lower()
        if mention not in wanted and mention.replace(" ", "") not in wanted:
            continue
        box = _box(detection)
        if box is None:
            continue
        x1, y1, x2, y2 = box
        x1, y1 = max(0, min(x1, x2)), max(0, min(y1, y2))
        x2, y2 = min(width, max(x1 + 1, max(x1, x2))), min(height, max(y1 + 1, max(y1, y2)))
        crop = frame[y1:y2, x1:x2]
        if crop.size:
            return jpeg_bytes(crop, quality=80)
    return jpeg_bytes(frame, quality=70)


def gemini_sharp(jpeg: bytes, name: str, fetch=None, timeout: float = 3.5) -> bool | None:
    """True when the picture shows a sharp end. None when Gemini cannot be asked."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key or not jpeg:
        return None
    prompt = (
        f"Look at this camera picture of a {name}. "
        "Does the object have a sharp end, such as a blade, a point, or a needle? "
        "Decide only from the picture. A closed handle with no blade or point showing is not sharp. "
        'Answer as JSON {"sharp": true} or {"sharp": false}.'
    )
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(jpeg).decode("ascii")}},
            ]
        }],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {"sharp": {"type": "BOOLEAN"}},
                "required": ["sharp"],
            },
        },
    }
    post = fetch or _post
    try:
        response = post(_URL.format(model=_MODEL), {"x-goog-api-key": key}, payload, timeout)
    except Exception:
        return None
    if getattr(response, "status_code", 0) != 200:
        return None
    try:
        body = response.json()
        text = body["candidates"][0]["content"]["parts"][0]["text"]
        sharp = json.loads(text).get("sharp")
    except Exception:
        return None
    return sharp if isinstance(sharp, bool) else None


def _post(url: str, headers: dict, payload: dict, timeout: float):
    return httpx.post(url, headers={**headers, "content-type": "application/json"}, json=payload, timeout=timeout)


def fake_sharp(item: str) -> bool:
    """The fake camera has no picture. The scalpel is the sharp instrument on the surgical tray."""
    return item.replace("_", " ").strip().lower() in {"scalpel", "knife", "blade"}
