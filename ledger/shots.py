"""Save Devpost screenshots from a fake-arm case.

Run from the repo root:

    python -m ledger.shots

Starts `python -m controller --fake-arm` and `python -m vision --fake` if those
ports are free, runs one hemostat handover, and writes PNGs under docs/media/.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "docs" / "media"
PY = sys.executable


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode())


def _post(url: str, body: dict | None = None) -> dict:
    data = json.dumps(body or {}).encode()
    request = urllib.request.Request(url, data=data, method="POST")
    request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=8) as response:
        raw = response.read().decode()
        return json.loads(raw) if raw else {}


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
    return subprocess.Popen(args, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT)


def _wait(url: str, seconds: float = 20) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if _up(url):
            return
        time.sleep(0.2)
    raise SystemExit(f"never answered: {url}")


def run_case() -> str:
    started = []
    if not _up("http://127.0.0.1:8000/state"):
        started.append(_start([PY, "-m", "controller", "--fake-arm"], "controller.log"))
    if not _up("http://127.0.0.1:8001/health"):
        started.append(_start([PY, "-m", "vision", "--fake"], "vision.log"))
    if not _up("http://127.0.0.1:8080/api/stats"):
        started.append(_start([PY, "-m", "ledger", "serve"], "ledger.log"))
    _wait("http://127.0.0.1:8000/state")
    _wait("http://127.0.0.1:8001/health")
    _wait("http://127.0.0.1:8080/api/stats")
    _post(
        "http://127.0.0.1:8000/command",
        {
            "action": "handover",
            "item": "hemostat",
            "heard": "hemostat",
            "source": "dashboard",
            "t": time.time(),
        },
    )
    deadline = time.time() + 50
    state = {}
    while time.time() < deadline:
        state = _get("http://127.0.0.1:8000/state")
        if state.get("step") == "idle" and "hemostat" in (state.get("out") or []):
            break
        if state.get("step") in ("stopped", "error"):
            break
        time.sleep(0.25)
    case_id = state.get("case_id") or ""
    print(f"case {case_id} step {state.get('step')} out {state.get('out')}")
    return case_id


def main() -> None:
    case_id = run_case()
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
