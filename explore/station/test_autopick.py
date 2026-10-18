"""Offline tests for the AutoPick driver (no arm, no API): fake station, fake detector, real URDF IK."""
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # explore/ (arm_ui)
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
    acts, end = run(AP.AutoPick({"mode": "hold"}, detector=Det()), St())
    assert end == {"done": "off"}
    A = np.array([[a[f"{m}.pos"] for m in AP.JOINTS] for a in acts if a])
    assert np.abs(np.diff(A, axis=0)).max() * 30 <= AP.MAX_DEG_S + 0.5
    last = acts[-1]
    assert last["gripper.pos"] == 9.0 and abs(last["shoulder_lift.pos"] - AP.load_calib()["home_deg"]["shoulder_lift"]) < 0.5


def test_warm_motors_move_slower():
    d1, d2 = AP.AutoPick({"mode": "hold"}, detector=Det()), AP.AutoPick({"mode": "hold"}, detector=Det())
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


def _run_with_jaw(stall, mode="hold"):
    class S2(St):
        def __init__(self):
            super().__init__()
            self.gripper = 35.0
    d, st = AP.AutoPick({"mode": mode}, detector=Det()), S2()
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
    d, end = _run_with_jaw(10.5, mode="hold")
    assert end == {"done": "off"} and d.grip_hold == 9.0


def test_empty_close_is_a_miss_in_hold_mode():
    d, end = _run_with_jaw(3.0)
    assert end == {"done": "home"} and d.missed and d.status()["phase"] == "missed"


def test_handoff_offers_even_when_the_jaw_reads_empty():
    d, end = _run_with_jaw(3.0, mode="handoff")
    assert not d.missed and d.hand is not None  # went on to the offer (magnets can hold a thin handle)


def _handoff(take_at=None, pull_at=None, timeout=60.0):
    """Simulate a person: grabs (load jumps) at pull_at s into the offer, takes it once the jaw opens."""
    import arm_ui
    d, st = AP.AutoPick({}, detector=Det()), St()
    d.start(st)
    d._detect_thread.join(10)
    t = [0.0]
    real = AP.time.perf_counter
    AP.time.perf_counter = lambda: t[0]
    phases, end, taken = [], None, False
    try:
        for _ in range(int(120 * 30)):
            a = d.tick(st, {})
            t[0] += 1 / 30
            ph = d.status()["phase"]
            if not phases or phases[-1] != ph:
                phases.append(ph)
            if a is None or "done" in a:
                end = a
                break
            if d.hand == "release" and take_at is not None:
                taken = True  # the person takes it while the jaw is open
            stop = 3.0 if taken else 10.5  # nothing left to stop the jaw once it's taken
            if "gripper.pos" in a:
                st.gripper = max(stop, a["gripper.pos"])
            offer_t = (t[0] - d.h_t0) if d.hand == "offer" else 0
            arm_ui.S["motors"] = {"gripper": {"load": 120 if (pull_at is not None and d.hand == "offer" and offer_t > pull_at) else 20}}
    finally:
        AP.time.perf_counter = real
        arm_ui.S.pop("motors", None)
    return d, end, phases


def test_handoff_grab_release_home():
    d, end, phases = _handoff(take_at=0, pull_at=3.0)
    assert end == {"done": "home"} and d.handed, phases
    for p in ("offer", "grabbed", "release", "check", "handed over"):
        assert p in phases, phases


def test_handoff_not_taken_regrips_and_offers_again():
    d, end, phases = _handoff(take_at=None, pull_at=3.0)
    assert phases.count("offer") >= 2 and "check" in phases, phases


def test_handoff_nobody_comes_goes_home_holding():
    d, end, phases = _handoff(take_at=None, pull_at=None)
    assert end == {"done": "off"} and not d.handed and d.grip_hold is not None


def test_bad_mode():
    try:
        AP.AutoPick({"mode": "fling"}, detector=Det())
    except ValueError:
        return
    raise AssertionError("bad mode accepted")


def test_spend_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(AP, "SPEND_FILE", tmp_path / "spend.jsonl")
    assert AP.gemini_spent() == 0.0
    usd = AP._record_spend("gemini-3-flash-preview", {"promptTokenCount": 1176, "candidatesTokenCount": 26, "thoughtsTokenCount": 2759})
    assert abs(usd - 0.00894) < 1e-4 and abs(AP.gemini_spent() - usd) < 1e-9
    monkeypatch.setattr(AP, "SPEND_CAP_USD", 0.001)
    called = []
    monkeypatch.setattr("requests.post", lambda *a, **k: called.append(1))
    assert AP.gemini_box(np.zeros((480, 640, 3), np.uint8)) is None and not called  # over the cap: no request


def test_calibrate_recovers_the_table_map(tmp_path, monkeypatch):
    """Synthetic camera: tape pixel = known map of the tip (shifted up with height); the fit must recover it."""
    import cv2
    real = AP.HERE / "autopick_calib.json"
    orig = real.read_text()
    monkeypatch.setattr(AP, "FRAMES_DIR", tmp_path)
    st = St()
    d = AP.AutoPick({"mode": "calibrate"})
    d.start(st)
    h_true = np.linalg.inv(np.array(AP.load_calib()["table_H"]))

    def frame(s):
        tip = d.kin.forward(np.array([s.joints[m] for m in AP.JOINTS]))
        p = h_true @ np.array([tip[0], tip[1], 1.0])
        img = np.full((480, 640, 3), 230, np.uint8)
        cv2.circle(img, (int(p[0] / p[2]), int(p[1] / p[2] - (tip[2] + 0.022) * 300)), 9, (200, 60, 0), -1)
        return img
    d._frame = frame
    t = [0.0]
    monkeypatch.setattr(AP.time, "perf_counter", lambda: t[0])
    try:
        for _ in range(20000):
            a = d.tick(st, {})
            t[0] += 1 / 30
            if a and "done" in a:
                break
            if a:
                st.joints = {m: a[f"{m}.pos"] for m in AP.JOINTS}
        assert d.status()["phase"] == "calibrated"
        hn = np.array(AP.load_calib()["table_H"])
        p, q = hn @ np.array([530, 305, 1.0]), np.linalg.inv(h_true) @ np.array([530, 305, 1.0])
        assert np.linalg.norm(p[:2] / p[2] - q[:2] / q[2]) < 0.005
    finally:
        real.write_text(orig)
