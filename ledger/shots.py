"""Save Devpost screenshots from a fake-arm case.

Run from the repo root:

    python -m ledger.shots

Uses :8000 (controller), :8001 (vision) and :8080 (ledger page). Starts
`python -m controller --fake-arm`, `python -m vision --fake` and `python -m ledger serve`
on whichever of those ports are free, runs one hemostat handover on the controller
at :8000 (refused if it is on the real arm), rewrites the PNGs under docs/media/
(tracked), then stops what it started. Run it only with no live stack.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "docs" / "media"
PY = sys.executable


def _get(url: str):
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode())


def _post(url: str, body: dict | None = None) -> dict:
    data = json.dumps(body or {}).encode()
    request = urllib.request.Request(url, data=data, method="POST")
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            raw = response.read().decode()
            parsed = json.loads(raw) if raw else {}
            return parsed if isinstance(parsed, dict) else {}
    except urllib.error.HTTPError as error:
        raw = error.read().decode()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"reason": raw or error.reason}
        if not isinstance(parsed, dict):
            parsed = {"reason": raw}
        if "reason" not in parsed and parsed.get("detail"):
            parsed["reason"] = parsed["detail"]
        parsed.setdefault("accepted", False)
        return parsed


def _up(url: str) -> bool:
    try:
        urllib.request.urlopen(url, timeout=1)
        return True
    except Exception:
        return False


def _chrome() -> str:
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        shutil.which("google-chrome") or "",
        shutil.which("chromium") or "",
    ]
    for path in candidates:
        if path and Path(path).exists():
            return path
    raise SystemExit("Chrome is not installed, so the screenshots were not taken")


def _shot(chrome: str, url: str, dest: Path, width: int, height: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            f"--window-size={width},{height}",
            f"--screenshot={dest}",
            "--virtual-time-budget=8000",
            url,
        ],
        check=True,
        timeout=40,
    )
    print(f"wrote {dest}")


def _start(args: list[str], log_name: str) -> subprocess.Popen:
    log = Path("/tmp") / f"scrub-{log_name}"
    handle = log.open("ab")
    try:
        return subprocess.Popen(args, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT)
    finally:
        handle.close()


def _wait(url: str, seconds: float = 20) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if _up(url):
            return
        time.sleep(0.2)
    raise SystemExit(f"never answered: {url}")


def run_case(started: list) -> str:
    if not _up("http://127.0.0.1:8000/state"):
        started.append(_start([PY, "-m", "controller", "--fake-arm"], "controller.log"))
        _wait("http://127.0.0.1:8000/state")
    state = _get("http://127.0.0.1:8000/state")
    if not isinstance(state, dict) or state.get("fake_arm") is not True:
        raise SystemExit("the controller is on the real arm; screenshots stay on --fake-arm")
    if not _up("http://127.0.0.1:8001/health"):
        started.append(_start([PY, "-m", "vision", "--fake"], "vision.log"))
    if not _up("http://127.0.0.1:8080/api/stats"):
        started.append(_start([PY, "-m", "ledger", "serve"], "ledger.log"))
    _wait("http://127.0.0.1:8001/health")
    _wait("http://127.0.0.1:8080/api/stats")
    if state.get("step") in ("stopped", "error"):
        _post("http://127.0.0.1:8000/reset", {})
        deadline = time.time() + 20
        while time.time() < deadline:
            state = _get("http://127.0.0.1:8000/state")
            if isinstance(state, dict) and state.get("step") == "idle":
                break
            time.sleep(0.25)
    asked_at = time.time()
    reply = _post(
        "http://127.0.0.1:8000/command",
        {
            "action": "handover",
            "item": "hemostat",
            "heard": "hemostat",
            "source": "dashboard",
            "t": asked_at,
        },
    )
    if reply.get("accepted") is False:
        print(f"handover refused: {reply.get('reason')}")
    deadline = time.time() + 50
    state = {}
    while time.time() < deadline:
        state = _get("http://127.0.0.1:8000/state")
        if not isinstance(state, dict):
            state = {}
        recent = _get("http://127.0.0.1:8000/events/recent?n=30")
        if not isinstance(recent, list):
            recent = []
        fresh = []
        for event in recent:
            if not isinstance(event, dict):
                continue
            try:
                stamp = float(event.get("t") or 0)
            except (TypeError, ValueError):
                stamp = 0.0
            if stamp >= asked_at - 0.5 and event.get("type") in (
                "handed", "set_down", "released", "missed", "stopped", "error",
            ):
                fresh.append(event)
        # Idle before the worker starts still has the previous count. Wait for this handover.
        if fresh and state.get("step") in ("idle", "stopped", "error"):
            break
        time.sleep(0.25)
    case_id = state.get("case_id") or ""
    print(f"case {case_id} step {state.get('step')} out {state.get('out')}")
    return case_id


def _stop(started: list) -> None:
    for proc in started:
        if proc.poll() is None:
            proc.terminate()
    for proc in started:
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> None:
    argparse.ArgumentParser(prog="python -m ledger.shots", description=__doc__,
                            formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    started: list = []
    try:
        _shots(run_case(started))
    finally:
        _stop(started)  # never leave a controller, vision or ledger page behind


def _shots(case_id: str) -> None:
    chrome = _chrome()
    pages = [
        ("http://127.0.0.1:8000/", MEDIA / "dashboard.png", 1280, 1500),
        ("http://127.0.0.1:8000/tablet.html", MEDIA / "tablet.png", 1280, 900),
        (
            f"http://127.0.0.1:8080/case.html?id={case_id}",
            MEDIA / "case.png",
            1280,
            900,
        ),
        ("http://127.0.0.1:8080/", MEDIA / "public.png", 1280, 1100),
        ("http://127.0.0.1:8080/", MEDIA / "public-phone.png", 500, 1700),
    ]
    for url, dest, width, height in pages:
        _shot(chrome, url, dest, width, height)


if __name__ == "__main__":
    main()
