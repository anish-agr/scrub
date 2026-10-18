"""No hardware: the busy-port refusal in arm_session.py and the --help of the port tools.

  .venv/bin/python -m pytest explore/test_arm_session.py -q
"""
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import arm_session as A  # noqa: E402

ARGS = SimpleNamespace(follower="/dev/tty.f", leader="/dev/tty.l", side=None, wrist=None)


def test_port_users_names_the_holder():
    users = A.port_users("/dev/tty.f", holders=lambda p: [111], ps=lambda pid: (1, "python -m controller --real-arm"))
    assert users == ["pid 111 (python -m controller --real-arm)"]


def test_own_child_is_not_a_holder():
    users = A.port_users("/dev/tty.f", holders=lambda p: [222], ps=lambda pid: (os.getpid(), "arm_session.py"))
    assert users == []


def test_session_child_ignores_its_supervisor_only():
    with mock.patch.dict(os.environ, {"SCRUB_CHILD": "1"}):
        users = A.port_users("/dev/tty.f", holders=lambda p: [os.getppid(), 333], ps=lambda pid: (1, "other"))
    assert users == ["pid 333 (other)"]
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("SCRUB_CHILD", None)
        users = A.port_users("/dev/tty.f", holders=lambda p: [os.getppid()], ps=lambda pid: (1, "zsh"))
    assert users == [f"pid {os.getppid()} (zsh)"]  # a supervisor's parent is a shell, not ours


def test_busy_ports_per_arm():
    busy = A.busy_ports(ARGS, users=lambda p: ["pid 5 (x)"] if p == "/dev/tty.f" else [])
    assert busy == {"follower arm": "follower arm port tty.f in use by pid 5 (x)"}


def test_missing_devices_never_pings_a_busy_bus():
    with mock.patch.object(A, "busy_ports", return_value={"follower arm": "follower arm port tty.f in use by pid 5 (x)"}), \
            mock.patch.object(A.os.path, "exists", return_value=True), \
            mock.patch.object(A, "stuck_motors") as stuck, \
            mock.patch.object(A, "silent_motors", return_value=[]) as silent:
        out = A.missing_devices(ARGS)
    assert out == ["follower arm port tty.f in use by pid 5 (x)"]
    stuck.assert_not_called()
    silent.assert_called_once_with("/dev/tty.l")


def test_session_flags_explicit_degrees():
    src = (HERE / "arm_session.py").read_text()
    assert '"--robot.use_degrees=true"' in src and '"--teleop.use_degrees=true"' in src


def test_port_tools_help_without_the_arm():
    for script in ("thermal_log.py", "home_pose.py", "arm_session.py"):
        out = subprocess.run([sys.executable, str(HERE / script), "--help"], capture_output=True, text=True, timeout=60)
        assert out.returncode == 0, (script, out.stderr[-300:])
        assert out.stdout.startswith("usage:")
