import json
import tempfile
import unittest
from pathlib import Path

import cv2

from explore.recognition import props

ROOT = Path(__file__).resolve().parents[2]


class PropsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name)
        props.generate(cls.out)
        cls.truth = json.loads((cls.out / "truth.json").read_text())["files"]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_files_exist(self):
        for name in self.truth:
            self.assertGreater((self.out / name).stat().st_size, 1000, name)
        for tid in props.TRAYS:
            for stem in (f"count_sheet_{tid}", f"tray_tag_{tid}"):
                self.assertTrue((self.out / f"{stem}.html").exists())
        self.assertTrue((self.out / "pack_labels.html").exists())

    def test_qr_decodes(self):
        det = cv2.QRCodeDetector()
        checked = 0
        for name, t in self.truth.items():
            if "qr" not in t:
                continue
            img = cv2.imread(str(self.out / name))
            self.assertEqual(img.shape[1], 1600, name)
            text, _, _ = det.detectAndDecode(img)
            self.assertEqual(text, f'scrub:tray:{t["tray_id"]}', name)
            checked += 1
        self.assertEqual(checked, 7)

    def test_truth_matches_settings(self):
        for tid in props.TRAYS:
            cfg = json.loads((ROOT / "settings" / f"{tid}.json").read_text())
            t = self.truth[f"count_sheet_{tid}.png"]
            self.assertEqual(t["tray_id"], cfg["id"])
            self.assertEqual([i["id"] for i in t["items"]], [i["id"] for i in cfg["items"]])
            self.assertEqual([i["name"] for i in t["items"]], [i["name"] for i in cfg["items"]])
            self.assertEqual([i["expected"] for i in t["items"]], [int(i.get("qty", 1)) for i in cfg["items"]])
        filled = self.truth["count_sheet_surgical_filled.png"]
        self.assertEqual([i["initial"] for i in filled["items"]], [1, 1, 1])
        self.assertEqual([i["closing"] for i in filled["items"]], [1, 0, 1])

    def test_pack_truth(self):
        labels = self.truth["pack_labels.png"]["labels"]
        self.assertEqual(len(labels), 4)
        self.assertEqual(sum(label["expired"] for label in labels), 1)
        self.assertEqual(sum(label["expires"] is None for label in labels), 1)
        names = {i["name"] for i in json.loads((ROOT / "settings/surgical.json").read_text())["items"]}
        self.assertTrue(all(label["item"] in names for label in labels))


if __name__ == "__main__":
    unittest.main()
