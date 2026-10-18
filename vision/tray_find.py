"""Find the tray as a light rectangle on the blue towel, then place the slot boxes on it.

No printed markers. When the towel is not in frame, the caller keeps the boxes in settings.
"""

from __future__ import annotations

import copy

import cv2
import numpy as np


def _order_corners(points: np.ndarray) -> list[list[float]]:
    pts = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    total = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).reshape(-1)
    ordered = [
        pts[int(np.argmin(total))],
        pts[int(np.argmin(diff))],
        pts[int(np.argmax(total))],
        pts[int(np.argmax(diff))],
    ]
    return [[float(p[0]), float(p[1])] for p in ordered]


def _quad(contour) -> np.ndarray | None:
    peri = cv2.arcLength(contour, True)
    if peri < 40:
        return None
    approx = cv2.approxPolyDP(contour, 0.04 * peri, True)
    if len(approx) != 4 or not cv2.isContourConvex(approx):
        return None
    return approx.reshape(4, 2)


def find_tray_corners(bgr: np.ndarray) -> list[list[float]] | None:
    """Four corners of the tray, ordered top-left, top-right, bottom-right, bottom-left. None if the towel is not there."""
    if bgr is None or bgr.size == 0:
        return None
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(hsv, (90, 50, 40), (140, 255, 255))
    blue = cv2.morphologyEx(blue, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    towels, _ = cv2.findContours(blue, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not towels:
        return None
    towel = max(towels, key=cv2.contourArea)
    if cv2.contourArea(towel) < 0.02 * bgr.shape[0] * bgr.shape[1]:
        return None
    x, y, w, h = cv2.boundingRect(towel)
    mask = np.zeros(blue.shape, dtype=np.uint8)
    mask[y : y + h, x : x + w] = 255
    light = cv2.inRange(hsv, (0, 0, 130), (180, 70, 255))
    light = cv2.bitwise_and(light, mask)
    light = cv2.morphologyEx(light, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(light, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    tray = max(contours, key=cv2.contourArea)
    if cv2.contourArea(tray) < 200:
        return None
    quad = _quad(tray)
    if quad is None:
        rect = cv2.minAreaRect(tray)
        quad = cv2.boxPoints(rect)
    return _order_corners(quad)


def _lerp(a, b, t: float) -> np.ndarray:
    return np.asarray(a, dtype=np.float64) * (1.0 - t) + np.asarray(b, dtype=np.float64) * t


def _bounds(points) -> list[int]:
    arr = np.asarray(points, dtype=np.float64)
    x0, y0 = arr.min(axis=0)
    x1, y1 = arr.max(axis=0)
    return [int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))]


def boxes_from_corners(corners: list[list[float]], n_items: int) -> tuple[list[list[int]], list[int]]:
    """Slot boxes along the tray, and a return spot just outside the far edge. Both follow the corners."""
    if n_items < 1:
        raise ValueError("need at least one slot")
    tl, tr, br, bl = [np.asarray(p, dtype=np.float64) for p in corners]
    slots = []
    for index in range(n_items):
        t0 = (index + 0.12) / n_items
        t1 = (index + 0.88) / n_items
        slots.append(_bounds([_lerp(tl, bl, t0), _lerp(tr, br, t0), _lerp(tl, bl, t1), _lerp(tr, br, t1)]))
    # One slot-height past the bottom edge, toward the side the return spot sits on in the layout.
    drop = 0.22
    height = 0.7 / n_items
    outer = [
        _lerp(bl, bl + (bl - tl), drop),
        _lerp(br, br + (br - tr), drop),
        _lerp(bl, bl + (bl - tl), drop + height),
        _lerp(br, br + (br - tr), drop + height),
    ]
    return slots, _bounds(outer)


def setting_with_tray(setting: dict, corners: list[list[float]]) -> dict:
    """Copy of the setting whose slot and return_spot boxes sit on this tray."""
    updated = copy.deepcopy(setting)
    items = updated.get("items") or []
    slots, return_box = boxes_from_corners(corners, len(items))
    for item, box in zip(items, slots):
        item["slot"] = box
    updated["return_spot"] = return_box
    updated["tray_corners"] = corners
    return updated


def register_tray(frame, setting: dict) -> dict:
    """Use the towel tray when it is visible. Otherwise leave the settings boxes as they are."""
    corners = find_tray_corners(frame)
    if corners is None:
        return setting
    return setting_with_tray(setting, corners)
