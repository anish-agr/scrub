"""Shared box math for tray slots and the blocked-path check."""

from __future__ import annotations


def normalize_label(text: str) -> str:
    return " ".join(text.lower().replace("_", " ").replace("-", " ").split())


def box_center(box) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def center_inside(box, slot) -> bool:
    if not box or not slot:
        return False
    cx, cy = box_center(box)
    return slot[0] <= cx <= slot[2] and slot[1] <= cy <= slot[3]


def iou(a, b) -> float:
    if not a or not b:
        return 0.0
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if inter <= 0:
        return 0.0
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    if union <= 0:
        return 0.0
    return inter / union


def segment_hits_box(start, end, box, samples: int = 24) -> bool:
    if not box:
        return False
    x1, y1, x2, y2 = box
    for step in range(samples + 1):
        t = step / samples
        x = start[0] + (end[0] - start[0]) * t
        y = start[1] + (end[1] - start[1]) * t
        if x1 <= x <= x2 and y1 <= y <= y2:
            return True
    return False


def path_is_clear(gripper_px, target_px, obstacles) -> bool:
    """False when a hand or the arm sits on the segment from the gripper to the target.

    Unknown gripper means we cannot see a block, so the path stays clear and the
    controller does not freeze on every frame before calibration.
    """
    if gripper_px is None or target_px is None:
        return True
    for box in obstacles:
        if segment_hits_box(gripper_px, target_px, box):
            return False
    return True
