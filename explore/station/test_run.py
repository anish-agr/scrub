"""No-hardware test of Run mode: a driver moves the follower instead of the leader, nothing is recorded.

  .venv/bin/python -m pytest explore/station/test_run.py -q
"""
from __future__ import annotations

import json
import time
import urllib.request

import numpy as np
import pandas as pd

import test_station as T
from test_station import S, TMP, MOTORS, until

PORT = 8198
TARGET = {f"{m}.pos": 5.0 * i for i, m in enumerate(MOTORS)}


class FakeDriver:
    """Holds TARGET (wrist_roll left out: it must hold); ends after `ticks` with `end`."""
    name = "fake"
    end = None
    ticks = 10 ** 9
    boom = False

    def __init__(self, args):
        if args.get("bad"):
            raise ValueError("bad args")
        self.n = 0
        self.aborted = False

    def start(self, st):
        pass

    def tick(self, st, obs):
        self.n += 1
        if FakeDriver.boom:
            raise RuntimeError("driver bug")
        if self.n > FakeDriver.ticks:
            return FakeDriver.end
        return {k: v for k, v in TARGET.items() if k != "wrist_roll.pos"}

    def abort(self):
        self.aborted = True

    def status(self):
        return {"phase": "go", "detail": f"tick {self.n}", "progress": 0.5}


def post(action, **kw):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/control", data=json.dumps({"action": action, **kw}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def status():
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/status", timeout=5) as r:
        return json.loads(r.read())


def wake_idle():
    assert post("wake")["ok"]
    until(lambda: status()["state"] == "idle" and not status()["parked"], what="idle")


def test_run_mode(monkeypatch):
    real_load = S.load_driver
    monkeypatch.setattr(S, "load_driver", lambda n: FakeDriver if n == "fake" else real_load(n))
    root = TMP / "run"
    robot, teleop, ds, st = T.make(root)
    srv = S.serve(st, PORT, host="0.0.0.0")
    st.start_thread()
    try:
        until(lambda: status()["loop_hz"] is not None, what="loop")
        assert not post("run", driver="nope")["ok"]
        assert not post("run", driver="fake", args={"bad": 1})["ok"] and status()["state"] == "idle"

        # the driver drives: follower goes to TARGET, wrist_roll holds, the leader is ignored, no recording
        robot.bus.pos["wrist_roll"] = 7.0
        assert post("run", driver="fake", args={"x": 1})["ok"]
        until(lambda: robot.bus.pos["shoulder_lift"] == 5.0, what="driver moved the arm")
        time.sleep(0.3)
        assert robot.bus.pos["wrist_roll"] == 7.0 and robot.bus.pos["gripper"] == 25.0
        s = status()
        assert s["state"] == "running" and s["run"]["driver"] == "fake" and s["run"]["args"] == {"x": 1}
        assert s["run"]["driver_status"]["phase"] == "go"
        assert not post("start")["ok"] and not post("run", driver="fake")["ok"]
        assert st.frames == 0 and ds.meta.total_episodes == 0

        # Stop: home, motors off
        assert post("stop")["ok"]
        until(lambda: status()["state"] == "parked", what="parked after stop")
        assert status()["runs"][-1]["result"] == "stopped" and not post("stop")["ok"]
        assert not post("run", driver="fake")["ok"]            # parked: Motors on first

        # KILL while running
        wake_idle()
        assert post("run", driver="fake")["ok"]
        drv = st.auto
        assert post("kill")["ok"]
        s = status()
        assert s["state"] == "killed" and drv.aborted and st.auto is None and not robot.bus.torque
        assert s["runs"][-1]["result"] == "aborted: kill"

        # Home while running
        wake_idle()
        assert post("run", driver="fake")["ok"]
        assert post("home")["ok"]
        until(lambda: status()["state"] == "parked", what="parked after home")
        assert status()["runs"][-1]["result"] == "aborted: home"

        # driver finishes (None): home, motors off; then mark it
        wake_idle()
        FakeDriver.ticks, FakeDriver.end = 5, None
        assert post("run", driver="fake")["ok"]
        until(lambda: status()["state"] == "parked", what="parked after done")
        assert status()["runs"][-1]["result"] == "done"
        assert post("mark", result="grabbed")["ok"] and status()["runs"][-1]["mark"] == "grabbed"
        assert not post("mark", result="maybe")["ok"]

        # driver finishes with {"done": "off"}: torque off in place, no KILL banner, Home refused, Motors on works
        wake_idle()
        FakeDriver.end = {"done": "off"}
        assert post("run", driver="fake")["ok"]
        until(lambda: status()["state"] == "off", what="off in place")
        s = status()
        assert not robot.bus.torque and not s["parked"] and not any("KILLED" in w for w in s["warnings"])
        assert s["runs"][-1]["then"] == "off"
        sent = robot.sent
        time.sleep(0.3)
        assert robot.sent == sent and not post("home")["ok"]
        assert post("wake")["ok"] and robot.bus.torque
        until(lambda: status()["state"] == "idle", what="idle after off")

        # driver raises: run ends, arm goes home
        FakeDriver.ticks, FakeDriver.boom = 10 ** 9, True
        assert post("run", driver="fake")["ok"]
        until(lambda: status()["state"] == "parked", what="parked after driver error")
        assert status()["runs"][-1]["result"].startswith("error: RuntimeError")
        FakeDriver.boom = False

        # cool-down while running aborts the run
        wake_idle()
        assert post("run", driver="fake")["ok"]
        robot.bus.temps["elbow_flex"] = 61
        until(lambda: status()["state"] == "cooling", what="cooling")
        assert st.auto is None and status()["runs"][-1]["result"] == "aborted: cooldown"
        robot.bus.temps["elbow_flex"] = 45
        until(lambda: status()["state"] in ("parked", "idle"), 8, "cooled")

        rows = [json.loads(x) for x in open(f"{root}-runs.jsonl")]
        assert {"id", "driver", "result", "seconds"} <= set(rows[0]) and any(r.get("mark") == "grabbed" for r in rows)
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/drivers", timeout=5) as r:
            d = json.loads(r.read())
        assert {"name": "replay", "ok": True} in d["drivers"] and isinstance(d["episodes"], list)
    finally:
        st.close()
        srv.shutdown()
    assert ds.meta.total_episodes == 0


def write_episode(root, ep, rows, task="pick the spatula"):
    (root / "data" / "chunk-000").mkdir(parents=True, exist_ok=True)
    (root / "meta" / "episodes" / "chunk-000").mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"episode_index": [ep] * len(rows), "frame_index": list(range(len(rows)))[::-1],
                  "action": [np.array(r, dtype=np.float32) for r in rows[::-1]]}).to_parquet(
        root / "data" / "chunk-000" / f"file-{ep:03d}.parquet")
    pd.DataFrame({"episode_index": [ep], "tasks": [[task]], "length": [len(rows)]}).to_parquet(
        root / "meta" / "episodes" / "chunk-000" / f"file-{ep:03d}.parquet")


def test_replay_driver():
    import replay
    root = TMP / "replay-ds"
    rows = [[float(i)] * 6 for i in range(10)]
    write_episode(root, 0, rows)
    write_episode(root, 1, [[1.0] * 6] * 3)
    (root / "data" / "chunk-000" / "file-002.parquet").write_bytes(b"still being written")
    (root / "meta" / "episodes" / "chunk-000" / "file-002.parquet").write_bytes(b"open")
    assert replay.episodes(root) == [{"episode": 0, "task": "pick the spatula", "length": 10},
                                     {"episode": 1, "task": "pick the spatula", "length": 3}]
    assert replay.load_actions(root, 0)[:, 0].tolist() == list(map(float, range(10)))  # frame order
    try:
        replay.load_actions(root, 2)
        raise AssertionError("open episode loaded")
    except ValueError as e:
        assert "not readable" in str(e)

    names = [f"{m}.pos" for m in MOTORS]
    st = type("St", (), {})()
    st.ds = type("Ds", (), {"features": {"action": {"names": names}}})()
    st.root, st.fps = root, 30
    st.joints = {m: 30.0 for m in MOTORS[:-1]}
    st.gripper = 30.0
    try:
        replay.Replay({})
        raise AssertionError("no episode accepted")
    except ValueError:
        pass
    r = replay.Replay({"episode": 0, "speed": 0.5})
    r.start(st)
    assert r.approach_n == 45                              # 30 deg gap: 1.5 s minimum at 30 Hz
    out = [r.tick(st, {}) for _ in range(r.approach_n)]
    assert out[0]["shoulder_pan.pos"] < 30.0 and out[-1] == {n: 0.0 for n in names} and r.phase == "play"
    vals = []
    while (a := r.tick(st, {})) is not None:
        vals.append(a["gripper.pos"])
    assert vals == [float(i // 2) for i in range(20)] and r.status()["progress"] == 1.0
    r2 = replay.Replay({"episode": 1, "speed": 5})
    assert r2.speed == 1.0
    r2.start(st)
    r2.abort()
    assert r2.tick(st, {}) is None
