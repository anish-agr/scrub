"""Offline checks for capture. Run: .venv/bin/python -m unittest explore.recognition.test_capture"""
import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from explore.recognition import bench, capture

IDS = ["scalpel", "hemostat", "mayo_scissors"]
SETTING = {"items": [{"id": i} for i in IDS]}


def frame(v=100):
    return np.full((48, 64, 3), v, np.uint8)


class LabelTests(unittest.TestCase):
    def test_label_map(self):
        labels = capture.label_list(SETTING)
        for want in ["full", "no_scalpel", "alone_hemostat", "grip_mayo_scissors", "glove_blue", "glove_white",
                     "count_sheet_clean", "count_sheet_written", "count_sheet_angle", "tray_tag", "pack_label",
                     "pack_label_angle"]:
            self.assertIn(want, labels)
        self.assertEqual(len(labels), len(set(labels)))
        self.assertEqual(len(labels), 1 + 9 + 8)

    def test_items(self):
        self.assertEqual(capture.items_for("full", IDS), IDS)
        self.assertEqual(capture.items_for("no_hemostat", IDS), ["scalpel", "mayo_scissors"])
        self.assertEqual(capture.items_for("alone_mayo_scissors", IDS), ["mayo_scissors"])
        self.assertEqual(capture.items_for("grip_scalpel", IDS), ["scalpel"])
        self.assertEqual(capture.items_for("tray_tag", IDS), [])

    def test_keys_unique_and_cover_real_settings(self):
        for name in ("surgical", "bench"):
            labels = capture.label_list(capture.load_setting(name))
            keys = capture.key_map(labels)
            self.assertEqual(len(keys), len(labels))
            self.assertFalse(set(keys) & set("ql[] "))

    def test_match_label(self):
        labels = capture.label_list(SETTING)
        self.assertEqual(capture.match_label("pack_label_angle_2", labels), "pack_label_angle")
        self.assertEqual(capture.match_label("pack_label_2", labels), "pack_label")
        self.assertEqual(capture.match_label("No_Scalpel IMG 4", labels), "no_scalpel")
        self.assertIsNone(capture.match_label("fullness", labels))
        self.assertIsNone(capture.match_label("IMG_1234", labels))


class FileTests(unittest.TestCase):
    def test_save_and_bench_reads(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "s"
            a = capture.save_frame(folder, "full", frame(), IDS, "overhead", "bright")
            b = capture.save_frame(folder, "full", frame(), IDS, "overhead", "dim")
            c = capture.save_frame(folder, "no_scalpel", frame(), IDS, "overhead", "normal")
            self.assertEqual((a, b), ("full_1.jpg", "full_2.jpg"))
            labels = json.loads((folder / "labels.json").read_text())
            self.assertEqual(labels[c]["items"], ["hemostat", "mayo_scissors"])
            self.assertEqual(labels[c]["boxes"], {})
            self.assertEqual((labels[b]["light"], labels[b]["camera"], labels[b]["label"]), ("dim", "overhead", "full"))
            self.assertIn("t", labels[a])
            cases = bench.load_cases(folder, IDS, Path(d))
            got = {x["name"]: x["expected"] for x in cases}
            self.assertEqual(sorted(got), ["tray:full_1.jpg", "tray:full_2.jpg", "tray:no_scalpel_1.jpg"])
            self.assertEqual(got["tray:no_scalpel_1.jpg"], ["hemostat", "mayo_scissors"])

    def test_light_validated(self):
        with self.assertRaises(ValueError):
            capture.entry_for("full", IDS, "overhead", "sunny")

    def test_import(self):
        with tempfile.TemporaryDirectory() as d:
            src, folder = Path(d) / "in", Path(d) / "out"
            src.mkdir()
            cv2.imwrite(str(src / "alone_hemostat_a.jpg"), frame())
            cv2.imwrite(str(src / "alone_hemostat_b.png"), frame(50))
            cv2.imwrite(str(src / "count_sheet_written_1.jpg"), frame())
            cv2.imwrite(str(src / "IMG_0001.jpg"), frame())
            (src / "full_1.heic").write_bytes(b"x")
            (src / "notes.txt").write_text("hi")
            saved, skipped = capture.import_folder(src, folder, capture.label_list(SETTING), IDS, "dim")
            self.assertEqual(sorted(saved), ["alone_hemostat_1.jpg", "alone_hemostat_2.jpg", "count_sheet_written_1.jpg"])
            self.assertEqual(len(skipped), 3)
            self.assertTrue(any("IMG_0001" in s for s in skipped))
            self.assertTrue(any("heic" in s for s in skipped))
            labels = json.loads((folder / "labels.json").read_text())
            self.assertEqual(labels["alone_hemostat_1.jpg"]["items"], ["hemostat"])
            self.assertEqual(labels["alone_hemostat_1.jpg"]["camera"], "phone")
            self.assertEqual(labels["count_sheet_written_1.jpg"]["light"], "dim")
            self.assertEqual(labels["count_sheet_written_1.jpg"]["items"], [])

    def test_camera_index(self):
        self.assertEqual(capture.camera_index("3"), 3)
        with self.assertRaises(ValueError):
            capture.camera_index("top")


class LiveLoopTests(unittest.TestCase):
    """run_live with a fake camera (saved images) and scripted keys: no camera, no window."""

    def test_fake_camera_and_keys(self):
        with tempfile.TemporaryDirectory() as d:
            src, folder = Path(d) / "frames", Path(d) / "out"
            src.mkdir()
            cv2.imwrite(str(src / "a.jpg"), frame(30))
            cv2.imwrite(str(src / "b.png"), frame(200))
            cap = capture.FolderCapture(src)
            self.assertTrue(cap.isOpened())
            script = iter([ord("1"), ord(" "), ord("l"), ord("2"), ord("x"), ord("]"), ord(" "), -1, ord("q")])
            shown = []
            capture.run_live(folder, capture.label_list(SETTING), IDS, "frames", "normal", cap=cap,
                             show=shown.append, wait_key=lambda: next(script))
            labels = json.loads((folder / "labels.json").read_text())
            self.assertEqual(sorted(labels), ["full_1.jpg", "full_2.jpg", "no_hemostat_1.jpg", "no_scalpel_1.jpg"])
            self.assertEqual(labels["full_2.jpg"]["light"], "normal")
            self.assertEqual(labels["no_scalpel_1.jpg"]["light"], "dim")  # "l" cycles normal -> dim
            self.assertEqual(labels["no_hemostat_1.jpg"]["items"], ["scalpel", "mayo_scissors"])
            self.assertEqual(labels["full_1.jpg"]["camera"], "frames")
            self.assertEqual(len(shown), 9)
            self.assertTrue((folder / "no_hemostat_1.jpg").exists())

    def test_empty_folder_is_not_a_camera(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(capture.FolderCapture(Path(d)).isOpened())
            with self.assertRaises(SystemExit):
                capture.run_live(Path(d) / "o", ["full"], IDS, "frames", "normal", cap=capture.FolderCapture(Path(d)),
                                 show=lambda v: None, wait_key=lambda: ord("q"))


if __name__ == "__main__":
    unittest.main()
