"""Overhead camera with locked exposure and one shared frame grabber."""

from __future__ import annotations

import threading
import time

import cv2
import numpy as np

# On UVC cameras OpenCV uses 0.75 for auto exposure and 0.25 for manual.
# V4L2 uses 3 for auto and 1 for manual. We try the manual values and keep
# the first one the camera does not report back as auto.
MANUAL_EXPOSURE_CANDIDATES = (0.25, 1.0, 0.0)
AUTO_EXPOSURE_READINGS = {0.75, 3.0}


def is_manual_exposure(value: float) -> bool:
    return float(value) not in AUTO_EXPOSURE_READINGS


def lock_controls(cap, exposure: float | None = -6.0, white_balance: float | None = 4500.0) -> dict:
    """Turn off auto exposure and auto white balance, then hold a fixed exposure.

    Some UVC cameras report auto exposure as -1 no matter what you set. Writing
    CAP_PROP_EXPOSURE is what actually holds the brightness.
    """
    cap.set(cv2.CAP_PROP_AUTO_WB, 0)
    if white_balance is not None:
        cap.set(cv2.CAP_PROP_WB_TEMPERATURE, float(white_balance))

    chosen = None
    for value in MANUAL_EXPOSURE_CANDIDATES:
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, value)
        readback = float(cap.get(cv2.CAP_PROP_AUTO_EXPOSURE))
        if is_manual_exposure(readback):
            chosen = value
            break
    if chosen is None:
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, MANUAL_EXPOSURE_CANDIDATES[0])

    if exposure is not None:
        cap.set(cv2.CAP_PROP_EXPOSURE, float(exposure))

    return {
        "auto_exposure": float(cap.get(cv2.CAP_PROP_AUTO_EXPOSURE)),
        "exposure": float(cap.get(cv2.CAP_PROP_EXPOSURE)),
        "auto_wb": float(cap.get(cv2.CAP_PROP_AUTO_WB)),
        "wb_temperature": float(cap.get(cv2.CAP_PROP_WB_TEMPERATURE)),
    }


def exposure_is_locked(controls: dict) -> bool:
    return is_manual_exposure(controls.get("auto_exposure", 0.75)) and float(controls.get("auto_wb", 1)) == 0.0


def open_capture(index: int):
    """Open the overhead camera. Prefer DirectShow on Windows, then Media Foundation."""
    cap = None
    for backend in (getattr(cv2, "CAP_DSHOW", cv2.CAP_ANY), getattr(cv2, "CAP_MSMF", cv2.CAP_ANY), cv2.CAP_ANY):
        attempt = cv2.VideoCapture(index, backend)
        if attempt.isOpened():
            cap = attempt
            break
        attempt.release()
    if cap is None:
        cap = cv2.VideoCapture(index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


class FrameGrabber:
    """One thread reads the camera. Hand tracking and tray perception share the latest frame."""

    def __init__(self, capture):
        self.capture = capture
        self._lock = threading.Lock()
        self._frame = None
        self._t = 0.0
        self._misses = 0
        self.reads_ok = False
        self.fps = 0.0  # frames read per second, averaged over about 1 s
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._loop, name="frame-grabber", daemon=True)
        self._thread.start()
        return self

    def _loop(self):
        n, t0 = 0, time.time()
        while not self._stop.is_set():
            ok, frame = self.capture.read()
            if not ok or frame is None:
                self._misses += 1
                if self._misses >= 15:
                    self.reads_ok = False
                time.sleep(0.02)
                continue
            with self._lock:
                self._frame = frame
                self._t = time.time()
                self._misses = 0
                self.reads_ok = True
            n += 1
            if self._t - t0 >= 1.0:
                self.fps, n, t0 = n / (self._t - t0), 0, self._t

    def latest(self):
        with self._lock:
            if self._frame is None:
                return None
            return self._frame.copy(), self._t

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        release = getattr(self.capture, "release", None)
        if release:
            release()


class FakeCapture:
    """Camera stand-in. Auto exposure pulls every frame back to a mid gray, which is the brightness jump."""

    def __init__(self, width: int = 640, height: int = 480):
        self.width = width
        self.height = height
        self.props: dict = {}
        self.lamp = 40
        self.opened = True
        self.unplugged = False
        self._target_mean = 110.0

    def isOpened(self):
        return self.opened

    def set(self, prop, value):
        self.props[prop] = value
        return True

    def get(self, prop):
        if prop in self.props:
            return float(self.props[prop])
        return 0.0

    def read(self):
        if self.unplugged:
            return False, None
        frame = np.full((self.height, self.width, 3), int(np.clip(self.lamp, 0, 255)), dtype=np.uint8)
        auto = float(self.props.get(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75))
        if not is_manual_exposure(auto):
            mean = float(frame.mean())
            if mean > 1:
                frame = np.clip(frame.astype(np.float32) * (self._target_mean / mean), 0, 255).astype(np.uint8)
        return True, frame

    def release(self):
        self.opened = False
