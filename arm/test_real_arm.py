import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from unittest.mock import Mock

import numpy as np
from PIL import Image

from . import hardware, real_arm, taught
from .backends import LeRobotBackend, SavedImageBackend
from .real_arm import Arm
from .sessions import DryPolicySession
from .test_hardware import FakeBus


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
        arm.rig["home"] = None
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


class BusBackend(SavedImageBackend):
    """Saved images and fake joints, plus a fake LeRobot bus. Fails the test on a write while torque is off."""
    def __init__(self, side, wrist, joints, bus):
        super().__init__(side, wrist, joints=joints)
        self.bus = bus

    def read_joints(self):
        self.bus.sync_read("Present_Position")  # goes through the arm's retries
        return super().read_joints()

    jaw_stop = None  # an item in the jaws: the gripper stops closing here

    def send(self, row):
        if not self.bus.torque:
            raise AssertionError("position written while torque is off")
        row = np.array(row, dtype=float)
        if self.jaw_stop is not None:
            row[5] = max(row[5], self.jaw_stop)
        super().send(row)


class HardwareLayerTests(ArmTests.__bases__[0]):
    def setUp(self):
        ArmTests.setUp(self)
        patcher = mock.patch.object(real_arm, "THERMAL_EVERY_S", .05)
        patcher.start()
        self.addCleanup(patcher.stop)

    def arm(self, joints=(0, 0, 0, 0, 0, 100), bus=None):
        bus = bus or FakeBus()
        backend = BusBackend(self.side, self.wrist, joints, bus)
        arm = Arm(dry_run=True, backend=backend)
        arm.connect()
        self.addCleanup(arm.disconnect)
        return arm, backend, bus

    def wait_for(self, check, seconds=2.0):
        end = time.time() + seconds
        while time.time() < end:
            if check():
                return True
            time.sleep(.02)
        return False

    def test_bus_reads_retry(self):
        arm, backend, bus = self.arm()
        bus.fail_reads = 3  # LeRobot alone would end the session on the first dropped reply
        time.sleep(.2)
        self.assertIsNone(arm._error)
        bus.fail_reads = 2
        self.assertTrue(self.wait_for(lambda: bus.fail_reads == 0))
        self.assertIsNone(arm._error)

    def test_rest_then_wake_writes_nothing_between(self):
        arm, backend, bus = self.arm()
        arm.rig["home"] = [8, 0, 0, 0, 0, 100]
        arm.rest()
        np.testing.assert_allclose(backend.joints[:5], [8, 0, 0, 0, 0], atol=1)
        self.assertFalse(bus.torque)
        sent = len(backend.sent)
        time.sleep(.2)
        self.assertEqual(len(backend.sent), sent)  # torque off: nothing written
        with self.assertRaisesRegex(RuntimeError, "resting"):
            arm.go_carry()
        arm.rest()  # already resting: no-op
        here = backend.joints.copy()
        writes = len(bus.writes)
        arm.wake()
        new = [w for w in bus.writes[writes:] if w[0] in ("Goal_Position", "torque")]
        self.assertEqual([w[0] for w in new[:2]], ["Goal_Position", "torque"])  # goal := present, then torque on
        self.assertTrue(bus.torque)
        self.assertTrue(self.wait_for(lambda: len(backend.sent) > sent))
        np.testing.assert_allclose(backend.joints, here)  # nothing moved
        arm.wake()  # awake: no-op

    def test_rest_at_measured_home_skips_the_move(self):
        home = [2.8, -102.2, 97.7, 72.3, -9.3, 4.8]  # past the URDF lift and elbow limits; must still connect
        arm, backend, bus = self.arm(joints=home)
        self.assertEqual(arm.rig["home"], home)
        sent = len(backend.sent)
        arm.rest()
        self.assertFalse(bus.torque)
        self.assertLessEqual(len(backend.sent) - sent, 3)  # a few hold ticks, no trajectory
        np.testing.assert_allclose(backend.joints, home)
        arm.wake()
        self.assertTrue(bus.torque)
        time.sleep(.1)
        np.testing.assert_allclose(backend.joints, home)  # woken where it rests, not pulled to the limit

    def test_joint_limits_clamp_moves(self):
        arm, backend, bus = self.arm()
        arm.rig["carry"] = [0, 0, 0, 0, 160, 100]
        arm.go_carry()
        self.assertAlmostEqual(backend.joints[4], 150, places=1)  # wrist_roll held to +-150

    def test_gripper_torque_by_situation(self):
        with mock.patch.object(hardware, "GRIP_IDLE_S", .1):
            arm, backend, bus = self.arm(joints=(0, 0, 0, 0, 0, 0))  # shut on nothing (0 = closed)
            limits = lambda: [w[2] for w in bus.writes if w[0] == "Torque_Limit"]  # noqa: E731
            self.assertTrue(self.wait_for(lambda: limits()[-1:] == [hardware.GRIP_TORQUE_IDLE]))
            self.assertEqual(limits()[0], hardware.GRIP_TORQUE_MOVE)
            arm.open_gripper()
            self.assertEqual(limits()[-1], hardware.GRIP_TORQUE_MOVE)
            backend.jaw_stop = 40.0  # an instrument in the jaws
            _, set_gripper, _ = arm.taught_controls()
            self.assertTrue(set_gripper(1.0))  # the claw guard's hold at contact counts as done
            self.assertIsNotNone(arm._grip["hold"])
            self.assertTrue(self.wait_for(lambda: limits()[-1] == hardware.GRIP_TORQUE_HOLD))

    def test_thermal_trip_stops_folds_home_and_raises(self):
        arm, backend, bus = self.arm()
        arm.rig["home"] = [0, 0, 0, 0, 0, 100]
        arm.rig["carry"] = [30, 0, 0, 0, 0, 100]
        threading.Timer(.3, lambda: bus.temps.update(elbow_flex=61)).start()
        with self.assertRaisesRegex(hardware.ArmFault, "Too hot: elbow_flex 61 C. Cooling down."):
            arm.go_carry()
        self.assertEqual(arm.last_reason, "too_hot")
        np.testing.assert_allclose(backend.joints[:5], [0, 0, 0, 0, 0], atol=1)  # empty jaw: folded home
        self.assertTrue(arm.telemetry()["cooling"])
        with self.assertRaises(hardware.ArmFault):
            arm.run_skill("pick the hemostat", 1)
        arm.go_home()  # home is allowed while cooling
        bus.temps["elbow_flex"] = 50
        self.assertTrue(self.wait_for(lambda: not arm.telemetry()["cooling"]))
        arm.go_carry()

    def test_thermal_trip_holding_an_item_holds_in_place(self):
        arm, backend, bus = self.arm(joints=(0, 0, 0, 0, 0, 50))  # jaw half closed on an instrument
        arm.rig["home"] = [0, 0, 0, 0, 0, 100]
        arm.rig["carry"] = [30, 0, 0, 0, 0, 50]
        threading.Timer(.8, lambda: bus.temps.update(gripper=62)).start()
        with self.assertRaisesRegex(hardware.ArmFault, "gripper 62"):
            arm.go_carry()
        stopped = backend.joints.copy()
        self.assertTrue(2 < stopped[0] < 29)  # stopped mid-move, not folded, not opened
        self.assertEqual(stopped[5], 50)
        time.sleep(.2)
        np.testing.assert_allclose(backend.joints, stopped, atol=.5)

    def test_thermal_trip_during_model_skill(self):
        arm, backend, bus = self.arm()
        arm._session_factory = lambda instruction: DryPolicySession(instruction, .02)
        arm.rig["home"] = None  # nowhere to fold: hold where it stopped
        threading.Timer(.3, lambda: bus.temps.update(shoulder_lift=60)).start()
        with self.assertRaisesRegex(hardware.ArmFault, "shoulder_lift 60"):
            arm.run_skill("pick the hemostat", 3)

    def test_telemetry_shape(self):
        arm, backend, bus = self.arm()
        bus.loads["gripper"] = -87
        self.assertTrue(self.wait_for(lambda: (arm.telemetry() or {}).get("loads", {}).get("gripper") == -87))
        t = arm.telemetry()
        self.assertEqual(set(t), {"temps", "loads", "hottest", "cooling", "t"})
        self.assertEqual(set(t["temps"]), set(hardware.MOTORS))
        self.assertEqual((t["hottest"], t["cooling"], t["loads"]["gripper"]), (40, False, -87))
        dry, _ = ArmTests.arm(self)
        self.assertIsNone(dry.telemetry())  # saved images: no bus, no numbers made up

    def test_taught_source_plays_through_guarded_motion(self):
        skill = {"item": "hemostat", "direction": "pick", "waypoints": [
            {"name": "approach", "joints": {"shoulder_pan": 5, "shoulder_lift": 0, "elbow_flex": 0,
                                            "wrist_flex": 0, "wrist_roll": 170}, "gripper": None, "speed": .5},
            {"name": "grip", "joints": {"shoulder_pan": 5, "shoulder_lift": 2, "elbow_flex": 0,
                                        "wrist_flex": 0, "wrist_roll": 140}, "gripper": .6, "speed": .5},
            {"name": "carry", "joints": {"shoulder_pan": 0, "shoulder_lift": 0, "elbow_flex": 0,
                                         "wrist_flex": 0, "wrist_roll": 140}, "gripper": None, "speed": 1}]}
        arm, backend, bus = self.arm(joints=(0, 0, 0, 0, 140, 100))
        calls = []
        play = taught.play

        def spy(s, *, goto, set_gripper, stopped):
            def g(joints, speed):
                ok = goto(joints, speed)
                calls.append(backend.joints.copy())
                return ok
            return play(s, goto=g, set_gripper=set_gripper, stopped=stopped)

        with mock.patch.object(taught, "load", return_value=skill) as load, mock.patch.object(taught, "play", spy):
            self.assertTrue(arm.run_skill("pick the hemostat", 15, source="taught"))
        load.assert_called_once_with("hemostat", "pick", setting=None)
        self.assertEqual(arm.last_reason, "taught_done")
        self.assertAlmostEqual(calls[0][4], 150, places=1)  # wrist_roll clamped like every other move
        np.testing.assert_allclose(backend.joints, [0, 0, 0, 0, 140, 40], atol=1)  # 0.6 closed, kept to carry
        with mock.patch.object(taught, "load", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "No taught skill"):
                arm.run_skill("pick the hemostat", 5, source="taught")
        with self.assertRaises(ValueError):
            arm.run_skill("pick the hemostat", 5, source="other")
        arm.freeze()
        with mock.patch.object(taught, "load", return_value=skill):
            self.assertFalse(arm.run_skill("pick the hemostat", 5, source="taught"))


if __name__ == "__main__":
    unittest.main()
