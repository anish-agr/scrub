"""Windows launcher behavior, without opening services or hardware."""
from unittest.mock import MagicMock, patch

from controller import run_all as R


def test_windows_resolves_npm_and_owns_a_process_group():
    stack = R.Stack(out=lambda _: None)
    child = R.Child("voice", ["npm", "run", "dev"], R.ROOT / "voice", {}, None)
    with patch.object(R.os, "name", "nt"), patch.object(R.shutil, "which", return_value="C:/node/npm.cmd"), \
         patch.object(R.subprocess, "CREATE_NEW_PROCESS_GROUP", 512, create=True), \
         patch.object(R.subprocess, "Popen") as popen, patch.object(R.threading, "Thread"):
        stack.start(child)
    assert popen.call_args.args[0] == ["C:/node/npm.cmd", "run", "dev"]
    assert popen.call_args.kwargs["creationflags"] == 512
    assert "start_new_session" not in popen.call_args.kwargs


def test_windows_force_stop_targets_only_owned_child_tree():
    proc = MagicMock(pid=12345)
    with patch.object(R.os, "name", "nt"), patch.object(R.subprocess, "run") as run:
        R._signal(proc, R.signal.SIGTERM)
    assert run.call_args.args[0] == ["taskkill", "/PID", "12345", "/T", "/F"]


def test_windows_command_split_keeps_backslashes():
    with patch.object(R.os, "name", "nt"):
        assert R.split_command(r'"C:\Program Files\Python\python.exe" C:\Temp\agent.py') == [
            r'C:\Program Files\Python\python.exe', r'C:\Temp\agent.py']
