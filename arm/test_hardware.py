"""arm/hardware.py, arm/thermal.py and arm/handoff.py against a fake LeRobot bus."""
from contextlib import contextmanager
from types import SimpleNamespace
import unittest

from . import handoff, hardware, thermal
from .kinematics import Kinematics

MOTORS = hardware.MOTORS


class FakeBus:
    """LeRobot MotorsBus shape: a read fails `fail_reads` times in a row, then answers; num_retry
    retries like LeRobot's. Records every write."""
    def __init__(self, fail_reads=0):
        self.fail_reads = fail_reads
        self.temps = {m: 40 for m in MOTORS}
        self.loads = {m: 0 for m in MOTORS}
        self.raw = {m: 2048 for m in MOTORS}
        self.regs = {"CW_Dead_Zone": 1, "CCW_Dead_Zone": 1}
        self.calibration = {m: SimpleNamespace(range_min=0, range_max=4095) for m in MOTORS}
        self.torque = True
        self.writes = []

    def _answer(self, num_retry):
        for _ in range(1 + num_retry):
            if self.fail_reads > 0:
                self.fail_reads -= 1
                continue
            return
        raise ConnectionError("Failed to sync read: There is no status packet!")

    def sync_read(self, name, motors=None, *, normalize=True, num_retry=0):
        self._answer(num_retry)
        table = {"Present_Temperature": self.temps, "Present_Load": self.loads, "Present_Position": self.raw}[name]
        motors = [motors] if isinstance(motors, str) else motors
        return {m: v for m, v in table.items() if motors is None or m in motors}

    def read(self, name, motor, *, normalize=True, num_retry=0):
        self._answer(num_retry)
        return self.regs[name] if name in self.regs else self.sync_read(name, motor)[motor]

    def sync_write(self, name, values, *, normalize=True):
        self.writes.append((name, dict(values)))

    def write(self, name, motor, value, *, normalize=True):
        self.writes.append((name, motor, value))
        if name in self.regs:
            self.regs[name] = value

    def enable_torque(self, motors=None):
        self.torque = True
        self.writes.append(("torque", True))

    def disable_torque(self, motors=None):
        self.torque = False
        self.writes.append(("torque", False))

    @contextmanager
    def torque_disabled(self, motors=None):
        self.writes.append(("torque_disabled", motors))
        yield


class HardwareTests(unittest.TestCase):
    def test_retry_reads_instance_and_class(self):
        bus = FakeBus(fail_reads=2)
        with self.assertRaises(ConnectionError):
            bus.sync_read("Present_Temperature")  # LeRobot's default: no retry
        bus.fail_reads = 2
        hardware.retry_reads(bus)
        hardware.retry_reads(bus)  # twice is harmless
        self.assertEqual(bus.sync_read("Present_Temperature")["gripper"], 40)
        bus.fail_reads = 3
        self.assertEqual(bus.read("Present_Load", "gripper", normalize=False), 0)
        bus.fail_reads = 4
        with self.assertRaises(ConnectionError):
            bus.sync_read("Present_Temperature")

        class Bus(FakeBus):
            pass
        hardware.retry_reads(Bus)
        self.assertEqual(Bus(fail_reads=3).sync_read("Present_Load", "gripper"), {"gripper": 0})

    def test_joint_limits_hold_wrist_roll_and_clamp(self):
        lim = hardware.joint_limits(FakeBus())
        self.assertAlmostEqual(lim["shoulder_pan"][1], 179.0, places=3)
        self.assertEqual(lim["wrist_roll"], (-150.0, 150.0))
        self.assertEqual(lim["gripper"], (1.0, 99.0))
        out = hardware.clamp_action({"wrist_roll.pos": 170.0, "gripper.pos": 0.0, "elbow_flex.pos": 10.0, "x": 5}, lim)
        self.assertEqual(out, {"wrist_roll.pos": 150.0, "gripper.pos": 1.0, "elbow_flex.pos": 10.0, "x": 5})
        self.assertEqual(hardware.clamp_action({"wrist_roll": -170}, lim), {"wrist_roll": -150.0})

    def test_rest_and_wake_order(self):
        bus = FakeBus()
        hardware.rest(bus)
        self.assertFalse(bus.torque)
        hardware.wake(bus)
        self.assertEqual(bus.writes[1], ("Goal_Position", bus.raw))  # goal := present first ...
        self.assertEqual(bus.writes[2], ("torque", True))             # ... then torque on

    def test_gripper_torque_by_situation(self):
        st = {}
        self.assertEqual(hardware.gripper_torque_want(st, 50, 80, False, 0.0), 500)   # moving / opening
        self.assertEqual(hardware.gripper_torque_want(st, 40, 30, True, 0.0), 350)    # holding an item
        self.assertEqual(hardware.gripper_torque_want(st, 3, 2, False, 10.0), 500)    # just shut
        self.assertEqual(hardware.gripper_torque_want(st, 3, 2, False, 11.0), 500)
        self.assertEqual(hardware.gripper_torque_want(st, 3, 2, False, 11.6), 150)    # shut on nothing 1.5 s
        self.assertEqual(hardware.gripper_torque_want(st, 3, 50, False, 12.0), 500)   # told to open
        bus = FakeBus()
        self.assertTrue(hardware.set_gripper_torque(bus, st, 350))
        self.assertFalse(hardware.set_gripper_torque(bus, st, 350))  # no write when unchanged
        self.assertEqual(bus.writes, [("Torque_Limit", "gripper", 350)])

    def test_dead_zone_written_once(self):
        bus = FakeBus()
        self.assertTrue(hardware.set_dead_zone(bus))
        self.assertEqual(bus.regs, {"CW_Dead_Zone": 3, "CCW_Dead_Zone": 3})
        self.assertFalse(hardware.set_dead_zone(bus))

    def test_arm_fault_is_runtime_error(self):
        self.assertTrue(issubclass(hardware.ArmFault, RuntimeError))


class ThermalTests(unittest.TestCase):
    def test_trip_message_and_telemetry(self):
        bus = FakeBus()
        bus.temps["elbow_flex"] = 61
        temps = thermal.read_temps(bus)
        hot = thermal.too_hot(temps)
        self.assertEqual(hot, {"elbow_flex": 61})
        self.assertEqual(thermal.fault_message(hot), "Too hot: elbow_flex 61 C. Cooling down.")
        row = thermal.telemetry(temps, thermal.read_loads(bus), True, t=5.0)
        self.assertEqual(set(row), {"temps", "loads", "hottest", "cooling", "t"})
        self.assertEqual((row["hottest"], row["cooling"], row["t"]), (61, True, 5.0))
        self.assertEqual(thermal.too_hot({"gripper": 59, "x": None}), {})

    def test_cooling_resume_rule(self):
        c = thermal.Cooling()
        self.assertFalse(c.done(60, now=0))
        self.assertFalse(c.done(51, now=10))
        self.assertTrue(c.done(50, now=20))
        level = thermal.Cooling()
        self.assertFalse(level.done(54, now=0))
        self.assertFalse(level.done(54, now=100))
        self.assertTrue(level.done(54, now=181))  # levelled off at or below 55 for 180 s
        warm = thermal.Cooling()
        warm.done(57, now=0)
        self.assertFalse(warm.done(57, now=500))  # above 55: wait for 50
        self.assertFalse(thermal.Cooling().done(None))


class HandoffTests(unittest.TestCase):
    def test_lift_once_per_grasp(self):
        g = {}
        self.assertIsNone(handoff.track_lift(g, 0.10))
        self.assertIsNone(handoff.track_lift(g, 0.12))
        self.assertAlmostEqual(handoff.track_lift(g, 0.135), 0.035)
        self.assertIsNone(handoff.track_lift(g, 0.14))
        self.assertAlmostEqual(g["lift_max"], 0.04)

    def test_pulled_out(self):
        g = {}
        self.assertFalse(handoff.pulled_out(g, 120, 0.0, True))
        self.assertFalse(handoff.pulled_out(g, 20, 1.0, True))   # collapsed ...
        self.assertTrue(handoff.pulled_out(g, 20, 1.31, True))   # ... for PULL_S
        light = {}
        handoff.pulled_out(light, 40, 0.0, True)                  # never a real squeeze
        self.assertFalse(handoff.pulled_out(light, 5, 1.0, True))
        self.assertFalse(handoff.pulled_out(light, 5, 2.0, True))
        released = {"peak": 120}
        self.assertFalse(handoff.pulled_out(released, 10, 0.0, False))  # told to open: not a pull
        self.assertIsNone(released["low_since"])
        self.assertFalse(handoff.pulled_out(g, None, 3.0, True))

    def test_tip_z_clamps_folded_pose(self):
        kin = Kinematics()
        z = handoff.tip_z(kin, [2.8, -102.2, 97.7, 72.3, -9.3])  # the folded home, past the URDF limits
        self.assertTrue(-0.2 < z < 0.5)


if __name__ == "__main__":
    unittest.main()
