"""pytest sim/test_sim.py (from the repo root, with .venv active)"""
import threading
import time

import pytest
from fastapi.testclient import TestClient

from sim.server import Grabber, create_app
from sim.sim_arm import SimArm


@pytest.fixture(scope="module")
def arm():
    a = SimArm()
    a.connect()
    yield a
    a.disconnect()


POINTS = [(0.25, 0.0, 0.15), (0.30, -0.10, 0.12), (0.20, 0.10, 0.20), (0.35, 0.0, 0.10), (0.22, -0.05, 0.08)]


@pytest.mark.parametrize("p", POINTS)
def test_move_to_reaches_within_2cm(arm, p):
    assert arm.move_to(*p, speed=0.5)
    err = ((arm.tip() - p) ** 2).sum() ** 0.5
    assert err < 0.02


def test_out_of_region_is_false(arm):
    assert arm.move_to(0.6, 0.0, 0.1) is False
    assert arm.move_to(0.25, 0.0, 0.9) is False


def test_freeze_interrupts_within_100ms(arm):
    arm.go_home()
    out = {}
    t = threading.Thread(target=lambda: out.update(r=arm.move_to(0.35, 0.0, 0.1, speed=0.05)))
    t.start()
    time.sleep(0.5)
    t0 = time.time()
    arm.freeze()
    t.join(1)
    assert not t.is_alive() and out["r"] is False
    assert time.time() - t0 < 0.1


def test_run_skill_picks_item(arm):
    arm.go_home()
    assert arm.run_skill("pick the hemostat")
    assert arm.state()["holding"] == "hemostat"
    assert arm.gripper_position() > 0.5 and arm.gripper_load() > 0
    assert arm.set_down_safe_spot()
    assert arm.state()["holding"] is None


def test_run_skill_rejects_unknown_item(arm):
    assert arm.run_skill("pick the wire cutters") is False  # not in the surgical setting
    assert arm.run_skill("dance") is False


def test_http_reach_and_state(arm):
    c = TestClient(create_app(arm, Grabber(arm)))
    r = c.get("/reach", params={"x": 0.25, "y": 0, "z": 0.1}).json()
    assert r["reachable"] and r["error_m"] < 0.005 and len(r["q"]) == 6
    far = c.post("/reach/batch", json={"points": [[0.25, 0, 0.1], [0.9, 0, 0.1]]}).json()["results"]
    assert [x["reachable"] for x in far] == [True, False]
    s = c.get("/state").json()
    assert len(s["q"]) == 6 and len(s["names"]) == 6 and "holding" in s
    assert c.get("/layout").json()["setting"] == "surgical"


def test_camera_frames(arm):
    g = Grabber(arm)  # pytest runs on the main thread, so rendering works inline
    for cam in ("overhead", "wrist"):
        assert g.frame(cam)[:2] == b"\xff\xd8"
