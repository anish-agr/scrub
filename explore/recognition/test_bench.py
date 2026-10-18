"""Offline checks for the bench scoring. Run: .venv/bin/python -m unittest explore.recognition.test_bench"""
import unittest

from explore.recognition import bench

SETTING = {"items": [{"id": "scalpel", "name": "scalpel", "aliases": ["knife"]},
                     {"id": "hemostat", "name": "hemostat", "aliases": []}]}


def det(mention, box):
    return {"mention": mention, "point_box": {"top_left": {"x": box[0], "y": box[1]}, "bottom_right": {"x": box[2], "y": box[3]}}}


class ScoreTests(unittest.TestCase):
    def test_iou_and_alias(self):
        s = bench.score_detect(SETTING, [det("knife", [0, 0, 10, 10])], ["scalpel"], {"scalpel": [0, 0, 10, 12]}, (100, 100))
        self.assertTrue(s["items"]["scalpel"]["ok"])
        self.assertGreater(s["items"]["scalpel"]["iou"], 0.8)

    def test_miss_and_extra(self):
        s = bench.score_detect(SETTING, [det("hemostat", [0, 0, 10, 10])], ["scalpel"], {}, (100, 100))
        self.assertFalse(s["items"]["scalpel"]["found"])
        self.assertEqual(s["extra"], ["hemostat"])

    def test_box_sanity(self):
        self.assertTrue(bench.box_sanity([0, 0, 50, 50], 100, 100))
        self.assertFalse(bench.box_sanity([0, 0, 1, 1], 100, 100))
        self.assertFalse(bench.box_sanity([50, 50, 40, 60], 100, 100))
        self.assertFalse(bench.box_sanity(None, 100, 100))

    def test_wrong_box_without_label_uses_sanity(self):
        s = bench.score_detect(SETTING, [det("scalpel", [0, 0, 1, 1])], ["scalpel"], {}, (100, 100))
        self.assertFalse(s["items"]["scalpel"]["ok"])

    def test_tray(self):
        self.assertTrue(bench.score_tray(["a", "b"], ["b", "a"])["ok"])
        t = bench.score_tray(["a", "b"], ["a", "c"])
        self.assertEqual((t["missing"], t["extra"]), (["b"], ["c"]))

    def test_summary(self):
        rows = [{"ok": True, "found": True, "latency": 1.0}, {"ok": False, "found": True, "latency": 3.0},
                {"error": "boom"}, {"ok": None, "found": True, "latency": 2.0}]
        s = bench.summarize(rows)
        self.assertEqual((s["found_rate"], s["accuracy"], s["median_latency_s"], s["failures"]), (1.0, 0.5, 2.0, ["boom"]))

    def test_compose_boxes_inside(self):
        import numpy as np
        crops = {"scalpel": np.zeros((23, 80, 3), np.uint8)}
        img, boxes = bench.compose_tray(crops, ["scalpel", "hemostat"])
        self.assertEqual(list(boxes), ["scalpel"])
        self.assertTrue(bench.box_sanity(boxes["scalpel"], 640, 480))


if __name__ == "__main__":
    unittest.main()
