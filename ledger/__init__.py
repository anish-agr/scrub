"""MongoDB log for Scrub. Never raises.

`log` stores controller events. `log_test` stores a measured trial.
`stats` is what `GET /stats` should return unchanged.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUFFER = Path(__file__).resolve().parent / "buffer.jsonl"
DB_NAME = "scrub"

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:
    pass

_lock = threading.Lock()
_client = None
_db = None
_connecting = False
_next_try = 0.0


def _uri() -> str:
    return os.environ.get("MONGODB_URI", "").strip()


def _kick_connect() -> None:
    global _connecting
    with _lock:
        if _db is not None or _connecting or not _uri():
            return
        if time.time() < _next_try:
            return
        _connecting = True
    threading.Thread(target=_connect, name="ledger-mongo", daemon=True).start()


def _connect() -> None:
    global _client, _db, _connecting, _next_try
    client = None
    try:
        from pymongo import MongoClient

        client = MongoClient(
            _uri(),
            serverSelectionTimeoutMS=2000,
            connectTimeoutMS=2000,
        )
        client.admin.command("ping")
        db = client[DB_NAME]
    except Exception:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        with _lock:
            _connecting = False
            _next_try = time.time() + 15
        return
    with _lock:
        _client = client
        _db = db
        _connecting = False
        _flush_locked()


def _append(kind: str, doc: dict) -> None:
    BUFFER.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"kind": kind, "doc": doc}, separators=(",", ":"))
    with BUFFER.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _collection(kind: str) -> str:
    return "events" if kind == "event" else "tests"


def _flush_locked() -> None:
    if _db is None or not BUFFER.exists():
        return
    try:
        lines = BUFFER.read_text(encoding="utf-8").splitlines()
    except Exception:
        return
    kept: list[str] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            _db[_collection(row["kind"])].insert_one(dict(row["doc"]))
        except Exception:
            kept.append(line)
    try:
        if kept:
            BUFFER.write_text("\n".join(kept) + "\n", encoding="utf-8")
        else:
            BUFFER.unlink()
    except Exception:
        pass


def _wait_for_connect(timeout: float = 1.0) -> None:
    _kick_connect()
    deadline = time.time() + timeout
    while time.time() < deadline:
        with _lock:
            if _db is not None or not _connecting:
                return
        time.sleep(0.05)


def _store(kind: str, doc: dict) -> None:
    global _db, _next_try
    try:
        with _lock:
            db = _db
            if db is None:
                _append(kind, doc)
                kick = True
            else:
                kick = False
        if kick:
            _kick_connect()
            return
        db[_collection(kind)].insert_one(dict(doc))
    except Exception:
        try:
            with _lock:
                _db = None
                _next_try = 0
                _append(kind, doc)
        except Exception:
            return
        _kick_connect()


def log(event: dict) -> None:
    """Store one controller event. Buffers locally if MongoDB is down."""
    try:
        if not isinstance(event, dict):
            return
        doc = dict(event)
        doc.setdefault("t", time.time())
        _store("event", doc)
    except Exception:
        return


def log_test(
    item: str,
    setting: str,
    lighting: str,
    success: bool,
    seconds: float | None,
    retries: int,
) -> None:
    """Store one measured trial for the success tables."""
    try:
        doc = {
            "item": item,
            "setting": setting,
            "lighting": lighting,
            "success": bool(success),
            "seconds": None if seconds is None else float(seconds),
            "retries": int(retries),
            "t": time.time(),
        }
        _store("test", doc)
    except Exception:
        return


def _read_buffer() -> tuple[list[dict], list[dict]]:
    events: list[dict] = []
    tests: list[dict] = []
    if not BUFFER.exists():
        return events, tests
    try:
        lines = BUFFER.read_text(encoding="utf-8").splitlines()
    except Exception:
        return events, tests
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        doc = row.get("doc")
        if not isinstance(doc, dict):
            continue
        if row.get("kind") == "event":
            events.append(doc)
        elif row.get("kind") == "test":
            tests.append(doc)
    return events, tests


def _read_mongo() -> tuple[list[dict], list[dict]]:
    with _lock:
        db = _db
    if db is None:
        return [], []
    try:
        events = list(db.events.find({}, {"_id": 0}))
        tests = list(db.tests.find({}, {"_id": 0}))
        return events, tests
    except Exception:
        return [], []


def _median(values: list[float]) -> float | None:
    nums = sorted(value for value in values if isinstance(value, (int, float)))
    if not nums:
        return None
    mid = len(nums) // 2
    if len(nums) % 2:
        return float(nums[mid])
    return (float(nums[mid - 1]) + float(nums[mid])) / 2


def _samples(tests: list[dict], events: list[dict], **match) -> list[float]:
    values: list[float] = []
    for event in events:
        if event.get("type") != "handed":
            continue
        if event.get("request_to_hand_s") is None:
            continue
        if all(event.get(key) == expected for key, expected in match.items()):
            values.append(float(event["request_to_hand_s"]))
    if values:
        return values
    for test in tests:
        if test.get("seconds") is None:
            continue
        if all(test.get(key) == expected for key, expected in match.items()):
            values.append(float(test["seconds"]))
    return values


def _rate_rows(tests: list[dict], events: list[dict], key: str) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for test in tests:
        name = test.get(key)
        if not name:
            continue
        grouped.setdefault(name, []).append(test)
    rows = []
    for name in sorted(grouped):
        group = grouped[name]
        attempts = len(group)
        successes = sum(1 for test in group if test.get("success"))
        rows.append(
            {
                key: name,
                "attempts": attempts,
                "successes": successes,
                "success_rate": successes / attempts if attempts else None,
                "median_request_to_hand_s": _median(_samples(group, events, **{key: name})),
            }
        )
    return rows


def _out(events: list[dict]) -> list[str]:
    """The count on the newest event.

    The controller puts its current `out` list on every event, including the
    step it emits after a reset or a tray change. Replaying `handed` and
    `returned` from the whole history keeps items that were cleared.
    """
    ordered = sorted(events, key=lambda event: float(event.get("t") or 0))
    for event in reversed(ordered):
        listed = event.get("out")
        if isinstance(listed, list):
            return [item for item in listed if isinstance(item, str) and item]
    held: list[str] = []
    for event in ordered:
        item = event.get("item")
        kind = event.get("type")
        if kind in ("handed", "set_down") and item and item not in held:
            held.append(item)
        elif kind == "returned" and item in held:
            held.remove(item)
    return held


def stats() -> dict:
    """Success rate by item and by lighting, plus the median handoff time."""
    empty = {
        "by_item": [],
        "by_lighting": [],
        "median_request_to_hand_s": None,
        "out": [],
        "t": time.time(),
    }
    try:
        _wait_for_connect(2.5 if _uri() else 0)
        with _lock:
            _flush_locked()
        mongo_events, mongo_tests = _read_mongo()
        file_events, file_tests = _read_buffer()
        events = mongo_events + file_events
        tests = mongo_tests + file_tests
        return {
            "by_item": _rate_rows(tests, events, "item"),
            "by_lighting": _rate_rows(tests, events, "lighting"),
            "median_request_to_hand_s": _median(_samples(tests, events)),
            "out": _out(events),
            "t": time.time(),
        }
    except Exception:
        return empty
