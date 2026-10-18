"""The labeled SIMULATION backup video, captured from a running sim backup stack.

Start the stack first (its own ledger file, so another stack's Atlas flush can't take the rows):

  LEDGER_BUFFER=$PWD/data/video/sim-run/ledger.jsonl SCRUB_STATE_FILE= \\
    .venv/bin/python -m controller.run_all backup --offline --loop --pause 2 --base-port 8500 --no-open

Then, while it prints CLEAN:

  LEDGER_BUFFER=$PWD/data/video/sim-run/ledger.jsonl .venv/bin/python -m video.sim_backup capture
  LEDGER_BUFFER=$PWD/data/video/sim-run/ledger.jsonl .venv/bin/python -m video.sim_backup build --root <printed root>

`capture` records the sim overhead MJPEG and headless-Chromium screenshots of the dashboard, resampled to 30 FPS
on the capture clock (time.time at frame arrival, the same clock the controller stamps events with), so playback
is 1x and each clip's start_time is its first frame. `build` ingests both clips as kind simulation, picks one
complete clean case from the ledger that lies inside the capture window, burns the overlay from that case only,
renders without --demo (every frame carries the SIMULATION bar) and copies the result to data/video/out/.
Reads only; nothing here moves an arm or touches a real camera.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import threading
import time
from pathlib import Path

import cv2
import httpx
import numpy as np

from .common import BASE, Workspace, encode, events, info, provenance, read_json, resolve_events, write_json

OUT = BASE / "out"
FAILED = {"error", "missed", "stopped"}


def _mjpeg(url, stop, frames, errors):
    try:
        with httpx.stream("GET", url, timeout=httpx.Timeout(10, read=10)) as response:
            response.raise_for_status()
            buffer = b""
            for chunk in response.iter_bytes():
                buffer += chunk
                while True:
                    start = buffer.find(b"\xff\xd8")
                    end = buffer.find(b"\xff\xd9", start + 2) if start >= 0 else -1
                    if start < 0 or end < 0:
                        buffer = buffer[start:] if start >= 0 else b""
                        break
                    frames.append((time.time(), buffer[start:end + 2]))
                    buffer = buffer[end + 2:]
                if stop.is_set():
                    return
    except Exception as error:  # noqa: BLE001 - reported, never raised from the thread
        errors.append(f"{type(error).__name__}: {error}")


def _resample(stamped, fps=30):
    """Constant-rate frames on the capture clock: frame k shows the newest image that had arrived by t0 + k/fps."""
    t0, t1 = stamped[0][0], stamped[-1][0]
    count = int((t1 - t0) * fps) + 1
    index = 0
    image = None
    for k in range(count):
        now = t0 + k / fps
        while index + 1 < len(stamped) and stamped[index + 1][0] <= now:
            index += 1
            image = None
        if image is None:
            decoded = cv2.imdecode(np.frombuffer(stamped[index][1], np.uint8), cv2.IMREAD_COLOR)
            if decoded is None:
                raise ValueError("Undecodable captured frame")
            h, w = decoded.shape[:2]
            image = decoded[:h - h % 2, :w - w % 2]
        yield image


def capture(root, base_port, seconds):
    sim, controller = f"http://127.0.0.1:{base_port + 2}", f"http://127.0.0.1:{base_port}"
    dashboard = f"{controller}/?vision=http://localhost:{base_port + 1}&ledger=http://localhost:{base_port + 3}"
    state = httpx.get(f"{controller}/state", timeout=5).json()
    if httpx.get(f"{controller}/sim/vision", timeout=5).status_code != 200:
        raise ValueError(f"{controller} is not a sim controller; start the backup stack first")
    ws = Workspace(root)
    raw = ws.root / "raw"
    if raw.exists() and any(raw.iterdir()):
        raise ValueError(f"{raw} already holds a capture; pass a new --root")
    raw.mkdir(parents=True, exist_ok=True)
    stop, overhead, errors = threading.Event(), [], []
    reader = threading.Thread(target=_mjpeg, args=(f"{sim}/stream?cam=overhead", stop, overhead, errors), daemon=True)
    shots = []
    import os
    from playwright.sync_api import sync_playwright
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(BASE / "browser"))
    started = time.time()
    reader.start()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            page.goto(dashboard, wait_until="load", timeout=30000)
            while time.time() - started < seconds:
                before = time.time()
                data = page.screenshot(type="jpeg", quality=90, timeout=30000)
                shots.append(((before + time.time()) / 2, data))
                time.sleep(max(0, 0.25 - (time.time() - before)))
        finally:
            browser.close()
    stop.set()
    reader.join(15)
    ended = time.time()
    if errors or len(overhead) < 30:
        raise RuntimeError(f"Overhead stream gave {len(overhead)} frames: {errors[:1]}")
    clips = {}
    for name, stamped in (("overhead.mp4", overhead), ("dashboard.mp4", shots)):
        result = encode(ws, raw / name, _resample(stamped), 30)
        clips[name] = {"start_time": stamped[0][0], "kind": "simulation", "method": "capture clock (time.time at frame arrival)",
                       "frames_received": len(stamped), "received_fps": len(stamped) / max(1e-6, stamped[-1][0] - stamped[0][0]),
                       "duration_s": result["duration_s"]}
    write_json(ws.out("sync.json"), {name: {k: v[k] for k in ("start_time", "kind", "method")} for name, v in clips.items()})
    report = {"root": str(ws.root), "started": started, "ended": ended, "dashboard": dashboard, "overhead": f"{sim}/stream?cam=overhead",
              "state_at_start": {k: state.get(k) for k in ("step", "setting", "lighting", "fake_arm", "sim_arm", "sim", "arm", "case_id")},
              "clips": clips}
    write_json(ws.out("capture.json"), report)
    return report


def clean_cases(rows, start, end):
    """Cases fully inside [start, end] that ran the whole backup script with no failure."""
    cases = {}
    for row in rows:
        if row.get("case_id"):
            cases.setdefault(row["case_id"], []).append(row)
    found = []
    for case_id, group in sorted(cases.items(), key=lambda kv: kv[1][0]["t"]):
        if group[0]["t"] < start or group[-1]["t"] > end:
            continue
        handovers = [r for r in group if r.get("type") == "command" and r.get("action") == "handover" and r.get("accepted")]
        done = {r.get("command_id") for r in group if r.get("type") in ("handed", "set_down")}
        counted = any(r.get("type") == "command" and r.get("action") == "count" and r.get("accepted") for r in group)
        returned = any(r.get("type") == "returned" for r in group)
        if (len(handovers) >= 3 and all(r.get("command_id") in done for r in handovers) and counted and returned
                and not any(r.get("type") in FAILED for r in group)):
            found.append({"case_id": case_id, "start": group[0]["t"], "end": group[-1]["t"], "events": len(group),
                          "handovers": [(r.get("item"), next((e.get("request_to_hand_s") for e in group
                                         if e.get("command_id") == r.get("command_id") and e.get("request_to_hand_s") is not None), None))
                                        for r in handovers]})
    return found


def build(root, events_flag=None, case_id=None, dashboard_s=6.0):
    from .edit import render
    from .ingest import ingest
    from .overlay import overlay
    ws = Workspace(root)
    ingest(ws, "sync.json")
    ledger, how = resolve_events(ws, events_flag)
    print(f"video.sim_backup: events from {how}", file=sys.stderr)
    clips = {name: provenance(ws.root / "raw" / name) for name in ("overhead.mp4", "dashboard.mp4")}
    span = {name: (meta["start_time"], meta["start_time"] + info(ws.root / "raw" / name)["duration_s"]) for name, meta in clips.items()}
    start, end = span["overhead.mp4"]
    cases = clean_cases(events(ledger), start, end)
    if case_id:
        cases = [c for c in cases if c["case_id"] == case_id]
    if not cases:
        raise ValueError(f"No complete clean case inside the capture window {start:.1f} to {end:.1f}; capture longer")
    case = cases[0]
    overlay(ws, "raw/overhead.mp4", ledger, "overlays/overhead.mp4", case["case_id"])
    in_s = max(0.0, case["start"] - start - 0.5)
    action = round(min(end - start - in_s, case["end"] - start + 2.0 - in_s) * 30) / 30
    d0, d1 = span["dashboard.mp4"]
    dash_in = min(max(0.0, case["end"] - d0 + 0.5), max(0.0, d1 - d0 - dashboard_s))
    dash_len = round(min(dashboard_s, d1 - d0 - dash_in) * 30) / 30
    bindings = {"SIM_CASE": {"source": "overlays/overhead.mp4", "in_s": in_s},
                "SIM_DASHBOARD": {"source": "raw/dashboard.mp4", "in_s": dash_in}}
    write_json(ws.out("sim-backup.json"), bindings)
    edl = ws.out("sim-backup.yaml")
    edl.write_text("version: 1\nwidth: 1920\nheight: 1080\nfps: 30\nreal_only: false  # a SIMULATION backup, never the real-arm cut\n"
                   f"shots:\n - {{slot: SIM_CASE, duration_s: {action}}}\n - {{slot: SIM_DASHBOARD, duration_s: {dash_len}}}\n", encoding="utf-8")
    report = render(ws, edl, ws.out("sim-backup.json"), "renders/sim-backup.mp4")
    OUT.mkdir(parents=True, exist_ok=True)
    final = OUT / "sim-backup.mp4"
    shutil.copyfile(ws.root / "renders/sim-backup.mp4", final)
    shutil.copyfile(Path(str(ws.root / "renders/sim-backup.mp4") + ".video.json"), Path(str(final) + ".video.json"))
    timeline = read_json(ws.root / "overlays" / "overhead-sources.json")["changes"]
    summary = {"output": str(final), "duration_s": report["duration_s"], "frames": report["frames"], "case": case,
               "events_source": how, "case_starts_at_output_s": case["start"] - start - in_s,
               "overlay_changes": [{"output_s": round(c["output_s"] - in_s, 2), "item": c["item"], "seconds": c["seconds"],
                                    "caption": c["caption"], "out": c["out"]} for c in timeline
                                   if c["output_s"] >= in_s and (c["seconds"] is not None or c["caption"])]}
    write_json(OUT / "sim-backup-summary.json", summary)
    return summary


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("capture", help="record the sim overhead stream and the dashboard")
    c.add_argument("--root", help="workspace inside data/video/ (default data/video/sim-run/capture-<time>)")
    c.add_argument("--base-port", type=int, default=8500)
    c.add_argument("--seconds", type=float, default=110, help="one backup pass is about 52 s; 110 s always holds a whole case")
    b = sub.add_parser("build", help="ingest, overlay one clean case, render to data/video/out/sim-backup.mp4")
    b.add_argument("--root", required=True)
    b.add_argument("--events", help="ledger JSONL; default the ledger (LEDGER_BUFFER, ledger/buffer.jsonl, Atlas)")
    b.add_argument("--case-id")
    a = p.parse_args(argv)
    try:
        if a.command == "capture":
            result = capture(a.root or BASE / "sim-run" / f"capture-{int(time.time())}", a.base_port, a.seconds)
        else:
            result = build(a.root, a.events, a.case_id)
        print(json.dumps(result, indent=2, default=str))
        return 0
    except (ValueError, OSError, RuntimeError, KeyError, httpx.HTTPError) as error:
        print(f"video.sim_backup: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
