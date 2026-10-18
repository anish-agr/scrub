import copy
import json
from pathlib import Path
import tempfile
import unittest

from . import taught
from .kinematics import Kinematics

EXAMPLE = json.loads((taught.SKILLS_DIR / "example" / "hemostat-pick.json").read_text())


def recorder(fail_at=None, stop_after=None):
    calls = []

    def goto(joints, speed):
        calls.append(("goto", joints, speed))
        return len(calls) != fail_at

    def set_gripper(fraction):
        calls.append(("gripper", fraction))
        return len(calls) != fail_at

    return calls, goto, set_gripper, (lambda: stop_after is not None and len(calls) >= stop_after)


class TaughtTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.kin = Kinematics()

    def write(self, setting, skill):
        path = taught.skill_path(setting, skill["item"], skill["direction"], self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(skill))
        return path

    def test_parse_matches_controller_instructions(self):
        self.assertEqual(taught.parse_instruction("pick the hemostat"), ("hemostat", "pick"))
        self.assertEqual(taught.parse_instruction("return the mayo scissors"), ("mayo_scissors", "return"))
        self.assertEqual(taught.parse_instruction("Pick the needle-nose pliers"), ("needle_nose_pliers", "pick"))
        self.assertEqual(taught.parse_instruction("  return   the scalpel "), ("scalpel", "return"))
        self.assertIsNone(taught.parse_instruction("hand me the scalpel"))
        self.assertIsNone(taught.parse_instruction(""))
        for path in taught.SETTINGS_DIR.glob("*.json"):
            if path.name.endswith(".local.json"):
                continue
            for it in json.loads(path.read_text())["items"]:
                self.assertEqual(taught.parse_instruction(it["pick_instruction"]), (it["id"], "pick"))
                self.assertEqual(taught.parse_instruction(it["return_instruction"]), (it["id"], "return"))

    def test_skill_path_and_bad_direction(self):
        self.assertEqual(taught.skill_path("surgical", "hemostat", "pick", self.root),
                         self.root / "surgical" / "hemostat-pick.json")
        with self.assertRaises(ValueError):
            taught.skill_path("surgical", "hemostat", "drop")

    def test_load_and_available(self):
        self.assertEqual(taught.available(root=self.root), {})
        self.assertIsNone(taught.load("hemostat", "pick", root=self.root))
        self.write("surgical", EXAMPLE)
        ret = dict(EXAMPLE, direction="return")
        self.write("surgical", ret)
        self.write("bench", dict(EXAMPLE, item="hex_key"))
        self.write("example", dict(EXAMPLE, item="ghost"))
        self.assertEqual(taught.available("surgical", self.root), {"hemostat": {"pick", "return"}})
        self.assertEqual(taught.available(root=self.root), {"hemostat": {"pick", "return"}, "hex_key": {"pick"}})
        self.assertEqual(taught.load("hemostat", "return", root=self.root)["direction"], "return")
        self.assertIsNotNone(taught.load("hex_key", "pick", root=self.root))
        self.assertIsNone(taught.load("hex_key", "pick", "surgical", self.root))
        self.assertIsNone(taught.load("ghost", "pick", root=self.root))  # example skills are never a first match
        self.assertIsNotNone(taught.load("ghost", "pick", "example", self.root))
        taught.skill_path("surgical", "scalpel", "pick", self.root).write_text("{broken")
        self.assertIsNone(taught.load("scalpel", "pick", root=self.root))

    def test_play_order_with_gripper_after_motion(self):
        calls, goto, set_gripper, stopped = recorder()
        self.assertTrue(taught.play(EXAMPLE, goto=goto, set_gripper=set_gripper, stopped=stopped))
        kinds = [c[0] for c in calls]
        self.assertEqual(kinds, ["goto", "gripper", "goto", "goto", "gripper", "goto", "goto"])
        self.assertEqual(calls[0][1], EXAMPLE["waypoints"][0]["joints"])
        self.assertEqual(calls[1], ("gripper", 0.0))
        self.assertEqual(calls[4], ("gripper", 1.0))
        self.assertEqual(calls[2][2], 0.15)

    def test_play_stops_on_stop_or_failed_move(self):
        calls, goto, set_gripper, stopped = recorder(stop_after=3)
        self.assertFalse(taught.play(EXAMPLE, goto=goto, set_gripper=set_gripper, stopped=stopped))
        self.assertEqual(len(calls), 3)
        calls, goto, set_gripper, stopped = recorder(fail_at=2)
        self.assertFalse(taught.play(EXAMPLE, goto=goto, set_gripper=set_gripper, stopped=stopped))
        self.assertEqual(len(calls), 2)
        calls, goto, set_gripper, _ = recorder()
        self.assertFalse(taught.play(EXAMPLE, goto=goto, set_gripper=set_gripper, stopped=lambda: True))
        self.assertEqual(calls, [])

    def test_offset_shifts_slot_waypoints_only(self):
        calls, goto, set_gripper, stopped = recorder()
        taught.play(EXAMPLE, goto=goto, set_gripper=set_gripper, stopped=stopped, offset=2.5)
        moves = [c[1] for c in calls if c[0] == "goto"]
        names = [wp["name"] for wp in EXAMPLE["waypoints"]]
        for name, joints, wp in zip(names, moves, EXAMPLE["waypoints"]):
            want = wp["joints"]["shoulder_pan"] + (0 if name == "carry" else 2.5)
            self.assertAlmostEqual(joints["shoulder_pan"], want)
            self.assertEqual(joints["elbow_flex"], wp["joints"]["elbow_flex"])
        calls, goto, set_gripper, stopped = recorder()
        taught.play(EXAMPLE, goto=goto, set_gripper=set_gripper, stopped=stopped, offset={"wrist_roll": -3})
        self.assertEqual(calls[0][1]["wrist_roll"], -3)
        self.assertEqual(EXAMPLE["waypoints"][0]["joints"]["wrist_roll"], 0.0)  # never mutates the skill

    def test_validate(self):
        self.assertEqual(taught.validate(EXAMPLE, self.kin), [])
        bad = copy.deepcopy(EXAMPLE)
        bad["waypoints"] = bad["waypoints"][:2]
        self.assertTrue(any("at least 3" in p for p in taught.validate(bad, self.kin)))
        bad = copy.deepcopy(EXAMPLE)
        bad["waypoints"][1]["joints"]["shoulder_pan"] = 500
        bad["waypoints"][3]["joints"].pop("wrist_roll")
        bad["waypoints"][4]["speed"] = 0
        problems = taught.validate(bad, self.kin)
        self.assertTrue(any("waypoint 2: joints outside limits" in p for p in problems))
        self.assertTrue(any("waypoint 4: joints must be" in p for p in problems))
        self.assertTrue(any("waypoint 5: speed" in p for p in problems))
        bad = copy.deepcopy(EXAMPLE)
        for wp in bad["waypoints"]:
            wp["gripper"] = None
        self.assertTrue(any("never closes" in p for p in taught.validate(bad, self.kin)))
        ret = copy.deepcopy(EXAMPLE)
        ret["direction"] = "return"
        for wp in ret["waypoints"]:
            wp["gripper"] = 1.0 if wp["gripper"] is not None else None
        self.assertTrue(any("never opens" in p for p in taught.validate(ret, self.kin)))

    def test_check_lists_validates_and_dry_plays(self):
        lines = []
        self.assertFalse(taught.check("surgical", root=self.root, kin=self.kin, write=lines.append))
        self.assertIn("no skills taught yet", lines[0])
        self.write("surgical", EXAMPLE)
        lines = []
        self.assertTrue(taught.check("surgical", root=self.root, kin=self.kin, write=lines.append))
        text = "\n".join(lines)
        self.assertIn("hemostat pick: ok, 5 waypoints, dry playback 7 steps", text)
        self.assertIn("hemostat return: not taught", text)
        self.assertIn("scalpel pick: not taught", text)
        bad = copy.deepcopy(EXAMPLE)
        bad["direction"] = "return"
        bad["waypoints"][0]["gripper"] = None
        self.write("surgical", bad)
        lines = []
        self.assertFalse(taught.check("surgical", root=self.root, kin=self.kin, write=lines.append))
        self.assertIn("hemostat return: FAIL return never opens", "\n".join(lines))

    def test_check_replays_on_arm_slowly(self):
        self.write("surgical", EXAMPLE)
        moves = []

        class FakeArm:
            homes = 0

            def go_home(self):
                FakeArm.homes += 1

        original = taught.arm_controls
        taught.arm_controls = lambda arm, speed: (lambda j, s: moves.append(min(s, speed)) or True,
                                                   lambda g: True, lambda: False)
        try:
            self.assertTrue(taught.check("surgical", root=self.root, kin=self.kin, arm=FakeArm(), write=lambda _: None))
        finally:
            taught.arm_controls = original
        self.assertEqual(FakeArm.homes, 1)
        self.assertTrue(moves and max(moves) <= taught.CHECK_SPEED)

    def test_arm_controls_build_guarded_trajectories(self):
        import numpy as np
        from unittest.mock import Mock

        arm = Mock()
        arm.rig = {"gripper_open": 100.0, "gripper_closed": 0.0}
        arm._commanded_start.return_value = np.array([0, 0, 0, 0, 0, 100.])
        arm._execute.return_value = True
        goto, set_gripper, stopped = taught.arm_controls(arm, 0.2)
        self.assertTrue(goto(EXAMPLE["waypoints"][0]["joints"], 0.9))
        start, goal, speed = arm.kin.trajectory.call_args.args
        self.assertEqual(goal.tolist(), [10, -20, 30, 40, 0, 100])
        self.assertEqual(speed, 0.2)
        set_gripper(0.75)
        self.assertEqual(arm.kin.trajectory.call_args.args[1][5], 25.0)
        self.assertIs(stopped, arm._frozen.is_set)

    def test_cli_fake_never_opens_port(self):
        with self.assertRaises(SystemExit) as done:
            taught.main(["--check", "--setting", "example", "--fake"])
        self.assertEqual(done.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
