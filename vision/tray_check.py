"""Tray verification before a case (X3).

Compares detected instruments against the active setting's slots and items,
identifying missing instruments, misplaced instruments (wrong slot), and occupied return spots.
Exposed via GET /tray_check on port 8001.
"""

from __future__ import annotations

import time
from typing import Any

from vision.geometry import center_inside, iou
from vision.tray import detection_box, match_item


def _slot_matches(box: list[float], slot: list[float] | None) -> bool:
    if slot is None or box is None:
        return False
    return center_inside(box, slot) or iou(box, slot) >= 0.15


def check_tray(setting: dict, detections: list[dict]) -> dict[str, Any]:
    """Compare detected items on the tray to the setting's item list and slot definitions.

    Returns:
        ok (bool): True if all items are present in their designated slots and no items are misplaced.
        ready (bool): Alias for ok.
        setting (str): Setting ID.
        missing (list[str]): List of item IDs that are expected but not found in their slot or anywhere on tray.
        wrong_slot (list[dict]): List of items located in the wrong slot or return spot.
        correct (list[str]): List of item IDs found in their correct slots.
        slots (list[dict]): Per-slot status for each item in the setting.
        return_spot (dict): Status of the return spot.
        summary (str): Plain-word summary of the tray status.
    """
    items = setting.get("items") or []
    setting_id = setting.get("id", "unknown")
    return_box = setting.get("return_spot")

    slots_by_id = {it["id"]: it.get("slot") for it in items}

    # Map detections to matched items and their boxes
    detected_items: list[dict[str, Any]] = []
    for d in detections:
        mention = d.get("mention", "")
        item_id = match_item(mention, setting)
        box = detection_box(d)
        if item_id and box is not None:
            detected_items.append({"item": item_id, "mention": mention, "box": box, "detection": d})

    missing: list[str] = []
    wrong_slot: list[dict[str, Any]] = []
    correct: list[str] = []
    correct_set: set[str] = set()
    found_anywhere: set[str] = set()

    for det in detected_items:
        item_id = det["item"]
        box = det["box"]
        found_anywhere.add(item_id)
        expected_slot = slots_by_id.get(item_id)

        if expected_slot is None:
            # Uncalibrated / unmarked slot: detection anywhere counts
            if item_id not in correct_set:
                correct.append(item_id)
                correct_set.add(item_id)
            continue

        if _slot_matches(box, expected_slot):
            if item_id not in correct_set:
                correct.append(item_id)
                correct_set.add(item_id)
        else:
            # Misplaced: find where it is
            found_in = "unassigned"
            if return_box and _slot_matches(box, return_box):
                found_in = "return_spot"
            else:
                for other in items:
                    if other["id"] != item_id and other.get("slot") and _slot_matches(box, other["slot"]):
                        found_in = other["id"]
                        break
            wrong_slot.append(
                {
                    "item": item_id,
                    "expected_slot": expected_slot,
                    "actual_box": box,
                    "found_in": found_in,
                    # Another item's id, or null. The controller words a null as "not in its place"; a
                    # string here was read as an item ("in the unassigned slot", "in the return_spot slot").
                    "in_slot_of": found_in if found_in in slots_by_id else None,
                }
            )

    # A second one of an item (a restock) lying loose is not a misplaced item when one sits in its slot.
    # One in another item's slot still counts: that slot is taken.
    wrong_slot = [w for w in wrong_slot if not (w["item"] in correct_set and w["in_slot_of"] is None)]

    # Check for missing items (not in correct slot and not detected anywhere)
    for item in items:
        item_id = item["id"]
        if item_id not in correct_set:
            if item_id not in found_anywhere:
                missing.append(item_id)

    # Return spot status
    ret_item = None
    if return_box:
        for det in detected_items:
            if _slot_matches(det["box"], return_box):
                ret_item = det["item"]
                break

    return_status = {
        "item": ret_item,
        "box": return_box,
        "occupied": ret_item is not None,
    }

    slots_status = []
    for item in items:
        item_id = item["id"]
        status = "ok" if item_id in correct_set else "missing"
        slots_status.append(
            {
                "item": item_id,
                "status": status,
                "slot": item.get("slot"),
            }
        )

    ok = len(missing) == 0 and len(wrong_slot) == 0

    if ok:
        summary = f"Tray is ready with all {len(items)} items in place."
    else:
        parts = []
        if missing:
            parts.append(f"Missing: {', '.join(missing)}")
        if wrong_slot:
            wrong_descs = [f"{w['item']} (in {w['found_in']} slot)" for w in wrong_slot]
            parts.append(f"Wrong slot: {', '.join(wrong_descs)}")
        summary = ". ".join(parts) + "."

    return {
        "ok": ok,
        "ready": ok,
        "setting": setting_id,
        "missing": missing,
        "wrong_slot": wrong_slot,
        "extra": [],
        "correct": correct,
        "slots": slots_status,
        "return_spot": return_status,
        "stale": False,
        "summary": summary,
        "t": time.time(),
    }
