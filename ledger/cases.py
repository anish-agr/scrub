"""Group ledger events into cases for the replay page."""

from __future__ import annotations

from ledger import _out, stored_rows

_FIELDS = (
    "t",
    "type",
    "item",
    "step",
    "say",
    "request_to_hand_s",
    "out",
    "lighting",
    "setting",
    "case_id",
)


def _cid(event: dict) -> str:
    return str(event.get("case_id") or "no-case")


def _stamp(event: dict) -> float:
    try:
        return float(event.get("t") or 0)
    except (TypeError, ValueError):
        return 0.0


def list_cases(events: list[dict] | None = None) -> list[dict]:
    if events is None:
        events, _tests = stored_rows()
    groups: dict[str, list[dict]] = {}
    for event in events:
        groups.setdefault(_cid(event), []).append(event)
    rows = []
    for case_id, group in groups.items():
        group.sort(key=_stamp)
        setting = next((event.get("setting") for event in group if event.get("setting")), None)
        rows.append(
            {
                "case_id": case_id,
                "setting": setting,
                "started": group[0].get("t"),
                "ended": group[-1].get("t"),
                "n": len(group),
                "out": _out(group),
            }
        )
    rows.sort(key=lambda row: float(row["started"] or 0), reverse=True)
    return rows


def _summary(group: list[dict]) -> str:
    setting = next((event.get("setting") for event in group if event.get("setting")), "this")
    handed = []
    asked = []
    missed = []
    returned = []
    times = []
    for event in group:
        kind = event.get("type")
        item = event.get("item")
        if kind == "command" and event.get("action") == "handover" and item and event.get("accepted") is not False:
            asked.append(item)
        if kind == "handed" and item:
            seconds = event.get("request_to_hand_s")
            handed.append(item if seconds is None else f"{item} in {float(seconds):.1f}s")
            if isinstance(seconds, (int, float)):
                times.append(float(seconds))
        elif kind == "set_down" and item:
            handed.append(f"{item} at the safe spot")
        elif kind == "missed" and item:
            missed.append(item)
        elif kind == "returned" and item:
            returned.append(item)
    parts = [f"{setting} case, {len(group)} events."]
    if asked:
        parts.append("Asked: " + ", ".join(asked) + ".")
    parts.append("Passed: " + (", ".join(handed) if handed else "nothing yet") + ".")
    if missed:
        parts.append("Missed: " + ", ".join(missed) + ".")
    if returned:
        parts.append("Back: " + ", ".join(returned) + ".")
    if times:
        ordered = sorted(times)
        mid = ordered[len(ordered) // 2]
        parts.append(f"Median request to hand {mid:.1f}s.")
    held = _out(group)
    parts.append("Out now: " + (", ".join(held) if held else "nothing") + ".")
    return " ".join(parts)


def case_view(case_id: str, events: list[dict] | None = None) -> dict | None:
    if events is None:
        events, _tests = stored_rows()
    group = [event for event in events if _cid(event) == case_id]
    if not group:
        return None
    group.sort(key=_stamp)
    slim = []
    for event in group:
        slim.append({field: event.get(field) for field in _FIELDS})
    return {
        "case_id": case_id,
        "setting": next((event.get("setting") for event in group if event.get("setting")), None),
        "started": group[0].get("t"),
        "ended": group[-1].get("t"),
        "summary": _summary(group),
        "out": _out(group),
        "events": slim,
    }
