"""Reading (OCR): ask vision's POST /read/<kind> and compare a count sheet with Scrub's own count.

Blocking; the controller runs it on its own thread, never the event loop or the arm worker, so stop never
waits on it. Vision answers {"ok", "method", "latency_ms", "error", ...the reader's fields} (vision/README.md
"Reading (OCR)"). Vision down, an HTTP error, a timeout or a body that is not a JSON object give None.
"""
import os

import httpx

from . import settings
from .traycheck import vision_url

TIMEOUT_S = float(os.environ.get("READ_TIMEOUT_S") or 20.0)  # vision tries Perceptron (8 s) then Gemini (15 s)
KINDS = {"read_sheet": "count_sheet", "read_tray": "tray_tag", "read_pack": "pack_label"}


def fetch(kind: str, setting_id: str) -> dict | None:
    """Vision's read of the overhead frame, or None. A 4xx/5xx with a JSON body (no frame yet) is that body."""
    try:
        r = httpx.post(f"{vision_url()}/read/{kind}", json={"source": "overhead", "setting": setting_id},
                       timeout=TIMEOUT_S)
        data = r.json()
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(data, dict) or (r.status_code >= 400 and "ok" not in data):
        return None
    return data


def _n(v) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def sheet_state(result: dict, t: float) -> dict:
    """State.sheet: {"tray", "items": {id: {"expected", "initial", "closing"}}, "method", "t"}."""
    items = {}
    for row in result.get("items") or []:
        if isinstance(row, dict) and row.get("item"):
            items[str(row["item"])] = {k: _n(row.get(k)) for k in ("expected", "initial", "closing")}
    return {"tray": result.get("tray"), "items": items, "method": result.get("method"), "t": t}


def on_tray(sheet_row: dict, item_id: str, out: list) -> int:
    """Scrub's own on-tray count: the sheet's expected (1 when blank) minus how many of the item are out."""
    expected = sheet_row.get("expected")
    return (1 if expected is None else expected) - out.count(item_id)


def closing_mismatch(sheet: dict, out: list) -> list | None:
    """[{"item", "sheet", "scrub"}] where a written closing count differs from Scrub's. None: no closing written."""
    rows = {i: r for i, r in (sheet.get("items") or {}).items() if r.get("closing") is not None}
    if not rows:
        return None
    return [{"item": i, "sheet": r["closing"], "scrub": on_tray(r, i, out)}
            for i, r in rows.items() if r["closing"] != on_tray(r, i, out)]


def initial_mismatch(sheet: dict) -> list | None:
    """[{"item", "sheet", "expected"}] where a written initial count differs from the expected. None: none written."""
    rows = {i: r for i, r in (sheet.get("items") or {}).items()
            if r.get("initial") is not None and r.get("expected") is not None}
    if not rows:
        return None
    return [{"item": i, "sheet": r["initial"], "expected": r["expected"]}
            for i, r in rows.items() if r["initial"] != r["expected"]]


def tray_label(setting_id: str) -> str | None:
    """"robotics bench" for bench; None for an id the controller can't load."""
    try:
        s = settings.load(setting_id)
    except (KeyError, ValueError, OSError):
        return None
    return str(s.get("label") or setting_id).lower()
