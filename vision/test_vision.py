"""Fake-input checks for the vision tasks. Run: python -m vision.test_vision"""

from __future__ import annotations

import json
import math
import tempfile
import threading
import time
import unittest
from pathlib import Path

import cv2
import numpy as np

from vision.app import create_app
from vision.calibrate import calibration_from_points, palm_target, reprojection_error_m
from vision.camera import FakeCapture, exposure_is_locked, lock_controls
from vision.geometry import path_is_clear
from vision.hand import hand_is_open, palm_center, synthetic_landmarks
from vision.heights import height_for
from vision.mark_slots import boxes_from_clicks, format_for_evan, labeled_boxes
from vision.service import build_runtime, publish_hand, publish_tray, remember_clinician, start_loops
from vision.tray import FakeDetector, fallback_setting, gripper_and_obstacles, tray_from_detections


class RecordingPoster:
    def __init__(self, setting: str = "surgical"):
        self.posts = []
        self.setting = setting

    def post(self, path, payload):
        self.posts.append((path, payload))
        return True

    def current_setting(self, fallback):
        return self.setting


class ScriptDetector:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def detect(self, frame, categories):
        self.calls += 1
        if not self.script:
            return []
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def _hemostat_box(present: bool):
    if not present:
        return []
    return [
        {
            "mention": "hemostat",
            "point_box": {"top_left": {"x": 130, "y": 90}, "bottom_right": {"x": 240, "y": 130}},
        }
    ]


class CameraTests(unittest.TestCase):
    def test_lock_turns_off_auto_exposure_and_white_balance(self):
        capture = FakeCapture()
        capture.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)
        controls = lock_controls(capture, exposure=-6, white_balance=4500)
        self.assertTrue(exposure_is_locked(controls))
        self.assertEqual(controls["exposure"], -6)
        self.assertEqual(controls["wb_temperature"], 4500)

    def test_locked_exposure_does_not_jump_back_when_the_lamp_turns_on(self):
        auto = FakeCapture()
        auto.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)
        auto.lamp = 40
        _ok, dark_auto = auto.read()
        auto.lamp = 220
        _ok, bright_auto = auto.read()
        self.assertLess(abs(float(dark_auto.mean()) - float(bright_auto.mean())), 5)

        locked = FakeCapture()
        lock_controls(locked, exposure=-6)
        locked.lamp = 40
        _ok, dark = locked.read()
        locked.lamp = 220
        _ok, bright = locked.read()
        _ok, still = locked.read()
        self.assertLess(float(dark.mean()), 50)
        self.assertGreater(float(bright.mean()), 200)
        self.assertLess(abs(float(bright.mean()) - float(still.mean())), 1)


class HandTests(unittest.TestCase):
    def test_open_palm_and_closed_fist(self):
        width, height = 640, 480
        self.assertTrue(hand_is_open(synthetic_landmarks(True), width, height))
        self.assertFalse(hand_is_open(synthetic_landmarks(False), width, height))

    def test_palm_center_is_on_the_palm(self):
        center = palm_center(synthetic_landmarks(True), 640, 480)
        self.assertGreater(center[0], 250)
        self.assertLess(center[0], 420)
        self.assertGreater(center[1], 250)
        self.assertLess(center[1], 420)

    def test_hand_posts_about_ten_times_a_second_with_null_target(self):
        capture = FakeCapture()
        lock_controls(capture)
        runtime = build_runtime(
            capture,
            fake_hands=lambda _frame: [synthetic_landmarks(True)],
            detector=ScriptDetector([]),
            heights_path=Path(tempfile.mkdtemp()) / "heights.json",
            calibration_path=Path(tempfile.mkdtemp()) / "missing.json",
        )
        poster = RecordingPoster()
        runtime.poster = poster
        runtime.hand_period = 0.1
        stop = start_loops(runtime)
        time.sleep(0.75)
        stop.set()
        runtime.grabber.stop()
        hands = [payload for path, payload in poster.posts if path == "/vision/hand"]
        self.assertGreaterEqual(len(hands), 5)
        self.assertLessEqual(len(hands), 10)
        self.assertTrue(hands[-1]["seen"])
        self.assertTrue(hands[-1]["open"])
        self.assertIsNone(hands[-1]["target"])
        self.assertIsInstance(hands[-1]["palm_px"], list)
        self.assertIsInstance(hands[-1]["t"], float)


class StreamTests(unittest.TestCase):
    def test_snapshot_draws_the_palm_dot_and_slot_boxes(self):
        capture = FakeCapture()
        controls = lock_controls(capture, exposure=-6, white_balance=4500)
        setting = fallback_setting("surgical")
        setting["items"][1]["slot"] = [100, 80, 260, 160]
        detector = ScriptDetector([_hemostat_box(True)])
        runtime = build_runtime(
            capture,
            controls=controls,
            fake_hands=lambda _frame: [synthetic_landmarks(True)],
            detector=detector,
            heights_path=Path(tempfile.mkdtemp()) / "heights.json",
            calibration_path=Path(tempfile.mkdtemp()) / "missing.json",
        )
        runtime.repo = _repo_with_setting(setting)
        runtime.poster = RecordingPoster()
        publish_hand(runtime)
        publish_tray(runtime)
        encoded = runtime.preview_jpeg()
        self.assertTrue(encoded.startswith(b"\xff\xd8"))
        image = cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_COLOR)
        px, py = runtime.hand["palm_px"]
        pixel = image[py, px]
        self.assertGreater(int(pixel[0]), 200)
        self.assertGreater(int(pixel[1]), 200)
        self.assertLess(int(pixel[2]), 80)
        border = image[78:84, 110:250]
        self.assertGreater(int(border[:, :, 1].max()), 120)

        client = _client(runtime)
        response = client.get("/stream?frames=1")
        self.assertEqual(response.status_code, 200)
        self.assertIn("multipart/x-mixed-replace", response.headers["content-type"])
        self.assertIn(b"\xff\xd8", response.content)
        self.assertTrue(response.content.startswith(b"--frame"))
        health = client.get("/health").json()
        self.assertTrue(health["exposure_locked"])
        self.assertTrue(health["camera"])


class TrayTests(unittest.TestCase):
    def test_lifting_an_item_clears_the_slot_within_one_tick(self):
        capture = FakeCapture()
        lock_controls(capture)
        setting = fallback_setting("surgical")
        setting["items"][1]["slot"] = [100, 80, 260, 160]
        setting["return_spot"] = [400, 300, 520, 380]
        detector = ScriptDetector([_hemostat_box(True), _hemostat_box(False), RuntimeError("api down")])
        runtime = build_runtime(
            capture,
            fake_hands=lambda _frame: [],
            detector=detector,
            heights_path=Path(tempfile.mkdtemp()) / "heights.json",
            calibration_path=Path(tempfile.mkdtemp()) / "missing.json",
        )
        runtime.repo = _repo_with_setting(setting)
        poster = RecordingPoster()
        runtime.poster = poster
        runtime.tray_period = 1.0

        first = publish_tray(runtime)
        self.assertFalse(first["stale"])
        self.assertTrue(_slot(first, "hemostat")["present"])
        self.assertEqual(_slot(first, "hemostat")["box"], [100, 80, 260, 160])
        self.assertEqual(first["return_spot"]["item"], None)

        second = publish_tray(runtime)
        self.assertFalse(_slot(second, "hemostat")["present"])
        self.assertFalse(second["stale"])

        third = publish_tray(runtime)
        self.assertTrue(third["stale"])
        self.assertFalse(_slot(third, "hemostat")["present"])
        self.assertEqual(runtime.tray_period, 1.0)

    def test_return_spot_and_aliases(self):
        setting = fallback_setting("surgical")
        setting["items"][1]["aliases"] = ["kelly"]
        setting["items"][1]["slot"] = [100, 80, 260, 160]
        setting["return_spot"] = [400, 300, 520, 380]
        detections = [
            {
                "mention": "kelly",
                "point_box": {"top_left": {"x": 410, "y": 310}, "bottom_right": {"x": 500, "y": 360}},
            }
        ]
        state = tray_from_detections(setting, detections)
        self.assertFalse(_slot(state, "hemostat")["present"])
        self.assertEqual(state["return_spot"]["item"], "hemostat")

    def test_robot_arm_between_gripper_and_target_blocks_the_path(self):
        detections = [
            {
                "mention": "robot arm",
                "point_box": {"top_left": {"x": 200, "y": 140}, "bottom_right": {"x": 280, "y": 220}},
            },
            {
                "mention": "gripper",
                "point_box": {"top_left": {"x": 10, "y": 10}, "bottom_right": {"x": 30, "y": 30}},
            },
        ]
        gripper, obstacles = gripper_and_obstacles(detections, None)
        self.assertEqual(gripper, [20.0, 20.0])
        self.assertFalse(path_is_clear(gripper, [400, 300], obstacles))
        self.assertTrue(path_is_clear(gripper, [40, 20], obstacles))
        self.assertTrue(path_is_clear(None, [400, 300], obstacles))


class CalibrationTests(unittest.TestCase):
    def test_palm_target_is_within_2cm_and_short_of_the_palm(self):
        image_points = []
        arm_points = []
        for px, py in ((100, 80), (500, 80), (500, 400), (100, 400), (300, 200), (180, 300), (420, 140), (250, 360)):
            image_points.append([px, py])
            arm_points.append([px * 0.001, py * 0.001, 0.18])
        calibration = calibration_from_points(image_points, arm_points, hand_height_m=0.18)
        self.assertLess(calibration["max_error_m"], 0.02)
        self.assertLess(
            reprojection_error_m(np.array(calibration["homography"]), image_points, arm_points),
            0.02,
        )
        palm_px = [300, 200]
        target = palm_target(calibration, palm_px, 0.18)
        palm_xy = (0.300, 0.200)
        distance = math.hypot(target[0] - palm_xy[0], target[1] - palm_xy[1])
        self.assertAlmostEqual(distance, 0.04, delta=0.02)
        self.assertAlmostEqual(target[2], 0.18, places=3)
        self.assertLess(math.hypot(target[0], target[1]), math.hypot(*palm_xy))

    def test_saved_hand_height_changes_the_target(self):
        image_points = [[0, 0], [100, 0], [100, 100], [0, 100]]
        arm_points = [[0, 0, 0], [0.2, 0, 0], [0.2, 0.2, 0], [0, 0.2, 0]]
        calibration = calibration_from_points(image_points, arm_points)
        capture = FakeCapture()
        lock_controls(capture)
        directory = Path(tempfile.mkdtemp())
        cal_path = directory / "calibration.json"
        cal_path.write_text(json.dumps(calibration), encoding="utf-8")
        heights_path = directory / "heights.json"
        runtime = build_runtime(
            capture,
            fake_hands=lambda _frame: [synthetic_landmarks(True)],
            detector=ScriptDetector([]),
            calibration_path=cal_path,
            heights_path=heights_path,
        )
        runtime.poster = RecordingPoster()
        remember_clinician(runtime, "brandon", 0.21)
        self.assertEqual(height_for(runtime.heights, "brandon"), 0.21)
        message = publish_hand(runtime)
        self.assertIsNotNone(message["target"])
        self.assertAlmostEqual(message["target"][2], 0.21, places=3)
        runtime.grabber.stop()


class SlotMarkTests(unittest.TestCase):
    def test_scripted_clicks_print_boxes_for_all_three_roles(self):
        setting = fallback_setting("surgical")
        clicks = boxes_from_clicks(
            [
                (10, 20),
                (110, 80),
                (120, 20),
                (220, 80),
                (230, 20),
                (330, 80),
                (400, 300),
                (520, 380),
            ]
        )
        marked = labeled_boxes(setting, clicks)
        text = format_for_evan(marked)
        self.assertIn("scalpel [10, 20, 110, 80]", text)
        self.assertIn("hemostat [120, 20, 220, 80]", text)
        self.assertIn("mayo_scissors [230, 20, 330, 80]", text)
        self.assertIn("return_spot [400, 300, 520, 380]", text)
        self.assertIn("settings/surgical.json", text)


def _slot(state, item_id):
    for slot in state["slots"]:
        if slot["item"] == item_id:
            return slot
    raise AssertionError(item_id)


def _repo_with_setting(setting: dict) -> Path:
    root = Path(tempfile.mkdtemp())
    folder = root / "settings"
    folder.mkdir()
    (folder / f"{setting['id']}.json").write_text(json.dumps(setting), encoding="utf-8")
    return root


def _client(runtime):
    from fastapi.testclient import TestClient

    return TestClient(create_app(runtime))


class PreviewServerTests(unittest.TestCase):
    def test_preview_page_and_controller_contract(self):
        capture = FakeCapture()
        controls = lock_controls(capture, exposure=-6, white_balance=4500)
        runtime = build_runtime(
            capture,
            controls=controls,
            fake_hands=lambda _frame: [synthetic_landmarks(False)],
            detector=ScriptDetector([_hemostat_box(True)]),
            heights_path=Path(tempfile.mkdtemp()) / "heights.json",
            calibration_path=Path(tempfile.mkdtemp()) / "missing.json",
        )
        setting = fallback_setting("surgical")
        setting["items"][1]["slot"] = [100, 80, 260, 160]
        runtime.repo = _repo_with_setting(setting)
        received = {"hand": [], "tray": []}

        from fastapi import FastAPI

        controller = FastAPI()

        @controller.post("/vision/hand")
        def take_hand(body: dict):
            received["hand"].append(body)
            return {"ok": True}

        @controller.post("/vision/tray")
        def take_tray(body: dict):
            received["tray"].append(body)
            return {"ok": True}

        @controller.get("/state")
        def state():
            return {"setting": "surgical", "step": "idle"}

        import uvicorn

        port = _free_port()
        thread = threading.Thread(
            target=uvicorn.run,
            kwargs={"app": controller, "host": "127.0.0.1", "port": port, "log_level": "error"},
            daemon=True,
        )
        thread.start()
        deadline = time.monotonic() + 5
        import httpx

        while time.monotonic() < deadline:
            try:
                if httpx.get(f"http://127.0.0.1:{port}/state", timeout=0.2).status_code == 200:
                    break
            except Exception:
                time.sleep(0.05)
        runtime.poster = __import__("vision.service", fromlist=["Poster"]).Poster(f"http://127.0.0.1:{port}")
        publish_hand(runtime)
        publish_tray(runtime)
        self.assertEqual(received["hand"][-1]["seen"], True)
        self.assertEqual(received["hand"][-1]["open"], False)
        self.assertEqual(received["tray"][-1]["setting"], "surgical")
        self.assertTrue(_slot(received["tray"][-1], "hemostat")["present"])
        page = _client(runtime).get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("/stream", page.text)
        runtime.grabber.stop()

class ToolingTests(unittest.TestCase):
    def test_fake_mark_writes_settings_for_all_three_trays(self):
        from vision.mark_slots import main
        from vision.service import ROOT

        out = Path(tempfile.mkdtemp())
        main(["--fake", "--repo", str(ROOT), "--out", str(out)])
        for setting_id in ("surgical", "dental", "bench"):
            document = json.loads((out / f"{setting_id}.json").read_text(encoding="utf-8"))
            self.assertEqual(document["id"], setting_id)
            self.assertEqual(len(document["items"]), 3)
            for item in document["items"]:
                self.assertEqual(len(item["slot"]), 4)
                self.assertTrue(all(isinstance(value, int) for value in item["slot"]))
            self.assertEqual(len(document["return_spot"]), 4)
            original = json.loads((ROOT / "settings" / f"{setting_id}.json").read_text(encoding="utf-8"))
            self.assertIsNone(original["return_spot"])
            image = cv2.imread(str(out / f"{setting_id}.jpg"))
            self.assertIsNotNone(image)

    def test_saved_image_and_clicks_keep_the_settings_shape(self):
        from vision.mark_slots import main

        directory = Path(tempfile.mkdtemp())
        image_path = directory / "tray.jpg"
        cv2.imwrite(str(image_path), np.zeros((480, 640, 3), dtype=np.uint8))
        out = directory / "surgical.json"
        clicks = "10,20,110,80,120,20,220,80,230,20,330,80,400,300,520,380"
        main(["--setting", "surgical", "--repo", str(Path(__file__).resolve().parents[1]), "--image", str(image_path), "--clicks", clicks, "--out", str(out)])
        document = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(document["id"], "surgical")
        self.assertEqual(document["items"][0]["slot"], [10, 20, 110, 80])
        self.assertEqual(document["items"][0]["id"], "scalpel")
        self.assertEqual(document["return_spot"], [400, 300, 520, 380])
        self.assertIn("kelly", document["items"][1]["aliases"])

    def test_pairs_file_reports_centimeters_and_the_hand_post_has_a_target(self):
        import contextlib
        import io

        from vision.calibrate import load_calibration, main

        directory = Path(tempfile.mkdtemp())
        pairs = {
            "image_points": [[100, 80], [500, 80], [500, 400], [100, 400], [300, 200], [180, 300]],
            "arm_points": [
                [0.10, 0.08, 0.18],
                [0.50, 0.08, 0.18],
                [0.50, 0.40, 0.18],
                [0.10, 0.40, 0.18],
                [0.30, 0.20, 0.18],
                [0.18, 0.30, 0.18],
            ],
            "hand_height_m": 0.18,
            "image_size": [1280, 720],
            "rms_mm": 1.2,
            "names": ["m1", "m2", "m3", "m4", "m5", "m6"],
            "camera_source": "MOCK (not a real camera)",
        }
        pairs_path = directory / "pairs.json"
        pairs_path.write_text(json.dumps(pairs), encoding="utf-8")
        out = directory / "calibration.json"
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            main(["--pairs", str(pairs_path), "--out", str(out)])
        self.assertIn("cm", buffer.getvalue())
        calibration = load_calibration(out)
        self.assertLess(calibration["max_error_m"], 0.02)

        capture = FakeCapture()
        lock_controls(capture)
        runtime = build_runtime(
            capture,
            fake_hands=lambda _frame: [synthetic_landmarks(True)],
            detector=ScriptDetector([]),
            calibration_path=out,
            heights_path=directory / "heights.json",
        )
        poster = RecordingPoster()
        runtime.poster = poster
        message = publish_hand(runtime)
        runtime.grabber.stop()
        self.assertIsInstance(message["target"], list)
        self.assertEqual(len(message["target"]), 3)
        self.assertTrue(all(isinstance(value, float) for value in message["target"]))
        posted = [payload for path, payload in poster.posts if path == "/vision/hand"]
        self.assertEqual(posted[-1]["target"], message["target"])

    def test_guided_point_lines_fit(self):
        import contextlib
        import io

        from vision.calibrate import main, parse_guided_lines

        lines = [
            "0 0 0 0 0.18",
            "100 0 0.2 0 0.18",
            "100 100 0.2 0.2 0.18",
            "0 100 0 0.2 0.18",
            "50 40 0.1 0.08 0.18",
            "20 80 0.04 0.16 0.18",
        ]
        image_points, arm_points = parse_guided_lines(lines)
        self.assertEqual(len(image_points), 6)
        self.assertEqual(len(arm_points[0]), 3)
        directory = Path(tempfile.mkdtemp())
        points = directory / "points.txt"
        points.write_text("\n".join(lines) + "\n", encoding="utf-8")
        out = directory / "calibration.json"
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            main(["--points", str(points), "--out", str(out), "--hand-height", "0.18"])
        self.assertRegex(buffer.getvalue(), r"max error \d+\.\d{2} cm")
        self.assertTrue(out.exists())

    def test_lighting_csv_records_rates_per_tag(self):
        from vision.camera import FrameGrabber
        from vision.lighting import _FlakyDetector, append_csv, sample_rates

        capture = FakeCapture()
        lock_controls(capture)
        grabber = FrameGrabber(capture).start()
        try:
            sample = sample_rates(
                grabber,
                _FlakyDetector(fail_on={1, 3}),
                lambda _frame: [synthetic_landmarks(True)],
                ["hemostat"],
                0.35,
            )
        finally:
            grabber.stop()
        self.assertGreater(sample["frames"], 2)
        self.assertGreater(sample["hand_rate"], 0.9)
        self.assertGreater(sample["stale"], 0)
        self.assertLess(sample["detect_rate"], 1)
        path = Path(tempfile.mkdtemp()) / "lighting_tests.csv"
        append_csv(path, "bright", 0.35, sample)
        append_csv(path, "dim", 0.35, sample)
        rows = path.read_text(encoding="utf-8").splitlines()
        self.assertTrue(rows[0].startswith("t,lighting,"))
        self.assertIn("stale_rate", rows[0])
        self.assertIn(",bright,", rows[1])
        self.assertIn(",dim,", rows[2])


class VisionFixesTests(unittest.TestCase):
    def test_qa04_synthetic_hand_gives_real_target_in_fake_mode(self):
        capture = FakeCapture()
        lock_controls(capture)
        runtime = build_runtime(
            capture,
            fake_hands=lambda _f: [synthetic_landmarks(True)],
            detector=FakeDetector(),
            fake_calibration=True,
        )
        msg = publish_hand(runtime)
        runtime.grabber.stop()
        self.assertTrue(msg["seen"])
        self.assertIsNotNone(msg["target"])
        self.assertEqual(len(msg["target"]), 3)
        self.assertAlmostEqual(msg["target"][0], 0.22, places=2)
        self.assertAlmostEqual(msg["target"][1], -0.10, places=2)
        self.assertAlmostEqual(msg["target"][2], 0.18, places=2)
        self.assertIsNotNone(msg["target_px"])

    def test_qa05_fake_detector_detects_all_nine_instruments(self):
        detector = FakeDetector()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        # Surgical
        surg = detector.detect(frame, ["scalpel", "hemostat", "mayo scissors"])
        surg_items = {d["mention"] for d in surg}
        self.assertEqual(surg_items, {"scalpel", "hemostat", "mayo scissors"})
        # Dental
        dent = detector.detect(frame, ["mouth mirror", "explorer", "cotton pliers"])
        dent_items = {d["mention"] for d in dent}
        self.assertEqual(dent_items, {"mouth mirror", "explorer", "cotton pliers"})
        # Bench
        bench = detector.detect(frame, ["needle nose pliers", "wire cutters", "hex key"])
        bench_items = {d["mention"] for d in bench}
        self.assertEqual(bench_items, {"needle nose pliers", "wire cutters", "hex key"})
        # Total distinct items across all settings is 9
        all_items = surg_items | dent_items | bench_items
        self.assertEqual(len(all_items), 9)

    def test_qa06_slot_depletion_and_return_spot(self):
        detector = FakeDetector()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        cats = ["scalpel", "hemostat", "mayo scissors"]

        # Initial: all detected
        dets = detector.detect(frame, cats)
        mentions = [d["mention"] for d in dets]
        self.assertIn("hemostat", mentions)

        # Hemostat picked: slot emptied
        detector.empty_slot("hemostat")
        dets = detector.detect(frame, cats)
        mentions = [d["mention"] for d in dets]
        self.assertNotIn("hemostat", mentions)
        self.assertIn("scalpel", mentions)

        # Hemostat in return spot
        detector.set_return_spot("hemostat")
        dets = detector.detect(frame, cats)
        return_dets = [d for d in dets if d["point_box"]["top_left"]["x"] == 400]
        self.assertEqual(len(return_dets), 1)
        self.assertEqual(return_dets[0]["mention"], "hemostat")

        # Returned: slot filled, return spot cleared
        detector.fill_slot("hemostat")
        detector.set_return_spot(None)
        dets = detector.detect(frame, cats)
        mentions = [d["mention"] for d in dets]
        self.assertIn("hemostat", mentions)
        return_dets = [d for d in dets if d["point_box"]["top_left"]["x"] == 400]
        self.assertEqual(len(return_dets), 0)

    def test_v1_mark_slots_fake_mode_all_three_trays(self):
        from vision.mark_slots import apply_boxes_to_setting, mark_setting
        from vision.tray import load_setting

        tmp = Path(tempfile.mkdtemp())
        for setting_id in ["surgical", "dental", "bench"]:
            out_file = tmp / f"marked_{setting_id}.json"
            marked = mark_setting(setting_id, repo=Path("."), fake=True, out_path=out_file)
            self.assertEqual(len(marked["slots"]), 3)
            self.assertEqual(len(marked["return_spot"]), 4)
            self.assertTrue(out_file.exists())

            setting = load_setting(Path("."), setting_id)
            applied = apply_boxes_to_setting(setting, marked)
            for item in applied["items"]:
                self.assertIsNotNone(item["slot"])
                self.assertEqual(len(item["slot"]), 4)
            self.assertIsNotNone(applied["return_spot"])
            self.assertEqual(len(applied["return_spot"]), 4)

    def test_v2_calibrate_page42_pairs_and_rms_error(self):
        from vision.calibrate import main as cal_main, reprojection_error_m, rms_error_m

        tmp = Path(tempfile.mkdtemp())
        pairs_file = tmp / "pairs.json"
        out_cal = tmp / "calibration.json"
        pairs_data = {
            "image_points": [[100, 80], [500, 80], [500, 400], [100, 400], [300, 240]],
            "arm_points": [[0.10, 0.08, 0.18], [0.50, 0.08, 0.18], [0.50, 0.40, 0.18], [0.10, 0.40, 0.18], [0.30, 0.24, 0.18]],
            "hand_height_m": 0.18,
            "rms_mm": 0.1,
        }
        pairs_file.write_text(json.dumps(pairs_data), encoding="utf-8")
        cal_main(["--pairs", str(pairs_file), "--out", str(out_cal)])
        self.assertTrue(out_cal.exists())
        cal = json.loads(out_cal.read_text(encoding="utf-8"))
        self.assertIn("rms_error_m", cal)
        self.assertIn("max_error_m", cal)
        self.assertLess(cal["max_error_m"], 0.02)
        self.assertLess(cal["rms_error_m"], 0.02)

    def test_v3_lighting_test_mode_and_csv(self):
        from vision.hand import HandTracker
        from vision.lighting import run_lighting_test

        capture = FakeCapture()
        lock_controls(capture)
        grabber = __import__("vision.camera", fromlist=["FrameGrabber"]).FrameGrabber(capture).start()
        tracker = HandTracker(None)
        tracker.detect = lambda _f: [synthetic_landmarks(True)]
        detector = FakeDetector()
        tmp_csv = Path(tempfile.mkdtemp()) / "lighting_test.csv"
        try:
            res = run_lighting_test(
                grabber,
                detector,
                tracker,
                ["scalpel", "hemostat"],
                label="normal",
                duration_s=0.25,
                out_csv=tmp_csv,
            )
            self.assertEqual(res["lighting"], "normal")
            self.assertGreater(res["detection_rate"], 0.8)
            self.assertGreater(res["hand_tracking_rate"], 0.8)
            self.assertEqual(res["stale_rate"], 0.0)
            self.assertTrue(tmp_csv.exists())
        finally:
            grabber.stop()

    def test_f5_lighting_classification_and_publishing(self):
        from vision.service import classify_lighting, publish_lighting

        self.assertEqual(classify_lighting(200.0)[0], "bright")
        self.assertEqual(classify_lighting(120.0)[0], "normal")
        self.assertEqual(classify_lighting(40.0)[0], "dim")

        capture = FakeCapture()
        lock_controls(capture)
        runtime = build_runtime(capture, fake_hands=lambda _f: [], detector=FakeDetector())
        poster = RecordingPoster()
        runtime.poster = poster
        res = publish_lighting(runtime)
        runtime.grabber.stop()
        self.assertIn("lighting", res)
        self.assertIn("lux", res)
        posted = [p for path, p in poster.posts if path == "/lighting"]
        self.assertEqual(len(posted), 1)

        client = _client(runtime)
        resp = client.get("/lighting")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("lighting", resp.json())

    def test_f6_draw_annotations_boxes_confidence_return_spot_target(self):
        from vision.draw import annotate

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        hand = {
            "seen": True,
            "open": True,
            "palm_px": [320, 240],
            "target_px": [300, 220],
            "path_clear": True,
        }
        tray = {
            "slots": [{"item": "hemostat", "present": True, "box": [100, 80, 240, 140]}],
            "return_spot": {"item": "scalpel", "box": [400, 300, 520, 380]},
        }
        detections = [
            {
                "mention": "hemostat",
                "confidence": 0.94,
                "point_box": {"top_left": {"x": 100, "y": 80}, "bottom_right": {"x": 240, "y": 140}},
            }
        ]
        annotated = annotate(frame, hand, tray, detections)
        self.assertEqual(annotated.shape, (480, 640, 3))
        # Non-black pixels drawn
        self.assertGreater(int(annotated.sum()), 1000)


def _free_port() -> int:
    import socket

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


if __name__ == "__main__":
    unittest.main()
