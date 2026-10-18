"""Why is a camera under 30 fps? Measure it at 640x480 a few ways and say which one reaches 29.

    .venv/bin/python explore/camera_fps.py icspring          # the wrist camera
    .venv/bin/python explore/camera_fps.py C920 --seconds 5  # the side camera

Nothing else may hold the camera (stop the station, teleop, the controller first).
On macOS most UVC cameras pick their exposure time from the light: a dim scene makes a
long exposure, and a long exposure caps the frame rate (33 ms per frame at 30 fps).
So the usual fix is more light on what the camera sees, not a setting. The table
prints mean brightness next to fps to show that.
"""
import argparse
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from arm.check_setup import camera_names, resolve_camera  # noqa: E402


def measure(index, seconds, fourcc=None):
    cap = cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION if sys.platform == "darwin" else cv2.CAP_ANY)
    if not cap.isOpened():
        return {"error": "would not open"}
    if fourcc:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 30)
    end = time.perf_counter() + 1.0  # let auto exposure settle
    while time.perf_counter() < end:
        cap.read()
    n, bright, t0 = 0, 0.0, time.perf_counter()
    while time.perf_counter() - t0 < seconds:
        ok, frame = cap.read()
        if ok:
            n += 1
            bright += float(frame.mean())
    dt = time.perf_counter() - t0
    shape = frame.shape[:2] if n else None
    cap.release()
    return {"fps": round(n / dt, 1), "brightness": round(bright / n, 1) if n else None, "shape": shape}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("camera", help='name part ("icspring", "C920") or an OpenCV index')
    p.add_argument("--seconds", type=float, default=4.0)
    a = p.parse_args(argv)
    names = camera_names()
    index, label = resolve_camera(a.camera, names)
    if index is None:
        raise SystemExit(f"camera {a.camera!r} not found in {names}")
    print(f"{label} (index {index}), 640x480 asked at 30 fps, {a.seconds:.0f} s each")
    best = 0.0
    for mode in (None, "MJPG", "YUY2"):
        r = measure(index, a.seconds, mode)
        best = max(best, r.get("fps") or 0)
        print(f"  {mode or 'default':8} {r}")
    if best >= 29:
        print("PASS: at least one mode reaches 29 fps")
    else:
        print("UNDER 29: add light on the scene (lamp on the tray, not into the lens), try another USB port "
              "with no hub, then run again. Brightness under ~80 usually means exposure is capping fps.")
    return 0 if best >= 29 else 1


if __name__ == "__main__":
    raise SystemExit(main())
