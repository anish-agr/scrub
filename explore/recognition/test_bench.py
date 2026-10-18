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


IDS = ["scalpel", "hemostat"]


class NewScoringTests(unittest.TestCase):
    def case(self, expected, truth=None, light="normal"):
        import numpy as np
        return {"name": "t", "kind": "tray", "img": np.zeros((100, 100, 3), np.uint8), "expected": expected, "boxes": {},
                "label": "x", "light": light, "missing_truth": truth, "file": None}

    def test_missing_set_exact_match(self):
        self.assertEqual(bench.missing_set(IDS, ["hemostat"]), ["scalpel"])
        c = self.case(["hemostat"], truth=["scalpel"])
        self.assertTrue(bench.row_from_present(c, ["hemostat"], IDS)["missing_ok"])
        self.assertFalse(bench.row_from_present(c, [], IDS)["missing_ok"])  # says both missing
        self.assertFalse(bench.row_from_present(c, IDS, IDS)["missing_ok"])  # says none missing
        self.assertNotIn("missing_ok", bench.row_from_present(self.case(["hemostat"]), ["hemostat"], IDS))

    def test_detect_row_missing(self):
        c = self.case(["hemostat"], truth=["scalpel"])
        r = bench.row_from_detect(c, SETTING, [det("hemostat", [0, 0, 50, 50])], IDS)
        self.assertTrue(r["missing_ok"] and r["found"])
        r = bench.row_from_detect(c, SETTING, [det("hemostat", [0, 0, 50, 50]), det("knife", [60, 60, 90, 90])], IDS)
        self.assertFalse(r["missing_ok"])

    def test_group_by_light(self):
        rows = [{"light": "dim", "found": True, "latency": 1.0}, {"light": "dim", "found": False, "latency": 3.0},
                {"light": "bright", "found": True, "latency": 2.0}, {"found": True, "latency": 2.0}, {"light": "dim", "error": "x"}]
        g = bench.by_light(rows)
        self.assertEqual(list(g), ["bright", "dim", "unknown"])
        self.assertEqual((g["dim"]["found_rate"], g["dim"]["errors"], g["dim"]["calls"]), (0.5, 1, 3))
        self.assertEqual(g["unknown"]["calls"], 1)

    def test_per_item_and_p90(self):
        rows = [{"items": {"scalpel": {"found": True, "iou": 0.8}}}, {"items": {"scalpel": {"found": False}}}]
        self.assertEqual(bench.by_item(rows)["scalpel"], {"n": 2, "found_rate": 0.5, "iou_mean": 0.8})
        self.assertEqual(bench.percentile(list(range(1, 11)), 0.9), 9)
        self.assertEqual(bench.summarize([{"found": True, "latency": v} for v in range(1, 11)])["p90_latency_s"], 9)

    def test_crop_box(self):
        self.assertEqual(bench.tray_crop_box(SETTING, (640, 480)), [96, 72, 544, 408])  # no slots: central 70%
        s = {"items": [{"id": "a", "slot": [100, 100, 200, 200]}, {"id": "b", "slot": [300, 120, 500, 400]}, {"id": "c", "slot": None}]}
        self.assertEqual(bench.tray_crop_box(s, (640, 480)), [80, 85, 520, 415])
        tiny = {"items": [{"id": "a", "slot": [10, 10, 20, 20]}]}
        self.assertEqual(bench.tray_crop_box(tiny, (640, 480)), [96, 72, 544, 408])
        far = {"items": [{"id": "a", "slot": [3000, 3000, 4000, 4000]}]}
        self.assertEqual(bench.tray_crop_box(far, (640, 480)), [96, 72, 544, 408])

    def test_offset_detections(self):
        d = bench.offset_detections([det("knife", [1, 2, 3, 4])], 10, 20)
        self.assertEqual(bench.detection_box(d[0]), [11.0, 22.0, 13.0, 24.0])

    def test_budget(self):
        b = bench.Budget(5)
        sub = b.share(2)
        self.assertEqual(sub.total, 2)
        self.assertEqual([sub.take() for _ in range(3)], [True, True, False])
        b.used += sub.used
        self.assertEqual(b.share(1).total, 3)

    def test_run_api_stops_at_budget(self):
        c = self.case(["hemostat"])
        calls = []
        def fake(case):
            calls.append(1)
            return {"found": True, "ok": True}, 0.5
        res = bench.run_api("m", [c, c], 3, bench.Budget(4), fake)
        self.assertEqual((len(calls), res["skipped_for_budget"], res["summary"]["calls"]), (4, 2, 4))

    def test_run_api_records_errors(self):
        def boom(case):
            raise TimeoutError("slow")
        res = bench.run_api("m", [self.case(["hemostat"])], 1, bench.Budget(5), boom)
        self.assertEqual(res["summary"]["errors"], 1)

    def test_glove_scoring_with_fake_landmarker(self):
        import numpy as np
        from vision.hand import synthetic_landmarks

        class Fake:
            def __init__(self):
                self.seq = [[synthetic_landmarks(True)], [synthetic_landmarks(False)], []]
                self.n = 0
            def detect(self, bgr):
                self.n += 1
                return self.seq[(self.n - 2) % 3] if self.n > 1 else []  # first call is the warm-up

        cases = [{**self.case([], light=l), "kind": "glove", "name": f"g{l}"} for l in ("bright", "dim", "dim")]
        res = bench.run_glove(cases, Fake())
        s = res["summary"]
        self.assertEqual((s["calls"], s["found_rate"], s["open_rate"]), (3, 0.667, 0.5))
        self.assertEqual(res["by_light"]["dim"]["found_rate"], 0.5)
        self.assertIsNotNone(s["median_latency_s"])
        self.assertEqual(bench.score_glove([], 100, 100), {"found": False, "open": None, "hands": 0})

    def test_load_cases_labels_and_light(self):
        import json, tempfile
        from pathlib import Path
        import cv2, numpy as np
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            for n in ("full_1.jpg", "no_scalpel_1.jpg", "glove_blue_1.jpg", "tag_1.jpg"):
                cv2.imwrite(str(d / n), np.zeros((20, 20, 3), np.uint8))
            lab = {"full_1.jpg": {"items": IDS, "light": "dim", "label": "full"},
                   "no_scalpel_1.jpg": {"items": ["hemostat"], "label": "no_scalpel"},
                   "glove_blue_1.jpg": {"items": IDS, "light": "bright", "label": "glove_blue"},
                   "tag_1.jpg": {"items": [], "label": "tray_tag"}}
            (d / "labels.json").write_text(json.dumps(lab))
            cases = bench.load_cases(d, IDS, d)
        k = {c["file"].split("/")[-1]: c for c in cases}
        self.assertEqual(set(k), {"full_1.jpg", "no_scalpel_1.jpg", "glove_blue_1.jpg"})
        self.assertEqual((k["full_1.jpg"]["light"], k["full_1.jpg"]["missing_truth"]), ("dim", []))
        self.assertEqual((k["no_scalpel_1.jpg"]["light"], k["no_scalpel_1.jpg"]["missing_truth"]), ("unknown", ["scalpel"]))
        self.assertEqual(k["glove_blue_1.jpg"]["kind"], "glove")


if __name__ == "__main__":
    unittest.main()
