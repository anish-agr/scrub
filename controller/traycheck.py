"""Tray check (X3): ask vision's GET /tray_check and word the answer. Blocking; the route runs it in a thread.

Vision answers {"ok", "setting", "missing": [ids], "wrong_slot": [{"item", "in_slot_of"}], "extra": [ids],
"stale", "t"}; anything missing or extra is tolerated. Vision down, 404, timeout or a stale view:
ok false and "I can't check the tray right now."
"""
import os

import httpx

from . import lines, settings

TIMEOUT_S = 3.0


def vision_url() -> str:
    return os.environ.get("VISION_URL", "http://localhost:8001").rstrip("/")


def fetch() -> dict | None:
    """Vision's answer, or None if it isn't there (down, 404, timeout, not JSON)."""
    try:
        r = httpx.get(vision_url() + "/tray_check", timeout=TIMEOUT_S)
        r.raise_for_status()
        data = r.json()
    except (httpx.HTTPError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _ids(v) -> list[str]:
    return [str(x) for x in v if x] if isinstance(v, list) else []


def check(setting: dict, fetch=fetch) -> dict:
    """Vision's fields plus `say`, `available`, `label` and `items` (the setting's item names)."""
    names = [i["name"] for i in setting["items"]]
    name = lambda i: (settings.item(setting, i) or {"name": i.replace("_", " ")})["name"]  # noqa: E731
    base = {"setting": setting["id"], "label": setting.get("label") or setting["id"], "items": names,
            "missing": [], "wrong_slot": [], "extra": [], "stale": None, "t": None}
    v = fetch()
    if v is None:
        return {**base, "ok": False, "available": False, "say": lines.CANT_CHECK_TRAY}
    out = {**base, **v, "available": True}
    missing, extra = _ids(v.get("missing")), _ids(v.get("extra"))
    wrong = [w for w in v.get("wrong_slot") or [] if isinstance(w, dict) and w.get("item")]
    out.update(missing=missing, extra=extra, wrong_slot=wrong, setting=setting["id"])
    if v.get("stale"):
        return {**out, "ok": False, "say": lines.CANT_CHECK_TRAY}
    seen = v.get("setting")
    if seen and seen != setting["id"]:
        return {**out, "ok": False, "vision_setting": seen, "say": lines.tray_other_setting(seen, setting["id"])}
    ok = (bool(v["ok"]) if "ok" in v else True) and not (missing or wrong)
    parts = [lines.tray_missing([name(i) for i in missing])] if missing else []
    for w in wrong:
        slot = w.get("in_slot_of")
        parts.append(lines.tray_wrong_slot(name(w["item"]), name(str(slot))) if slot else lines.tray_wrong_place(name(w["item"])))
    if ok:
        parts.insert(0, lines.tray_ready(names))
    elif not parts:
        parts.append(lines.TRAY_NOT_READY)
    if extra:
        parts.append(lines.tray_extra([name(i) for i in extra]))
    return {**out, "ok": ok, "say": " ".join(parts)}
