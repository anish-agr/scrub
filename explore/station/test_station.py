"""No-hardware test of the recording station: fake follower/leader/cameras, a temp dataset, the web API.

  .venv/bin/python -m pytest explore/station/test_station.py -q
  .venv/bin/python explore/station/test_station.py

Nothing here opens a serial port or a camera, and telemetry goes to a temp folder (MongoDB off).
"""
from __future__ import annotations

import atexit
import io
import json
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import station as S  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="station-test-"))
atexit.register(shutil.rmtree, TMP, True)
S.thermal_log.DIR = TMP / "thermal"          # telemetry to a temp dir ...
S.thermal_log._uri = lambda: None            # ... and never MongoDB
PORT = 8197
H, W = 48, 64                                # small frames keep the encoder fast
MOTORS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")


class FakeBus:
    def __init__(self):
        self.motors = {m: i for i, m in enumerate(MOTORS, 1)}
        self.pos = {m: 0.0 for m in MOTORS}
        self.temps = {m: 40 for m in MOTORS}
        self.torque = True
        self.fail = False
        self.is_connected = True
        self.goals = []

    def _check(self):
        if self.fail:
            raise ConnectionError("There is no status packet!")

    def sync_read(self, reg, motors=None, normalize=True):
        self._check()
        src = {"Present_Position": self.pos, "Present_Temperature": self.temps,
               "Present_Load": {m: 0 for m in MOTORS}}[reg]
        return {m: src[m] for m in (motors or MOTORS)}

    def sync_write(self, reg, vals, normalize=True):
        self._check()
        self.goals.append(dict(vals))

    def enable_torque(self, *a, **k):
        self._check()
        self.torque = True

    def disable_torque(self, *a, **k):
        self._check()
        self.torque = False

    def connect(self, *a, **k):
        self.fail, self.is_connected = False, True

    def disconnect(self, *a, **k):
        self.is_connected = False


class FakeCam:
    def __init__(self):
        self.is_connected = True


class FakeRobot:
    """Looks like SOFollower to the station; send_action plays the guard's part (park/wake, motors)."""
    name = robot_type = "so_follower"

    def __init__(self):
        self.bus = FakeBus()
        self.config = SimpleNamespace(use_degrees=True)
        self.cameras = {"side": FakeCam(), "wrist": FakeCam()}
        self.observation_features = {**{f"{m}.pos": float for m in MOTORS}, "side": (H, W, 3), "wrist": (H, W, 3)}
        self.action_features = {f"{m}.pos": float for m in MOTORS}
        self.sent = 0
        self.park_left = None
        self.drop_wrist = False

    def get_observation(self):
        self.bus._check()
        obs = {f"{m}.pos": v for m, v in self.bus.pos.items()}
        rng = np.random.default_rng(self.sent)
        obs["side"] = rng.integers(0, 255, (H, W, 3), dtype=np.uint8)
        obs["wrist"] = rng.integers(0, 255, (H, W, 3), dtype=np.uint8)
        return obs

    def send_action(self, action):
        self.bus._check()
        ui = S.arm_ui.S
        req = ui.pop("park_req", None)
        if req == "home" and self.park_left is None and not ui.get("parked"):
            self.park_left = 3
        elif req == "wake":
            if ui.get("parked"):
                self.bus.torque = True
            self.park_left = None
            ui["parked"] = False
        if self.park_left is not None:
            self.park_left -= 1
            if self.park_left <= 0:
                self.bus.torque, self.park_left, ui["parked"] = False, None, True
            return action
        if ui.get("parked"):
            return action
        self.sent += 1
        for k, v in action.items():
            self.bus.pos[k[:-4]] = v
        ui["motors"] = {m: {"temp_c": t, "load": 0, "held": False, "limp": False} for m, t in self.bus.temps.items()}
        return action

    def configure(self):
        pass

    def disconnect(self):
        self.bus.disconnect()


class FakeTeleop:
    def __init__(self):
        self.bus = FakeBus()
        self.config = SimpleNamespace(use_degrees=True)
        self.t = 0

    def get_action(self):
        self.bus._check()
        self.t += 1
        return {f"{m}.pos": float(10 * np.sin(self.t / 30 + i)) for i, m in enumerate(MOTORS)}

    def configure(self):
        pass

    def disconnect(self):
        self.bus.disconnect()


def fake_reconnect(robot, teleop):
    for d in (robot, teleop):
        d.bus.connect()
    S.A.hardware.hold_present(robot.bus)


def until(cond, timeout=10.0, what=""):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {what}")


def get(path):
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=5) as r:
        return r.read()


def status():
    return json.loads(get("/status"))


def post(action, **kw):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/control", data=json.dumps({"action": action, **kw}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def events():
    rows = []
    for p in (TMP / "thermal").glob("*.jsonl"):
        rows += [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
    return rows


def make(root, task="pick the hemostat", **kw):
    robot, teleop = FakeRobot(), FakeTeleop()
    ds = S.open_dataset(root, robot)
    st = S.Station(robot, teleop, ds, task, root, reconnect=fake_reconnect, **kw)
    return robot, teleop, ds, st


def write_video(path, frames, fps=30):
    """A small mp4 (mp4v) from BGR frames."""
    h, w = frames[0].shape[:2]
    vw = S_cv2().VideoWriter(str(path), S_cv2().VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for f in frames:
        vw.write(f)
    vw.release()
    return {"path": str(path), "from_s": 0.0, "to_s": len(frames) / fps}


def S_cv2():
    import cv2
    return cv2


def test_allowed_tasks_and_refusals():
    allowed = S.allowed_tasks()
    assert allowed[:6] == ["pick the hemostat", "return the hemostat", "pick the mayo scissors",
                           "return the mayo scissors", "pick the scalpel", "return the scalpel"]
    assert S.check_task("pick the hemostat") == (True, None)
    for bad in ("pick the spatula", "Pick the hemostat", "pick the hemostat ", ""):
        ok, why = S.check_task(bad)
        assert not ok and why, bad
    assert S.check_task("wave hello", any_task=True)[0]
    # --task at startup: refused before any log, port or hardware is touched
    with pytest.raises(SystemExit) as e:
        S.main(["--task", "pick the spatula", "--no-browser"])
    assert "pick the spatula" in str(e.value) and "pick the hemostat" in str(e.value)
    with pytest.raises(ValueError):
        make(TMP / "refused", task="pick the spatula")


def test_quick_flags():
    ok = {"camera_fps": {"side": 30.0, "wrist": 29.4}, "seconds": 12.0}
    assert S.quick_flags(ok) == []
    f = S.quick_flags({"camera_fps": {"side": 30.0, "wrist": 22.5}, "seconds": 21.0})
    assert any("wrist camera 22.5 fps" in x for x in f) and any("over 20 s" in x for x in f)
    assert any("side camera fps unknown" in x for x in S.quick_flags({"camera_fps": {"wrist": 30}, "seconds": 3}))


def test_video_qa_flags():
    rng = np.random.default_rng(0)
    good = [rng.integers(60, 200, (48, 64, 3), dtype=np.uint8) for _ in range(60)]
    res = S.video_qa({"episode_index": 0, "tasks": ["pick the hemostat"], "length": 60,
                      "videos": {"observation.images.side": write_video(TMP / "good.mp4", good)}})
    assert res["flags"] == [], res
    rep = [good[i - i % 2] for i in range(60)]           # every frame twice: a 15 fps camera
    res = S.video_qa({"episode_index": 1, "tasks": ["pick the hemostat"], "length": 60,
                      "videos": {"observation.images.wrist": write_video(TMP / "rep.mp4", rep)}})
    assert res["flags"] == ["repeated_frames"] and "under 29" in res["reasons"][0], res
    dark = [np.full((48, 64, 3), 10, np.uint8)] * 60
    res = S.video_qa({"episode_index": 2, "tasks": ["pick the hemostat"], "length": 60,
                      "videos": {"observation.images.side": write_video(TMP / "dark.mp4", dark)}})
    assert {"dark", "frozen"} <= set(res["flags"]), res
    # the same check through the subprocess the station uses (never on the loop's GIL)
    res = S.video_qa_subprocess({"episode_index": 2, "tasks": [], "length": 60,
                                 "videos": {"observation.images.side": {"path": str(TMP / "dark.mp4"),
                                                                        "from_s": 0.0, "to_s": 2.0}}})
    assert "frozen" in res["flags"]


def test_any_task_and_qa_banner():
    calls = []

    def fake_qa(ep, fps):
        calls.append(ep["episode_index"])
        return {"flags": ["dark"], "reasons": ["side: dark, luminance 12 < 40"]}

    robot, teleop, ds, st = make(TMP / "anytask", task="wave hello", any_task=True, video_qa_fn=fake_qa)
    s = st.status()
    assert s["any_task"] and not s["task_ok"]
    assert any("NOT FOR TRAINING" in w for w in s["warnings"])
    assert st.control("task", "wave goodbye")["ok"] and st.task == "wave goodbye"
    assert st.control("task", "pick the hemostat")["ok"] and st.status()["task_ok"]
    assert not any("NOT FOR TRAINING" in w for w in st.status()["warnings"])
    # QA: a quick flag shows at once; the video result is added from the background worker
    ep = {"episode_index": 7, "tasks": ["pick the hemostat"], "length": 30, "videos": {}}
    st._qa_begin(7, "pick the hemostat", {"camera_fps": {"side": 30, "wrist": 24.0}, "seconds": 5}, ep)
    s = st.status()
    assert s["last_qa"]["episode"] == 7 and s["last_qa"]["status"] == "FAIL"
    until(lambda: st.qa_idle(), what="qa worker")
    s = st.status()
    assert calls == [7] and s["last_qa"]["video_done"]
    assert s["rerecord"] == ["RE-RECORD episode 7: wrist camera 24 fps (under 29); side: dark, luminance 12 < 40"]
    assert 7 in s["counts"]["flagged_session"]
    st._qa_begin(8, "pick the hemostat", {"camera_fps": {"side": 30, "wrist": 30}, "seconds": 5}, None)
    assert st.status()["qa"][-1]["status"] == "PASS"     # no video span: quick checks only
    assert st.control("qa_ack")["ok"] and st.status()["rerecord"] == []
    qa_file = json.loads(Path(f"{TMP / 'anytask'}-station-qa.json").read_text())
    assert [e["episode"] for e in qa_file["episodes"]] == [7, 8]
    ds.finalize()


def test_cooling_rule():
    c = S.A.thermal.Cooling(resume=S.COOL_RESUME, trip=S.COOL_TRIP, plateau_s=S.COOL_PLATEAU_S)
    assert not c.done(58, now=0) and not c.done(54, now=10)
    assert not c.done(54, now=100)
    assert c.done(54, now=10 + 181)          # stuck at 54 C for 3 min
    assert S.A.thermal.Cooling(resume=50, trip=60).done(50)


def test_meta_only_dataset_moved_aside():
    root = TMP / "metaonly"
    (root / "meta").mkdir(parents=True)
    (root / "meta" / "info.json").write_text(json.dumps({"total_episodes": 0}))
    ds = S.open_dataset(root, FakeRobot())
    assert ds.meta.total_episodes == 0
    assert any(p.name.startswith("metaonly.incomplete-") for p in TMP.iterdir())
    ds.finalize()


def test_station_end_to_end():
    root = TMP / "ds"
    robot, teleop, ds, st = make(root)
    srv = S.serve(st, PORT, host="0.0.0.0")
    st.start_thread()
    try:
        assert b"Scrub Station" in get("/")
        s = status()
        assert s["state"] == "idle" and s["episodes_total"] == 0 and s["task"] == "pick the hemostat"
        assert not s["any_task"] and s["task_ok"] and s["use_degrees"] is True
        assert s["allowed_tasks"][0] == "pick the hemostat" and s["last_qa"] is None
        assert b"NOT FOR TRAINING" in get("/") and b'id="tasks"' in get("/")
        until(lambda: status()["loop_hz"] is not None, what="loop rate")

        # MJPEG stream
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/stream/side", timeout=5) as r:
            chunk = r.read(2000)
        assert b"--frame" in chunk and b"\xff\xd8" in chunk

        # start -> save
        assert post("start")["ok"]
        assert status()["state"] == "recording"
        assert not post("home")["ok"]                    # refused while recording
        assert not post("task", task="return the hemostat")["ok"]  # refused while recording
        time.sleep(1.2)
        s = status()
        assert s["frames"] > 25 and s["recording_s"] > 1.0, s
        assert post("save")["ok"]
        until(lambda: not status()["saving"], 60, "save")
        s = status()
        assert s["state"] == "idle" and s["episodes_total"] == 1 and s["episodes_session"] == 1, s
        n_ep0 = ds.meta.episodes[0]["length"] if ds.meta.episodes is not None else None

        # start -> discard
        assert post("start")["ok"]
        time.sleep(0.4)
        assert post("discard")["ok"]
        assert status()["episodes_total"] == 1 and status()["state"] == "idle"

        # kill while recording: torque off, episode discarded, start refused; wake resumes
        assert post("start")["ok"]
        time.sleep(0.3)
        assert post("kill")["ok"]
        s = status()
        assert s["state"] == "killed" and s["killed"] and not robot.bus.torque
        assert any("KILLED" in w for w in s["warnings"])
        sent = robot.sent
        time.sleep(0.3)
        assert robot.sent == sent                        # nothing sent while killed
        assert not post("start")["ok"] and not post("home")["ok"]
        assert post("wake")["ok"] and robot.bus.torque
        until(lambda: robot.sent > sent, what="following again")
        assert status()["state"] == "idle" and status()["episodes_total"] == 1

        # home -> parked -> wake
        assert post("home")["ok"]
        until(lambda: status()["state"] == "parked", what="parked")
        assert status()["parked"] and not robot.bus.torque
        assert not post("start")["ok"]
        assert post("wake")["ok"]
        until(lambda: not status()["parked"], what="unparked")
        assert status()["state"] == "idle"

        # task change: only exact settings instructions
        assert not post("task", task="pick the spatula")["ok"] and status()["task"] == "pick the hemostat"
        assert not post("task", task="pick the Hemostat")["ok"]
        assert post("task", task="return the hemostat")["ok"] and status()["task"] == "return the hemostat"
        assert post("task", task="pick the hemostat")["ok"]

        # cool-down while recording: discard, park, locked until <= 50 C, then parked
        assert post("start")["ok"]
        time.sleep(0.3)
        robot.bus.temps["elbow_flex"] = 61
        until(lambda: status()["state"] == "cooling", what="cooling")
        until(lambda: status()["parked"], what="parked for cooling")
        assert status()["episodes_total"] == 1
        assert not post("start")["ok"] and not post("wake")["ok"]
        robot.bus.temps["elbow_flex"] = 52
        time.sleep(2.5)
        assert status()["state"] == "cooling"            # 52 C is not cool enough
        robot.bus.temps["elbow_flex"] = 49
        until(lambda: status()["state"] == "parked", 6, "cooled -> parked")
        assert post("wake")["ok"]
        until(lambda: status()["state"] == "idle" and not status()["parked"], what="idle after cooling")

        # Enter in the terminal: start, then save
        stdin = io.StringIO("\n")
        S.stdin_loop(st, stdin)
        assert status()["state"] == "recording"
        time.sleep(0.6)
        S.stdin_loop(st, io.StringIO("\n"))
        until(lambda: not status()["saving"] and status()["episodes_total"] == 2, 60, "second save")
        until(lambda: st.qa_idle(), 120, "video QA")
        s = status()
        assert [r["episode"] for r in s["qa"]] == [0, 1] and s["last_qa"]["episode"] == 1
        for r in s["qa"]:
            assert r["status"] in ("PASS", "FAIL") and r["video_done"], r
            assert "error" not in (r["video"] or {}), r
            assert not set(r["video"]["flags"]) & {"dark", "frozen", "unreadable"}, r
            for cam in ("side", "wrist"):
                assert r["video"]["cameras"][cam]["frames"] > 10, r  # the saved AV1 span really decoded
        c = s["counts"]
        assert c["by_task"]["pick the hemostat"] == {"dataset": 0, "session": 2, "total": 2}
        assert c["by_task"]["return the hemostat"]["total"] == 0
        run1 = c["targets"][0]
        assert run1["done"] == 2 and (run1["min"], run1["max"]) == (30, 40)
        assert run1["tasks"]["pick the hemostat"] == {"target": 24, "done": 2}
        assert run1["tasks"]["return the hemostat"]["target"] == 12

        # toggle via the page action (Space) and a camera going down mid-episode
        assert post("toggle")["ok"] and status()["state"] == "recording"
        time.sleep(0.3)
        S.arm_ui.cfg["cams"][1] = "wrist"
        S.arm_ui.camera_down(1, True)                    # what tolerate_camera_stalls calls
        until(lambda: status()["state"] == "idle", what="discard on camera down")
        assert not post("start")["ok"]                   # blocked while a camera is down
        S.arm_ui.camera_down(1, False)
        assert status()["episodes_total"] == 2

        # bus lost while recording: error, discard, reconnect
        assert post("start")["ok"]
        time.sleep(0.3)
        robot.bus.fail = True
        until(lambda: status()["state"] == "error", what="error state")
        assert status()["episodes_total"] == 2 and any("ERROR" in w for w in status()["warnings"])
        assert not post("start")["ok"] and not post("wake")["ok"]
        assert post("reconnect")["ok"]
        until(lambda: status()["state"] == "idle" and status()["loop_hz"], what="idle after reconnect")

        # non-local POST is refused (only checkable when this Mac has a LAN address)
        ip = S.arm_ui.lan_ip()
        if ip:
            req = urllib.request.Request(f"http://{ip}:{PORT}/control", data=b'{"action":"kill"}', method="POST")
            try:
                urllib.request.urlopen(req, timeout=3)
                raise AssertionError("remote control was accepted")
            except urllib.error.HTTPError as e:
                assert e.code == 403
            except urllib.error.URLError:
                pass
            assert status()["state"] == "idle"

        # an episode open at exit is discarded, then the arm parks and the dataset is finalized
        assert post("start")["ok"]
        time.sleep(0.3)
    finally:
        st.close()
        srv.shutdown()
    assert S.arm_ui.S.get("parked") is True and not robot.bus.is_connected

    # the saved episodes load back with LeRobot
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    back = LeRobotDataset(S.REPO, root=root)
    assert back.num_episodes == 2, back.num_episodes
    for k in ("observation.state", "action", "observation.images.side", "observation.images.wrist"):
        assert k in back.features, k
    assert back.features["observation.images.side"]["shape"] == (H, W, 3)
    assert back.num_frames > 40
    item = back[0]
    assert tuple(item["observation.images.side"].shape) == (3, H, W)
    assert item["task"] == "pick the hemostat"
    if n_ep0:
        assert back.meta.episodes[0]["length"] == n_ep0
    cad = json.loads(Path(f"{root}-cadence.json").read_text())["episodes"]
    assert [e["episode_index"] for e in cad] == [0, 1]
    for e in cad:
        assert e["use_degrees"] is True and e["task"] == "pick the hemostat", e

    # telemetry
    rows = events()
    kinds = {r.get("event") for r in rows if r["kind"] == "event"}
    for k in ("episode_start", "episode_end", "episode_saved", "episode_discarded", "control", "kill",
              "cooldown_trip", "cooldown_done", "session_end"):
        assert k in kinds, k
    reasons = {r["reason"] for r in rows if r.get("event") == "episode_discarded"}
    assert {"user", "kill", "cooldown", "camera_down", "error", "exit"} <= reasons, reasons
    assert any(r["kind"] == "cooling" for r in rows)
    assert not S.thermal_log.get().mongo

    # resume the same dataset, record one more, reload
    robot2, teleop2, ds2, st2 = make(root)
    assert ds2.meta.total_episodes == 2
    assert st2.counts()["by_task"]["pick the hemostat"] == {"dataset": 2, "session": 0, "total": 2}
    st2.start_thread()
    try:
        assert st2.control("start")["ok"]
        time.sleep(0.6)
        assert st2.control("save")["ok"]
        until(lambda: not st2.saving, 60, "resume save")
    finally:
        st2.close()
    assert LeRobotDataset(S.REPO, root=root).num_episodes == 3


if __name__ == "__main__":
    test_allowed_tasks_and_refusals()
    test_quick_flags()
    test_video_qa_flags()
    test_any_task_and_qa_banner()
    test_cooling_rule()
    test_meta_only_dataset_moved_aside()
    test_station_end_to_end()
    print("all passed")
