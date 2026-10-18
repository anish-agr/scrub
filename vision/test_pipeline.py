"""Sim source, towel tray, local detector, gripper-tip calibration, and loop timing."""

from __future__ import annotations

import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np

from vision.auto_calibrate import calibrate_frames, find_gripper_tip, paint_tip
from vision.calibrate import arm_to_pixel, calibration_from_points, parse_guided_lines
from vision.camera import FrameGrabber
from vision.local_detect import LocalDetector, occupied_crop
from vision.profile_loop import sample, serve_mjpeg, _jpeg
from vision.service import build_runtime, publish_hand, publish_tray
from vision.sim_source import SimCapture, frame_from_buffer
from vision.test_vision import RecordingPoster, _repo_with_setting
from vision.tray import fallback_setting
from vision.tray_find import find_tray_corners, register_tray


def _towel(x0, y0, x1, y1, width=640, height=480) -> np.ndarray:
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:] = (210, 40, 25)
    cv2.rectangle(frame, (x0, y0), (x1, y1), (188, 188, 188), -1)
    return frame


class _JpegServer(ThreadingHTTPServer):
    allow_reuse_address = True


def _start_jpeg_server(jpeg: bytes):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            for _ in range(8):
                try:
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n")
                except Exception:
                    return
                time.sleep(0.02)

        def log_message(self, _format, *_args):
            return

    server = _JpegServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class SimSourceTests(unittest.TestCase):
    def test_mjpeg_buffer_yields_one_frame(self):
        image = np.zeros((20, 30, 3), dtype=np.uint8)
        image[5, 5] = (0, 255, 0)
        _ok, encoded = cv2.imencode(".jpg", image)
        blob = b"junk" + encoded.tobytes() + b"tail"
        frame, rest = frame_from_buffer(blob)
        self.assertIsNotNone(frame)
        self.assertEqual(frame.shape[0], 20)
        self.assertEqual(rest, b"tail")

    def test_sim_capture_reconnects_after_the_stream_drops(self):
        image = np.full((48, 64, 3), 90, dtype=np.uint8)
        _ok, encoded = cv2.imencode(".jpg", image)
        capture = SimCapture("http://127.0.0.1:9/stream", timeout=0.4)
        ok, _frame = capture.read()
        self.assertFalse(ok)
        server = _start_jpeg_server(encoded.tobytes())
        port = server.server_address[1]
        capture.url = f"http://127.0.0.1:{port}/stream"
        capture.timeout = 2.0
        try:
            ok, frame = False, None
            for _ in range(8):
                ok, frame = capture.read()
                if ok:
                    break
                time.sleep(0.05)
            self.assertTrue(ok, capture.last_error)
            self.assertEqual(frame.shape[1], 64)
            capture.unplugged = True
            self.assertFalse(capture.read()[0])
            capture.unplugged = False
            ok, again = capture.read()
            self.assertTrue(ok)
            self.assertIsNotNone(again)
        finally:
            server.shutdown()
            capture.release()

    def test_grabber_marks_the_camera_down_and_back(self):
        image = np.full((40, 40, 3), 30, dtype=np.uint8)
        _ok, encoded = cv2.imencode(".jpg", image)
        server = _start_jpeg_server(encoded.tobytes())
        port = server.server_address[1]
        capture = SimCapture(f"http://127.0.0.1:{port}/stream", timeout=0.5)
        grabber = FrameGrabber(capture).start()
        try:
            deadline = time.monotonic() + 2
            while not grabber.reads_ok and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(grabber.reads_ok)
            capture.unplugged = True
            deadline = time.monotonic() + 2
            while grabber.reads_ok and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertFalse(grabber.reads_ok)
            capture.unplugged = False
            deadline = time.monotonic() + 2
            while not grabber.reads_ok and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(grabber.reads_ok)
        finally:
            grabber.stop()
            server.shutdown()


class TrayFindTests(unittest.TestCase):
    def test_slots_follow_the_towel_rectangle(self):
        setting = fallback_setting("surgical")
        for item in setting["items"]:
            item["slot"] = [1, 2, 3, 4]
        setting["return_spot"] = [9, 9, 10, 10]
        first = register_tray(_towel(80, 60, 280, 360), setting)
        second = register_tray(_towel(140, 90, 340, 390), setting)
        self.assertIsNotNone(first["items"][0]["slot"])
        self.assertNotEqual(first["items"][0]["slot"], [1, 2, 3, 4])
        moved = first["items"][0]["slot"][0] != second["items"][0]["slot"][0]
        self.assertTrue(moved)
        self.assertNotEqual(first["return_spot"], second["return_spot"])
        self.assertEqual(len(first["items"]), 3)

    def test_no_towel_keeps_the_settings_boxes(self):
        setting = fallback_setting("surgical")
        setting["items"][0]["slot"] = [10, 10, 40, 40]
        setting["return_spot"] = [50, 50, 80, 80]
        frame = np.full((120, 160, 3), 20, dtype=np.uint8)
        registered = register_tray(frame, setting)
        self.assertIsNone(find_tray_corners(frame))
        self.assertEqual(registered["items"][0]["slot"], [10, 10, 40, 40])
        self.assertEqual(registered["return_spot"], [50, 50, 80, 80])


class LocalDetectTests(unittest.TestCase):
    def test_empty_crop_and_a_colored_instrument(self):
        empty = np.full((40, 80, 3), 150, dtype=np.uint8)
        full = empty.copy()
        cv2.rectangle(full, (10, 8), (70, 32), (20, 20, 200), -1)
        self.assertFalse(occupied_crop(empty)[0])
        self.assertTrue(occupied_crop(full, empty)[0])

    def test_failed_detect_uses_the_local_slot_check(self):
        frame = np.full((200, 320, 3), 140, dtype=np.uint8)
        cv2.rectangle(frame, (20, 30), (100, 90), (30, 30, 210), -1)
        setting = fallback_setting("surgical")
        setting["items"][0]["slot"] = [20, 30, 100, 90]
        setting["items"][1]["slot"] = [140, 30, 220, 90]
        setting["items"][2]["slot"] = [230, 30, 300, 90]
        setting["return_spot"] = [20, 120, 100, 180]

        class Down:
            def detect(self, _frame, _categories):
                raise RuntimeError("out of credits")

        runtime = build_runtime(
            type("Cap", (), {
                "read": lambda self: (True, frame),
                "isOpened": lambda self: True,
                "set": lambda self, *_a: True,
                "get": lambda self, *_a: 0.25,
                "release": lambda self: None,
            })(),
            fake_hands=lambda _frame: [],
            detector=Down(),
            heights_path=Path(__file__).with_name("_no_heights.json"),
            calibration_path=Path(__file__).with_name("_no_cal.json"),
        )
        runtime.repo = _repo_with_setting(setting)
        runtime.poster = RecordingPoster()
        try:
            state = publish_tray(runtime)
        finally:
            runtime.grabber.stop()
        self.assertEqual(state["detector"], "local")
        self.assertFalse(state["stale"])
        self.assertTrue(state["slots"][0]["present"])
        self.assertFalse(state["slots"][1]["present"])

    def test_slow_detect_does_not_block_the_hand_loop(self):
        started = threading.Event()

        class Slow:
            def detect(self, _frame, _categories):
                started.set()
                time.sleep(0.6)
                return []

        runtime = build_runtime(
            type("Cap", (), {
                "read": lambda self: (True, np.zeros((80, 80, 3), np.uint8)),
                "isOpened": lambda self: True,
                "set": lambda self, *_a: True,
                "get": lambda self, *_a: 0.25,
                "release": lambda self: None,
            })(),
            fake_hands=lambda _frame: [],
            detector=Slow(),
            heights_path=Path(__file__).with_name("_no_heights.json"),
            calibration_path=Path(__file__).with_name("_no_cal.json"),
        )
        runtime.poster = RecordingPoster()
        worker = threading.Thread(target=publish_tray, args=(runtime,))
        worker.start()
        self.assertTrue(started.wait(1.5))
        began = time.perf_counter()
        publish_hand(runtime)
        elapsed = time.perf_counter() - began
        worker.join(timeout=2)
        runtime.grabber.stop()
        self.assertLess(elapsed, 0.25)


class AutoCalibrateTests(unittest.TestCase):
    def test_manual_lines_still_parse(self):
        image, arm = parse_guided_lines(["10 20 0.1 0.2 0.18", "30 40 0.3 0.1 0.18"])
        self.assertEqual(len(image), 2)
        self.assertEqual(arm[0][2], 0.18)

    def test_tip_fit_error_is_a_few_millimetres(self):
        seed = calibration_from_points(
            [[120, 140], [420, 140], [420, 360], [120, 360]],
            [[0.12, 0.08, 0.02], [0.32, 0.08, 0.02], [0.32, -0.10, 0.02], [0.12, -0.10, 0.02]],
        )
        homography = np.array(seed["homography"], dtype=np.float64)
        tips = [
            [0.15, 0.04, 0.02],
            [0.22, 0.01, 0.02],
            [0.28, -0.02, 0.02],
            [0.18, -0.06, 0.02],
            [0.26, 0.06, 0.02],
            [0.16, -0.01, 0.02],
        ]
        pairs = []
        for tip in tips:
            px, py = arm_to_pixel(homography, tip[0], tip[1])
            pairs.append((paint_tip(np.full((480, 640, 3), 35, dtype=np.uint8), (px, py)), tip))
            found = find_gripper_tip(pairs[-1][0])
            self.assertIsNotNone(found)
            self.assertLess(abs(found[0] - px), 3)
            self.assertLess(abs(found[1] - py), 3)
        fitted = calibrate_frames(pairs)
        self.assertLess(fitted["max_error_mm"], 8)

    def test_sim_plane_projects_inside_the_overhead_frame(self):
        try:
            import mujoco
        except ImportError:
            self.skipTest("mujoco is not installed")
        from sim import scene as sim_scene

        scene_path = sim_scene.build()
        model = mujoco.MjModel.from_xml_path(str(scene_path))
        data = mujoco.MjData(model)
        mujoco.mj_forward(model, data)
        cam = model.camera("overhead").id
        fovy = np.deg2rad(float(model.cam_fovy[cam]))
        height, width = 480, 640
        fy = (height / 2) / np.tan(fovy / 2)
        fx = fy * (width / height)

        def project(point):
            rel = data.cam_xmat[cam].reshape(3, 3).T @ (np.asarray(point) - data.cam_xpos[cam])
            if rel[2] >= -1e-6:
                return None
            depth = -rel[2]
            return width / 2 + fx * rel[0] / depth, height / 2 - fy * rel[1] / depth

        # Tray corners on the table, from sim/layout.json (center 0.24, 0; size 0.10 x 0.26).
        corners = [(0.19, -0.13, 0.006), (0.29, -0.13, 0.006), (0.29, 0.13, 0.006), (0.19, 0.13, 0.006)]
        pixels = [project(point) for point in corners]
        self.assertTrue(all(pixel is not None for pixel in pixels))
        xs = [pixel[0] for pixel in pixels]
        ys = [pixel[1] for pixel in pixels]
        self.assertTrue(min(xs) > 0 and max(xs) < width)
        self.assertGreater(max(xs) - min(xs), 40)
        self.assertGreater(max(ys) - min(ys), 40)
        frame = np.full((height, width, 3), 35, dtype=np.uint8)
        renderer = mujoco.Renderer(model, height, width)
        renderer.update_scene(data, camera="overhead")
        rendered = cv2.cvtColor(renderer.render(), cv2.COLOR_RGB2BGR)
        self.assertEqual(rendered.shape, (height, width, 3))
        tips = []
        for index, pixel in enumerate(pixels):
            tips.append((paint_tip(frame, pixel), [corners[index][0], corners[index][1], 0.02]))
        fitted = calibrate_frames(tips)
        self.assertLess(fitted["max_error_mm"], 15)
        renderer.close()


class ProfileTests(unittest.TestCase):
    def test_short_sim_source_loop_stays_bounded(self):
        server, port = serve_mjpeg(_jpeg())
        try:
            stats = sample(1.2, f"http://127.0.0.1:{port}/stream")
        finally:
            server.shutdown()
        self.assertGreater(stats["hand_fps"], 5)
        self.assertGreater(stats["detects"], 2)
        self.assertLess(stats["detect_latency_s"], 0.5)
        self.assertGreater(stats["rss_start"], 0)
        self.assertGreater(stats["rss_end"], 0)
        self.assertLess(stats["rss_end"], stats["rss_start"] * 1.5 + 80_000_000)


if __name__ == "__main__":
    unittest.main()
