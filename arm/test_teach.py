import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np

from .teach import DEFAULT_RIG, FakeTeachBackend, TeachBackend, Teacher, interact, main


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


if __name__ == "__main__":
    unittest.main()
