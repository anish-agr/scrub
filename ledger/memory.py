"""What the arm remembers, for the Backboard track.

Each accepted handover is one note. With `BACKBOARD_API_KEY` and
`BACKBOARD_ASSISTANT_ID` the same note is stored on Backboard, and a question
is sent there with memory turned on. Without those, the answer comes from the
local notes and the ledger.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

NOTES = Path(__file__).resolve().parent / "memory-buffer.jsonl"
_API = "https://app.backboard.io/api"


def configured() -> bool:
    return bool(os.environ.get("BACKBOARD_API_KEY", "").strip() and os.environ.get("BACKBOARD_ASSISTANT_ID", "").strip())


def _key() -> str:
    return os.environ.get("BACKBOARD_API_KEY", "").strip()


def _assistant() -> str:
    return os.environ.get("BACKBOARD_ASSISTANT_ID", "").strip()


def _post(path: str, payload: dict, form: bool = False) -> dict | None:
    if not _key():
        return None
    if form:
        body = urllib.parse.urlencode(payload).encode()
        content_type = "application/x-www-form-urlencoded"
    else:
        body = json.dumps(payload).encode()
        content_type = "application/json"
    request = urllib.request.Request(_API + path, data=body, method="POST")
    request.add_header("X-API-Key", _key())
    request.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(request, timeout=2.5) as response:
            raw = response.read().decode()
            parsed = json.loads(raw) if raw else {}
            return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _append(note: dict) -> None:
    NOTES.parent.mkdir(parents=True, exist_ok=True)
    with NOTES.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(note, separators=(",", ":")) + "\n")


def notes(limit: int = 12) -> list[dict]:
    if not NOTES.exists():
        return []
    rows = []
    try:
        lines = NOTES.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    for line in lines[-limit:]:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def remember_event(event: dict) -> None:
    """Remember an accepted handover. Never raises."""
    try:
        if not isinstance(event, dict):
            return
        if event.get("type") != "command" or event.get("action") != "handover":
            return
        if event.get("accepted") is False or not event.get("item"):
            return
        item = str(event["item"]).replace("_", " ")
        setting = str(event.get("setting") or "this tray")
        text = f"In the {setting} tray, someone asked for {item}."
        note = {"t": event.get("t") or time.time(), "text": text, "item": event["item"], "setting": event.get("setting")}
        _append(note)
        if configured():
            _post(
                f"/assistants/{_assistant()}/memories",
                {"content": text, "metadata": {"item": event["item"], "setting": setting}},
            )
    except Exception:
        return


def _follows(events: list[dict], item: str) -> dict | None:
    from ledger import next_likely

    if not item:
        return next_likely(events)
    sequences: dict[str, list[str]] = {}
    for event in events:
        if event.get("type") != "command" or event.get("action") != "handover":
            continue
        if event.get("accepted") is False or not event.get("item"):
            continue
        sequences.setdefault(str(event.get("case_id") or "no-case"), []).append(event["item"])
    counts: dict[str, int] = {}
    total = 0
    for seq in sequences.values():
        for previous, following in zip(seq, seq[1:]):
            if previous != item:
                continue
            counts[following] = counts.get(following, 0) + 1
            total += 1
    if not total:
        return None
    winner = max(counts, key=lambda name: (counts[name], name))
    return {"item": winner, "after": item, "share": counts[winner] / total, "n": total}


def _named_item(question: str, events: list[dict]) -> str:
    folded = question.replace("-", " ").replace("_", " ").lower()
    found = ""
    for event in events:
        item = event.get("item")
        if not item:
            continue
        label = str(item).replace("_", " ").replace("-", " ").lower()
        if label and label in folded and len(label) > len(found):
            found = str(item)
    return found


def _local_answer(question: str, events: list[dict]) -> str:
    item = _named_item(question, events)
    guess = _follows(events, item)
    if not guess:
        return "Nothing usually follows that yet."
    after = str(guess["after"]).replace("_", " ")
    nxt = str(guess["item"]).replace("_", " ")
    share = round(float(guess["share"]) * 100)
    return f"After {after}, the next instrument is usually {nxt} ({share}% of {guess['n']})."


def answer(question: str, events: list[dict] | None = None) -> dict:
    from ledger import stored_rows

    if events is None:
        events, _tests = stored_rows()
    question = (question or "").strip()
    if not question:
        return {"source": "local", "answer": "Ask what usually comes next.", "backboard": configured()}
    if configured():
        opened = _post(f"/assistants/{_assistant()}/threads", {})
        thread_id = (opened or {}).get("thread_id")
        if thread_id:
            sent = _post(
                f"/threads/{thread_id}/messages",
                {"content": question, "stream": "false", "memory": "Auto"},
                form=True,
            )
            text = (sent or {}).get("content")
            if isinstance(text, str) and text.strip():
                return {"source": "backboard", "answer": text.strip(), "backboard": True}
    return {"source": "local", "answer": _local_answer(question, events), "backboard": configured()}
