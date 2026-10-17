import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
from PIL import Image

from .backends import LeRobotBackend, SavedImageBackend
from .real_arm import Arm
from .sessions import DryPolicySession


class ArmTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.side = Path(self.temp.name) / "side.png"
        self.wrist = Path(self.temp.name) / "wrist.png"
        Image.new("RGB", (640, 480), (10, 20, 30)).save(self.side)
        Image.new("RGB", (640, 480), (30, 20, 10)).save(self.wrist)

    def arm(self, factory=None, joints=None):
        backend = SavedImageBackend(self.side, self.wrist, joints=joints)
        arm = Arm(dry_run=True, backend=backend, session_factory=factory)
        arm.connect()
        self.addCleanup(arm.disconnect)
        return arm, backend

    def test_closed_still_and_session_reset_reuse(self):
        sessions = []

        def factory(instruction):
            session = DryPolicySession(instruction)
            sessions.append(session)
            return session

        arm, backend = self.arm(factory, joints=[0, 0, 0, 0, 0, 50])
        self.assertTrue(arm.run_skill("pick the hemostat", 3))
        self.assertEqual(arm.last_reason, "closed_and_still")
        self.assertEqual(sessions[0].reset_count, 1)
        self.assertAlmostEqual(arm.gripper_position(), .6, places=2)
        requests = sessions[0].requests
        self.assertGreaterEqual(len(requests), 2)
        self.assertNotIn("rtc", requests[0])
        self.assertTrue(any("rtc" in r for r in requests[1:]))
        for a, b in zip(requests, requests[1:]):
            self.assertGreater(b["timestamp_seconds"], a["timestamp_seconds"])
            elapsed_rows = (b["timestamp_seconds"] - a["timestamp_seconds"]) * 30
            self.assertAlmostEqual(elapsed_rows, round(elapsed_rows), places=4)
            self.assertGreaterEqual((b["timestamp_seconds"] - a["timestamp_seconds"]), .49)
        self.assertTrue(arm.run_skill("pick the hemostat", 2))
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].reset_count, 2)
        # The reused/reset session starts a fresh sequence with no prior chunk.
        fresh = [r for r in sessions[0].requests if r["sequence"] == 0]
        self.assertEqual(len(fresh), 2)
        self.assertTrue(all("rtc" not in r for r in fresh))
        self.assertGreater(len(backend.sent), 30)

    def test_freeze_during_inflight_reply_is_nonblocking_and_latched(self):
        entered = threading.Event()
        release = threading.Event()

        class Blocked(DryPolicySession):
            def predict(self, metadata, images):
                entered.set()
                release.wait(2)
                return super().predict(metadata, images)

        arm, backend = self.arm(lambda instruction: Blocked(instruction))
        outcome = []
        worker = threading.Thread(target=lambda: outcome.append(arm.run_skill("pick the hemostat", 2)))
        worker.start()
        self.assertTrue(entered.wait(1))
        before = time.perf_counter()
        arm.freeze()
        self.assertLess(time.perf_counter() - before, .05)
        time.sleep(.08)
        held = backend.joints.copy()
        release.set()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(outcome, [False])
        self.assertEqual(arm.counters["accepted"], 0)
        np.testing.assert_array_equal(backend.joints, held)
        self.assertFalse(arm.run_skill("pick the hemostat", .1))
        arm.resume()
        self.assertFalse(arm._frozen.is_set())

    def test_late_policy_holds_and_max_s(self):
        arm, backend = self.arm(lambda instruction: DryPolicySession(instruction, .43))
        start = backend.joints.copy()
        self.assertFalse(arm.run_skill("pick the hemostat", 1.1))
        self.assertEqual(arm.last_reason, "max_s")
        self.assertGreater(arm.counters["late"], 0)
        self.assertEqual(arm.counters["accepted"], 0)
        np.testing.assert_array_equal(backend.joints, start)

    def test_one_predict_in_flight(self):
        count = [0, 0]

        class Counted(DryPolicySession):
            def predict(self, metadata, images):
                count[0] += 1
                count[1] = max(count[0], count[1])
                try:
                    return super().predict(metadata, images)
                finally:
                    count[0] -= 1

        arm, _ = self.arm(lambda instruction: Counted(instruction, .03))
        self.assertTrue(arm.run_skill("pick the hemostat", 3))
        self.assertEqual(count[1], 1)

    def test_hardware_guard_and_missing_poses(self):
        with self.assertRaisesRegex(RuntimeError, "unmeasured"):
            Arm().connect()
        arm, _ = self.arm()
        with self.assertRaisesRegex(RuntimeError, "home"):
            arm.go_home()
        self.assertFalse(arm.move_to(99, 99, 99))

    def test_feetech_load_is_direct_and_raw(self):
        backend = LeRobotBackend("unused", "unused", 0, 1)
        bus = Mock()
        bus.read.return_value = -123
        backend.robot = SimpleNamespace(bus=bus)
        self.assertEqual(backend.read_load(), -123)
        bus.read.assert_called_once_with("Present_Load", "gripper", normalize=False)

    def test_pose_keeps_grip_and_safe_spot_releases_only_on_arrival(self):
        arm, backend = self.arm(joints=[0, 0, 0, 0, 0, 98])
        arm.rig["carry"] = [0, 0, 0, 0, 0, 0]
        arm.go_carry()
        self.assertAlmostEqual(backend.joints[5], 98)
        arm.rig["safe_spot"] = [0, 0, 0, 0, 0, 0]
        self.assertTrue(arm.set_down_safe_spot())
        self.assertAlmostEqual(arm.gripper_position(), 0)
        arm.freeze()
        self.assertFalse(arm.set_down_safe_spot())

    def test_policy_error_stops_and_does_not_invent_load(self):
        class Broken(DryPolicySession):
            def predict(self, metadata, images):
                raise RuntimeError("fake network unavailable")

        arm, backend = self.arm(lambda instruction: Broken(instruction))
        self.assertFalse(arm.run_skill("pick the hemostat", 1))
        self.assertTrue(arm._frozen.is_set())
        arm._load = None
        with self.assertRaisesRegex(RuntimeError, "got_it"):
            arm.gripper_load()
        np.testing.assert_array_equal(backend.joints, [0, 0, 0, 0, 0, 100])

    def test_new_instruction_closes_old_session(self):
        sessions = []

        def factory(instruction):
            session = DryPolicySession(instruction)
            sessions.append(session)
            return session

        arm, _ = self.arm(factory)
        arm.run_skill("pick the hemostat", .1)
        arm.run_skill("return the hemostat", .1)
        self.assertEqual(len(sessions), 2)
        self.assertTrue(sessions[0].closed)
        self.assertFalse(sessions[1].closed)

    def test_move_to_on_fake_joints(self):
        from .kinematics import Kinematics

        kin = Kinematics()
        rng = np.random.default_rng(7)
        for _ in range(1000):
            start = kin.from_urdf(rng.uniform(kin.lower * .7, kin.upper * .7))
            goal = start.copy()
            goal[0] += .5
            if kin.valid(goal) and kin.in_region(kin.forward(start)) and kin.in_region(kin.forward(goal)):
                break
        else:
            self.fail("No synthetic in-region pose")
        arm, backend = self.arm(joints=np.r_[start, 60.])
        target = kin.forward(goal)
        self.assertTrue(arm.move_to(*target))
        self.assertLess(np.linalg.norm(kin.forward(backend.joints[:5]) - target), .002)
        self.assertEqual(backend.joints[5], 60)


if __name__ == "__main__":
    unittest.main()
