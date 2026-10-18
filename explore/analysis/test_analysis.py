"""Offline tests for the loader, the real/fake split, the stats and the whole run on a tiny fixture."""

import json

import pytest

from explore.analysis import source, stats


EVENTS = [
    {"type": "handed", "item": "hemostat", "t": 100.0},  # before tags: test data
    {"type": "handed", "item": "hemostat", "t": 200.0, "fake_arm": True},
    {"type": "handed", "item": "hemostat", "t": 210.0, "fake_arm": False},
    {"type": "handed", "item": "hemostat", "t": 220.0, "fake_arm": False, "sim": True},
    {"type": "handed", "item": "hemostat", "t": 230.0},  # untagged after tags started: still not real
]


def test_tag_start_is_first_tagged_row():
    assert source.tag_start(EVENTS) == 200.0
    assert source.tag_start([{"t": 1}]) is None


def test_arm_kind_splits_rows():
    start = source.tag_start(EVENTS)
    assert [source.arm_kind(e, start) for e in EVENTS] == ["pretag", "fake", "real", "sim", "pretag"]
    assert [e["t"] for e in source.real_events(EVENTS)] == [210.0]


def test_wilson_matches_known_values():
    lo, hi = stats.wilson(9, 10)
    assert lo == pytest.approx(0.5958, abs=1e-3) and hi == pytest.approx(0.9821, abs=1e-3)
    assert stats.wilson(0, 0) is None
    lo, hi = stats.wilson(0, 5)
    assert lo == 0.0 and hi == pytest.approx(0.4345, abs=1e-3)


def test_percentiles():
    assert stats.median([3, 1, 2]) == 2
    assert stats.pct([1, 2, 3, 4], 90) == pytest.approx(3.7)
    assert stats.pct([], 50) is None


def test_load_fixture(tmp_path):
    p = tmp_path / "d.json"
    p.write_text(json.dumps({"events": EVENTS, "read_at": 5}))
    d = source.load(p)
    assert len(d["events"]) == 5 and d["episodes"] == [] and d["thermal"] == [] and d["read_at"] == 5
