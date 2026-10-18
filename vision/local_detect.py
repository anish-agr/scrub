"""Decide each slot full or empty from the picture when Perceptron does not answer.

An empty slot is a flat crop. A full slot has edges, color, or a difference from an empty reference crop.
"""

from __future__ import annotations

import cv2
import numpy as np

from vision.tray import tray_from_detections


def crop_box(frame, box) -> np.ndarray | None:
    if frame is None or box is None or len(box) != 4:
        return None
    height, width = frame.shape[:2]
    x0 = max(0, min(width - 1, int(box[0])))
    y0 = max(0, min(height - 1, int(box[1])))
    x1 = max(x0 + 1, min(width, int(box[2])))
    y1 = max(y0 + 1, min(height, int(box[3])))
    crop = frame[y0:y1, x0:x1]
    if crop.size == 0:
        return None
    return crop


def occupied_crop(crop: np.ndarray, reference: np.ndarray | None = None) -> tuple[bool, float]:
    """True when the crop looks like it holds an instrument."""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 40, 120)
    edge = float((edges > 0).mean())
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    sat = float(hsv[:, :, 1].mean()) / 255.0
    contrast = float(gray.std()) / 128.0
    diff = 0.0
    if reference is not None and reference.shape == crop.shape:
        diff = float(np.abs(crop.astype(np.int16) - reference.astype(np.int16)).mean()) / 80.0
    score = edge * 2.5 + sat * 1.6 + contrast * 0.9 + diff
    return score >= 0.45, round(min(score, 1.0), 3)


def _detection(item_id: str, box: list) -> dict:
    return {
        "mention": item_id.replace("_", " "),
        "point_box": {
            "top_left": {"x": box[0], "y": box[1]},
            "bottom_right": {"x": box[2], "y": box[3]},
        },
    }


class LocalDetector:
    """Slot occupancy from the image. Remembers an empty crop per slot when it sees one."""

    def __init__(self):
        self.references: dict[str, np.ndarray] = {}

    def set_reference(self, item_id: str, crop: np.ndarray) -> None:
        self.references[item_id] = crop.copy()

    def read(self, frame, setting: dict) -> dict | None:
        items = setting.get("items") or []
        boxed = [item for item in items if item.get("slot")]
        if not boxed and not setting.get("return_spot"):
            return None
        detections = []
        empty_ids = []
        for item in boxed:
            crop = crop_box(frame, item["slot"])
            if crop is None:
                continue
            full, _score = occupied_crop(crop, self.references.get(item["id"]))
            if full:
                detections.append(_detection(item["id"], item["slot"]))
            else:
                empty_ids.append(item["id"])
                if item["id"] not in self.references:
                    self.references[item["id"]] = crop.copy()
        return_box = setting.get("return_spot")
        if return_box and empty_ids:
            crop = crop_box(frame, return_box)
            if crop is not None and occupied_crop(crop, self.references.get("return_spot"))[0]:
                detections.append(_detection(empty_ids[0], return_box))
            elif crop is not None and "return_spot" not in self.references:
                self.references["return_spot"] = crop.copy()
        return tray_from_detections(setting, detections, stale=False, detector="local")
