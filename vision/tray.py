"""Perceptron tray perception. Maps detections onto slot boxes and posts a TrayState."""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from pathlib import Path

import cv2
import httpx

from vision.geometry import center_inside, iou, normalize_label

logger = logging.getLogger("vision.tray")
ROOT = Path(__file__).resolve().parent.parent
_missing_settings: set[str] = set()

DETECT_URL = "https://api.perceptron.inc/v1/detect"

# Used when settings/<id>.json is not on disk yet (Evan's task). Boxes stay null.
FALLBACK_ITEMS = {
    "surgical": ["scalpel", "hemostat", "mayo_scissors"],
    "dental": ["mouth_mirror", "explorer", "cotton_pliers"],
    "bench": ["needle_nose_pliers", "wire_cutters", "hex_key"],
}

# Asked alongside the instruments so a robot arm in the path can block a handoff.
EXTRA_CATEGORIES = ("robot arm", "gripper")
BLOCK_LABELS = {"robot arm", "arm", "person", "hand"}
GRIPPER_LABELS = {"gripper", "robot gripper"}


def fallback_setting(setting_id: str) -> dict:
    items = []
    for item_id in FALLBACK_ITEMS.get(setting_id, FALLBACK_ITEMS["surgical"]):
        items.append(
            {
                "id": item_id,
                "name": item_id.replace("_", " "),
                "aliases": [],
                "sharp": item_id == "scalpel",
                "slot": None,
                "pick_instruction": f"pick the {item_id.replace('_', ' ')}",
                "return_instruction": f"return the {item_id.replace('_', ' ')}",
            }
        )
    return {"id": setting_id, "label": setting_id, "items": items, "return_spot": None}


def load_setting(repo: Path, setting_id: str) -> dict:
    path = repo / "settings" / f"{setting_id}.json"
    if not path.exists():
        if setting_id not in _missing_settings:
            _missing_settings.add(setting_id)
            logger.info("settings/%s.json missing; using item ids with null boxes", setting_id)
        return fallback_setting(setting_id)
    import json

    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def item_labels(item: dict) -> set[str]:
    raw = [item.get("id", ""), item.get("name", "")]
    raw.extend(item.get("aliases") or [])
    return {normalize_label(text) for text in raw if text}


def categories_for(setting: dict, include_extras: bool = True) -> list[str]:
    categories = []
    for item in setting.get("items") or []:
        name = (item.get("name") or item["id"]).replace("_", " ").strip()
        if name and "," not in name and name not in categories:
            categories.append(name)
    if include_extras:
        for extra in EXTRA_CATEGORIES:
            if extra not in categories:
                categories.append(extra)
    return categories


def match_item(mention: str, setting: dict) -> str | None:
    key = normalize_label(mention or "")
    if not key:
        return None
    for item in setting.get("items") or []:
        if key in item_labels(item):
            return item["id"]
    return None


def detection_box(detection: dict) -> list[float] | None:
    point_box = detection.get("point_box")
    if not point_box:
        return None
    top_left = point_box.get("top_left") or {}
    bottom_right = point_box.get("bottom_right") or {}
    if "x" not in top_left or "x" not in bottom_right:
        return None
    return [
        float(top_left["x"]),
        float(top_left["y"]),
        float(bottom_right["x"]),
        float(bottom_right["y"]),
    ]


def _slot_hit(detection_box_px, slot) -> bool:
    if slot is None:
        return False
    return center_inside(detection_box_px, slot) or iou(detection_box_px, slot) >= 0.15


class PerceptronDetector:
    """POST /v1/detect. Boxes come back in pixels. The API does not return confidence."""

    def __init__(self, api_key: str, url: str = DETECT_URL, timeout: float = 4.0):
        self.api_key = api_key
        self.url = url
        self.timeout = timeout
        self.last_latency_s: float | None = None

    def detect(self, bgr, categories: list[str]) -> list[dict]:
        if not self.api_key:
            raise RuntimeError("PERCEPTRON_API_KEY is empty")
        ok, encoded = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        if not ok:
            raise RuntimeError("could not encode frame")
        data_url = "data:image/jpeg;base64," + base64.b64encode(encoded.tobytes()).decode("ascii")
        payload = {
            "media": {"type": "image", "image_url": data_url},
            "categories": categories,
            "config": {"output": "box", "reasoning_effort": "none"},
        }
        started = time.perf_counter()
        response = httpx.post(
            self.url,
            json=payload,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=self.timeout,
        )
        self.last_latency_s = time.perf_counter() - started
        response.raise_for_status()
        body = response.json()
        if body.get("error"):
            raise RuntimeError(body["error"].get("message") or "detect error")
        return list(body.get("detections") or [])


class FakeDetector:
    """Fake tray detector that simulates detections for all items in the active setting,
    tracks slot emptying from the controller or programmatically, and can place items in the return spot.
    """

    def __init__(self, controller_url: str | None = None, repo: Path | None = None):
        self.controller_url = (controller_url or os.environ.get("CONTROLLER_URL", "http://localhost:8000")).rstrip("/")
        self.repo = repo or ROOT
        self._empty_items: set[str] = set()
        self._filled_items: set[str] = set()
        self._return_item: str | None = None
        self._client = httpx.Client(timeout=0.2)
        self.calls = 0

    def empty_slot(self, item_id: str) -> None:
        self._empty_items.add(item_id)
        self._filled_items.discard(item_id)

    def fill_slot(self, item_id: str) -> None:
        self._empty_items.discard(item_id)
        self._filled_items.add(item_id)

    def set_return_spot(self, item_id: str | None) -> None:
        self._return_item = item_id

    def reset(self) -> None:
        self._empty_items.clear()
        self._filled_items.clear()
        self._return_item = None

    def _sync_with_controller(self) -> tuple[set[str], str | None, dict | None]:
        empty = set(self._empty_items)
        ret_item = self._return_item
        setting_doc = None
        try:
            resp = self._client.get(f"{self.controller_url}/state")
            if resp.status_code == 200:
                state = resp.json()
                step = state.get("step")
                item = state.get("item")
                out = state.get("out") or []
                if step in ("checking", "moving_to_hand", "waiting_for_pull", "releasing", "setting_down") and item:
                    empty.add(item)
                for out_item in out:
                    if step != "returning" or item != out_item:
                        empty.add(out_item)
                if step == "returning" and item:
                    empty.discard(item)
        except Exception:
            pass
        try:
            resp = self._client.get(f"{self.controller_url}/setting")
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and data.get("items"):
                    setting_doc = data
        except Exception:
            pass
        for f in self._filled_items:
            empty.discard(f)
        return empty, ret_item, setting_doc

    def detect(self, frame, categories: list[str]) -> list[dict]:
        self.calls += 1
        empty_items, return_item, setting_doc = self._sync_with_controller()
        detections = []

        slots_by_id = {}
        ret_box = [400, 300, 520, 380]
        if setting_doc:
            for it in setting_doc.get("items") or []:
                if it.get("slot"):
                    slots_by_id[it["id"]] = it["slot"]
            if setting_doc.get("return_spot"):
                ret_box = setting_doc["return_spot"]

        default_boxes = [
            [60, 80, 200, 140],
            [220, 80, 360, 140],
            [380, 80, 520, 140],
        ]
        item_categories = [c for c in categories if c not in EXTRA_CATEGORIES]
        for index, category in enumerate(item_categories):
            normalized = normalize_label(category)
            item_id = normalized.replace(" ", "_")
            if item_id in empty_items:
                continue
            box = slots_by_id.get(item_id) or default_boxes[index % len(default_boxes)]
            detections.append(
                {
                    "mention": category,
                    "confidence": 0.95,
                    "point_box": {
                        "top_left": {"x": box[0], "y": box[1]},
                        "bottom_right": {"x": box[2], "y": box[3]},
                    },
                }
            )

        if return_item:
            detections.append(
                {
                    "mention": return_item.replace("_", " "),
                    "confidence": 0.95,
                    "point_box": {
                        "top_left": {"x": ret_box[0], "y": ret_box[1]},
                        "bottom_right": {"x": ret_box[2], "y": ret_box[3]},
                    },
                }
            )

        return detections


def tray_from_detections(setting: dict, detections: list[dict], stale: bool = False) -> dict:
    """Build a TrayState. A slot with a null box counts a matching detection anywhere."""
    by_item: dict[str, list] = {item["id"]: [] for item in setting.get("items") or []}
    for detection in detections:
        item_id = match_item(detection.get("mention", ""), setting)
        box = detection_box(detection)
        if item_id and box is not None:
            by_item.setdefault(item_id, []).append(box)

    slots = []
    for item in setting.get("items") or []:
        slot = item.get("slot")
        hits = by_item.get(item["id"]) or []
        if slot is None:
            present = bool(hits)
        else:
            present = any(_slot_hit(box, slot) for box in hits)
        slots.append(
            {
                "item": item["id"],
                "present": present,
                "confidence": 1.0,
                "box": slot,
            }
        )

    return_box = setting.get("return_spot")
    return_item = None
    if return_box is not None:
        for item in setting.get("items") or []:
            for box in by_item.get(item["id"]) or []:
                if _slot_hit(box, return_box):
                    return_item = item["id"]
                    break
            if return_item:
                break

    return {
        "setting": setting.get("id"),
        "slots": slots,
        "return_spot": {
            "item": return_item,
            "confidence": 1.0 if return_item else 0.0,
            "box": return_box,
        },
        "stale": stale,
        "t": time.time(),
    }


def empty_tray(setting: dict, stale: bool = True) -> dict:
    return tray_from_detections(setting, [], stale=stale)


def gripper_and_obstacles(detections: list[dict], target_hand_box):
    """Gripper pixel from a gripper detection, and boxes that can block the path."""
    gripper_px = None
    obstacles = []
    for detection in detections:
        label = normalize_label(detection.get("mention") or "")
        box = detection_box(detection)
        if box is None:
            continue
        if label in GRIPPER_LABELS:
            cx, cy = ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)
            gripper_px = [cx, cy]
            continue
        if label not in BLOCK_LABELS:
            continue
        if target_hand_box and iou(box, target_hand_box) > 0.3:
            continue
        obstacles.append(box)
    return gripper_px, obstacles
