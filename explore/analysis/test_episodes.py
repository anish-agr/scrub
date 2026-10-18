from pathlib import Path

import numpy as np

from explore.analysis import episodes as E


def make(idx, n=300, fps=30, head=0, tail=0, grip="closes", start=None):
    """Synthetic episode: arm sweeps 120 deg over the middle; gripper opens then (maybe) closes."""
    t = np.arange(n) / fps
    s = np.zeros((n, 6))
    s[:, :5] = np.asarray(start if start is not None else [0, -100, 95, 75, 0])
    mid = slice(head, n - tail)
    m = n - tail - head
    s[mid, 0] += np.linspace(0, 120, m)
    s[n - tail:, 0] = s[n - tail - 1, 0]
    s[:, 5] = 3
    if grip != "never":
        s[head + m // 3:, 5] = 30
        if grip == "closes":
            s[head + 2 * m // 3:, 5] = 10
    return {"episode_index": idx, "task": "pick", "length": n, "fps": fps, "duration_s": n / fps,
            "joints": ["a", "b", "c", "d", "e", "gripper.pos"], "state": s.tolist(), "timestamp": t.tolist(), "handoff": None}


def test_clean_keep():
    r = E.analyze(make(0))
    assert r["verdict"] == "keep" and r["gripper_close_s"] is not None
    assert r["idle_start_s"] < 0.2 and r["idle_end_s"] < 0.2


def test_speed_math():
    r = E.analyze(make(0, n=301))  # 120 deg over 10 s = 12 deg/s
    assert abs(r["joints"]["a"]["mean_speed"] - 12.0) < 0.5
    assert abs(r["joints"]["a"]["range"] - 120) < 1e-6


def test_idle_head_and_tail():
    r = E.analyze(make(1, n=600, head=120, tail=90))
    assert 3.8 < r["idle_start_s"] < 4.3 and 2.8 < r["idle_end_s"] < 3.3
    assert r["verdict"] == "keep" and "trim" in r["reason"]


def test_no_gripper_open_drops():
    assert E.analyze(make(2, grip="never"))["verdict"] == "drop"


def test_open_no_close_rerecord():
    r = E.analyze(make(3, grip="open"))
    assert r["verdict"] == "re-record" and r["gripper_close_s"] is None


def test_build_flags_and_summary(tmp_path):
    data = {"episodes": [make(0), make(1, grip="never"), make(2, grip="open")]}
    out = E.build(data, tmp_path)
    s = out["summary"]
    assert [e["verdict"] for e in s["episodes"]] == ["keep", "drop", "re-record"]
    assert any("Only 3 episodes" in f for f in s["flags"])
    assert s["tasks"][0]["count"] == 3
    assert "drop" in out["notes"].lower() and out["numbers"][0]["value"] == "3"
    assert (Path(tmp_path) / "episodes.png").exists()
