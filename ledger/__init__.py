"""MongoDB log for Scrub. Never raises.

`log` stores controller events. `log_test` stores a measured trial.
`stats` is what `GET /stats` should return unchanged.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUFFER = Path(os.environ.get("LEDGER_BUFFER") or Path(__file__).resolve().parent / "buffer.jsonl")  # tests use a scratch file
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
CACHE_S = 5.0  # how old the Atlas copy may get before a background refresh
BATCH = 500  # rows per insert_many on reconnect
_cache: dict = {"events": [], "tests": [], "start": 0.0, "at": 0.0}  # last Atlas read, rows keep their _id
_recent: list = []  # (monotonic, kind, doc) inserted since the last read started, so stats see them at once
_refreshing = False


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
    _flush()
    _refresh_cache()


def _append(kind: str, doc: dict) -> None:
    BUFFER.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"kind": kind, "doc": doc}, separators=(",", ":"))
    with BUFFER.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _collection(kind: str) -> str:
    return "events" if kind == "event" else "tests"


def _flushing() -> Path:
    return BUFFER.with_name(BUFFER.stem + ".flushing" + BUFFER.suffix)


def _flush() -> None:
    """Upload the local buffer to Mongo in batches. The lock is held only to move the file."""
    global _db, _next_try
    with _lock:
        if _db is None:
            return
        db = _db
        moving = _flushing()
        if not moving.exists():  # a leftover from a crash is uploaded first
            if not BUFFER.exists():
                return
            try:
                BUFFER.replace(moving)
            except OSError:
                return
    try:
        lines = moving.read_text(encoding="utf-8").splitlines()
    except Exception:
        return
    rows: dict[str, list[tuple[str, dict]]] = {"events": [], "tests": []}
    for line in lines:
        try:
            row = json.loads(line)
            rows[_collection(row["kind"])].append((line, dict(row["doc"])))
        except Exception:
            continue  # a line that cannot be parsed can never be uploaded
    failed: list[str] = []
    broken = False  # once Mongo fails, everything not yet uploaded goes back to the buffer
    for name, pairs in rows.items():
        for start in range(0, len(pairs), BATCH):
            chunk = pairs[start : start + BATCH]
            if not broken:
                try:
                    db[name].insert_many([doc for _line, doc in chunk])
                    continue
                except Exception as error:
                    broken = True
                    chunk = chunk[(getattr(error, "details", None) or {}).get("nInserted", 0) :]
            failed.extend(line for line, _doc in chunk)
    with _lock:
        for line in failed:
            try:
                with BUFFER.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
            except Exception:
                pass
        if failed:
            _db = None  # reconnect later and try again
            _next_try = time.time() + 15
        try:
            moving.unlink()
        except Exception:
            pass


def _refresh_cache() -> None:
    """Read Atlas into the local copy. Only ever runs on a background thread."""
    global _cache, _refreshing
    with _lock:
        db = _db
        if db is None or _refreshing:
            return
        _refreshing = True
    start = time.monotonic()
    try:
        events = list(db.events.find({}))
        tests = list(db.tests.find({}))
        with _lock:
            _cache = {"events": events, "tests": tests, "start": start, "at": time.monotonic()}
            _recent[:] = [row for row in _recent if row[0] >= start]
    except Exception:
        pass
    finally:
        with _lock:
            _refreshing = False


def warm(timeout: float = 3.0) -> None:
    """Wait for the first Atlas connection and read. For one-shot use (`python -m ledger`); stats() never waits."""
    _kick_connect()
    deadline = time.time() + timeout
    while time.time() < deadline:
        with _lock:
            if _cache["at"] or (_db is None and not _connecting):
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
        row = dict(doc)
        db[_collection(kind)].insert_one(row)
        with _lock:
            _recent.append((time.monotonic(), kind, row))
            del _recent[:-2000]
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
        _side_tracks(doc)
    except Exception:
        return


def _side_tracks(doc: dict) -> None:
    """Tiger Data inserts only when its URL is set. Backboard uploads only when its key is set. Never raises."""
    try:
        from ledger.tiger import remember_event as remember_tiger

        remember_tiger(doc)
    except Exception:
        pass
    try:
        from ledger.memory import remember_event as remember_memory

        remember_memory(doc)
    except Exception:
        pass


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
    """The last Atlas copy plus rows inserted since. Never waits on Mongo."""
    with _lock:
        db = _db
        cache = _cache
        recent = list(_recent)
        stale = time.monotonic() - cache["at"] > CACHE_S
    if db is not None and stale:
        threading.Thread(target=_refresh_cache, name="ledger-mongo-read", daemon=True).start()
    out = {"event": list(cache["events"]), "test": list(cache["tests"])}
    seen = {row["_id"] for rows in out.values() for row in rows if "_id" in row}
    for mono, kind, row in recent:
        if mono >= cache["start"] and row.get("_id") not in seen:
            out[kind].append(row)
    strip = lambda rows: [{k: v for k, v in row.items() if k != "_id"} for row in rows]
    return strip(out["event"]), strip(out["test"])


def _num(value) -> float | None:
    """A finite number, or None. A bad timestamp must not wipe the tables."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _when(event: dict) -> float:
    return _num(event.get("t")) or 0.0


def _median(values: list[float]) -> float | None:
    nums = sorted(number for number in (_num(value) for value in values) if number is not None)
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
            number = _num(event.get("request_to_hand_s"))
            if number is not None:
                values.append(number)
    if values:
        return values
    for test in tests:
        if test.get("seconds") is None:
            continue
        if all(test.get(key) == expected for key, expected in match.items()):
            number = _num(test.get("seconds"))
            if number is not None:
                values.append(number)
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
        low, high = _wilson(successes, attempts)
        rows.append(
            {
                key: name,
                "attempts": attempts,
                "successes": successes,
                "success_rate": successes / attempts if attempts else None,
                "wilson_low": low,
                "wilson_high": high,
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
    ordered = sorted(events, key=_when)
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


def _wilson(successes: int, attempts: int, z: float = 1.96) -> tuple[float | None, float | None]:
    """95% Wilson interval for a success rate. None when there are no tries."""
    if attempts <= 0:
        return None, None
    p = successes / attempts
    z2 = z * z
    denom = 1 + z2 / attempts
    center = (p + z2 / (2 * attempts)) / denom
    margin = z * math.sqrt(p * (1 - p) / attempts + z2 / (4 * attempts * attempts)) / denom
    return max(0.0, center - margin), min(1.0, center + margin)


def stored_rows() -> tuple[list[dict], list[dict]]:
    """Events and trials from the Atlas copy plus anything still in the local buffer. Never waits on Mongo."""
    try:
        _kick_connect()
        mongo_events, mongo_tests = _read_mongo()
        file_events, file_tests = _read_buffer()
        return mongo_events + file_events, mongo_tests + file_tests
    except Exception:
        return [], []


def next_likely(events: list[dict]) -> dict | None:
    """The instrument that most often follows the latest request, in this setting.

    A suggestion only. Nothing here moves the arm.
    """
    ordered = sorted(events, key=_when)
    setting = None
    for event in reversed(ordered):
        if event.get("setting"):
            setting = event["setting"]
            break
    sequences: dict[str, list[str]] = {}
    last_item = None
    last_t = -1.0
    for event in ordered:
        if event.get("type") != "command" or event.get("action") != "handover":
            continue
        if event.get("accepted") is False or not event.get("item"):
            continue
        if setting and event.get("setting") not in (None, setting):
            continue
        cid = str(event.get("case_id") or "no-case")
        sequences.setdefault(cid, []).append(event["item"])
        stamp = _when(event)
        if stamp >= last_t:
            last_t = stamp
            last_item = event["item"]
    if not last_item:
        return None
    counts: dict[str, int] = {}
    total = 0
    for seq in sequences.values():
        for previous, following in zip(seq, seq[1:]):
            if previous != last_item:
                continue
            counts[following] = counts.get(following, 0) + 1
            total += 1
    if not total:
        return None
    item = max(counts, key=lambda name: (counts[name], name))
    return {
        "item": item,
        "after": last_item,
        "share": counts[item] / total,
        "n": total,
        "setting": setting,
    }


def _is_sim(row: dict) -> bool:
    """True for a row the controller tagged `fake_arm` or `sim` (optional fields). Untagged rows count as real."""
    return bool(row.get("fake_arm") or row.get("sim"))


def stats(include_sim: bool = False) -> dict:
    """Success rate by item and by lighting, plus the median handoff time.

    Rows tagged `fake_arm` or `sim` are left out of the rates and medians unless
    `include_sim`. The count (`out`) always reads every event: it is live state.
    """
    empty = {
        "by_item": [],
        "by_lighting": [],
        "median_request_to_hand_s": None,
        "out": [],
        "next_likely": None,
        "t": time.time(),
    }
    try:
        all_events, all_tests = stored_rows()
        events, tests = all_events, all_tests
        if not include_sim:
            events = [row for row in all_events if not _is_sim(row)]
            tests = [row for row in all_tests if not _is_sim(row)]
        return {
            "by_item": _rate_rows(tests, events, "item"),
            "by_lighting": _rate_rows(tests, events, "lighting"),
            "median_request_to_hand_s": _median(_samples(tests, events)),
            "out": _out(all_events),
            "next_likely": next_likely(events),
            "t": time.time(),
        }
    except Exception:
        return empty
