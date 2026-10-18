"""Where is the item, really? Centre, rotation and offset from its slot, for smart pick (GET /locate, GET /safe_zone).

Local check first (OpenCV on the slot crop), Perceptron box second, Gemini only when those two disagree or the answer
is weak. Never raises over HTTP: a miss is found false, method "none", confidence 0.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path

import cv2
import numpy as np

from vision.calibrate import arm_to_pixel, pixel_to_arm
from vision.geometry import box_center
from vision.local_detect import crop_box, occupied_crop
from vision.tray import detection_box, match_item, normalize_label

# Physical size of the tray (width, height) in mm, used to turn pixel offsets into mm when there is no calibration.
# A standard instrument tray is about 400 x 300 mm. A setting can override it with "tray_mm": [w, h].
TRAY_MM = (400.0, 300.0)

DISAGREE_MM = 15.0  # local and Perceptron centres further apart than this are a disagreement
LOW_CONFIDENCE = 0.5  # below this we ask Gemini
BUDGET_S = 2.5  # per request, all steps
GEMINI_TIMEOUT_S = 4.0
PAD = 0.30  # slot box padding for the local search
TAG_TTL_S = 60.0
ROOT = Path(__file__).resolve().parent.parent


def _miss(item_id: str, error: str | None = None, **extra) -> dict:
    out = {
        "item": item_id, "found": False, "center_px": None, "slot_center_px": None, "offset_px": None,
        "offset_mm": None, "yaw_deg": None, "arm_xy": None, "arm_offset": None, "confidence": 0.0,
        "method": "none", "agree": None, "tray": None, "setting_ok": None, "t": time.time(),
    }
    out.update(extra)
    if error:
        out["error"] = error
    return out


# ---------------------------------------------------------------- local

def _wrap_axis(deg: float) -> float:
    """Wrap an axis angle (a line, not an arrow) into [-90, 90)."""
    return (deg + 90.0) % 180.0 - 90.0


def local_estimate(frame, slot, reference=None) -> dict:
    """Presence, centre (full-frame px), long-axis yaw vs the slot's long axis, and confidence from one slot crop.

    The background is the median of the padded crop's border, so a dark instrument on a light tray and the reverse
    both segment. Returns {"present": bool, "center": [x, y] | None, "yaw": float | None, "conf": float}.
    """
    h, w = frame.shape[:2]
    sw, sh = slot[2] - slot[0], slot[3] - slot[1]
    padded = [slot[0] - PAD * sw, slot[1] - PAD * sh, slot[2] + PAD * sw, slot[3] + PAD * sh]
    x0, y0 = max(0, int(padded[0])), max(0, int(padded[1]))
    x1, y1 = min(w, int(padded[2])), min(h, int(padded[3]))
    inner = crop_box(frame, slot)
    if x1 - x0 < 8 or y1 - y0 < 8 or inner is None:
        return {"present": False, "center": None, "yaw": None, "conf": 0.0}
    crop = frame[y0:y1, x0:x1]
    full, _score = occupied_crop(inner, reference)
    gray = cv2.GaussianBlur(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), (5, 5), 0).astype(np.float32)
    border = np.concatenate([gray[0], gray[-1], gray[:, 0], gray[:, -1]])
    diff = np.abs(gray - float(np.median(border))).astype(np.uint8)
    thresh, mask = cv2.threshold(diff, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if thresh < 20:  # a flat crop: Otsu would split noise
        mask[:] = 0
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    big = max(contours, key=cv2.contourArea) if contours else None
    if not full or big is None or cv2.contourArea(big) < 0.03 * sw * sh:
        # The crop looks occupied but nothing separable: the item is there, we can't refine it.
        return {"present": bool(full), "center": None, "yaw": None, "conf": 0.45 if full else 0.4}
    rect = cv2.minAreaRect(big)
    pts = cv2.boxPoints(rect)
    edges = [pts[(i + 1) % 4] - pts[i] for i in range(4)]
    long_edge = max(edges, key=lambda e: float(np.hypot(*e)))
    axis = math.degrees(math.atan2(float(long_edge[1]), float(long_edge[0])))
    slot_axis = 0.0 if sw >= sh else 90.0
    yaw = _wrap_axis(axis - slot_axis)
    m = cv2.moments(big)
    cx = m["m10"] / m["m00"] + x0 if m["m00"] else rect[0][0] + x0
    cy = m["m01"] / m["m00"] + y0 if m["m00"] else rect[0][1] + y0
    rect_area = max(1.0, rect[1][0] * rect[1][1])
    fill = min(1.0, cv2.contourArea(big) / rect_area)
    bx, by, bw, bh = cv2.boundingRect(big)
    touches = bx <= 1 or by <= 1 or bx + bw >= crop.shape[1] - 1 or by + bh >= crop.shape[0] - 1
    conf = 0.5 + 0.4 * fill - (0.2 if touches else 0.0)
    return {"present": True, "center": [float(cx), float(cy)], "yaw": float(yaw), "conf": float(max(0.0, min(0.95, conf)))}


# ---------------------------------------------------------------- perceptron

def perceptron_estimate(detector, frame, setting: dict, item: dict, slot) -> dict:
    """{"ran": bool, "present": bool, "center": [x, y] | None}. The detector gives no confidence and no yaw."""
    if detector is None:
        return {"ran": False, "present": False, "center": None}
    name = (item.get("name") or item["id"]).replace("_", " ")
    detections = detector.detect(frame, [name])
    centers = []
    for det in detections or []:
        if match_item(det.get("mention", ""), setting) != item["id"] and normalize_label(det.get("mention", "")) != normalize_label(name):
            continue
        box = detection_box(det)
        if box:
            centers.append(box_center(box))
    if not centers:
        return {"ran": True, "present": False, "center": None}
    if slot:
        sc = box_center(slot)
        centers.sort(key=lambda c: math.hypot(c[0] - sc[0], c[1] - sc[1]))
    return {"ran": True, "present": True, "center": [float(centers[0][0]), float(centers[0][1])]}


# ---------------------------------------------------------------- gemini

GEMINI_SCHEMA = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "center_px": {"type": "array", "items": {"type": "number"}},
        "yaw_deg": {"type": "number"},
    },
    "required": ["found", "center_px", "yaw_deg"],
}


def ask_gemini(jpeg: bytes, item_name: str, slot_box, timeout: float = GEMINI_TIMEOUT_S) -> dict | None:
    """Gemini structured output on the overhead frame. None without GEMINI_API_KEY, on timeout or any failure."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return None
    try:
        from vision.reading import GeminiOCR

        hint = f" It should be near the box {[round(v) for v in slot_box]} (x0, y0, x1, y1)." if slot_box else ""
        prompt = (
            f"This is an overhead photo of a surgical instrument tray. Find the {item_name}.{hint} Return found, "
            "center_px as [x, y] in image pixels, and yaw_deg: the rotation in degrees (-90 to 90, clockwise "
            "positive in the image) of the instrument's long axis away from horizontal. If it is not visible "
            "set found false and use 0 for the numbers."
        )
        data = GeminiOCR(key, timeout=timeout).extract(jpeg, prompt, GEMINI_SCHEMA, "locate")
        center = data.get("center_px")
        return {
            "found": bool(data.get("found")),
            "center_px": [float(center[0]), float(center[1])] if isinstance(center, list) and len(center) >= 2 else None,
            "yaw_deg": float(data["yaw_deg"]) if isinstance(data.get("yaw_deg"), (int, float)) else None,
        }
    except Exception:
        return None


# ---------------------------------------------------------------- locate

def _find_slot(frame, setting: dict, item_id: str):
    """(item dict, slot box, tray corners). A null slot takes its box from the towel tray when it is found."""
    from vision.tray_find import find_tray_corners, setting_with_tray

    item = next((i for i in setting.get("items") or [] if i.get("id") == item_id), None)
    if item is None:
        return None, None, None
    corners = setting.get("tray_corners") or find_tray_corners(frame)
    slot = item.get("slot")
    if slot is None and corners:
        placed = setting_with_tray(setting, corners)
        slot = next((i.get("slot") for i in placed["items"] if i["id"] == item_id), None)
    return item, slot, corners


def _mm_per_px(frame, setting: dict, corners) -> float:
    tray_w_mm = float((setting.get("tray_mm") or TRAY_MM)[0])
    if corners:
        xs = [p[0] for p in corners]
        width = max(xs) - min(xs)
    else:
        slots = [i["slot"] for i in setting.get("items") or [] if i.get("slot")]
        width = max(s[2] for s in slots) - min(s[0] for s in slots) if len(slots) > 1 else frame.shape[1]
    return tray_w_mm / max(1.0, float(width))


def _dist_mm(a, b, mm_px: float) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1]) * mm_px


def locate(frame, setting, item_id, *, detector=None, local=None, gemini=None, calibration=None, tray_tag=None,
           budget_s: float = BUDGET_S) -> dict:
    """The item's pose against its slot. See SPEC "Located pose". gemini=None uses ask_gemini (a no-op without a key).

    local is a vision.local_detect.LocalDetector whose empty-slot references are used for presence, or None.
    """
    deadline = time.monotonic() + budget_s
    try:
        return _locate(frame, setting, item_id, detector, local, gemini, calibration, tray_tag, deadline)
    except Exception as exc:  # never raise to the route
        return _miss(item_id, f"{type(exc).__name__}: {exc}")


def _call(pool: ThreadPoolExecutor, deadline: float, fn, *args):
    """Run fn in the pool; None if it fails or misses the deadline."""
    future = pool.submit(fn, *args)
    try:
        return future.result(timeout=max(0.05, deadline - time.monotonic()))
    except (FutureTimeout, Exception):
        return None


def _locate(frame, setting, item_id, detector, local, gemini, calibration, tray_tag, deadline) -> dict:
    if frame is None or not setting:
        return _miss(item_id, "no frame" if frame is None else "no setting")
    item, slot, corners = _find_slot(frame, setting, item_id)
    out = _miss(item_id)
    if tray_tag:
        out["tray"] = tray_tag.get("tray")
        out["setting_ok"] = (tray_tag.get("tray") == setting.get("id")) if tray_tag.get("tray") else None
    if item is None or not slot:
        return out
    sc = box_center(slot)
    out["slot_center_px"] = [float(sc[0]), float(sc[1])]
    mm_px = _mm_per_px(frame, setting, corners)

    reference = (getattr(local, "references", None) or {}).get(item_id)
    loc = local_estimate(frame, slot, reference)
    loc_center = loc["center"] or (list(sc) if loc["present"] else None)

    pool = ThreadPoolExecutor(max_workers=2)
    try:
        per = {"ran": False, "present": False, "center": None}
        if detector is not None:
            got = _call(pool, deadline, perceptron_estimate, detector, frame, setting, item, slot)
            if got is not None:
                per = got

        both = per["ran"]
        if both:
            if loc["present"] and per["present"]:
                agree = _dist_mm(loc_center, per["center"], mm_px) <= DISAGREE_MM
            else:
                agree = loc["present"] == per["present"]
        else:
            agree = None

        # Best answer without Gemini.
        center, yaw, conf, method = None, loc["yaw"], 0.0, "none"
        if loc["present"] and per["present"]:
            center, conf = loc_center, (0.95 if agree else 0.4)
            method = "local" if loc["center"] else "slot"
            if agree and not loc["center"]:
                center, method, conf = per["center"], "perceptron", 0.8
        elif loc["present"]:
            center, conf = loc_center, min(loc["conf"], 0.4) if both else loc["conf"]
            method = "local" if loc["center"] else "slot"
        elif per["present"]:
            center, conf, method = per["center"], 0.4, "perceptron"

        if agree is True and not loc["present"] and not per["present"]:
            return {**out, "agree": True}  # both say it is gone: found false, nothing to ask

        if (agree is False or conf < LOW_CONFIDENCE) and time.monotonic() < deadline:
            ask = gemini if gemini is not None else ask_gemini
            ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            name = (item.get("name") or item_id).replace("_", " ")
            answer = _call(pool, deadline, ask, encoded.tobytes(), name, slot) if ok else None
            if isinstance(answer, dict) and answer.get("found") and answer.get("center_px"):
                gc = [float(answer["center_px"][0]), float(answer["center_px"][1])]
                near = [c for c in (loc_center, per["center"]) if c and _dist_mm(c, gc, mm_px) <= DISAGREE_MM]
                center, method = gc, "gemini"
                conf = 0.85 if near else 0.7
                if answer.get("yaw_deg") is not None:
                    yaw = float(answer["yaw_deg"])
            elif isinstance(answer, dict) and not answer.get("found") and not (loc["present"] and per["present"]):
                return {**out, "agree": agree}  # Gemini says it is not there and no two sources claim it
    finally:
        pool.shutdown(wait=False)

    if center is None:
        return {**out, "agree": agree}

    out.update(found=True, center_px=[round(center[0], 1), round(center[1], 1)], agree=agree, method=method,
               confidence=round(float(conf), 2), yaw_deg=None if yaw is None else round(float(yaw), 1))
    dx, dy = center[0] - sc[0], center[1] - sc[1]
    out["offset_px"] = [round(dx, 1), round(dy, 1)]
    out["offset_mm"] = [round(dx * mm_px, 1), round(dy * mm_px, 1)]
    if calibration and calibration.get("homography"):
        h = calibration["homography"]
        ax, ay = pixel_to_arm(h, center[0], center[1])
        bx, by = pixel_to_arm(h, sc[0], sc[1])
        out["arm_xy"] = [round(ax, 4), round(ay, 4)]
        out["arm_offset"] = [round(ax - bx, 4), round(ay - by, 4)]
        out["offset_mm"] = [round((ax - bx) * 1000, 1), round((ay - by) * 1000, 1)]  # calibration beats the tray size
    out["t"] = time.time()
    return out


# ---------------------------------------------------------------- safe zone

def load_rig(repo: Path = ROOT) -> dict | None:
    """arm/rig.json as plain JSON (arm is not imported here)."""
    try:
        return json.loads((Path(repo) / "arm" / "rig.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def zone_polygon(setting: dict, calibration=None, rig=None) -> list | None:
    """The safe zone as pixel corners: rig safe_zone through the calibration, else setting safe_zone_px."""
    zone = (rig or {}).get("safe_zone")
    if zone and calibration and calibration.get("homography"):
        cx, cy = zone["center"][0], zone["center"][1]
        hx, hy = zone["size"][0] / 2.0, zone["size"][1] / 2.0
        yaw = math.radians(float(zone.get("yaw_deg") or 0.0))
        c, s = math.cos(yaw), math.sin(yaw)
        corners = [(cx + c * dx - s * dy, cy + s * dx + c * dy) for dx, dy in ((-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy))]
        return [list(arm_to_pixel(calibration["homography"], x, y)) for x, y in corners]
    px = (setting or {}).get("safe_zone_px")
    if px and len(px) == 4:
        return [[px[0], px[1]], [px[2], px[1]], [px[2], px[3]], [px[0], px[3]]]
    return None


def _inside(poly, point) -> bool:
    contour = np.array(poly, dtype=np.float32).reshape(-1, 1, 2)
    return cv2.pointPolygonTest(contour, (float(point[0]), float(point[1])), False) >= 0


def safe_zone_check(frame, setting, *, calibration=None, rig=None, detections=None, hand=None) -> dict:
    """Is the set-down square free of a hand and of instruments? clear is None when the zone's pixels are unknown.

    detections: raw Perceptron detections from a fresh read, or None when there is no such read (hand check only,
    method "local"). hand: runtime.hand ({"seen", "palm_px", optional "box"}).
    """
    out = {"clear": None, "blocked_by": [], "item_in_zone": None, "method": "none", "confidence": 0.0, "t": time.time()}
    poly = zone_polygon(setting or {}, calibration, rig)
    if poly is None:
        return out
    blocked, in_zone = [], None
    if hand and hand.get("seen", True):
        palm, box = hand.get("palm_px"), hand.get("box") or hand.get("hand_box")
        zx = [p[0] for p in poly]
        zy = [p[1] for p in poly]
        overlap = bool(box) and not (box[2] < min(zx) or box[0] > max(zx) or box[3] < min(zy) or box[1] > max(zy))
        if overlap or (palm and _inside(poly, palm)):
            blocked.append("hand")
    if detections is not None:
        for det in detections:
            box = detection_box(det)
            item_id = match_item(det.get("mention", ""), setting or {})
            if box and item_id and _inside(poly, box_center(box)):
                in_zone = in_zone or item_id
                if item_id not in blocked:
                    blocked.append(item_id)
    out.update(clear=not blocked, blocked_by=blocked, item_in_zone=in_zone,
               method="perceptron" if detections is not None else "local",
               confidence=0.8 if detections is not None else 0.5)
    return out


# ---------------------------------------------------------------- routes

class RuntimeDetector:
    """The tray loop's last Perceptron answer when it is fresh (a live detect is 2 to 5 s, past the route's budget),
    otherwise the runtime's own detector."""

    def __init__(self, runtime, max_age_s: float = 2.0):
        self.runtime, self.max_age_s = runtime, max_age_s

    def detect(self, frame, categories):
        tray = self.runtime.tray
        if (isinstance(tray, dict) and tray.get("detector") == "perceptron" and not tray.get("stale")
                and time.time() - float(tray.get("t") or 0) <= self.max_age_s):
            with self.runtime.lock:
                return list(self.runtime.detections)
        return self.runtime.detector.detect(frame, categories)


def register(app, runtime) -> None:
    """Add GET /locate and GET /safe_zone to the vision app. Both answer 200 with an error string, never 500."""
    from fastapi.concurrency import run_in_threadpool
    import asyncio

    from vision import reading
    from vision.service import setting_document

    # Test hooks: app.state.locate_hooks = {"detector":..., "gemini":..., "tag_reader": ...}
    app.state.locate_hooks = {}
    cache = {"tag": None, "t": 0.0, "busy": False}

    def refresh_tag(frame):
        try:
            hooks = app.state.locate_hooks
            reader = hooks.get("tag_reader") or (lambda img: reading.read_tray_tag(
                img, backends=getattr(app.state, "read_backends", None), repo=runtime.repo))
            result = reader(frame)
            cache["tag"] = result if isinstance(result, dict) and result.get("tray") else None
            cache["t"] = time.time()
        except Exception:
            cache["t"] = time.time()
        finally:
            cache["busy"] = False

    def current_tag(frame):
        """The last tray tag read, refreshed in the background at most every 60 s so a request never waits on OCR."""
        if time.time() - cache["t"] > TAG_TTL_S and not cache["busy"]:
            cache["busy"] = True
            threading.Thread(target=refresh_tag, args=(frame.copy(),), daemon=True).start()
        return cache["tag"]

    def work_locate(item_id):
        latest = runtime.grabber.latest()
        if latest is None:
            return _miss(item_id, "no overhead frame yet")
        frame = latest[0]
        hooks = app.state.locate_hooks
        return locate(frame, setting_document(runtime), item_id, detector=hooks.get("detector") or RuntimeDetector(runtime),
                      local=runtime.local_detector, gemini=hooks.get("gemini"), calibration=runtime.calibration,
                      tray_tag=current_tag(frame))

    @app.get("/locate")
    async def locate_route(item: str = ""):
        try:
            return await asyncio.wait_for(run_in_threadpool(work_locate, item), BUDGET_S + 0.5)
        except asyncio.TimeoutError:
            return _miss(item, "timeout")
        except Exception as exc:
            return _miss(item, f"{type(exc).__name__}: {exc}")

    def work_zone():
        latest = runtime.grabber.latest()
        frame = latest[0] if latest else None
        with runtime.lock:
            tray, hand = runtime.tray, runtime.hand
            detections = list(runtime.detections)
        fresh = (isinstance(tray, dict) and tray.get("detector") == "perceptron" and not tray.get("stale")
                 and time.time() - float(tray.get("t") or 0) <= 8.0)
        return safe_zone_check(frame, setting_document(runtime), calibration=runtime.calibration,
                               rig=load_rig(runtime.repo), detections=detections if fresh else None, hand=hand)

    @app.get("/safe_zone")
    async def safe_zone_route():
        try:
            return await asyncio.wait_for(run_in_threadpool(work_zone), BUDGET_S)
        except Exception as exc:
            return {"clear": None, "blocked_by": [], "item_in_zone": None, "method": "none", "confidence": 0.0,
                    "t": time.time(), "error": f"{type(exc).__name__}: {exc}"}
