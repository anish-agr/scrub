"""Offline tests for the AutoPick driver (no arm, no API): fake station, fake detector, real URDF IK."""
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import autopick as AP  # noqa: E402


class Det:
    def __init__(self, box=(434, 278, 502, 326)):
        self.box = box

    def detect(self, img, cats):
        if self.box is None:
            return []
        x1, y1, x2, y2 = self.box
        return [{"mention": "scalpel handle", "point_box": {"top_left": {"x": x1, "y": y1}, "bottom_right": {"x": x2, "y": y2}}}]


class St:
    joints = {"shoulder_pan": 2.8, "shoulder_lift": -100.0, "elbow_flex": 97.7, "wrist_flex": 72.3, "wrist_roll": -9.3}
    gripper = 4.8

    def __init__(self, hot=False):
        self.hot, self.notes = hot, []
        self.gripper = 35.0

    def temps(self):
        return {"gripper": 56 if self.hot else 45}

    def jpeg(self, cam):
        import cv2
        img = np.full((480, 640, 3), 235, np.uint8)
        cv2.line(img, (440, 305), (500, 300), (40, 40, 40), 4)  # a dark handle on a white sheet
        return cv2.imencode(".jpg", img)[1].tobytes()

    def note(self, m):
        self.notes.append(m)


def run(driver, st):
    driver.start(st)
    driver._detect_thread.join(10)
    t = [0.0]
    real = AP.time.perf_counter
    AP.time.perf_counter = lambda: t[0]
    acts, end = [], None
    try:
        for _ in range(20000):
            a = driver.tick(st, {})
            t[0] += 1 / 30
            if a is None or "done" in a:
                end = a
                break
            acts.append(a)
            if a and "gripper.pos" in a:
                st.gripper = max(10.5, a["gripper.pos"])  # the handle stops the jaw
    finally:
        AP.time.perf_counter = real
    return acts, end


def test_full_pick_is_smooth_and_ends_off():
    acts, end = run(AP.AutoPick({}, detector=Det()), St())
    assert end == {"done": "off"}
    A = np.array([[a[f"{m}.pos"] for m in AP.JOINTS] for a in acts if a])
    assert np.abs(np.diff(A, axis=0)).max() * 30 <= AP.MAX_DEG_S + 0.5
    last = acts[-1]
    assert last["gripper.pos"] == 9.0 and abs(last["shoulder_lift.pos"] - AP.load_calib()["home_deg"]["shoulder_lift"]) < 0.5


def test_warm_motors_move_slower():
    d1, d2 = AP.AutoPick({}, detector=Det()), AP.AutoPick({}, detector=Det())
    a1, _ = run(d1, St())
    a2, _ = run(d2, St(hot=True))
    assert len(a2) > len(a1) * 1.4


def test_no_handle_goes_home():
    d = AP.AutoPick({}, detector=Det(box=None))
    acts, end = run(d, St())
    assert end == {"done": "home"} and d.status()["phase"] == "failed"


def test_out_of_reach_refused():
    d = AP.AutoPick({}, detector=Det(box=(0, 0, 30, 30)))
    _acts, end = run(d, St())
    assert end == {"done": "home"} and "outside" in d.status()["detail"]


def test_abort_is_instant():
    d = AP.AutoPick({}, detector=Det())
    d.start(St())
    d.abort()
    assert d.tick(St(), {}) is None


def test_bad_args():
    try:
        AP.AutoPick({"label": ""}, detector=Det())
    except ValueError:
        return
    raise AssertionError("empty label accepted")


def _run_with_jaw(stall):
    class S2(St):
        def __init__(self):
            super().__init__()
            self.gripper = 35.0
    d, st = AP.AutoPick({}, detector=Det()), S2()
    d.start(st)
    d._detect_thread.join(10)
    t = [0.0]
    real = AP.time.perf_counter
    AP.time.perf_counter = lambda: t[0]
    try:
        for _ in range(5000):
            a = d.tick(st, {})
            t[0] += 1 / 30
            if a is None or "done" in a:
                return d, a
            if "gripper.pos" in a:
                st.gripper = max(stall, a["gripper.pos"])
    finally:
        AP.time.perf_counter = real


def test_handle_in_jaw_holds_gentle_squeeze():
    d, end = _run_with_jaw(10.5)
    assert end == {"done": "off"} and d.grip_hold == 9.0


def test_empty_close_is_a_miss():
    d, end = _run_with_jaw(3.0)
    assert end == {"done": "home"} and d.missed and d.status()["phase"] == "missed"
