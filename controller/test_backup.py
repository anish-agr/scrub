"""The sim backup (`run_all backup`) end to end: a sim-arm controller on free ports, offline, no keys, one scripted run.

  .venv/bin/python -m pytest -q controller/test_backup.py      # about a minute (MuJoCo, real-time motion)
"""
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest

from . import run_all as R

ROOT = Path(__file__).resolve().parent.parent
pytest.importorskip("mujoco")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def sim_stack():
    port, sim_port, tmp = _free_port(), _free_port(), Path(tempfile.mkdtemp())
    env = {**os.environ, "MONGODB_URI": "", "TIGER_DATABASE_URL": "", "BACKBOARD_API_KEY": "",
           "LEDGER_BUFFER": str(tmp / "buffer.jsonl"), "SCRUB_STATE_FILE": "", "SCRUB_TRIES_FILE": str(tmp / "t.json"),
           "VISION_URL": "http://127.0.0.1:9"}  # nothing listens: the sim arm's own TrayState stands in
    proc = subprocess.Popen([sys.executable, "-m", "controller", "--sim-arm", "--port", str(port),
                             "--sim-port", str(sim_port)], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    try:
        end = time.time() + 60
        while not R.answers(f"{url}/state") and time.time() < end:
            assert proc.poll() is None, "the sim controller exited at start"
            time.sleep(0.3)
        assert R.answers(f"{url}/state"), "the sim controller never answered"
        yield url, sim_port
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_sim_state_says_sim_and_not_real(sim_stack):
    st = httpx.get(f"{sim_stack[0]}/state", timeout=5).json()
    assert (st["fake_arm"], st.get("arm"), st.get("sim")) == (True, "sim", True), st


def test_backup_run_is_clean_on_the_sim_arm(sim_stack, capsys):
    url, sim_port = sim_stack
    t0 = time.time()
    code = R.main(["backup", "--url", url, "--sim-port", str(sim_port), "--no-open", "--pause", "0.3", "--offline"])
    out = capsys.readouterr().out
    assert code == 0 and "backup run 1: CLEAN" in out and "FAIL" not in out, out
    assert out.count("ok  ") == len(R.BACKUP_SCRIPT), out
    assert time.time() - t0 < 120, time.time() - t0
    evs = httpx.get(f"{url}/events/recent", params={"n": 200}, timeout=5).json()
    handed = [e for e in evs if e["type"] in ("handed", "set_down") and e.get("t", 0) >= t0]
    assert handed and all(e["arm"] == "sim" and e["fake_arm"] is True for e in handed), handed


def test_backup_refuses_a_taken_port_without_url(sim_stack, capsys):
    url, _ = sim_stack
    port = url.rsplit(":", 1)[1]
    assert R.main(["backup", "--port", port, "--no-open", "--offline"]) == 1
    assert "is taken by another controller" in capsys.readouterr().out
