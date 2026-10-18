import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np

from .teach import DEFAULT_RIG, FakeTeachBackend, SkillTeacher, TeachBackend, Teacher, interact, interact_skill, main
from .taught import validate


class TeachTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "rig.json"
        self.rig = json.loads(DEFAULT_RIG.read_text())
        self.rig["urdf"] = str(DEFAULT_RIG.with_name("so101_chain.urdf").resolve())
        self.rig["hardware_verified"] = True
        self.rig["custom_setting"] = {"keep": 42}
        self.path.write_text(json.dumps(self.rig))
        self.backend = FakeTeachBackend([5, 10, -10, 2, 3, 60])
        self.teacher = Teacher(self.path, self.backend)

    def test_all_pose_saves_preserve_other_settings_and_disable_hardware(self):
        for name in ("home", "carry", "safe_spot"):
            self.teacher.pose(name)
        rig = json.loads(self.path.read_text())
        for name in ("home", "carry", "safe_spot"):
            self.assertEqual(rig[name], [5, 10, -10, 2, 3, 60])
        self.assertEqual(rig["custom_setting"], {"keep": 42})
        self.assertEqual(rig["verified_contract_id"], self.rig["verified_contract_id"])
        self.assertFalse(rig["hardware_verified"])

    def test_region_corners_saved_as_sorted_fk_box(self):
        self.backend.joints = np.array([0, 0, 0, 0, 0, 100.])
        a = self.teacher.corner("a")
        self.assertEqual(json.loads(self.path.read_text())["handoff_region"], self.rig["handoff_region"])
        self.backend.joints = np.array([30, 30, -30, 30, 0, 100.])
        b = self.teacher.corner("b")
        region = json.loads(self.path.read_text())["handoff_region"]
        np.testing.assert_allclose(region["min"], np.minimum(a, b))
        np.testing.assert_allclose(region["max"], np.maximum(a, b))

    def test_degenerate_corners_and_invalid_joints_do_not_write(self):
        original = self.path.read_text()
        self.teacher.corner("a")
        with self.assertRaisesRegex(ValueError, "separation"):
            self.teacher.corner("b")
        self.assertEqual(self.path.read_text(), original)
        self.backend.joints[0] = float("nan")
        with self.assertRaisesRegex(ValueError, "limits"):
            self.teacher.pose("home")
        self.assertEqual(self.path.read_text(), original)

    def test_concurrent_rig_edit_not_overwritten(self):
        self.path.write_text(self.path.read_text() + "\n")
        other_edit = self.path.read_text()
        with self.assertRaisesRegex(RuntimeError, "changed elsewhere"):
            self.teacher.pose("home")
        self.assertEqual(self.path.read_text(), other_edit)

    def test_keyboard_flow(self):
        keys = iter(["p", "h", "c", "s", "invalid", "q"])
        messages = []
        interact(self.teacher, read=lambda prompt: next(keys), write=messages.append)
        self.assertEqual({v["saved"] for v in messages if isinstance(v, dict) and "saved" in v}, {"home", "carry", "safe_spot"})

    def test_disconnect_keeps_torque_off(self):
        backend = TeachBackend("fake", "fake")
        backend.robot = Mock()
        backend.robot.bus.is_connected = True
        backend.close()
        backend.robot.bus.disconnect.assert_called_once_with(disable_torque=True)
        backend.robot.send_action.assert_not_called()

    def test_cli_refuses_real_or_shipped_dry_run_without_safety_args(self):
        with patch("sys.stderr"):
            with self.assertRaises(SystemExit):
                main(["--dry-run"])
            with self.assertRaises(SystemExit):
                main(["--port", "fake"])

    def test_real_backend_never_calls_configure_or_enables_torque(self):
        import types

        config_module = types.ModuleType("lerobot.robots.so_follower.config_so_follower")
        robot_module = types.ModuleType("lerobot.robots.so_follower.so_follower")
        config_module.SO101FollowerConfig = Mock()
        robot = Mock()
        robot.calibration = {"saved": True}
        robot.is_calibrated = True
        robot_module.SO101Follower = Mock(return_value=robot)
        modules = {config_module.__name__: config_module, robot_module.__name__: robot_module}
        with patch.dict("sys.modules", modules):
            backend = TeachBackend("fake", "scrub_follower")
            backend.connect()
        robot.bus.connect.assert_called_once()
        robot.bus.disable_torque.assert_called_once()
        robot.connect.assert_not_called()
        robot.configure.assert_not_called()
        robot.bus.enable_torque.assert_not_called()
        self.assertTrue(config_module.SO101FollowerConfig.call_args.kwargs["use_degrees"])


class SkillTeachTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.backend = FakeTeachBackend([5, 10, -10, 2, 3, 60])

    def teacher(self, direction="pick"):
        return SkillTeacher(self.backend, "hemostat", direction, "surgical", root=self.root)

    def test_keys_save_waypoints_and_file(self):
        teacher = self.teacher()
        poses = iter([[5, 10, -10, 2, 3, 60], [5, 20, -5, 10, 3, 60], [5, 20, -5, 10, 3, 20], [0, 0, 0, 0, 0, 20]])
        keys = iter(["", "", "g", "x", "", "q"])
        messages = []

        def read(prompt):
            key = next(keys)
            if key in {"", "g"}:
                self.backend.joints = np.array(next(poses), dtype=float)
            return key

        path = interact_skill(teacher, read=read, write=messages.append)
        self.assertEqual(path, self.root / "surgical" / "hemostat-pick.json")
        skill = json.loads(path.read_text())
        self.assertEqual((skill["item"], skill["direction"], skill["setting"]), ("hemostat", "pick", "surgical"))
        self.assertEqual([w["name"] for w in skill["waypoints"]], ["approach", "descend", "grip", "lift"])
        self.assertEqual([w["gripper"] for w in skill["waypoints"]], [None, None, 1.0, None])
        self.assertEqual(skill["waypoints"][1]["joints"],
                         {"shoulder_pan": 5, "shoulder_lift": 20, "elbow_flex": -5, "wrist_flex": 10, "wrist_roll": 3})
        self.assertIn("Unknown key; nothing saved", messages)
        self.assertEqual(validate(skill), [])

    def test_return_names_undo_open_and_reported_problems(self):
        teacher = self.teacher("return")
        keys = iter(["", "u", "", "o", "q"])
        messages = []
        interact_skill(teacher, read=lambda prompt: next(keys), write=messages.append)
        skill = json.loads((self.root / "surgical" / "hemostat-return.json").read_text())
        self.assertEqual([w["name"] for w in skill["waypoints"]], ["carry", "descend"])
        self.assertEqual(skill["waypoints"][1]["gripper"], 0.0)
        self.assertTrue(any(isinstance(m, str) and "at least 3" in m for m in messages))

    def test_invalid_joints_not_saved_and_eof_does_not_write(self):
        teacher = self.teacher()
        self.backend.joints[0] = 500
        with self.assertRaisesRegex(ValueError, "limits"):
            teacher.add()
        self.assertEqual(teacher.waypoints, [])

        def eof(prompt):
            raise EOFError

        self.assertIsNone(interact_skill(teacher, read=eof, write=lambda _: None))
        self.assertFalse((self.root / "surgical" / "hemostat-pick.json").exists())

    def test_skill_cli_dry_run_and_safety_args(self):
        with patch("sys.stderr"):
            with self.assertRaises(SystemExit):
                main(["skill", "hemostat", "pick", "--dry-run"])  # no --skills-dir
            with self.assertRaises(SystemExit):
                main(["skill", "hemostat", "pick", "--port", "fake"])  # no --supported-and-empty
            with self.assertRaises(SystemExit):
                main(["skill", "hemostat", "grab", "--dry-run", "--skills-dir", str(self.root)])
        keys = iter(["", "g", "", "q"])
        with patch("builtins.input", lambda prompt: next(keys)), patch("builtins.print"):
            main(["skill", "hemostat", "pick", "--dry-run", "--skills-dir", str(self.root),
                  "--joints", "1", "2", "3", "4", "5", "50"])
        skill = json.loads((self.root / "surgical" / "hemostat-pick.json").read_text())
        self.assertEqual(len(skill["waypoints"]), 3)


if __name__ == "__main__":
    unittest.main()
