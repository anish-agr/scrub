"""Check the recording setup before `python -m arm.record`: arm USB ports and both cameras.

  python -m arm.check_setup                               # ports + every camera found
  python -m arm.check_setup --side C920 --wrist icspring  # also check the two policy cameras by name
  python -m arm.check_setup --side 0 --wrist 1 --json     # Windows: OpenCV indexes, machine output

Ports are only listed (never opened), so the arm's motors are not touched. Each camera is opened
at 640x480 at 30 fps, its real frame rate is measured over --seconds, and one test frame is saved to
--out (default ~/scrub-setup-check/<time>/, outside the repo). Close teleop, recording and vision
first: a camera another process owns fails here.

Cameras are matched by name where the OS gives names (macOS: AVFoundation, the same order OpenCV
uses; Windows: pygrabber if installed), because OpenCV's indexes change when a camera is replugged.
Exit 0 when everything required passes, 1 otherwise.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from pathlib import Path

WIDTH, HEIGHT, FPS = 640, 480, 30
MIN_FPS = 28.0
ARM_HINTS = ("usbmodem", "usbserial", "ch340", "ch341", "ch9102", "wchusbserial", "usb serial", "usb-serial")
ARM_VIDS = {0x1A86, 0x0403, 0x10C4}  # WCH (CH340/CH9102), FTDI, Silicon Labs: the SO-101 driver boards


def camera_names() -> list[str]:
    """Camera names in OpenCV's index order, or [] when the OS gives none."""
    if sys.platform == "darwin":
        try:
            import AVFoundation as AVF
        except ImportError:
            return []
        devs = AVF.AVCaptureDevice.devicesWithMediaType_(AVF.AVMediaTypeVideo)
        # OpenCV's macOS backend sorts devices by uniqueID (which includes the USB location)
        return [str(d.localizedName()) for d in sorted(devs, key=lambda d: str(d.uniqueID()))]
    if sys.platform.startswith("win"):
        try:
            from pygrabber.dshow_graph import FilterGraph
            return list(FilterGraph().get_input_devices())  # DirectShow order = OpenCV CAP_DSHOW index
        except Exception:  # noqa: BLE001 - not installed or no DirectShow
            return []
    return []


def resolve_camera(spec: str | None, names: list[str]) -> tuple[int | None, str]:
    """(index, why) for a name part like "C920" or an index like "0"."""
    if spec is None:
        return None, "not given"
    if str(spec).isdigit():
        return int(spec), "index"
    hits = [i for i, n in enumerate(names) if spec.lower() in n.lower()]
    if len(hits) == 1:
        return hits[0], f"name match {names[hits[0]]!r}"
    if not names:
        return None, f"no camera names on this OS: pass an index instead of {spec!r}"
    return None, f"{spec!r} matches {len(hits)} of {names}"


ROOT = Path(__file__).resolve().parents[1]


def known_ports() -> dict:
    """{port: "follower"/"leader"} from SCRUB_FOLLOWER_PORT / SCRUB_LEADER_PORT, else the ports
    explore/arm_session.py records with on the Mac (read from that file, not copied)."""
    out = {}
    try:
        sys.path.insert(0, str(ROOT / "explore"))
        import arm_session  # no LeRobot or hardware at import time (only arm.hardware/thermal/handoff)
        out = {arm_session.FOLLOWER: "follower", arm_session.LEADER: "leader"}
    except Exception:  # noqa: BLE001 - explore/ missing or mid-edit
        pass
    finally:
        if sys.path and sys.path[0] == str(ROOT / "explore"):
            sys.path.pop(0)
    for role in ("follower", "leader"):
        env = os.environ.get(f"SCRUB_{role.upper()}_PORT")
        if env:
            out = {k: v for k, v in out.items() if v != role}
            out[env] = role
    return out


def _comports():
    from serial.tools import list_ports
    return list_ports.comports()


def list_ports(comports=None, known=None) -> dict:
    """Serial ports and which look like an SO-101 board. Never opens a port."""
    known = known_ports() if known is None else known
    try:
        found = list((comports or _comports)())
    except ImportError:
        devs = sorted(glob.glob("/dev/tty.usbmodem*") + glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))
        return {"ok": len(devs) >= 2, "error": "pyserial not installed (pip install pyserial); listed /dev only",
                "ports": [{"device": d, "description": "", "arm_candidate": True, "role": known.get(d)}
                          for d in devs]}
    ports, seen = [], set()
    for p in found:
        dev, desc = str(getattr(p, "device", p)), str(getattr(p, "description", "") or "")
        hw = str(getattr(p, "hwid", "") or "")
        vid = getattr(p, "vid", None)
        if sys.platform == "darwin" and dev.startswith("/dev/cu."):
            dev = "/dev/tty." + dev[len("/dev/cu."):]  # LeRobot and arm_session use the tty name
        if dev in seen:
            continue
        seen.add(dev)
        text = f"{dev} {desc} {hw}".lower()
        cand = vid in ARM_VIDS or any(h in text for h in ARM_HINTS)
        if "bluetooth" in text or "debug-console" in text:
            cand = False
        ports.append({"device": dev, "description": desc, "arm_candidate": cand, "role": known.get(dev)})
    return {"ok": sum(p["arm_candidate"] for p in ports) >= 2, "error": None, "ports": ports}


def _backend(cv2):
    if sys.platform == "darwin":
        return cv2.CAP_AVFOUNDATION
    if sys.platform.startswith("win"):
        return cv2.CAP_DSHOW
    return cv2.CAP_ANY


def measure_camera(index: int, seconds: float, out_dir: Path | None, label: str, cv2=None) -> dict:
    """Open one camera at 640x480 at 30 fps, count frames for `seconds`, save one frame."""
    row = {"index": index, "opened": False, "width": None, "height": None, "fps": None, "frame": None,
           "ok": False, "error": None}
    if cv2 is None:
        try:
            import cv2
        except ImportError:
            row["error"] = "opencv not installed (pip install opencv-python)"
            return row
    cap = cv2.VideoCapture(index, _backend(cv2))
    try:
        if not cap.isOpened():
            row["error"] = "would not open (unplugged, or another process owns it)"
            return row
        row["opened"] = True
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, FPS)
        first = None
        warm = time.perf_counter() + 1.0  # auto exposure settles, first frames come late
        while time.perf_counter() < warm:
            ok, frame = cap.read()
            if ok:
                first = frame
        frames, t0 = 0, time.perf_counter()
        while time.perf_counter() - t0 < seconds:
            ok, frame = cap.read()
            if ok:
                frames += 1
                first = frame
        dt = time.perf_counter() - t0
        if first is None:
            row["error"] = "opened but sent no frames"
            return row
        row["height"], row["width"] = int(first.shape[0]), int(first.shape[1])
        row["fps"] = round(frames / dt, 1) if dt > 0 else 0.0
        if out_dir is not None:
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"camera{index}-{_safe(label)}.jpg"
            if cv2.imwrite(str(path), first):
                row["frame"] = str(path)
        problems = []
        if (row["width"], row["height"]) != (WIDTH, HEIGHT):
            problems.append(f"size {row['width']}x{row['height']}, need {WIDTH}x{HEIGHT}")
        if row["fps"] < MIN_FPS:
            problems.append(f"{row['fps']} fps, need about {FPS} (close other apps, check USB, lighting)")
        row["error"] = "; ".join(problems) or None
        row["ok"] = not problems
        return row
    finally:
        cap.release()


def _safe(label: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in label).strip("-")[:40] or "camera"


def probe_indexes(names: list[str], max_index: int) -> list[int]:
    return list(range(len(names))) if names else list(range(max_index + 1))


def run_check(side=None, wrist=None, seconds=2.0, out=None, max_index=4, cameras=True,
              comports=None, names=None, cv2=None, measure=measure_camera, known=None) -> dict:
    names = camera_names() if names is None else names
    ports = list_ports(comports, known)
    roles = {}
    for role, spec in (("side", side), ("wrist", wrist)):
        if spec is not None:
            idx, why = resolve_camera(spec, names)
            roles[role] = {"spec": spec, "index": idx, "why": why}
    out_dir = None
    if cameras:
        out_dir = Path(out).expanduser() if out else Path.home() / "scrub-setup-check" / time.strftime("%Y%m%d-%H%M%S")
    cams = []
    indexes = probe_indexes(names, max_index)
    for r in roles.values():
        if r["index"] is not None and r["index"] not in indexes:
            indexes.append(r["index"])
    if cameras:
        for i in sorted(indexes):
            label = names[i] if i < len(names) else f"index{i}"
            row = measure(i, seconds, out_dir, label, cv2=cv2)
            row["name"] = names[i] if i < len(names) else None
            row["role"] = ",".join(k for k, r in roles.items() if r["index"] == i) or None
            if not names and not row["opened"] and row["role"] is None:
                continue  # blind probing on Windows/Linux: an empty index is not a camera
            cams.append(row)
    for role, r in roles.items():
        hit = next((c for c in cams if c["index"] == r["index"]), None) if r["index"] is not None else None
        r["ok"] = bool(hit and hit["ok"]) if cameras else r["index"] is not None
    if roles:
        cams_ok = all(r["ok"] for r in roles.values()) and len(roles) == 2
    else:
        cams_ok = (sum(c["ok"] for c in cams) >= 2) if cameras else len(names) >= 2
    return {"platform": sys.platform, "ok": ports["ok"] and cams_ok, "ports": ports, "camera_names": names,
            "roles": roles, "cameras": cams, "cameras_checked": cameras,
            "frames_dir": str(out_dir) if out_dir else None,
            "need": f"2 arm ports, side + wrist cameras at {WIDTH}x{HEIGHT} >= {MIN_FPS:g} fps"}


def _mark(ok) -> str:
    return "PASS" if ok else "FAIL"


def print_table(r: dict) -> None:
    print("Serial ports (listed only, never opened)")
    if r["ports"]["error"]:
        print(f"  note: {r['ports']['error']}")
    if not r["ports"]["ports"]:
        print("  none found: plug in both arms' USB and power")
    for p in r["ports"]["ports"]:
        tag = (p["role"] or "arm candidate") if p["arm_candidate"] else "other"
        print(f"  {p['device']:<36} {tag:<14} {p['description']}")
    n = sum(p["arm_candidate"] for p in r["ports"]["ports"])
    print(f"  {_mark(r['ports']['ok'])}: {n} arm candidate(s), need 2 (follower + leader). "
          "Unplug one to tell them apart, or run lerobot-find-port")
    print()
    print(f"Cameras ({WIDTH}x{HEIGHT} at {FPS} fps requested)")
    if not r["cameras_checked"]:
        print("  not opened (--no-cameras); names in OpenCV order:")
        for i, n in enumerate(r["camera_names"]):
            print(f"  {i}: {n}")
    else:
        if not r["cameras"]:
            print("  none opened")
        print(f"  {'idx':<4}{'role':<11}{'name':<28}{'size':<10}{'fps':<7}result")
        for c in r["cameras"]:
            size = f"{c['width']}x{c['height']}" if c["width"] else "-"
            fps = f"{c['fps']}" if c["fps"] is not None else "-"
            res = _mark(c["ok"]) + (f" ({c['error']})" if c["error"] else "")
            print(f"  {c['index']:<4}{(c['role'] or ''):<11}{(c['name'] or '?')[:27]:<28}{size:<10}{fps:<7}{res}")
    for role, x in r["roles"].items():
        print(f"  {role}: {x['spec']!r} -> {x['index'] if x['index'] is not None else 'not found'} "
              f"({x['why']}) {_mark(x['ok'])}")
    if not r["roles"]:
        print("  tip: pass --side and --wrist (name part or index) to check the two policy cameras")
    if r["frames_dir"]:
        print(f"  test frames: {r['frames_dir']}")
    print()
    print(f"{_mark(r['ok'])}: {r['need']}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m arm.check_setup", description="List arm ports and check both cameras at 640x480 at 30 fps")
    p.add_argument("--side", help='side camera: name part like "C920", or an OpenCV index')
    p.add_argument("--wrist", help='wrist camera: name part like "icspring", or an OpenCV index')
    p.add_argument("--seconds", type=float, default=2.0, help="how long to measure each camera")
    p.add_argument("--out", help="folder for test frames (default ~/scrub-setup-check/<time>)")
    p.add_argument("--max-index", type=int, default=4, help="indexes to probe when the OS gives no names")
    p.add_argument("--no-cameras", action="store_true", help="only list ports and camera names")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    a = p.parse_args(argv)
    r = run_check(a.side, a.wrist, a.seconds, a.out, a.max_index, cameras=not a.no_cameras)
    if a.json:
        print(json.dumps(r, indent=1))
    else:
        print_table(r)
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
