"""MediaPipe hand landmarker and the open-palm check."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import cv2
import httpx

logger = logging.getLogger("vision.hand")

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task"
)

# Tip landmark, then the middle joint of that digit (IP for the thumb, PIP for the rest).
FINGERS = (
    (4, 3),
    (8, 6),
    (12, 10),
    (16, 14),
    (20, 18),
)
# Wrist plus the four finger MCP joints. That is the palm, not the fingertips.
PALM_LANDMARKS = (0, 5, 9, 13, 17)


def model_path(repo: Path) -> Path:
    return repo / "vision" / "models" / "hand_landmarker.task"


def ensure_model(repo: Path) -> Path:
    path = model_path(repo)
    if path.exists() and path.stat().st_size > 1000:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("downloading hand landmarker model")
    with httpx.stream("GET", MODEL_URL, timeout=60, follow_redirects=True) as response:
        response.raise_for_status()
        with path.open("wb") as handle:
            for chunk in response.iter_bytes():
                handle.write(chunk)
    return path


def _xy(landmark):
    if hasattr(landmark, "x"):
        return float(landmark.x), float(landmark.y)
    return float(landmark[0]), float(landmark[1])


def landmark_px(landmarks, index: int, width: int, height: int) -> tuple[float, float]:
    x, y = _xy(landmarks[index])
    return x * width, y * height


def _dist(a, b) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def palm_center(landmarks, width: int, height: int) -> list[int]:
    points = [landmark_px(landmarks, index, width, height) for index in PALM_LANDMARKS]
    x = sum(point[0] for point in points) / len(points)
    y = sum(point[1] for point in points) / len(points)
    return [int(round(x)), int(round(y))]


def hand_is_open(landmarks, width: int, height: int) -> bool:
    """Open when every fingertip is farther from the wrist than that finger's middle joint."""
    wrist = landmark_px(landmarks, 0, width, height)
    for tip, middle in FINGERS:
        tip_px = landmark_px(landmarks, tip, width, height)
        middle_px = landmark_px(landmarks, middle, width, height)
        if _dist(tip_px, wrist) <= _dist(middle_px, wrist):
            return False
    return True


def hand_box(landmarks, width: int, height: int, pad: int = 8) -> list[float]:
    points = [landmark_px(landmarks, index, width, height) for index in range(len(landmarks))]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return [min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad]


def synthetic_landmarks(open_hand: bool = True) -> list[list[float]]:
    """21 normalized landmarks. Used by the fake camera and the tests."""
    points = [[0.5, 0.75] for _ in range(21)]
    points[0] = [0.50, 0.80]
    fingers = (
        (1, 2, 3, 4),
        (5, 6, 7, 8),
        (9, 10, 11, 12),
        (13, 14, 15, 16),
        (17, 18, 19, 20),
    )
    for index, (cmc, mcp, pip, tip) in enumerate(fingers):
        x = 0.38 + index * 0.06
        points[cmc] = [x, 0.72]
        points[mcp] = [x, 0.66]
        if open_hand:
            points[pip] = [x, 0.52]
            points[tip] = [x, 0.36]
        else:
            points[pip] = [x, 0.60]
            points[tip] = [x, 0.70]
    return points


class HandTracker:
    def __init__(self, task_path: Path | None):
        self.task_path = task_path
        self._landmarker = None
        self._timestamp_ms = 0
        self._warned = False

    def detect(self, bgr):
        """Return a list of hands. Each hand is a sequence of normalized landmarks."""
        if self.task_path is None or not Path(self.task_path).exists():
            if not self._warned:
                logger.warning("hand landmarker model missing; reporting no hand")
                self._warned = True
            return []
        try:
            landmarker = self._ensure()
        except Exception:
            if not self._warned:
                logger.exception("hand landmarker failed to load")
                self._warned = True
            return []
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        rgb = np_as_contiguous(rgb)
        import mediapipe as mp

        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        timestamp = self._next_timestamp()
        result = landmarker.detect_for_video(mp_image, timestamp)
        return list(result.hand_landmarks or [])

    def _ensure(self):
        if self._landmarker is not None:
            return self._landmarker
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision as mp_vision

        options = mp_vision.HandLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(self.task_path)),
            running_mode=mp_vision.RunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._landmarker = mp_vision.HandLandmarker.create_from_options(options)
        return self._landmarker

    def _next_timestamp(self) -> int:
        now = int(time.monotonic() * 1000)
        if now <= self._timestamp_ms:
            now = self._timestamp_ms + 1
        self._timestamp_ms = now
        return now


def np_as_contiguous(rgb):
    import numpy as np

    return np.ascontiguousarray(rgb)
