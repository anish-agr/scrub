"""Reading bench scoring and the camera simulation, no API. Run: .venv/bin/python -m unittest explore.recognition.test_read_bench"""
import json
import unittest
from pathlib import Path

import cv2

from explore.recognition import read_bench as rb

PROPS = Path(__file__).resolve().parent / "props"
TRUTH = json.loads((PROPS / "truth.json").read_text())["files"]


class FakeOCR:
    name = "perceptron"

    def __init__(self, answer):
        self.answer = answer

    def extract(self, jpeg, prompt, schema, schema_name):
        return self.answer


class ScoreTests(unittest.TestCase):
    def test_count_sheet_exact_and_wrong_cell(self):
        t = TRUTH["count_sheet_surgical_filled.png"]
        items = [{"item": i["id"], "expected": i["expected"], "initial": i["initial"], "closing": i["closing"]} for i in t["items"]]
        res = {"ok": True, "tray": "surgical", "items": items}
        self.assertTrue(rb.score_count_sheet(t, res)["exact"])
        items[1] = {**items[1], "closing": 1}
        s = rb.score_count_sheet(t, res)
        self.assertFalse(s["exact"])
        self.assertEqual((s["cells_right"], s["cells"]), (8, 9))

    def test_pack(self):
        t = TRUTH["pack_labels.png"]
        labels = [{"item": lab["item"].replace(" ", "_"), "lot": lab["lot"], "expires": lab["expires"], "expired": lab["expired"]}
                  for lab in t["labels"]]
        self.assertTrue(rb.score_pack(t, {"ok": True, "labels": labels})["exact"])
        labels[2]["expired"] = False
        s = rb.score_pack(t, {"ok": True, "labels": labels})
        self.assertFalse(s["expired_flag"])
        self.assertFalse(s["exact"])

    def test_tray_tag(self):
        t = TRUTH["tray_tag_bench.png"]
        self.assertTrue(rb.score_tray_tag(t, {"ok": True, "tray": "bench"})["exact"])
        self.assertFalse(rb.score_tray_tag(t, {"ok": True, "tray": "surgical"})["exact"])


class RunTests(unittest.TestCase):
    def test_camera_sim_shape_and_qr_still_reads(self):
        img = cv2.imread(str(PROPS / "tray_tag_bench.png"))
        sim = rb.camera_sim(img)
        self.assertEqual(sim.shape, (720, 1280, 3))
        self.assertLess(sim.mean(), img.mean())

    def test_run_with_fake_backend_and_budget(self):
        cases = [c for c in rb.load_cases(PROPS, ["render"]) if c["name"] == "count_sheet_surgical_filled.png"]
        t = cases[0]["truth"]
        answer = {"tray": "surgical", "tray_text": "Operating room", "items": [
            {"item": i["id"], "printed_name": i["name"], "expected": i["expected"], "initial": i["initial"],
             "closing": i["closing"]} for i in t["items"]]}
        rows = rb.run(cases, ["perceptron", "gemini"], max_calls=1,
                      make=lambda m: FakeOCR(answer) if m == "perceptron" else None)
        self.assertTrue(rows[0]["exact"])
        self.assertEqual(rows[1]["skipped"], "no key")
        rows = rb.run(cases * 2, ["perceptron"], max_calls=1, make=lambda m: FakeOCR(answer))
        self.assertEqual(rows[1]["skipped"], "budget")
        md = rb.markdown(rb.summarize(rows), rows)
        self.assertIn("SYNTHETIC", md)
        self.assertIn("| count_sheet | render | perceptron | 1 | 1/1 | 9/9 |", md)


if __name__ == "__main__":
    unittest.main()
