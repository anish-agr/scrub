"""python -m unittest arm.test_grasp -v  (no hardware, no network)"""
import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

from . import grasp, taught
from .backends import SavedImageBackend
from .kinematics import JOINTS, Kinematics
from .real_arm import Arm

EXAMPLE = json.loads((taught.SKILLS_DIR / "example" / "hemostat-pick.json").read_text())
KIN = Kinematics()


def row(wp):
    return [wp["joints"][n] for n in JOINTS]


def tips(skill):
    return [KIN.forward(row(wp)) for wp in skill["waypoints"]]


class AdjustTaughtTests(unittest.TestCase):
    def test_arm_offset_moves_at_slot_tips_and_leaves_carry(self):
        off = (0.012, -0.018)
        out = grasp.adjust_taught(EXAMPLE, {"confidence": 0.9, "arm_offset": list(off)}, KIN)
        self.assertTrue(out["adjust"]["applied"])
        for wp, before, after in zip(EXAMPLE["waypoints"], tips(EXAMPLE), tips(out)):
            if wp["name"] in ("carry", "home"):
                np.testing.assert_allclose(after, before)
            else:
                self.assertLess(np.linalg.norm(after - (before + (*off, 0))), 0.005, wp["name"])
        self.assertEqual(EXAMPLE["waypoints"][0]["joints"]["shoulder_pan"], 10.0)  # input untouched

    def test_arm_offset_with_yaw_still_lands_on_target(self):
        out = grasp.adjust_taught(EXAMPLE, {"confidence": 0.9, "arm_offset": [0.01, 0.02], "yaw_deg": 25}, KIN)
        for wp, before, after in zip(EXAMPLE["waypoints"][:4], tips(EXAMPLE), tips(out)):
            self.assertLess(np.linalg.norm(after - (before + (0.01, 0.02, 0))), 0.005)
            self.assertAlmostEqual(out["waypoints"][0]["joints"]["wrist_roll"], 25.0)

    def test_ik_failure_falls_back_to_pan_nudge(self):
        with mock.patch.object(KIN, "inverse", return_value=None):
            out = grasp.adjust_taught(EXAMPLE, {"confidence": 0.9, "arm_offset": [0.0, 0.02]}, KIN)
        self.assertTrue(out["adjust"]["applied"])
        a, b = EXAMPLE["waypoints"][0]["joints"], out["waypoints"][0]["joints"]
        self.assertNotEqual(a["shoulder_pan"], b["shoulder_pan"])
        self.assertEqual(a["elbow_flex"], b["elbow_flex"])

    def test_mm_only_nudges_shoulder_pan(self):
        out = grasp.adjust_taught(EXAMPLE, {"confidence": 0.8, "offset_mm": [15, 4]}, KIN)
        self.assertTrue(out["adjust"]["applied"])
        for wp, a, b in zip(out["waypoints"], EXAMPLE["waypoints"], out["waypoints"]):
            changed = {n for n in JOINTS if abs(a["joints"][n] - b["joints"][n]) > 1e-9}
            self.assertEqual(changed, set() if wp["name"] == "carry" else {"shoulder_pan"})
        # default mapping: image +x is the arm's -y, so the tip swings about 15 mm toward -y
        dy = tips(out)[0][1] - tips(EXAMPLE)[0][1]
        self.assertAlmostEqual(dy, -0.015, delta=0.005)

    def test_yaw_turns_wrist_roll_clamped(self):
        out = grasp.adjust_taught(EXAMPLE, {"confidence": 0.8, "yaw_deg": 30}, KIN)
        self.assertEqual([wp["joints"]["wrist_roll"] for wp in out["waypoints"]], [30, 30, 30, 30, 0])
        out = grasp.adjust_taught(EXAMPLE, {"confidence": 0.8, "yaw_deg": 170}, KIN)
        self.assertEqual(out["waypoints"][0]["joints"]["wrist_roll"], 90)

    def test_unchanged_when_too_big_low_confidence_or_missing(self):
        for located, why in (({"confidence": 0.9, "arm_offset": [0.05, 0.0]}, "over 4 cm"),
                             ({"confidence": 0.9, "offset_mm": [30, 30]}, "over 4 cm"),
                             ({"confidence": 0.2, "arm_offset": [0.01, 0.0]}, "low confidence"),
                             ({"found": False, "confidence": 0.0}, "not found"),
                             (None, "no located")):
            out = grasp.adjust_taught(EXAMPLE, located, KIN)
            self.assertFalse(out["adjust"]["applied"])
            self.assertIn(why, out["adjust"]["why"])
            self.assertEqual(out["waypoints"], EXAMPLE["waypoints"])


class PlanIKTests(unittest.TestCase):
    def test_reachable_pick_is_valid_and_top_down(self):
        skill = grasp.plan_ik({"item": "hemostat", "confidence": 0.9, "arm_xy": [0.22, 0.05], "yaw_deg": 20},
                              KIN, {**KIN.rig, "carry": [0, -30, 40, 30, 0, 50]})
        self.assertEqual(taught.validate(skill, KIN), [])
        names = [wp["name"] for wp in skill["waypoints"]]
        self.assertEqual(names, ["approach", "descend", "grip", "lift", "carry"])
        above, down = (KIN.forward(row(skill["waypoints"][i])) for i in (0, 1))
        np.testing.assert_allclose(down, [0.22, 0.05, grasp.GRASP_Z], atol=0.003)
        np.testing.assert_allclose(above - down, [0, 0, 0.06], atol=0.003)
        self.assertEqual(skill["waypoints"][0]["gripper"], 0.0)
        self.assertEqual(skill["waypoints"][2]["gripper"], 1.0)
        self.assertAlmostEqual(skill["waypoints"][0]["joints"]["wrist_roll"], 20.0)  # rig carry roll 0 + yaw

    def test_return_opens_over_the_slot(self):
        skill = grasp.plan_ik({"item": "hemostat", "confidence": 1, "arm_xy": [0.25, -0.05]}, KIN, KIN.rig, direction="return")
        self.assertEqual(taught.validate(skill, KIN), [])
        self.assertEqual([wp["gripper"] for wp in skill["waypoints"]], [None, None, 0.0, None])

    def test_none_when_unreachable_or_unlocated(self):
        self.assertIsNone(grasp.plan_ik({"confidence": 1, "arm_xy": [0.8, 0.0]}, KIN, KIN.rig))
        self.assertIsNone(grasp.plan_ik({"confidence": 1, "offset_mm": [3, 3]}, KIN, KIN.rig))
        self.assertIsNone(grasp.plan_ik({"confidence": 0.1, "arm_xy": [0.22, 0.0]}, KIN, KIN.rig))
        self.assertIsNone(grasp.plan_ik(None, KIN, KIN.rig))

    def test_run_plays_through_given_controls(self):
        calls = []
        controls = (lambda j, s: calls.append(("goto", j)) or True, lambda g: calls.append(("grip", g)) or True,
                    lambda: False)
        ok = grasp.run("ik", "pick the hemostat", {"confidence": 1, "arm_xy": [0.22, 0.0]},
                       controls=controls, kin=KIN, rig=KIN.rig, setting=None)
        self.assertTrue(ok)
        self.assertEqual([c[1] for c in calls if c[0] == "grip"], [0.0, 1.0])
        self.assertFalse(grasp.run("ik", "pick the hemostat", None, controls=controls, kin=KIN, rig=KIN.rig, setting=None))
        report = {}
        with mock.patch.object(taught, "load", return_value=EXAMPLE):
            self.assertTrue(grasp.run("taught_adjusted", "pick the hemostat", {"confidence": 1, "arm_offset": [0, 0.01]},
                                      controls=controls, kin=KIN, rig=KIN.rig, setting=None, report=report))
        self.assertEqual(report["why"], "shifted by arm_offset")
        with mock.patch.object(taught, "load", return_value=None), self.assertRaisesRegex(RuntimeError, "No taught"):
            grasp.run("taught_adjusted", "pick the hemostat", None, controls=controls, kin=KIN, rig=KIN.rig, setting=None)
        with self.assertRaises(ValueError):
            grasp.run("model", "pick the hemostat", None, controls=controls, kin=KIN, rig=KIN.rig, setting=None)


class RulesTests(unittest.TestCase):
    def test_gripper_says(self):
        self.assertEqual(grasp.gripper_says(1.0, 100), "empty")
        self.assertEqual(grasp.gripper_says(0.94, None), "empty")
        self.assertEqual(grasp.gripper_says(0.6, 100), "held")
        self.assertEqual(grasp.gripper_says(0.1, 100), "unknown")
        self.assertEqual(grasp.gripper_says(None, None), "unknown")
        self.assertEqual(grasp.gripper_says(0.9, 0, closed_fraction=0.85), "empty")

    def rig(self, center, size=(0.08, 0.08), yaw=0.0):
        return {"handoff_region": {"min": [0.05, -0.25, 0.08], "max": [0.35, 0.05, 0.35]},
                "safe_zone": {"center": list(center), "size": list(size), "yaw_deg": yaw}}

    def test_safe_zone_problems(self):
        self.assertEqual(grasp.safe_zone_problems(self.rig((0.2, 0.25, 0.0))), [])
        close = grasp.safe_zone_problems(self.rig((0.2, 0.15, 0.0)))
        self.assertEqual(len(close), 1)
        self.assertIn("from the handoff box", close[0])
        big = grasp.safe_zone_problems(self.rig((0.2, 0.22, 0.0), size=(0.4, 0.4)))
        self.assertIn("safe zone overlaps the handoff box", big)
        inside = grasp.safe_zone_problems(self.rig((0.2, 0.0, 0.0)))
        self.assertEqual(len(inside), 2)
        self.assertTrue(grasp.safe_zone_problems({"safe_zone": None}))
        self.assertTrue(grasp.safe_zone_problems({"safe_zone": {"center": [1, 2], "size": [0.1, 0.1]}}))

    def test_segment_crosses_box(self):
        lo, hi = (0, 0, 0), (1, 1, 1)
        self.assertTrue(grasp.segment_crosses_box((-1, 0.5, 0.5), (2, 0.5, 0.5), lo, hi))
        self.assertFalse(grasp.segment_crosses_box((-1, 2, 0.5), (2, 2, 0.5), lo, hi))
        self.assertFalse(grasp.segment_crosses_box((-1, 0.5, 2), (2, 0.5, 1.5), lo, hi))  # passes over it
        self.assertTrue(grasp.segment_crosses_box((0.5, 0.5, 0.5), (3, 3, 3), lo, hi))  # starts inside
        self.assertTrue(grasp.segment_crosses_box((-1, -1, 0.5), (2, 2, 0.5), lo, hi))  # diagonal
        self.assertFalse(grasp.segment_crosses_box((-1, 0.5, 0.5), (-0.5, 0.5, 0.5), lo, hi))  # stops short
        self.assertFalse(grasp.path_enters_box((0.5, 0.5, 0.5), (3, 3, 3), lo, hi))  # leaving is not crossing
        self.assertTrue(grasp.path_enters_box((-1, 0.5, 0.5), (2, 0.5, 0.5), lo, hi))
        self.assertEqual((grasp.SHARP_SPEED, grasp.HAND_KEEPOUT_M), (0.5, 0.20))


class FakeArmTests(unittest.TestCase):
    def test_fail_sources_and_located(self):
        from controller.fake_arm import FakeArm
        arm = FakeArm(motion_s=0.01)
        located = {"confidence": 0.9, "arm_offset": [0.01, 0.0]}
        self.assertTrue(arm.run_skill("pick the hemostat", source="taught_adjusted", located=located))
        self.assertIs(arm.last_located, located)
        self.assertEqual(grasp.gripper_says(arm.gripper_position(), arm.gripper_load()), "held")
        arm.fail_sources = {"ik"}
        self.assertTrue(arm.run_skill("pick the hemostat", source="ik"))
        self.assertEqual(grasp.gripper_says(arm.gripper_position(), arm.gripper_load()), "empty")
        self.assertTrue(arm.run_skill("pick the hemostat", source="model"))
        self.assertEqual(arm.gripper_position(), 0.6)
        with self.assertRaises(ValueError):
            arm.run_skill("pick the hemostat", source="magic")
        arm.sharp_mode(True)
        self.assertTrue(arm.sharp and arm.hover_safe_spot() and arm.pose == "above_safe_spot")
        self.assertIsNone(arm.tip())
        self.assertIsNone(arm.wrist_jpeg())
        arm.wrist = b"\xff\xd8jpeg"
        self.assertEqual(arm.wrist_jpeg(), b"\xff\xd8jpeg")
        self.assertEqual(grasp.safe_zone_problems({"safe_zone": arm.safe_zone()}), [])


class RealArmTests(unittest.TestCase):
    """Saved images and a fake joint backend (dry_run): never opens a port or camera."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.side, self.wrist = Path(temp.name) / "side.png", Path(temp.name) / "wrist.png"
        Image.new("RGB", (640, 480), (10, 20, 30)).save(self.side)
        Image.new("RGB", (640, 480), (30, 20, 10)).save(self.wrist)

    def arm(self, joints):
        backend = SavedImageBackend(self.side, self.wrist, joints=joints)
        arm = Arm(dry_run=True, backend=backend)
        arm.connect()
        self.addCleanup(arm.disconnect)
        return arm, backend

    def skill(self):
        s = copy.deepcopy(EXAMPLE)
        for wp in s["waypoints"]:
            wp["speed"] = 1.0
        return s

    def test_taught_adjusted_plays_shifted_waypoints_through_playback(self):
        arm, backend = self.arm([0, -30, 40, 30, 0, 100])
        arm.rig["max_joint_speed_deg_s"] = 200.0  # a fast dry run; the same code path
        arm.kin.joint_speed_deg_s = np.minimum(200.0, arm.kin.velocity_deg_s)
        arm.rig["max_cartesian_speed_m_s"] = 1.0
        reached = []
        play = taught.play

        def spy(s, *, goto, set_gripper, stopped):
            def g(joints, speed):
                ok = goto(joints, speed)
                reached.append(backend.joints.copy())
                return ok
            return play(s, goto=g, set_gripper=set_gripper, stopped=stopped)

        located = {"confidence": 0.9, "arm_offset": [0.0, 0.02], "yaw_deg": 10}
        with mock.patch.object(taught, "load", return_value=self.skill()), mock.patch.object(taught, "play", spy):
            self.assertTrue(arm.run_skill("pick the hemostat", 30, source="taught_adjusted", located=located))
        self.assertEqual(arm.last_reason, "taught_done")
        want = grasp.adjust_taught(self.skill(), located, arm.kin)
        np.testing.assert_allclose(reached[0][:5], row(want["waypoints"][0]), atol=1.0)
        self.assertAlmostEqual(reached[0][4], 10.0, delta=1.0)
        tip = KIN.forward(reached[0][:5])
        self.assertLess(np.linalg.norm(tip - (KIN.forward(row(EXAMPLE["waypoints"][0])) + (0, 0.02, 0))), 0.006)
        with self.assertRaises(ValueError):
            arm.run_skill("pick the hemostat", 5, source="other")
        arm.freeze()
        with mock.patch.object(taught, "load", return_value=self.skill()):
            self.assertFalse(arm.run_skill("pick the hemostat", 5, source="taught_adjusted", located=located))
        self.assertFalse(arm.run_skill("pick the hemostat", 5, source="ik", located={"confidence": 1, "arm_xy": [0.22, 0]}))

    def test_ik_without_a_pose_returns_false(self):
        arm, _ = self.arm([0, -30, 40, 30, 0, 100])
        self.assertFalse(arm.run_skill("pick the hemostat", 5, source="ik", located=None))

    def test_sharp_mode_slows_moves(self):
        arm, backend = self.arm([0, 0, 0, 0, 0, 100])
        arm.rig["carry"] = [6, 0, 0, 0, 0, 100]
        arm.rig["home"] = [0, 0, 0, 0, 0, 100]
        t = time.perf_counter()
        arm.go_carry()
        normal = time.perf_counter() - t
        arm.go_home()
        arm.sharp_mode(True)
        t = time.perf_counter()
        arm.go_carry()
        slow = time.perf_counter() - t
        self.assertGreater(slow, normal + 0.2)
        np.testing.assert_allclose(backend.joints[:5], [6, 0, 0, 0, 0], atol=1)

    def test_set_down_refuses_a_path_through_the_handoff_box(self):
        arm, backend = self.arm([0, 0, 0, 0, 0, 100])  # tip at about (0.39, 0, 0.23)
        arm.rig["handoff_region"] = {"min": [0.2, -0.1, 0.0], "max": [0.3, 0.1, 0.4]}
        arm.rig["safe_spot"] = [0, 0, 0, 0, 0, 100]
        arm.rig["safe_zone"] = {"center": [0.0, 0.0, 0.0], "size": [0.08, 0.08], "yaw_deg": 0}
        self.assertFalse(arm.set_down_safe_spot())
        self.assertFalse(arm.hover_safe_spot())
        self.assertEqual(arm.last_reason, "safe_zone_path_crosses_handoff")
        np.testing.assert_allclose(backend.joints[:5], [0, 0, 0, 0, 0], atol=.01)  # held; nothing moved
        arm.rig["safe_zone"]["center"] = [0.3, 0.3, 0.0]
        self.assertTrue(arm.set_down_safe_spot())
        self.assertEqual(arm.safe_zone()["center"], [0.3, 0.3, 0.0])
        self.assertEqual(len(arm.tip()), 3)

    def test_wrist_jpeg_from_capture(self):
        arm, _ = self.arm([0, 0, 0, 0, 0, 100])
        self.assertEqual(arm.wrist_jpeg()[:2], b"\xff\xd8")
        arm._backend.capture = lambda: {}
        self.assertIsNone(arm.wrist_jpeg())


if __name__ == "__main__":
    unittest.main()
