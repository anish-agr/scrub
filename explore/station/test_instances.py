"""Which-one path with synthetic frames and fake motors only; LeRobot is not required."""
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import autopick as AP
import instances as I
import station as S


def hit(u, v=300, variant=None):
    value = (u, v, 0.0, [u - 30, v - 3, u + 30, v + 3])
    return (*value, variant) if variant else value


class FakeStation:
    joints = dict.fromkeys(AP.JOINTS, 0.0)
    gripper = 30.0

    def __init__(self):
        self.notes, self.events = [], []

    def note(self, msg):
        self.notes.append(msg)

    def event(self, kind, **fields):
        self.events.append({"type": kind, **fields})


def wait_for(check, timeout=2):
    deadline = time.perf_counter() + timeout
    while not check():
        assert time.perf_counter() < deadline, "worker did not publish the expected state"
        time.sleep(0.002)


@pytest.fixture
def setup_pick(monkeypatch):
    def make(hits=None, args=None):
        hits = [hit(450), hit(500)] if hits is None else hits
        st = FakeStation()
        d = AP.AutoPick(args or {}, kin=object())
        calls = []
        monkeypatch.setattr(d, "_frame", lambda st: np.zeros((480, 640, 3), np.uint8))
        monkeypatch.setattr(AP, "local_detect", lambda *a, **kw: hits)
        monkeypatch.setattr(AP, "save_example", lambda *a: None)
        monkeypatch.setattr(AP, "detect_handle", lambda *a, **kw: pytest.fail("valid local result used network"))

        def plan(st, xy):
            calls.append(xy.tolist())
            return [{"name": "raise", "from": {**st.joints, "gripper": st.gripper},
                     "to": {**st.joints, "gripper": st.gripper}, "dur": 1.0}]

        monkeypatch.setattr(d, "_make_plan", plan)
        d.start(st)
        return d, st, calls
    return make


@pytest.mark.parametrize("side,pixel", [("left", 500), ("right", 450)])
def test_two_candidates_hold_until_matching_answer(setup_pick, side, pixel):
    d, st, calls = setup_pick(args={"detector": "gemini"})
    wait_for(lambda: d.status()["question"])
    try:
        q = d.status()["question"]
        assert q["choices"] == ["left", "right"] and "image right" in q["orientation"]
        assert d.tick(st, {}) == {} and not calls and not d.plan
        assert not d.answer(st, "stale", side)[0]
        assert not d.answer(st, q["id"], "middle")[0]
        assert d.status()["question"] and not calls
        assert d.answer(st, q["id"], side)[0]
        d._detect_thread.join(2)
        assert not d._detect_thread.is_alive()
        assert d.found["pixel"][0] == pixel and len(calls) == 1
        assert d.status()["question"] is None
        assert not d.answer(st, q["id"], side)[0]  # double clicks never reselect
        assert [e["type"] for e in st.events] == ["clarify", "clarify_answer"]
        assert st.events[-1]["answer_ms"] >= 0 and st.events[-1]["question_id"] == q["id"]
    finally:
        d.abort()


@pytest.mark.parametrize("instance,pixel", [({"side": "left"}, 500), ({"side": "right"}, 450),
                                           ({"side": "closest"}, 480), ({"slot": 2}, 480)])
def test_supplied_selector_skips_question(setup_pick, instance, pixel):
    d, st, calls = setup_pick([hit(450, 310), hit(480, 285), hit(500, 305)], {"instance": instance})
    d._detect_thread.join(2)
    assert len(calls) == 1 and not st.events and d.found["pixel"][0] == pixel


def test_variant_must_be_verified_and_filters_choices(setup_pick):
    d, st, calls = setup_pick([hit(450, variant="large"), hit(500, variant="small")],
                              {"instance": {"variant": "Large"}})
    d._detect_thread.join(2)
    assert d.found["pixel"][0] == 450 and calls
    d, st, calls = setup_pick(args={"instance": {"variant": "unverified"}})
    d._detect_thread.join(2)
    assert not calls and d.tick(st, {}) == {} and d.status()["phase"] == "clarify_failed"


def test_three_candidates_closest_wording_and_answer(setup_pick):
    d, st, calls = setup_pick([hit(450, 310), hit(480, 285), hit(500, 305)])
    wait_for(lambda: d.status()["question"])
    q = d.status()["question"]
    assert q["count"] == 3 and "closest" in q["say"]
    assert not calls and d.tick(st, {}) == {}
    assert d.answer(st, q["id"], "closest")[0]
    d._detect_thread.join(2)
    assert d.found["pixel"][0] == 480


def test_timeout_clears_question_and_never_moves(setup_pick, monkeypatch):
    monkeypatch.setattr(I, "CLARIFY_TIMEOUT_S", 0.05)
    d, st, calls = setup_pick()
    wait_for(lambda: d.status()["question"])
    q = d.status()["question"]
    assert d.tick(st, {}) == {}
    d._detect_thread.join(2)
    assert not calls and not d.plan and d.status()["question"] is None
    assert d.status()["phase"] == "clarify_timeout" and d.tick(st, {}) == {}
    assert not d.answer(st, q["id"], "left")[0]


def test_abort_wakes_worker_and_late_detection_cannot_publish(setup_pick):
    d, st, calls = setup_pick()
    wait_for(lambda: d.status()["question"])
    q = d.status()["question"]
    d.abort()
    d._detect_thread.join(1)
    assert not d._detect_thread.is_alive() and not calls
    assert d.status()["question"] is None and d.tick(st, {}) is None
    assert not d.answer(st, q["id"], "left")[0]


@pytest.mark.parametrize("value", [[], {"slot": 0}, {"slot": True}, {"slot": 1.5},
                                  {"side": "middle"}, {"variant": ""}, {"unknown": 1}])
def test_invalid_selectors_refused_before_start(value):
    with pytest.raises(ValueError):
        AP.AutoPick({"instance": value}, kin=object())


def test_missing_slot_does_not_pick_another_candidate(setup_pick):
    d, st, calls = setup_pick(args={"instance": {"slot": 4}})
    d._detect_thread.join(2)
    assert not calls and d.tick(st, {}) == {} and d.status()["question"] is None


def test_conflicting_selector_holds(setup_pick):
    d, st, calls = setup_pick(args={"instance": {"side": "left", "slot": 2}})
    d._detect_thread.join(2)
    assert not calls and d.tick(st, {}) == {} and d.status()["phase"] == "clarify_failed"


def test_real_local_detector_keeps_two_close_components():
    import cv2
    img = np.full((480, 640, 3), 235, np.uint8)
    for y in (300, 315):
        cv2.line(img, (250, y), (350, y), (40, 40, 40), 3)
    H = [[0.001, 0, 0], [0, 0.001, -0.3], [0, 0, 1]]
    ws = {"x": [0.1, 0.5], "y": [-0.1, 0.1]}
    hits = AP.local_detect(img, H, ws, all_candidates=True)
    assert len(hits) == 2
    assert AP.local_detect(img, H, ws) is not None  # legacy single-target caller still works


def test_perceptron_preserves_instances_but_deduplicates_category_boxes():
    import cv2
    img = np.full((480, 640, 3), 235, np.uint8)
    boxes = [[430, 290, 495, 320], [430, 290, 495, 320], [500, 315, 565, 345]]
    for x1, y1, x2, y2 in boxes:
        cv2.line(img, (x1 + 3, y1 + 7), (x2 - 3, y1 + 7), (40, 40, 40), 4)

    class Detector:
        def detect(self, *a):
            return [{"mention": "scalpel handle", "point_box": {"top_left": {"x": b[0], "y": b[1]},
                    "bottom_right": {"x": b[2], "y": b[3]}}} for b in boxes]

    hits = AP.detect_handle(img, detector=Detector(), all_candidates=True)
    assert len(hits) == 2
    assert len(AP.detect_handle(img, detector=Detector(), in_reach=lambda u, v: u < 500, all_candidates=True)) == 1


def test_gemini_multi_instance_vote_preserves_two_of_three_rule(monkeypatch):
    a, b, wrong = [10, 20, 70, 26], [100, 50, 160, 56], [200, 80, 260, 86]
    replies = iter([[a, b], [a, wrong], [a, b]])
    monkeypatch.setattr(AP, "gemini_box", lambda *a, **kw: next(replies))
    assert AP.gemini_vote(np.zeros((1, 1, 3)), all_boxes=True) == [a, b]


def test_gemini_multi_box_adapter_and_cap(monkeypatch, tmp_path):
    monkeypatch.setattr("dotenv.dotenv_values", lambda *a: {"GEMINI_API_KEY": "offline-test-only"})
    monkeypatch.setattr(AP, "SPEND_FILE", tmp_path / "spend.jsonl")
    calls = []

    def post(*a, **kw):
        calls.append(kw["json"])
        data = {"usageMetadata": {"promptTokenCount": 1000}, "candidates": [{"content": {"parts": [
            {"text": json.dumps({"boxes_2d": [[500, 100, 600, 200], [500, 700, 600, 800]]})}]}}]}
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: data)

    monkeypatch.setattr("requests.post", post)
    img = np.zeros((480, 640, 3), np.uint8)
    assert AP.gemini_box(img, all_boxes=True) == [[64.0, 240.0, 128.0, 288.0], [448.0, 240.0, 512.0, 288.0]]
    assert "ALL matching handles" in calls[0]["contents"][0]["parts"][1]["text"]
    assert AP.gemini_spent() > 0
    monkeypatch.setattr(AP, "SPEND_CAP_USD", 0.00001)
    assert AP.gemini_box(img, all_boxes=True) is None and len(calls) == 1


def minimal_station(tmp_path, driver, fake_st):
    """Use the actual Station control/HTTP/run lifecycle without importing LeRobot or making a dataset."""
    st = S.Station.__new__(S.Station)
    st.loop_thread = None
    st.auto, st.state = driver, "running"
    st.auto_run = {"id": 1, "driver": "autopick", "args": {}, "t0": time.perf_counter()}
    st.root, st.runs = tmp_path / "fake", []
    st.killed, st.held_off = False, False
    st.robot = SimpleNamespace(bus=SimpleNamespace(disable_torque=lambda: None))
    st.note, st.event = fake_st.note, fake_st.event
    st.status = lambda: {"state": st.state, "run": st._run_status()}
    return st


def test_http_answer_payload_and_observation_hold(setup_pick, tmp_path):
    d, fake_st, calls = setup_pick()
    wait_for(lambda: d.status()["question"])
    st = minimal_station(tmp_path, d, fake_st)
    srv = S.serve(st, 0, host="127.0.0.1")
    try:
        url = f"http://127.0.0.1:{srv.server_port}"
        obs = {f"{m}.pos": float(i) for i, m in enumerate([*AP.JOINTS, "gripper"])}
        assert st._auto_step(obs) == obs and not calls  # leader is never copied during clarification
        q = json.load(urllib.request.urlopen(url + "/status"))["run"]["driver_status"]["question"]
        req = urllib.request.Request(url + "/control", method="POST", headers={"Content-Type": "application/json"},
                                     data=json.dumps({"action": "clarify_answer", "question_id": q["id"], "side": "left"}).encode())
        assert json.load(urllib.request.urlopen(req))["ok"]
        d._detect_thread.join(2)
        assert calls and d.found["pixel"][0] == 500
    finally:
        d.abort()
        srv.shutdown()
        srv.server_close()


@pytest.mark.parametrize("action", ["stop", "kill", "home", "cooldown", "exit"])
def test_station_lifecycle_clears_question(setup_pick, tmp_path, action):
    d, fake_st, calls = setup_pick()
    wait_for(lambda: d.status()["question"])
    st = minimal_station(tmp_path, d, fake_st)
    if action in ("stop", "kill", "home"):
        assert st.control(action)["ok"]
    else:
        st._auto_abort(action)
    d._detect_thread.join(1)
    assert st.auto is None and d.status()["question"] is None and not calls
    assert "question" not in (st._run_status() or {})
    assert not st.control("clarify_answer", payload={"side": "left"})["ok"]
