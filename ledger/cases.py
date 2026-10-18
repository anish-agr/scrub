"""Group ledger events into cases for the replay page."""

from __future__ import annotations

from ledger import _median, _num, _out, stored_rows

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
    "skill_source",
    "sheet_mismatch",
)

CAPTION_WINDOW_S = 10.0


def _cid(event: dict) -> str:
    return str(event.get("case_id") or "no-case")


def _stamp(event: dict) -> float:
    return _num(event.get("t")) or 0.0


def _name(item: str) -> str:
    return str(item).replace("_", " ")


def _is_caption(event: dict) -> bool:
    return event.get("type") == "caption"


def _split(events: list[dict]) -> tuple[list[dict], list[dict]]:
    """Real events and caption records. Captions are notes on events, never events."""
    return [e for e in events if not _is_caption(e)], [e for e in events if _is_caption(e)]


def _ratio(entry: dict) -> str:
    name = _name(entry.get("name") or entry.get("item") or "item")
    start = entry.get("initial")
    end = entry.get("closing")
    if end is not None:
        return f"{name} {start if start is not None else '?'}/{end}"
    if start is not None:
        return f"{name} {start}/{entry.get('expected', '?')}"
    return f"{name} {entry.get('expected', '?')}"


def _read_line(event: dict) -> str | None:
    """One plain line for a read event. None when the event has no read object."""
    read = event.get("read")
    if not isinstance(read, dict):
        return None
    kind = read.get("kind")
    title = {"count_sheet": "Count sheet", "tray_tag": "Tray tag", "pack_label": "Pack label"}.get(kind, "Paper")
    if read.get("ok") is False:
        title += " not read"
    else:
        title += " read"
    how = []
    if read.get("method"):
        how.append(str(read["method"]))
    ms = _num(read.get("latency_ms"))
    if ms is not None:
        how.append(f"{ms / 1000:.1f} s")
    head = title + (f" ({', '.join(how)})" if how else "")
    parts = []
    if kind == "count_sheet":
        if read.get("tray"):
            parts.append(f"tray {read['tray']}")
        items = [i for i in read.get("items") or [] if isinstance(i, dict)]
        parts.extend(_ratio(i) for i in items)
    elif kind == "tray_tag":
        if read.get("tray"):
            parts.append(f"tray {read['tray']}")
    elif kind == "pack_label":
        for label in read.get("labels") or []:
            if not isinstance(label, dict):
                continue
            text = _name(label.get("item") or label.get("item_text") or "pack")
            if label.get("lot"):
                text += f" lot {label['lot']}"
            if label.get("expires"):
                text += f" expires {label['expires']}"
            if label.get("expired"):
                text += " EXPIRED"
            parts.append(text)
    return head + (": " + ", ".join(parts) if parts else "")


def _attach_captions(rows: list[dict], captions: list[dict]) -> None:
    """Put each caption under the closest event with the same case, type and item, within the window."""
    free = list(captions)
    for row in rows:
        stamp = _stamp(row)
        best = None
        gap = CAPTION_WINDOW_S + 1
        for cap in free:
            if cap.get("event_type") != row.get("type") or cap.get("item") != row.get("item"):
                continue
            distance = abs(_stamp(cap) - stamp)
            if distance <= CAPTION_WINDOW_S and distance < gap:
                best, gap = cap, distance
        if best is None:
            continue
        free.remove(best)
        if best.get("label_source") == "perceptron" and best.get("label"):
            row["caption"] = {
                "label": best.get("label"),
                "agrees": best.get("agrees"),
                "disagrees": best.get("agrees") is False,
            }


def list_cases(events: list[dict] | None = None) -> list[dict]:
    if events is None:
        events, _tests = stored_rows()
    events, _captions = _split(events)
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
    rows.sort(key=lambda row: _stamp({"t": row["started"]}), reverse=True)
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
            asked.append(_name(item))
        if kind == "handed" and item:
            seconds = event.get("request_to_hand_s")
            label = _name(item)
            number = _num(seconds)
            handed.append(label if number is None else f"{label} in {number:.1f}s")
            if number is not None:
                times.append(number)
        elif kind == "set_down" and item:
            handed.append(f"{_name(item)} at the safe spot")
        elif kind == "missed" and item:
            missed.append(_name(item))
        elif kind == "returned" and item:
            returned.append(_name(item))
    parts = [f"{setting} case, {len(group)} events."]
    if asked:
        parts.append("Asked: " + ", ".join(asked) + ".")
    parts.append("Passed: " + (", ".join(handed) if handed else "nothing yet") + ".")
    if missed:
        parts.append("Missed: " + ", ".join(missed) + ".")
    if returned:
        parts.append("Back: " + ", ".join(returned) + ".")
    if times:
        mid = _median(times)
        if mid is not None:
            parts.append(f"Median request to hand {mid:.1f}s.")
    held = [_name(item) for item in _out(group)]
    parts.append("Out now: " + (", ".join(held) if held else "nothing") + ".")
    return " ".join(parts)


def case_view(case_id: str, events: list[dict] | None = None) -> dict | None:
    if events is None:
        events, _tests = stored_rows()
    events, captions = _split(events)
    group = [event for event in events if _cid(event) == case_id]
    if not group:
        return None
    group.sort(key=_stamp)
    slim = []
    for event in group:
        row = {field: event.get(field) for field in _FIELDS}
        line = _read_line(event)
        if line:
            row["read_line"] = line
            row["read"] = event.get("read")
        slim.append(row)
    _attach_captions(slim, [c for c in captions if _cid(c) == case_id])
    return {
        "case_id": case_id,
        "setting": next((event.get("setting") for event in group if event.get("setting")), None),
        "started": group[0].get("t"),
        "ended": group[-1].get("t"),
        "summary": _summary(group),
        "out": _out(group),
        "events": slim,
    }
