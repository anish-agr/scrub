"""Production TrayState preserves physical detections and stable identities, without cameras/APIs."""
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from vision import instances, locate, service, tray


def det(box):
    return {"mention": "hemostat", "point_box": {"top_left": {"x": box[0], "y": box[1]},
            "bottom_right": {"x": box[2], "y": box[3]}}}


class ProductionInstancesTests(unittest.TestCase):
    def setUp(self):
        self.setting = {"id": "surgical", "items": [{"id": "hemostat", "name": "hemostat",
                        "slot": [10, 10, 100, 60]}], "return_spot": None}
        self.detections = [det([20, 20, 80, 50]), det([220, 60, 280, 90])]

    def test_tray_keeps_two_detections_next_to_one_configured_slot(self):
        state = tray.tray_from_detections(self.setting, self.detections)
        self.assertEqual(len(state["slots"]), 1)
        self.assertEqual(state["slots"][0]["kind"], "configured")
        self.assertEqual(len(state["candidates"]), 2)
        self.assertEqual([c["slot"] for c in state["candidates"]], [1, 2])
        self.assertEqual(state["ambiguous_items"], ["hemostat"])

    def test_publish_forwards_candidates_and_preserves_remaining_slot(self):
        posts = []
        frame = np.zeros((120, 300, 3), dtype=np.uint8)
        rt = SimpleNamespace(grabber=SimpleNamespace(latest=lambda: (frame, time.time())),
                             clips=SimpleNamespace(add_frame=lambda *a: None), last_good_tray=None,
                             lock=threading.Lock(), tray_failing=False, hand=None, detections=[],
                             poster=SimpleNamespace(post=lambda path, body: posts.append(body)), tray=None)
        def publish(detections, local=False):
            state = tray.tray_from_detections(self.setting, detections, detector="perceptron")
            if local:
                state = {k: v for k, v in state.items() if k not in ("candidates", "ambiguous_items")}
                state["detector"] = "local"
            with patch.object(service, "setting_document", return_value=self.setting), \
                    patch.object(service, "perceive_tray", return_value=(state, detections)):
                return service.publish_tray(rt)
        first = publish(self.detections)
        self.assertEqual(len(posts[-1]["candidates"]), 2)
        second = publish([self.detections[1]])
        self.assertEqual(second["candidates"][0]["slot"], 2)
        self.assertEqual(second["candidates"][0]["id"], first["candidates"][1]["id"])
        self.assertEqual(rt.detections[0]["slot"], 2)  # runtime /locate gets the same identity
        publish(self.detections)
        fallback = publish([], local=True)
        self.assertTrue(fallback["candidates_stale"])
        self.assertEqual(len(fallback["candidates"]), 2)

    def test_stabilized_remaining_right_answer_locates_slot_two(self):
        initial = tray.tray_from_detections(self.setting, self.detections)
        remaining = tray.tray_from_detections(self.setting, [self.detections[1]])
        remaining["candidates"] = instances.stabilize(remaining["candidates"], initial["candidates"])
        rt = SimpleNamespace(tray=remaining, detections=[self.detections[1]], lock=threading.Lock())
        rt.detector = SimpleNamespace(detect=lambda *args: [self.detections[1]])
        # A cached detection without metadata is still reconciled against the production candidates.
        remaining["detector"] = "perceptron"
        result = locate.locate(np.zeros((120, 300, 3), dtype=np.uint8), self.setting, "hemostat",
                               detector=locate.RuntimeDetector(rt), instance={"side": "right", "slot": 2})
        self.assertTrue(result["found"], result)
        self.assertEqual(result["instance"]["slot"], 2)

    def test_merged_detection_cannot_reidentify_two_previous_objects(self):
        old = tray.tray_from_detections(self.setting, self.detections)["candidates"]
        merged = tray.tray_from_detections(self.setting, [det([15, 15, 290, 95])])["candidates"]
        result = instances.stabilize(merged, old)
        self.assertTrue(result[0]["identity_ambiguous"])


if __name__ == "__main__":
    unittest.main()
