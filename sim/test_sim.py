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


def test_return_picks_from_return_spot_and_slots_it(arm):
    from sim import scene
    arm.reload()  # earlier tests moved items
    arm.go_home()
    assert arm.run_skill("pick the hemostat")
    rx, ry = arm.layout["return_spot"]
    assert arm.move_to(rx, ry, 0.12)
    arm.open_gripper()  # clinician sets it in the return spot
    with arm.lock:
        arm.data.mocap_pos[arm._mocap["hemostat"]][:2] = (rx, ry)
    assert arm.run_skill("return the hemostat")
    assert arm.state()["holding"] is None
    sx, sy = scene.slot_position(arm.layout, "hemostat")
    with arm.lock:
        p = arm.data.mocap_pos[arm._mocap["hemostat"]].copy()
    assert ((p[:2] - (sx, sy)) ** 2).sum() ** 0.5 < 0.02
    assert arm.gripper_position() < 0.2


def test_return_item_still_in_slot_is_false(arm):
    arm.reload()
    arm.go_home()
    assert arm.run_skill("return the scalpel") is False


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


def test_scene_items_moves_item_and_pick_follows(arm):
    import numpy as np
    arm.reload()
    arm.go_home()
    c = TestClient(create_app(arm, Grabber(arm)))
    r = c.post("/scene/items", json={"items": [
        {"id": "hemostat", "x": 0.30, "y": 0.12, "yaw": 0.5},
        {"id": "scalpel", "x": 0.9, "y": 0.0, "yaw": 0},      # out of reach
        {"id": "nope", "x": 0.25, "y": 0.0, "yaw": 0},        # unknown id
        {"id": "wire_cutters", "x": 0.25, "y": 0.0, "yaw": 0},  # not in this setting
        {"id": "mayo_scissors"},                              # missing x, y
    ]}).json()["results"]
    assert [x["ok"] for x in r] == [True, False, False, False, False]
    assert all(x["why"] for x in r[1:])
    with arm.lock:
        assert np.allclose(arm.data.mocap_pos[arm._mocap["hemostat"]][:2], (0.30, 0.12))
    assert arm.run_skill("pick the hemostat")  # from the moved spot, not the tray slot
    # picked up and lifted to ABOVE_Z over the moved spot (the slot is at y=-0.08)
    assert np.allclose(arm.tip()[:2], (0.30, 0.12), atol=0.02)
    assert arm.state()["holding"] == "hemostat"
    assert arm.set_down_safe_spot()
    assert "hemostat" not in arm.layout.get("_item_xy", {})  # placed: override gone
    c.post("/scene/items", json={"items": [{"id": "scalpel", "x": 0.3, "y": -0.1}]})
    c.post("/scene/reset")
    assert arm.layout.get("_item_xy", {}) == {}
    with arm.lock:
        assert np.allclose(arm.data.mocap_pos[arm._mocap["scalpel"]][:2], arm.layout["slots"][1])


def test_scene_setting_switches_items_without_touching_layout_file(arm):
    c = TestClient(create_app(arm, Grabber(arm)))
    try:
        assert c.post("/scene/setting", json={"setting": "bench"}).json()["setting"] == "bench"
        assert c.post("/scene/setting", json={"setting": "nope"}).status_code == 404
        r = c.post("/scene/items", json={"items": [{"id": "hex_key", "x": 0.30, "y": -0.05, "yaw": 1.0}]}).json()
        assert r["results"][0]["ok"]
        arm.go_home()
        assert arm.run_skill("pick the hex key")
        assert abs(arm.tip()[0] - 0.30) < 0.02 and abs(arm.tip()[1] + 0.05) < 0.02
        assert c.get("/layout").json()["setting"] == "surgical"  # file unchanged
    finally:
        arm.setting_override = None
        arm.reload()


def test_run_skill_accepts_hyphenated_names(arm):
    arm.setting_override = "bench"
    try:
        arm.reload()
        arm.go_home()
        assert arm.run_skill("pick the needle-nose pliers")
        assert arm.state()["holding"] == "needle_nose_pliers"
    finally:
        arm.setting_override = None
        arm.reload()
