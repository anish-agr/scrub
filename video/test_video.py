"""Offline fixtures only: python -m unittest video.test_video -v."""
from __future__ import annotations

import shutil
import unittest
import uuid

import cv2
import numpy as np

from video.common import BASE, Workspace, info, provenance, stamp


class VideoTests(unittest.TestCase):
    def setUp(self):
        self.root = BASE / "tests" / uuid.uuid4().hex
        self.ws = Workspace(self.root)
        self.addCleanup(lambda: shutil.rmtree(self.root))

    def test_workspace_never_escapes_or_overwrites_raw(self):
        for name in ("../escape.mp4", "raw/original.mp4", "photos/original.png"):
            with self.assertRaises(ValueError):
                self.ws.out(name)
        with self.assertRaises(ValueError):
            Workspace(BASE.parent / "wrong")

    def test_disclosures_change_pixels_and_do_not_mutate_input(self):
        image = np.full((480, 640, 3), 100, np.uint8)
        for kind in ("simulation", "reconstructed", "unknown"):
            labeled = stamp(image, {"kind": kind})
            self.assertFalse(np.array_equal(image, labeled))
        self.assertTrue(np.all(image == 100))

    def test_demo_assets_real_encoding_and_mujoco(self):
        from video.synthetic import demo_assets
        result = demo_assets(self.ws, seconds=2)
        details = info(result["clip"])
        self.assertEqual(details["frames"], 60)
        self.assertTrue(details["audio"])
        self.assertTrue(provenance(result["clip"])["synthetic"])
        self.assertEqual(provenance(self.root / "raw-sim/so101.mp4")["kind"], "reconstructed")


if __name__ == "__main__":
    unittest.main()
