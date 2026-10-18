"""Read the sim's overhead MJPEG stream. Same grabber interface as a webcam."""

from __future__ import annotations

import os
import urllib.error
import urllib.request

import cv2
import numpy as np

DEFAULT_SIM_URL = "http://127.0.0.1:8002"


def sim_stream_url(base: str | None = None) -> str:
    root = (base or os.environ.get("SIM_URL") or DEFAULT_SIM_URL).rstrip("/")
    if root.endswith("/stream"):
        return root
    return root + "/stream"


def frame_from_buffer(buffer: bytes) -> tuple[np.ndarray | None, bytes]:
    """Pull one JPEG out of an MJPEG byte stream. Returns the frame and the leftover bytes."""
    start = buffer.find(b"\xff\xd8")
    end = buffer.find(b"\xff\xd9", start + 2 if start >= 0 else 0)
    if start < 0 or end < 0:
        if len(buffer) > 2_000_000:
            return None, buffer[-4:]
        return None, buffer
    jpg = buffer[start : end + 2]
    frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
    return frame, buffer[end + 2 :]


class SimCapture:
    """Overhead frames from `python -m sim` (port 8002). A dropped stream is opened again on the next read."""

    def __init__(self, url: str | None = None, timeout: float = 2.0):
        self.url = sim_stream_url(url)
        self.timeout = timeout
        self.props: dict = {}
        self.opened = True
        self.unplugged = False
        self.reconnects = 0
        self.last_error = ""
        self._stream = None
        self._buffer = b""

    def isOpened(self):
        return self.opened and not self.unplugged

    def set(self, prop, value):
        self.props[prop] = value
        return True

    def get(self, prop):
        if prop in self.props:
            return float(self.props[prop])
        return 0.0

    def _close_stream(self):
        stream = self._stream
        self._stream = None
        self._buffer = b""
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass

    def _ensure(self):
        if self._stream is not None:
            return
        self._stream = urllib.request.urlopen(self.url, timeout=self.timeout)
        self.reconnects += 1

    def read(self):
        if self.unplugged or not self.opened:
            return False, None
        try:
            self._ensure()
            while True:
                frame, self._buffer = frame_from_buffer(self._buffer)
                if frame is not None:
                    return True, frame
                chunk = self._stream.read(8192)
                if not chunk:
                    raise ConnectionError("sim stream closed")
                self._buffer += chunk
        except Exception as exc:
            self.last_error = type(exc).__name__ + ": " + str(exc)
            self._close_stream()
            return False, None

    def release(self):
        self.opened = False
        self._close_stream()
