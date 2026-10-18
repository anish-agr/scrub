"""Tests for vision/locate.py: item pose, safe zone, and the two routes. Fakes only, no network."""

from __future__ import annotations

import threading
import time
import unittest
from types import SimpleNamespace

import cv2
import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vision import locate as L
from vision.calibrate import calibration_from_points
from vision.local_detect import LocalDetector

SLOT = [100, 80, 300, 140]  # 200 x 60, long axis horizontal


def make_setting(slot=SLOT):
    return {"id": "surgical", "items": [
        {"id": "hemostat", "name": "hemostat", "aliases": [], "slot": slot},
        {"id": "scalpel", "name": "scalpel", "aliases": [], "slot": None},
    ], "return_spot": None}


def make_frame(angle=20.0, shift=(12, 0), present=True):
    frame = np.full((400, 480, 3), 225, np.uint8)  # light tray
    if present:
        cx, cy = 200 + shift[0], 110 + shift[1]
        rect = ((cx, cy), (160, 18), angle)
        cv2.fillPoly(frame, [cv2.boxPoints(rect).astype(np.int32)], (40, 40, 40))
    return frame


def det(mention, box):
    return {"mention": mention, "point_box": {"top_left": {"x": box[0], "y": box[1]}, "bottom_right": {"x": box[2], "y": box[3]}}}


class FakeDet:
    def __init__(self, detections):
        self.detections, self.calls = detections, 0

    def detect(self, frame, categories):
        self.calls += 1
        return self.detections


class Gem:
    def __init__(self, answer):
        self.answer, self.calls = answer, 0

    def __call__(self, jpeg, name, slot):
        self.calls += 1
        assert jpeg[:2] == b"\xff\xd8"
        return self.answer


class LocateTests(unittest.TestCase):
    def test_local_finds_yaw_and_offset_sign(self):
        gem = Gem(None)
        out = L.locate(make_frame(), make_setting(), "hemostat", gemini=gem)
        self.assertTrue(out["found"])
        self.assertEqual(out["method"], "local")
        self.assertAlmostEqual(out["yaw_deg"], 20, delta=5)
        self.assertGreater(out["offset_px"][0], 8)  # shifted right by 12
        self.assertGreater(out["offset_mm"][0], 0)
        self.assertAlmostEqual(out["center_px"][0], 212, delta=4)
        self.assertEqual(out["slot_center_px"], [200.0, 110.0])
        self.assertIsNone(out["agree"])
        self.assertIsNone(out["arm_xy"])
        self.assertGreaterEqual(out["confidence"], 0.5)
        self.assertEqual(gem.calls, 0)

    def test_negative_yaw_and_left_shift(self):
        out = L.locate(make_frame(-30, (-10, 0)), make_setting(), "hemostat", gemini=Gem(None))
        self.assertAlmostEqual(out["yaw_deg"], -30, delta=5)
        self.assertLess(out["offset_px"][0], -6)

    def test_agree_does_not_call_gemini(self):
        gem = Gem({"found": True, "center_px": [1, 1], "yaw_deg": 0})
        det_ok = FakeDet([det("hemostat", [132, 90, 292, 130])])  # centre (212, 110)
        out = L.locate(make_frame(), make_setting(), "hemostat", detector=det_ok, gemini=gem)
        self.assertTrue(out["agree"])
        self.assertEqual(gem.calls, 0)
        self.assertEqual(det_ok.calls, 1)
        self.assertGreaterEqual(out["confidence"], 0.9)

    def test_disagree_calls_gemini_and_uses_its_answer(self):
        gem = Gem({"found": True, "center_px": [213.0, 111.0], "yaw_deg": 18.0})
        far = FakeDet([det("hemostat", [250, 200, 330, 240])])
        out = L.locate(make_frame(), make_setting(), "hemostat", detector=far, gemini=gem)
        self.assertFalse(out["agree"])
        self.assertEqual(gem.calls, 1)
        self.assertEqual(out["method"], "gemini")
        self.assertEqual(out["yaw_deg"], 18.0)
        self.assertGreaterEqual(out["confidence"], 0.8)  # gemini sides with local

    def test_one_says_absent_calls_gemini_and_none_still_answers_lower(self):
        gem = Gem(None)
        empty = FakeDet([])
        out = L.locate(make_frame(), make_setting(), "hemostat", detector=empty, gemini=gem)
        self.assertFalse(out["agree"])
        self.assertEqual(gem.calls, 1)
        self.assertTrue(out["found"])
        self.assertEqual(out["method"], "local")
        self.assertLess(out["confidence"], 0.5)

    def test_empty_slot_is_not_found(self):
        out = L.locate(make_frame(present=False), make_setting(), "hemostat", gemini=Gem(None))
        self.assertFalse(out["found"])
        self.assertEqual(out["method"], "none")
        self.assertEqual(out["confidence"], 0)

    def test_gemini_rescues_an_empty_looking_slot(self):
        gem = Gem({"found": True, "center_px": [205, 112], "yaw_deg": 5})
        out = L.locate(make_frame(present=False), make_setting(), "hemostat", gemini=gem)
        self.assertTrue(out["found"])
        self.assertEqual(out["method"], "gemini")

    def test_no_slot_means_none(self):
        out = L.locate(make_frame(), make_setting(), "scalpel", gemini=Gem(None))
        self.assertFalse(out["found"])
        self.assertEqual(out["method"], "none")
        self.assertIsNone(out["slot_center_px"])
        self.assertFalse(L.locate(make_frame(), make_setting(), "nope")["found"])

    def test_calibration_fills_arm_fields(self):
        img = [[0, 0], [480, 0], [480, 400], [0, 400]]
        arm = [[0.30, -0.24, 0], [0.30, 0.24, 0], [0.10, 0.24, 0], [0.10, -0.24, 0]]
        cal = calibration_from_points(img, arm)
        out = L.locate(make_frame(), make_setting(), "hemostat", calibration=cal, gemini=Gem(None))
        self.assertEqual(len(out["arm_xy"]), 2)
        self.assertEqual(len(out["arm_offset"]), 2)
        self.assertGreater(out["arm_offset"][1], 0.005)  # +12 px right is +y, 0.001 m per px
        self.assertAlmostEqual(out["arm_offset"][1], 0.012, delta=0.004)

    def test_tray_tag_sets_setting_ok(self):
        ok = L.locate(make_frame(), make_setting(), "hemostat", gemini=Gem(None), tray_tag={"tray": "surgical"})
        bad = L.locate(make_frame(), make_setting(), "hemostat", gemini=Gem(None), tray_tag={"tray": "dental"})
        self.assertTrue(ok["setting_ok"])
        self.assertFalse(bad["setting_ok"])
        self.assertEqual(bad["tray"], "dental")

    def test_slow_detector_is_cut_off(self):
        class Slow:
            def detect(self, frame, categories):
                time.sleep(2)
                return []

        started = time.monotonic()
        out = L.locate(make_frame(), make_setting(), "hemostat", detector=Slow(), gemini=Gem(None), budget_s=0.3)
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertTrue(out["found"])

    def test_default_gemini_without_key_is_none(self):
        import os
        old = os.environ.pop("GEMINI_API_KEY", None)
        try:
            self.assertIsNone(L.ask_gemini(b"x", "hemostat", SLOT))
        finally:
            if old is not None:
                os.environ["GEMINI_API_KEY"] = old

    def test_multiple_detections_clarify_instead_of_nearest_slot_guess(self):
        detector = FakeDet([det("hemostat", [130, 90, 290, 130]), det("hemostat", [320, 180, 460, 220])])
        gem = Gem({"found": True, "center_px": [200, 110], "yaw_deg": 0})
        out = L.locate(make_frame(), make_setting(), "hemostat", detector=detector, gemini=gem)
        self.assertFalse(out["found"])
        self.assertTrue(out["ambiguous"])
        self.assertEqual([c["side"] for c in out["candidates"]], ["left", "right"])
        self.assertIsNone(out["center_px"])
        self.assertEqual(gem.calls, 0)  # Gemini must not silently choose for the surgeon

    def test_right_hint_uses_right_detection_not_local_or_nearest_slot(self):
        detector = FakeDet([det("hemostat", [130, 90, 290, 130]), det("hemostat", [320, 180, 460, 220])])
        cal = calibration_from_points([[0, 0], [480, 0], [480, 400], [0, 400]],
                                      [[0.30, -0.24, 0], [0.30, 0.24, 0], [0.10, 0.24, 0], [0.10, -0.24, 0]])
        out = L.locate(make_frame(), make_setting(), "hemostat", detector=detector, gemini=Gem(None),
                       calibration=cal, instance={"side": "right"})
        self.assertTrue(out["found"])
        self.assertTrue(out["instance_validated"])
        self.assertEqual(out["center_px"], [390, 200])
        self.assertEqual(out["instance"], {"side": "right", "slot": 2})
        self.assertGreater(out["arm_xy"][1], 0.1)

    def test_closest_uses_surgeon_bottom_orientation_and_ties_do_not_guess(self):
        detector = FakeDet([det("hemostat", [10, 10, 50, 30]), det("hemostat", [100, 180, 140, 210]),
                            det("hemostat", [320, 60, 460, 100])])
        out = L.locate(make_frame(), make_setting(), "hemostat", detector=detector, instance={"side": "closest"})
        self.assertTrue(out["found"])
        self.assertEqual(out["center_px"], [120, 195])
        self.assertEqual(out["instance"]["slot"], 2)
        detector.detections[2] = det("hemostat", [320, 180, 460, 210])
        tied = L.locate(make_frame(), make_setting(), "hemostat", detector=detector, instance={"side": "closest"})
        self.assertFalse(tied["found"])
        self.assertTrue(tied["ambiguous"])

    def test_conflicting_hint_and_overlapping_detections_fail_closed(self):
        detector = FakeDet([det("hemostat", [10, 10, 50, 30]), det("hemostat", [320, 60, 460, 100])])
        out = L.locate(make_frame(), make_setting(), "hemostat", detector=detector, instance={"side": "right", "slot": 1})
        self.assertFalse(out["found"])
        detector.detections[1] = det("hemostat", [20, 15, 60, 40])
        out = L.locate(make_frame(), make_setting(), "hemostat", detector=detector, instance={"slot": 1})
        self.assertFalse(out["found"])
        self.assertTrue(out["ambiguous"])

    def test_named_variant_is_validated_from_settings(self):
        setting = make_setting()
        setting["items"][0]["variant"] = "curved"
        out = L.locate(make_frame(), setting, "hemostat", detector=FakeDet([det("hemostat", [132, 90, 292, 130])]),
                       instance={"variant": "curved"})
        self.assertTrue(out["found"])
        self.assertTrue(out["instance_validated"])


class SafeZoneTests(unittest.TestCase):
    def setUp(self):
        img = [[0, 0], [480, 0], [480, 400], [0, 400]]
        arm = [[0.30, -0.24, 0], [0.30, 0.24, 0], [0.10, 0.24, 0], [0.10, -0.24, 0]]
        self.cal = calibration_from_points(img, arm)
        # zone centred at arm (0.20, 0.0) -> about pixel (240, 200), 0.10 m square -> about 100 px
        self.rig = {"safe_zone": {"center": [0.20, 0.0, 0.0], "size": [0.10, 0.10], "yaw_deg": 0.0}}

    def check(self, **kw):
        return L.safe_zone_check(make_frame(), make_setting(), calibration=self.cal, rig=self.rig, **kw)

    def test_clear(self):
        out = self.check(detections=[], hand={"seen": False, "palm_px": None})
        self.assertIs(out["clear"], True)
        self.assertEqual(out["blocked_by"], [])
        self.assertIsNone(out["item_in_zone"])
        self.assertEqual(out["method"], "perceptron")

    def test_hand_blocks(self):
        out = self.check(detections=[], hand={"seen": True, "palm_px": [240, 200]})
        self.assertIs(out["clear"], False)
        self.assertEqual(out["blocked_by"], ["hand"])
        far = self.check(detections=[], hand={"seen": True, "palm_px": [20, 20]})
        self.assertIs(far["clear"], True)

    def test_item_in_zone(self):
        out = self.check(detections=[det("hemostat", [220, 180, 260, 220]), det("scalpel", [5, 5, 30, 30])])
        self.assertIs(out["clear"], False)
        self.assertEqual(out["item_in_zone"], "hemostat")
        self.assertEqual(out["blocked_by"], ["hemostat"])

    def test_no_detections_is_local_hand_only(self):
        out = self.check(hand=None)
        self.assertIs(out["clear"], True)
        self.assertEqual(out["method"], "local")

    def test_no_calibration_is_unknown(self):
        out = L.safe_zone_check(make_frame(), make_setting(), rig=self.rig, detections=[])
        self.assertIsNone(out["clear"])
        self.assertEqual(out["method"], "none")

    def test_safe_zone_px_works_without_calibration(self):
        setting = make_setting()
        setting["safe_zone_px"] = [350, 250, 450, 350]
        out = L.safe_zone_check(None, setting, detections=[det("scalpel", [380, 280, 420, 320])])
        self.assertEqual(out["item_in_zone"], "scalpel")


class RouteTests(unittest.TestCase):
    def make_client(self, frame=None, setting=None, **runtime_kw):
        setting = setting or make_setting()
        rt = SimpleNamespace(
            grabber=SimpleNamespace(latest=lambda: None if frame is None else (frame, time.time())),
            poster=SimpleNamespace(get_json=lambda path: setting, current_setting=lambda fb: "surgical"),
            lock=threading.Lock(), tray=None, hand=None, detections=[], detector=FakeDet([]),
            local_detector=LocalDetector(), calibration=None, repo=L.ROOT, setting_id="surgical",
        )
        for k, v in runtime_kw.items():
            setattr(rt, k, v)
        app = FastAPI()
        L.register(app, rt)
        app.state.locate_hooks = {"detector": FakeDet([]), "gemini": Gem(None), "tag_reader": lambda img: {"tray": "surgical"}}
        return TestClient(app), app, rt

    def test_locate_route(self):
        client, app, _rt = self.make_client(make_frame())
        app.state.locate_hooks["detector"] = FakeDet([det("hemostat", [132, 90, 292, 130])])
        body = client.get("/locate", params={"item": "hemostat"}).json()
        self.assertTrue(body["found"])
        self.assertTrue(body["agree"])
        self.assertAlmostEqual(body["yaw_deg"], 20, delta=5)
        time.sleep(0.2)  # the tag refresh runs in the background
        self.assertEqual(client.get("/locate", params={"item": "hemostat"}).json()["tray"], "surgical")

    def test_locate_route_never_500(self):
        client, _app, _rt = self.make_client(frame=None)
        r = client.get("/locate", params={"item": "hemostat"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["found"])
        self.assertIn("error", r.json())
        client2, app2, _ = self.make_client(make_frame())

        class Boom:
            def detect(self, *a):
                raise RuntimeError("boom")

        app2.state.locate_hooks["detector"] = Boom()
        r = client2.get("/locate", params={"item": "hemostat"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(client2.get("/locate").status_code, 200)

    def test_locate_route_forwards_instance_queries(self):
        client, app, _rt = self.make_client(make_frame())
        app.state.locate_hooks["detector"] = FakeDet([det("hemostat", [10, 10, 50, 30]),
                                                         det("hemostat", [320, 60, 460, 100])])
        out = client.get("/locate", params={"item": "hemostat", "side": "right", "slot": 2}).json()
        self.assertTrue(out["found"])
        self.assertEqual(out["center_px"], [390, 80])
        wrong = client.get("/locate", params={"item": "hemostat", "slot": 99}).json()
        self.assertFalse(wrong["found"])
        self.assertTrue(wrong["ambiguous"])

    def test_safe_zone_route(self):
        client, _app, _rt = self.make_client(make_frame())
        body = client.get("/safe_zone").json()
        self.assertEqual(body["method"], "none")
        self.assertIsNone(body["clear"])
        setting = make_setting()
        setting["safe_zone_px"] = [350, 250, 450, 350]
        client, _app, rt = self.make_client(make_frame(), setting=setting)
        rt.hand = {"seen": True, "palm_px": [400, 300]}
        body = client.get("/safe_zone").json()
        self.assertIs(body["clear"], False)
        self.assertEqual(body["blocked_by"], ["hand"])

    def test_safe_zone_route_never_500(self):
        client, _app, rt = self.make_client(make_frame())
        rt.poster = SimpleNamespace()  # breaks setting_document
        r = client.get("/safe_zone")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.json()["clear"])


if __name__ == "__main__":
    unittest.main()
