"""Offline tests for arm.record and arm.check_setup: no arm, no camera, no network."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from arm import check_setup, record


def args(*extra):
    with mock.patch.dict(os.environ, {"SCRUB_SIDE_CAMERA": "", "SCRUB_WRIST_CAMERA": "",
                                      "SCRUB_FOLLOWER_PORT": "", "SCRUB_LEADER_PORT": ""}):
        return record.parse(list(extra))


def make_dataset(root: Path, episodes: int) -> None:
    (root / "meta").mkdir(parents=True, exist_ok=True)
    (root / "meta" / "info.json").write_text(json.dumps({"total_episodes": episodes}))


class TaskTests(unittest.TestCase):
    def test_exact_task_resolves(self):
        info = record.resolve_task("return the hemostat")
        self.assertEqual(info, {"task": "return the hemostat", "setting": "surgical", "item": "hemostat",
                                "direction": "put-back"})

    def test_setting_item_direction_with_alias(self):
        info = record.resolve_task(setting="bench", item="allen key", direction="hand-out")
        self.assertEqual(info["task"], "pick the hex key")
        self.assertEqual(record.resolve_task(setting="surgical", item="kelly", direction="hand-out")["task"],
                         "pick the hemostat")

    def test_inexact_task_refused(self):
        for bad in ("Pick the hemostat", "pick the kelly", "hand me the hemostat", "pick the hemostat "):
            with self.assertRaises(SystemExit):
                record.resolve_task(bad)

    def test_dental_not_recorded(self):
        with self.assertRaises(SystemExit):
            record.resolve_task(setting="dental", item="mirror", direction="hand-out")
        self.assertFalse(any(x["setting"] == "dental" for x in record.instructions()))

    def test_task_must_match_item(self):
        with self.assertRaises(SystemExit):
            record.resolve_task("pick the hemostat", item="scalpel")

    def test_every_settings_string_is_recordable(self):
        for sid in record.RECORDED_SETTINGS:
            data = json.loads((record.SETTINGS_DIR / f"{sid}.json").read_text())
            for it in data["items"]:
                for key in ("pick_instruction", "return_instruction"):
                    self.assertEqual(record.resolve_task(it[key])["item"], it["id"])

    def test_missing_task_info(self):
        with self.assertRaises(SystemExit):
            record.resolve_task(setting="surgical", item="hemostat")


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "scrub-dataset"
        self.real_busy_ports = record.busy_ports
        busy = mock.patch.object(record, "busy_ports", return_value={})  # never lsof the real arm's ports here
        busy.start()
        self.addCleanup(busy.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_refuses_while_the_arm_port_is_in_use(self):
        a = args("--task", "pick the hex key", "--lighting", "normal", "--follower", "/dev/tty.usbmodemA",
                 "--leader", "/dev/tty.usbmodemB")
        self.assertEqual(self.real_busy_ports(a, holders=lambda p: [7] if p.endswith("A") else []),
                         {"/dev/tty.usbmodemA": [7]})
        with mock.patch.object(record, "busy_ports", return_value={"/dev/tty.usbmodemA": [7]}), \
                mock.patch.object(record, "load_env"), \
                mock.patch.object(record.subprocess, "Popen") as popen, contextlib.redirect_stdout(io.StringIO()), \
                mock.patch.dict(os.environ, {"HF_USER": "me"}):
            with self.assertRaisesRegex(SystemExit, "in use"):
                record.main(["--task", "pick the hex key", "--lighting", "normal", "--root", str(self.root)])
        popen.assert_not_called()

    def test_arm_session_command_maps_settings(self):
        a = args("--task", "pick the hemostat", "--lighting", "bright", "--episodes", "7",
                 "--root", str(self.root), "--side", "C920", "--wrist", "icspring")
        cmd = record.arm_session_cmd(a, "pick the hemostat", "me/scrub", python="py")
        self.assertEqual(cmd[:2], ["py", str(record.ARM_SESSION)])
        pairs = dict(zip(cmd[2::2], cmd[3::2]))
        self.assertEqual(pairs["--task"], "pick the hemostat")
        self.assertEqual(pairs["--episodes"], "7")
        self.assertEqual(pairs["--episode-s"], "25")
        self.assertEqual(pairs["--reset-s"], "10")
        self.assertEqual(pairs["--repo"], "me/scrub")
        self.assertEqual(pairs["--root"], str(self.root))
        self.assertEqual((pairs["--side"], pairs["--wrist"]), ("C920", "icspring"))
        self.assertNotIn("--follower", cmd)  # arm_session's own Mac defaults

    def test_arm_session_flags_exist(self):
        """Every flag we pass is one explore/arm_session.py's argparse defines."""
        src = record.ARM_SESSION.read_text()
        a = args("--task", "pick the hemostat", "--lighting", "bright", "--follower", "/dev/x",
                 "--leader", "/dev/y", "--ease-s", "2", "--no-ui")
        for flag in (x for x in record.arm_session_cmd(a, "t", "r") if x.startswith("--")):
            self.assertIn(f'"{flag}"', src, flag)

    def test_lerobot_command(self):
        a = args("--task", "pick the hemostat", "--lighting", "bright", "--lerobot", "--follower", "COM5",
                 "--leader", "COM6", "--root", str(self.root))
        cmd = record.lerobot_cmd(a, "pick the hemostat", "me/scrub", 0, 1, resume=False)
        self.assertEqual(cmd[0], "lerobot-record")
        for want in ("--robot.use_degrees=true", "--teleop.use_degrees=true", "--dataset.fps=30",
                     "--dataset.episode_time_s=25", "--dataset.reset_time_s=10", "--dataset.repo_id=me/scrub",
                     "--dataset.single_task=pick the hemostat", "--dataset.num_episodes=5",
                     "--dataset.push_to_hub=false", "--robot.port=COM5", "--teleop.port=COM6",
                     "--robot.id=scrub_follower", "--teleop.id=scrub_leader"):
            self.assertIn(want, cmd)
        cams = next(x for x in cmd if x.startswith("--robot.cameras="))
        self.assertIn("side: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30}", cams)
        self.assertIn("wrist: {type: opencv, index_or_path: 1, width: 640, height: 480, fps: 30}", cams)
        self.assertNotIn("--resume=true", cmd)
        self.assertIn("--resume=true", record.lerobot_cmd(a, "t", "me/scrub", 0, 1, resume=True))

    def test_resume_detection(self):
        self.assertEqual(record.dataset_state(self.root), "new")
        self.root.mkdir()
        self.assertEqual(record.dataset_state(self.root), "bad")
        make_dataset(self.root, 4)
        self.assertEqual(record.dataset_state(self.root), "resume")
        self.assertEqual(record.episode_count(self.root), 4)
        a = args("--task", "pick the hemostat", "--lighting", "bright", "--lerobot", "--follower", "COM5",
                 "--leader", "COM6", "--side", "0", "--wrist", "1", "--root", str(self.root), "--hf-user", "me")
        pl = record.plan(a)
        self.assertTrue(pl["resume"])
        self.assertIn("--resume=true", pl["cmd"])

    def test_hf_user_order(self):
        with mock.patch.dict(os.environ, {"HF_USER": "envuser"}):
            self.assertEqual(record.hf_user("flaguser"), "flaguser")
            self.assertEqual(record.hf_user(None), "envuser")
        with mock.patch.dict(os.environ, {"HF_USER": ""}):
            self.assertEqual(record.hf_user(None, whoami=lambda token=None: {"name": "tokuser"}), "tokuser")

            def offline(token=None):
                raise OSError("offline")
            self.assertIsNone(record.hf_user(None, whoami=offline))

    def test_print_only_touches_nothing(self):
        out = io.StringIO()
        with mock.patch.object(record.subprocess, "Popen") as popen, \
                mock.patch.object(record, "load_env"), contextlib.redirect_stdout(out), \
                mock.patch.dict(os.environ, {"HF_USER": "me"}):
            rc = record.main(["--setting", "surgical", "--item", "hemostat", "--direction", "put-back",
                              "--lighting", "dim", "--root", str(self.root), "--print-only",
                              "--log", str(Path(self.tmp.name) / "log.md")])
        self.assertEqual(rc, 0)
        popen.assert_not_called()
        self.assertFalse(self.root.exists())
        self.assertFalse((Path(self.tmp.name) / "log.md").exists())
        text = out.getvalue()
        self.assertIn("me/scrub", text)
        self.assertIn("'return the hemostat'", text)
        self.assertIn("--episode-s 25 --reset-s 10", text)

    def test_run_logs_saved_episodes(self):
        """A batch: the fake recorder adds 3 episodes, one row is appended with Demos 3."""
        make_dataset(self.root, 2)
        log = Path(self.tmp.name) / "DATA-LOG.md"
        Path(f"{self.root}-cadence.json").write_text(json.dumps({"episodes": [
            {"episode_index": 1, "measured_fps": 25.0}, {"episode_index": 2, "measured_fps": 29.9},
            {"episode_index": 4, "measured_fps": 30.0}]}))

        def fake_popen(cmd, cwd=None):
            make_dataset(self.root, 5)
            return SimpleNamespace(wait=lambda: 0)
        with mock.patch.object(record.subprocess, "Popen", side_effect=fake_popen) as popen, \
                mock.patch.object(record, "load_env"), \
                contextlib.redirect_stdout(io.StringIO()), mock.patch.dict(os.environ, {"HF_USER": "me"}):
            rc = record.main(["--task", "pick the hex key", "--lighting", "normal", "--episodes", "3",
                              "--root", str(self.root), "--log", str(log), "--notes", "tray A"])
        self.assertEqual(rc, 0)
        self.assertNotIn("--resume=true", popen.call_args[0][0])  # arm_session adds it itself
        rows = [x for x in log.read_text().splitlines() if x.startswith("| 20")]
        self.assertEqual(len(rows), 1)
        cells = [c.strip() for c in rows[0].strip("|").split("|")]
        self.assertEqual(cells[1:], ["Robotics bench", "hex key", "hand-out", "normal", "3", "local",
                                     "loop 29.9-30 Hz; tray A"])

    def test_nothing_saved_no_row(self):
        log = Path(self.tmp.name) / "DATA-LOG.md"
        with mock.patch.object(record.subprocess, "Popen", return_value=SimpleNamespace(wait=lambda: 1)), \
                mock.patch.object(record, "load_env"), \
                contextlib.redirect_stdout(io.StringIO()), mock.patch.dict(os.environ, {"HF_USER": "me"}):
            rc = record.main(["--task", "pick the hex key", "--lighting", "normal", "--root", str(self.root),
                              "--log", str(log)])
        self.assertEqual(rc, 1)
        self.assertFalse(log.exists())

    def test_refuses_without_hf_user(self):
        with mock.patch.object(record, "load_env"), mock.patch.object(record, "hf_user", return_value=None), \
                mock.patch.object(record.subprocess, "Popen") as popen, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                record.main(["--task", "pick the hex key", "--lighting", "normal", "--root", str(self.root)])
        popen.assert_not_called()


class DataLogTests(unittest.TestCase):
    def test_row_matches_ledger_format(self):
        from ledger.logbook import HEADER, format_row
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "DATA-LOG.md"
            path.write_text("# Data log\n\n" + HEADER + "\n| --- | --- | --- | --- | --- | --- | --- | --- |\n")
            info = record.resolve_task("pick the hemostat")
            row = record.log_row(info, "bright", 5, "local", "cadence ok", path, when="2026-10-17 18:05")
            self.assertEqual(row, "| 2026-10-17 18:05 | Operating room | hemostat | hand-out | bright | 5 | local | cadence ok |")
            self.assertEqual(row, format_row("2026-10-17 18:05", "Operating room", "hemostat", "hand-out",
                                             "bright", 5, "local", "cadence ok"))
            self.assertTrue(path.read_text().endswith(row + "\n"))
            self.assertEqual(path.read_text().count(HEADER), 1)

    def test_fallback_writer_same_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a.md", Path(tmp) / "b.md"
            info = record.resolve_task("return the mayo scissors")
            ledger_row = record.log_row(info, "dim", 2, "local", "x|y", a, when="2026-10-17 19:00")
            with mock.patch.dict("sys.modules", {"ledger.logbook": None}):
                own_row = record.log_row(info, "dim", 2, "local", "x|y", b, when="2026-10-17 19:00")
            self.assertEqual(ledger_row, own_row)
            self.assertEqual(a.read_text(), b.read_text())


class CheckSetupTests(unittest.TestCase):
    def test_no_devices(self):
        with tempfile.TemporaryDirectory() as tmp:
            measured = []

            def measure(i, seconds, out_dir, label, cv2=None):
                measured.append(i)
                return {"index": i, "opened": False, "width": None, "height": None, "fps": None,
                        "frame": None, "ok": False, "error": "would not open"}
            r = check_setup.run_check(seconds=0.01, out=tmp, comports=lambda: [], names=[], measure=measure,
                                      known={})
            self.assertFalse(r["ok"])
            self.assertEqual(r["ports"]["ports"], [])
            self.assertEqual(r["cameras"], [])  # blind probes that never opened are not listed
            self.assertEqual(measured, [0, 1, 2, 3, 4])
            json.dumps(r)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                check_setup.print_table(r)
            self.assertIn("FAIL", out.getvalue())
            self.assertIn("none found", out.getvalue())

    def test_ports_listed_not_opened(self):
        ports = [SimpleNamespace(device="/dev/cu.usbmodem1", description="USB Single Serial", hwid="", vid=0x1A86),
                 SimpleNamespace(device="/dev/cu.usbmodem2", description="USB Single Serial", hwid="", vid=0x1A86),
                 SimpleNamespace(device="/dev/cu.Bluetooth-Incoming-Port", description="n/a", hwid="", vid=None)]
        r = check_setup.list_ports(lambda: ports, known={})
        self.assertTrue(r["ok"])
        self.assertEqual(sum(p["arm_candidate"] for p in r["ports"]), 2)

    def test_cameras_by_name(self):
        names = ["icspring camera", "HD Pro Webcam C920"]
        self.assertEqual(check_setup.resolve_camera("C920", names)[0], 1)
        self.assertEqual(check_setup.resolve_camera("3", [])[0], 3)
        self.assertIsNone(check_setup.resolve_camera("camera", names + ["MacBook Pro Camera"])[0])

        def measure(i, seconds, out_dir, label, cv2=None):
            return {"index": i, "opened": True, "width": 640, "height": 480, "fps": 30.0, "frame": None,
                    "ok": True, "error": None}
        ports = [SimpleNamespace(device=f"COM{i}", description="USB-SERIAL CH340", hwid="", vid=0x1A86) for i in (5, 6)]
        with tempfile.TemporaryDirectory() as tmp:
            r = check_setup.run_check("C920", "icspring", 0.01, tmp, comports=lambda: ports, names=names,
                                      measure=measure, known={})
        self.assertTrue(r["ok"])
        self.assertEqual(r["roles"]["side"]["index"], 1)
        self.assertEqual({c["role"] for c in r["cameras"]}, {"side", "wrist"})

    def test_measure_with_fake_opencv(self):
        import numpy as np

        class Cap:
            def __init__(self, *a):
                pass

            def isOpened(self):
                return True

            def set(self, *a):
                return True

            def read(self):
                return True, np.zeros((480, 640, 3), np.uint8)

            def release(self):
                pass
        saved = []
        fake = SimpleNamespace(VideoCapture=Cap, CAP_AVFOUNDATION=1, CAP_DSHOW=2, CAP_ANY=0,
                               CAP_PROP_FRAME_WIDTH=3, CAP_PROP_FRAME_HEIGHT=4, CAP_PROP_FPS=5,
                               imwrite=lambda p, f: saved.append(p) or True)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(check_setup.time, "perf_counter",
                                                                     side_effect=(i / 30 for i in range(10 ** 6))):
            row = check_setup.measure_camera(0, 1.0, Path(tmp), "HD Pro Webcam C920", cv2=fake)
        self.assertTrue(row["ok"], row)
        self.assertEqual((row["width"], row["height"]), (640, 480))
        self.assertTrue(saved and saved[0].endswith("camera0-HD-Pro-Webcam-C920.jpg"))

    def test_no_pyserial(self):
        def missing():
            raise ImportError("no serial")
        r = check_setup.list_ports(missing, known={})
        self.assertIn("pyserial", r["error"])


if __name__ == "__main__":
    unittest.main()
