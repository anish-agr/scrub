"""Ask the camera, through vision's GET /sharp, if the instrument has a sharp end.

Vision sends the camera crop to Gemini. This only reads the answer. A down camera
or a failed call is None, never a guess.
"""

from __future__ import annotations

import os

import httpx


def vision_url() -> str:
    return os.environ.get("VISION_URL", "http://localhost:8001").rstrip("/")


def camera_says_sharp(item_id: str, timeout: float = 4.5) -> bool | None:
    try:
        response = httpx.get(vision_url() + "/sharp", params={"item": item_id}, timeout=timeout)
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    try:
        sharp = response.json().get("sharp")
    except Exception:
        return None
    return sharp if isinstance(sharp, bool) else None
