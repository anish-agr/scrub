"""Read-only loading from MongoDB (database `scrub`) or a JSON fixture, plus the real/fake split.

Only `find` is ever called. Nothing here writes, updates or deletes a document.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COLLECTIONS = ("events", "episodes", "thermal")


def load(fixture: str | Path | None = None) -> dict:
    """{"events": [...], "episodes": [...], "thermal": [...], "read_at": epoch s, "source": "mongo" or path}."""
    if fixture:
        data = json.loads(Path(fixture).read_text())
        return {**{c: data.get(c, []) for c in COLLECTIONS}, "read_at": data.get("read_at", time.time()),
                "source": str(fixture)}
    from dotenv import load_dotenv
    from pymongo import MongoClient

    load_dotenv(ROOT / ".env")
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        raise SystemExit("MONGODB_URI is not set in .env")
    db = MongoClient(uri, serverSelectionTimeoutMS=10000)[os.environ.get("MONGODB_DB", "scrub")]
    out = {c: list(db[c].find({}, {"_id": 0})) for c in COLLECTIONS}
    return {**out, "read_at": time.time(), "source": "mongo"}


def tag_start(events: list[dict]) -> float | None:
    """Time of the first event that carries a `fake_arm` tag. Earlier rows are test data."""
    ts = [e["t"] for e in events if "fake_arm" in e and isinstance(e.get("t"), (int, float))]
    return min(ts) if ts else None


def arm_kind(row: dict, start: float | None) -> str:
    """real, sim, fake or pretag. `fake_arm: false` (and no sim marker) after the tags started is real."""
    if row.get("sim") or row.get("sim_arm") or str(row.get("arm") or "").lower() in ("sim", "simulation"):
        return "sim"
    if row.get("fake_arm"):
        return "fake"
    if "fake_arm" not in row or start is None or (row.get("t") or 0) < start:
        return "pretag"
    return "real"


def real_events(events: list[dict]) -> list[dict]:
    start = tag_start(events)
    return [e for e in events if arm_kind(e, start) == "real"]
