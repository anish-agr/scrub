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

    def test_markerless_corners_and_homography_under_two_mm(self):
        from video.geometry import detect_corners, homography
        image = np.full((480, 640, 3), (155, 70, 15), np.uint8)
        truth = np.float32([[90, 95], [552, 110], [580, 390], [55, 375]])
        cv2.fillConvexPoly(image, truth.astype(np.int32), (220, 225, 230))
        detected = detect_corners(image)
        matrix, size = homography(detected, 300, 180)
        got = cv2.perspectiveTransform(truth[None], matrix)[0]
        expected = np.float32([[0, 0], [599, 0], [599, 359], [0, 359]])
        error_mm = np.linalg.norm(got-expected, axis=1)/2
        self.assertLess(float(error_mm.max()), 2)
        self.assertEqual(size, (600, 360))

    def test_bad_geometry_is_refused(self):
        from video.geometry import order_corners, homography, detect_corners
        with self.assertRaises(ValueError):
            order_corners([[0,0]]*4)
        with self.assertRaises(ValueError):
            homography([[0,0],[100,0],[100,100],[0,100]], -1, 100)
        with self.assertRaises(ValueError):
            detect_corners(np.zeros((480,640,3), np.uint8))

    def test_ingest_does_not_invent_sync_or_downgrade_simulation(self):
        from video.common import save_provenance, read_json
        from video.ingest import ingest
        folder = self.root/'photos'
        folder.mkdir()
        path = folder/'tray.png'
        cv2.imwrite(str(path), np.full((240,320,3), 100, np.uint8))
        ingest(self.ws, kind='real')
        asset = read_json(self.root/'manifest.json')['assets'][0]
        self.assertIsNone(asset['start_time'])
        self.assertEqual(provenance(path)['kind'], 'real')
        save_provenance(path, kind='simulation', synthetic=True)
        with self.assertRaises(ValueError):
            ingest(self.ws, kind='real')


if __name__ == "__main__":
    unittest.main()
