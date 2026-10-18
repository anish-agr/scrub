"""Time the vision loops on a sim-style MJPEG source. No webcam and no Perceptron call."""

from __future__ import annotations

import argparse
import json
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np

from vision.camera import FrameGrabber
from vision.clips import ClipManager
from vision.local_detect import LocalDetector
from vision.service import Runtime, publish_hand, publish_tray
from vision.sim_source import SimCapture
from vision.tray import fallback_setting


class _Poster:
    def post(self, _path, _payload):
        return True

    def current_setting(self, fallback):
        return fallback


def rss_bytes() -> int:
    """Working set of this process. 0 only if the OS call is missing."""
    try:
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return 0
        return int(counters.WorkingSetSize)
    except Exception:
        return 0


def _jpeg() -> bytes:
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[:] = (200, 40, 30)
    cv2.rectangle(frame, (180, 80), (460, 400), (185, 185, 185), -1)
    ok, encoded = cv2.imencode(".jpg", frame)
    if not ok:
        raise RuntimeError("could not encode the profile frame")
    return encoded.tobytes()


class _Mjpeg(ThreadingHTTPServer):
    allow_reuse_address = True


def serve_mjpeg(jpeg: bytes) -> tuple[_Mjpeg, int]:
    boundary = jpeg

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            try:
                while True:
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + boundary + b"\r\n")
                    time.sleep(1 / 15)
            except Exception:
                return

        def log_message(self, _format, *_args):
            return

    server = _Mjpeg(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, name="profile-mjpeg", daemon=True).start()
    return server, server.server_address[1]


class _FastDetect:
    def __init__(self):
        self.calls = 0

    def detect(self, _frame, _categories):
        self.calls += 1
        time.sleep(0.01)
        return []


def sample(seconds: float, url: str) -> dict:
    """Run the hand and tray loops against a sim MJPEG url. Returns fps, detect latency, and memory."""
    capture = SimCapture(url, timeout=2.0)
    grabber = FrameGrabber(capture).start()
    deadline = time.monotonic() + 2.0
    while grabber.latest() is None and time.monotonic() < deadline:
        time.sleep(0.02)
    setting = fallback_setting("surgical")
    for item, box in zip(setting["items"], ([200, 100, 280, 180], [290, 100, 370, 180], [380, 100, 450, 180])):
        item["slot"] = box
    root = Path(tempfile.mkdtemp())
    folder = root / "settings"
    folder.mkdir()
    (folder / "surgical.json").write_text(json.dumps(setting), encoding="utf-8")
    runtime = Runtime(
        grabber=grabber,
        poster=_Poster(),
        tracker=None,
        detector=_FastDetect(),
        repo=root,
        hand_source=lambda _frame: [],
        local_detector=LocalDetector(),
        controls={"auto_exposure": 0.25, "auto_wb": 0.0},
        clips=ClipManager(clips_dir=root / "clips"),
    )
    stop = threading.Event()
    frames = {"n": 0}
    detects = {"n": 0, "slow": 0.0}

    def hand_loop():
        while not stop.is_set():
            started = time.perf_counter()
            publish_hand(runtime)
            frames["n"] += 1
            wait = 0.05 - (time.perf_counter() - started)
            if wait > 0:
                stop.wait(wait)

    def tray_loop():
        while not stop.is_set():
            started = time.perf_counter()
            publish_tray(runtime)
            detects["n"] += 1
            detects["slow"] = max(detects["slow"], runtime.last_detect_s or 0)
            wait = 0.2 - (time.perf_counter() - started)
            if wait > 0:
                stop.wait(wait)

    start_rss = rss_bytes()
    threads = [
        threading.Thread(target=hand_loop, name="profile-hand", daemon=True),
        threading.Thread(target=tray_loop, name="profile-tray", daemon=True),
    ]
    for thread in threads:
        thread.start()
    samples = [start_rss]
    started_at = time.monotonic()
    end = started_at + seconds
    next_report = started_at + 60
    while time.monotonic() < end:
        time.sleep(min(5.0, max(0.0, end - time.monotonic())))
        samples.append(rss_bytes())
        now = time.monotonic()
        if now >= next_report:
            print(
                f"t {now - started_at:.0f}s hand_frames {frames['n']} detects {detects['n']} rss {samples[-1]}",
                flush=True,
            )
            next_report += 60
    stop.set()
    for thread in threads:
        thread.join(timeout=2)
    elapsed = seconds
    grabber.stop()
    peak = max(samples) if samples else 0
    return {
        "seconds": round(elapsed, 1),
        "hand_frames": frames["n"],
        "hand_fps": round(frames["n"] / elapsed, 2) if elapsed else 0,
        "detects": detects["n"],
        "detect_latency_s": round(detects["slow"], 4),
        "rss_start": start_rss,
        "rss_end": samples[-1] if samples else 0,
        "rss_peak": peak,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Profile vision loops on a local sim-style stream")
    parser.add_argument("--seconds", type=float, default=30)
    args = parser.parse_args(argv)
    server, port = serve_mjpeg(_jpeg())
    try:
        stats = sample(args.seconds, f"http://127.0.0.1:{port}/stream")
    finally:
        server.shutdown()
    print(
        f"seconds {stats['seconds']} hand_fps {stats['hand_fps']} "
        f"detects {stats['detects']} detect_latency_s {stats['detect_latency_s']} "
        f"rss_start {stats['rss_start']} rss_end {stats['rss_end']} rss_peak {stats['rss_peak']}"
    )


if __name__ == "__main__":
    main()
