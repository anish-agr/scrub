"""Offline voice -> controller -> MuJoCo proof. No ports or cameras on the real arm.

python -m sim.which_one_smoke --base-port 8300
Uses run_all --offline --base-port 8300 --setting bench --no-open --arm sim.
"""
import argparse
import os
import tempfile
import time
from pathlib import Path

import httpx

from controller import run_all as R


def run(base_port=8300):
    with tempfile.TemporaryDirectory(prefix="scrub-which-one-") as tmp:
        # No test rows in Atlas and no saved count from another demo.
        os.environ.update(SCRUB_TEST="1", SCRUB_STATE_FILE="", MONGODB_URI="",
                          LEDGER_BUFFER=str(Path(tmp) / "events.jsonl"),
                          SCRUB_TRIES_FILE=str(Path(tmp) / "tries.json"))
        args = R.parse(["--offline", "--base-port", str(base_port), "--setting", "bench",
                        "--no-open", "--arm", "sim"])
        stack = R.Stack()
        ctl = f"http://127.0.0.1:{base_port}"
        voice = f"http://127.0.0.1:{base_port - 5000}"
        sim = f"http://127.0.0.1:{base_port + 2}"
        try:
            # run_all normally reuses optional services. A proof must own every service it calls.
            for port in R.ports(args).values():
                assert not R.port_busy(port), f"port {port} is occupied; choose a free base port"
            ok, skipped = R.bring_up(args, stack)
            assert ok and "voice" not in skipped, "the offline sim and voice must both start"
            assert {c.name for c in stack.children} >= {"voice", "controller"}, "do not reuse another stack"
            with httpx.Client(timeout=35, trust_env=False) as client:
                assert client.get(ctl + "/state").json()["arm"] == "sim"
                health = client.get(voice + "/health").json()
                assert health["ok"] and health["controller_url"] == f"http://localhost:{base_port}"
                assert not any(health["keys"].values()), "voice must be offline"
                before = client.get(sim + "/state").json()["items"]["flathead_screwdriver"]
                pose = client.get(sim + "/state").json()["q"]
                asked = client.post(voice + "/heard", json={"text": "screwdriver", "context": "which-one-smoke"}).json()
                print("SIMULATION ask:", " ".join(asked["say"]))
                assert any("Which screwdriver" in line for line in asked["say"]), asked
                unanswered_until = time.monotonic() + 0.6
                while time.monotonic() < unanswered_until:
                    ev = client.get(ctl + "/events/recent?n=200").json()
                    state = client.get(ctl + "/state").json()
                    current = client.get(sim + "/state").json()
                    assert state["step"] == "idle" and not state["queue"], state
                    assert not any(e["type"] in ("picked", "handed") or
                                   (e["type"] == "command" and e.get("action") == "handover") for e in ev)
                    assert max(abs(a - b) for a, b in zip(pose, current["q"])) < 0.001
                    assert current["holding"] is None
                    time.sleep(0.1)
                answer = client.post(voice + "/heard", json={"text": "Phillips", "context": "which-one-smoke"}).json()
                print("SIMULATION answer:", " ".join(answer["say"]))
                deadline = time.monotonic() + 25
                while time.monotonic() < deadline:
                    ev = client.get(ctl + "/events/recent?n=200").json()
                    if any(e["type"] == "handed" and e.get("item") == "phillips_screwdriver" for e in ev):
                        break
                    time.sleep(0.1)
                else:
                    raise AssertionError("Phillips was not handed in the sim")
                picks = [e["item"] for e in ev if e["type"] == "picked"]
                assert picks == ["phillips_screwdriver"], picks
                assert client.get(sim + "/state").json()["items"]["flathead_screwdriver"] == before
                assert any(e["type"] == "clarify_answer" for e in ev), "the answer must be logged"
                print("SIMULATION PASS: no pick before answer; picked Phillips; flathead untouched; question and answer logged.")
        finally:
            stack.stop()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-port", type=int, default=8300)
    run(p.parse_args().base_port)
