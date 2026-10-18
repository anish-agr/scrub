"""Real-arm safety on a physical-ish fake: servos that sag, a jaw stopped by the tool, Perceptron errors.

  .venv/bin/python -m unittest arm.test_safety -v

SavedImageBackend is a perfect position follower, so it can't show a hold that drifts or a grip that
relaxes. These backends behave like the STS3215s with LeRobot's P-only gains: a joint under load sits
a little below its goal, and a jaw closed on a tool stops at the contact point.
"""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from . import backends, real_arm
from .backends import SavedImageBackend, camera_index, port_holders
from .kinematics import Kinematics
from .perceptron import APIError
from .real_arm import Arm
from .sessions import DryPolicySession
from .streaming import Timeline

SAG_DEG = 2.0   # shoulder_lift reads this far below whatever it was last told (past the 1 deg settle check)
CONTACT = 60.0  # the jaw can't close past this: a tool is in it


class PhysicalBackend(SavedImageBackend):
    def read_joints(self):
        q = self.joints.copy()
        q[1] -= SAG_DEG
        q[5] = max(q[5], self.contact)
        return q

    contact = 0.0


class FixedPolicy(DryPolicySession):
    """Absolute targets like a trained policy (DryPolicySession echoes the reading, which sags with it)."""
    target = [0, 0, 0, 0, 0, 40.0]

    def predict(self, metadata, images):
        reply = super().predict(metadata, images)
        rows = np.tile(self.target, (30, 1)).astype(float)
        rtc = metadata.get("rtc")
        if rtc:
            rows[:len(rtc["committed_actions"])] = rtc["committed_actions"]
        reply["actions"] = rows.tolist()
        return reply


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.side = Path(self.temp.name) / "side.png"
        self.wrist = Path(self.temp.name) / "wrist.png"
        Image.new("RGB", (640, 480), (10, 20, 30)).save(self.side)
        Image.new("RGB", (640, 480), (30, 20, 10)).save(self.wrist)

    def arm(self, factory=None, joints=(0, 0, 0, 0, 0, 100), contact=0.0, backend_class=PhysicalBackend):
        backend = backend_class(self.side, self.wrist, joints=list(joints))
        backend.contact = contact
        arm = Arm(dry_run=True, backend=backend, session_factory=factory)
        arm.connect()
        self.addCleanup(arm.disconnect)
        return arm, backend

    @staticmethod
    def sent_since(backend, t0):
        return np.array([row for t, row in backend.sent if t >= t0])


class HoldTests(Base):
    def test_idle_hold_resends_the_command_not_a_sagging_reading(self):
        arm, backend = self.arm()
        t0 = time.perf_counter()
        time.sleep(0.5)
        rows = self.sent_since(backend, t0)
        self.assertGreater(len(rows), 10)
        # Old behavior sent the reading back: shoulder_lift walked down SAG_DEG every tick (about 15 deg here).
        self.assertTrue(np.allclose(rows, rows[0]), rows[:, 1])

    def test_freeze_holds_where_it_was_told(self):
        arm, backend = self.arm()
        arm.freeze()
        t0 = time.perf_counter()
        time.sleep(0.4)
        rows = self.sent_since(backend, t0)
        self.assertTrue(len(rows) > 5 and np.allclose(rows, rows[0]), rows[:, 1])
        self.assertFalse(arm.run_skill("pick the hemostat", .2))  # latched until resume


class GripTests(Base):
    def picked(self):
        arm, backend = self.arm(lambda i: FixedPolicy(i), contact=CONTACT)
        self.assertTrue(arm.run_skill("pick the hemostat", 4))  # the policy closes toward 40
        self.assertEqual(arm.last_reason, "closed_and_still")
        return arm, backend

    def test_squeeze_stops_just_past_the_contact_point(self):
        arm, backend = self.picked()
        hold = CONTACT - real_arm.GRIP_SQUEEZE
        t0 = time.perf_counter()
        time.sleep(0.3)
        rows = self.sent_since(backend, t0)
        # Still squeezing (below contact), never driven on toward 40 and stalled at the torque limit.
        self.assertTrue(np.allclose(rows[:, 5], hold), rows[:, 5])

    def test_carry_and_home_keep_the_grip(self):
        arm, backend = self.picked()
        arm.rig["carry"] = [5, 0, 0, 0, 0, 100]
        arm.rig["home"] = [0, 0, 0, 0, 0, 100]
        t0 = time.perf_counter()
        arm.go_carry()
        arm.go_home()
        rows = self.sent_since(backend, t0)
        # Old behavior started the move from the measured jaw (the contact point) and let go.
        self.assertTrue(np.all(rows[:, 5] < CONTACT), rows[:, 5])

    def test_release_opens_and_finishes(self):
        arm, backend = self.picked()
        arm.open_gripper()
        self.assertGreater(backend.joints[5], 95)

    def test_jaw_stays_inside_its_configured_range(self):
        arm, backend = self.arm()
        arm.rig["gripper_open"], arm.rig["gripper_closed"] = 90.0, 10.0
        with arm._lock:
            row = arm._guard_grip(np.array([0, 0, 0, 0, 0, 100.0]), np.array([0, 0, 0, 0, 0, 90.0]), 0.0)
            self.assertEqual(row[5], 90.0)
            row = arm._guard_grip(np.array([0, 0, 0, 0, 0, 0.0]), np.array([0, 0, 0, 0, 0, 12.0]), 0.0)
            self.assertEqual(row[5], 10.0)


class PutBack(FixedPolicy):
    """Grips for the first predicts, then opens: what a recorded "return the X" does."""
    def predict(self, metadata, images):
        self.target = [0, 0, 0, 0, 0, 30.0 if len(self.requests) < 6 else 100.0]
        return super().predict(metadata, images)


class ReturnTests(Base):
    def test_return_ends_after_letting_go_not_on_the_grip(self):
        arm, backend = self.arm(lambda i: PutBack(i))
        self.assertTrue(arm.run_skill("return the hemostat", 8))
        self.assertEqual(arm.last_reason, "released_and_still")
        self.assertGreater(backend.joints[5], 85)
        arm, _ = self.arm(lambda i: FixedPolicy(i))  # grips and never lets go: not a finished put-back
        self.assertFalse(arm.run_skill("return the hemostat", 3))
        self.assertEqual(arm.last_reason, "max_s")


class Flaky(FixedPolicy):
    """Raises the given APIErrors on its first predicts, then answers like FixedPolicy."""
    def __init__(self, instruction, errors=()):
        super().__init__(instruction)
        self.errors = list(errors)
        self.seen = []

    def predict(self, metadata, images):
        self.seen.append(metadata["sequence"])
        if self.errors:
            code = self.errors.pop(0)
            raise APIError("Perceptron inference transport failed" if code is None else f"Perceptron HTTP {code}")
        return super().predict(metadata, images)


class APIErrorTests(Base):
    def run_with(self, *per_session):
        sessions = []

        def factory(instruction):
            s = Flaky(instruction, per_session[len(sessions)] if len(sessions) < len(per_session) else ())
            sessions.append(s)
            return s
        arm, _ = self.arm(factory, joints=(0, 0, 0, 0, 0, 50))
        return arm, sessions

    def test_503_or_a_timeout_holds_and_retries_with_a_fresh_frame(self):
        for code in (503, None):
            arm, sessions = self.run_with([code])
            self.assertTrue(arm.run_skill("pick the hemostat", 3))
            self.assertEqual(arm.counters["api_errors"], 1)
            seq = sessions[0].seen
            self.assertEqual(seq[:2], [0, 1])  # the failed number is never reused
            self.assertTrue(all(b > a for a, b in zip(seq, seq[1:])), seq)

    def test_expired_session_regrants_once(self):
        for code in (401, 404, 410):
            arm, sessions = self.run_with([code])
            self.assertTrue(arm.run_skill("pick the hemostat", 3))
            self.assertEqual(len(sessions), 2)
            self.assertTrue(sessions[0].closed)
            self.assertEqual(sessions[1].seen[0], 0)

    def test_refused_sequence_resets_the_session(self):
        arm, sessions = self.run_with([409])
        self.assertTrue(arm.run_skill("pick the hemostat", 3))
        self.assertGreaterEqual(sessions[0].reset_count, 2)  # the 409 reset, then the end-of-run reset
        self.assertEqual(sessions[0].seen[:2], [0, 0])

    def test_gives_up_raises_and_holds(self):
        cases = ([401], [401])  # refused again after the fresh grant
        arm, _ = self.run_with(*cases)
        with self.assertRaisesRegex(APIError, "HTTP 401"):
            arm.run_skill("pick the hemostat", 3)
        self.assertTrue(arm._frozen.is_set())
        arm, _ = self.run_with([503] * real_arm.PREDICT_TRIES)
        with self.assertRaisesRegex(APIError, "HTTP 503"):
            arm.run_skill("pick the hemostat", 3)
        self.assertTrue(arm._frozen.is_set())
        arm, _ = self.run_with([400])
        with self.assertRaisesRegex(APIError, "HTTP 400"):
            arm.run_skill("pick the hemostat", 3)
        self.assertEqual(arm.counters["accepted"], 0)

    def test_controller_reads_the_code(self):
        from controller.core import _api_error
        self.assertEqual(_api_error(APIError("Perceptron HTTP 503")), (503, "Perceptron HTTP 503"))


class TimelineTests(unittest.TestCase):
    def test_no_chunk_holds_the_previous_command(self):
        line = Timeline(Kinematics())
        previous = np.array([10, 20, 0, 0, 0, 40.0])
        np.testing.assert_array_equal(line.command(5, previous), previous)


class BackendTests(unittest.TestCase):
    def test_camera_ids_by_index_path_or_name(self):
        self.assertEqual(camera_index(2), 2)
        self.assertEqual(camera_index("1"), 1)
        self.assertEqual(camera_index("/dev/video2"), "/dev/video2")
        with patch("arm.check_setup.camera_names", return_value=["FaceTime HD Camera", "HD Pro Webcam C920", "icspring camera"]):
            self.assertEqual(camera_index("C920"), 1)
            self.assertEqual(camera_index("icspring"), 2)
            with self.assertRaisesRegex(RuntimeError, "check_setup"):
                camera_index("nope")

    def test_busy_port_is_refused(self):
        with tempfile.NamedTemporaryFile() as port:
            class Done:
                stdout = "4242\n"
            self.assertEqual(port_holders(port.name, run=lambda *a, **k: Done()), [4242])
            Done.stdout = ""
            self.assertEqual(port_holders(port.name, run=lambda *a, **k: Done()), [])
            backend = backends.LeRobotBackend(port.name, "scrub_follower", 0, 1)
            with patch("arm.backends.port_holders", return_value=[4242]):
                with self.assertRaisesRegex(RuntimeError, "another process"):
                    backend.connect()
        self.assertEqual(port_holders("/dev/tty.usbmodem-not-plugged-in"), [])
        from .teach import TeachBackend  # torque off under a running controller would drop the arm
        with patch("arm.backends.port_holders", return_value=[4242]):
            with self.assertRaisesRegex(RuntimeError, "another process"):
                TeachBackend("/dev/tty.usbmodem1", "scrub_follower").connect()


if __name__ == "__main__":
    unittest.main()
