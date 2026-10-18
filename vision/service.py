"""Wires the camera, the hand tracker, and tray perception into one process."""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from vision.calibrate import load_calibration, palm_target, target_pixel
from vision.camera import FrameGrabber, exposure_is_locked
from vision.clips import ClipManager
from vision.draw import annotate, jpeg_bytes
from vision.geometry import path_is_clear
from vision.hand import HandTracker, hand_box, hand_is_open, palm_center
from vision.heights import height_for, load_heights, save_heights, set_clinician
from vision.tray import (
    PerceptronDetector,
    categories_for,
    detection_box,
    empty_tray,
    gripper_and_obstacles,
    load_setting,
    tray_from_detections,
)

logger = logging.getLogger("vision")

ROOT = Path(__file__).resolve().parent.parent


class Poster:
    """POST to the controller. Log the first failure for each path, then keep going.

    httpx.Client is safe to share across threads, so the hand loop never waits behind a tray-loop call.
    The lock only guards the warned set.
    """

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._warned: set[str] = set()
        self._lock = threading.Lock()
        self._client = httpx.Client(timeout=0.4)

    def post(self, path: str, payload: dict) -> bool:
        try:
            response = self._client.post(self.base_url + path, json=payload)
            response.raise_for_status()
            return True
        except Exception:
            with self._lock:
                first = path not in self._warned
                self._warned.add(path)
            if first:
                logger.warning("controller %s not accepting %s; continuing", self.base_url, path)
            return False

    def current_setting(self, fallback: str) -> str:
        try:
            response = self._client.get(self.base_url + "/state", timeout=0.4)
            response.raise_for_status()
            setting = response.json().get("setting")
            if setting:
                return setting
        except Exception:
            pass
        return os.environ.get("VISION_SETTING", fallback)

    def get_json(self, path: str):
        try:
            response = self._client.get(self.base_url + path, timeout=0.4)
            response.raise_for_status()
            return response.json()
        except Exception:
            return None


@dataclass
class Runtime:
    grabber: FrameGrabber
    poster: Poster
    tracker: HandTracker
    detector: object
    repo: Path = ROOT
    setting_id: str = "surgical"
    hand_source: object | None = None
    hand_period: float = 0.1
    tray_period: float = 1.0
    include_extra_categories: bool = True
    fake: bool = False
    calibration: dict | None = None
    heights: dict = field(default_factory=dict)
    heights_path: Path | None = None
    clinician: str | None = None
    gripper_px: list | None = None
    controls: dict = field(default_factory=dict)
    hand: dict | None = None
    tray: dict | None = None
    detections: list = field(default_factory=list)
    last_good_tray: dict | None = None
    tray_failing: bool = False
    detect_ms: list = field(default_factory=list)  # last 50 Perceptron detect times
    other_hand_boxes: list = field(default_factory=list)
    lighting: dict | None = None
    last_posted_lighting: str | None = None
    lighting_period: float = 1.0
    clips: ClipManager = field(default_factory=ClipManager)
    lock: threading.Lock = field(default_factory=threading.Lock)
    local_detector: object | None = None
    last_detect_s: float | None = None

    def preview_jpeg(self) -> bytes:
        latest = self.grabber.latest()
        if latest is None:
            import numpy as np

            frame = np.zeros((480, 640, 3), dtype=np.uint8)
        else:
            frame = latest[0]
        with self.lock:
            hand = self.hand
            tray = self.tray
            detections = list(self.detections)
        return jpeg_bytes(annotate(frame, hand, tray, detections))


def choose_hand(hands, width: int, height: int):
    if not hands:
        return None, []
    scored = []
    for landmarks in hands:
        box = hand_box(landmarks, width, height)
        area = max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])
        scored.append((area, landmarks, box))
    scored.sort(key=lambda item: item[0], reverse=True)
    _area, chosen, chosen_box = scored[0]
    others = [box for _area, _landmarks, box in scored[1:]]
    return (chosen, chosen_box), others


def publish_hand(runtime: Runtime) -> dict | None:
    latest = runtime.grabber.latest()
    if latest is None:
        return None
    frame, _t = latest
    runtime.clips.add_frame(frame, _t)
    height, width = frame.shape[:2]
    if runtime.hand_source is not None:
        hands = runtime.hand_source(frame)
    else:
        hands = runtime.tracker.detect(frame)
    chosen, other_boxes = choose_hand(hands, width, height)
    now = time.time()
    if chosen is None:
        message = {
            "seen": False,
            "open": False,
            "palm_px": None,
            "target": None,
            "path_clear": True,
            "t": now,
        }
        target_hand_box = None
        palm = None
    else:
        landmarks, target_hand_box = chosen
        palm = palm_center(landmarks, width, height)
        open_palm = hand_is_open(landmarks, width, height)
        height_m = height_for(runtime.heights, runtime.clinician)
        target = palm_target(runtime.calibration, palm, height_m)
        aim = target_pixel(runtime.calibration, palm, height_m)
        with runtime.lock:
            gripper = runtime.gripper_px
            obstacles = list(other_boxes) + list(runtime.other_hand_boxes)
        clear = path_is_clear(gripper, aim, obstacles)
        message = {
            "seen": True,
            "open": open_palm,
            "palm_px": palm,
            "target": target,
            "target_px": aim,
            "path_clear": clear,
            "t": now,
        }
    with runtime.lock:
        runtime.hand = message
    runtime.poster.post("/vision/hand", message)
    return message


def setting_document(runtime: Runtime) -> dict:
    """Prefer the controller's loaded setting (it has Evan's aliases). Fall back to the file."""
    getter = getattr(runtime.poster, "get_json", None)
    if getter is not None:
        data = getter("/setting")
        if isinstance(data, dict) and data.get("items"):
            return data
    setting_id = runtime.poster.current_setting(runtime.setting_id)
    return load_setting(runtime.repo, setting_id)


# A finished detect within the detector timeout is a Perceptron answer. A normal tray call is
# 3.8 to 4.7 s (docs/RECOGNITION.md), so the cutoff is that timeout (6 s), not a shorter guess.
# Anything slower, or a failed call, uses the local slot check.


def _stale_copy(previous: dict) -> dict:
    state = dict(previous)
    state["stale"] = True
    state["t"] = time.time()
    state["detector"] = "none"
    state["slots"] = [dict(slot) for slot in previous.get("slots") or []]
    state["return_spot"] = dict(previous.get("return_spot") or {})
    return state


def perceive_tray(runtime: Runtime, frame, setting: dict) -> tuple[dict, list]:
    """Perceptron when it answers quickly. Otherwise the local slot check. Stale only if both miss."""
    from vision.tray_find import register_tray

    setting = register_tray(frame, setting)
    categories = categories_for(setting, runtime.include_extra_categories)
    detections = None
    started = time.perf_counter()
    try:
        detections = list(runtime.detector.detect(frame, categories))
    except Exception as exc:
        failed = exc
    else:
        failed = None
    runtime.last_detect_s = time.perf_counter() - started
    history = list(getattr(runtime, "detect_ms", []) or [])
    history.append(round(runtime.last_detect_s * 1000))
    runtime.detect_ms = history[-50:]
    limit = float(getattr(runtime.detector, "timeout", None) or 6.0)
    fresh = detections is not None and failed is None and runtime.last_detect_s <= limit
    if fresh:
        state = tray_from_detections(setting, detections, stale=False, detector="perceptron")
        return state, detections
    local = runtime.local_detector
    if local is not None:
        state = local.read(frame, setting)
        if state is not None:
            return state, []
    if failed is not None:
        raise failed
    if detections is None:
        raise RuntimeError("detect failed")
    state = tray_from_detections(setting, detections, stale=False, detector="perceptron")
    return state, detections


def publish_tray(runtime: Runtime) -> dict | None:
    latest = runtime.grabber.latest()
    if latest is None:
        return None
    frame, _t = latest
    runtime.clips.add_frame(frame, _t)
    setting = setting_document(runtime)
    try:
        state, detections = perceive_tray(runtime, frame, setting)
        from vision import instances
        previous = runtime.last_good_tray or {}
        if state.get("detector") == "perceptron" and "candidates" in state:
            old = previous.get("candidates", []) if previous.get("setting") == state.get("setting") else []
            state["candidates"] = instances.stabilize(state["candidates"], old)
            unresolved = {c["item"] for c in state["candidates"] if c.get("identity_ambiguous")}
            if unresolved:
                state["ambiguous_items"] = sorted(set(state.get("ambiguous_items", [])) | unresolved)
                state["candidates_stale"] = True
            # /locate reuses these detections: carry the same stable physical identity, not a re-numbered slot.
            for detection in detections:
                box = detection_box(detection)
                matches = [c for c in state["candidates"] if c.get("box") == box]
                if len(matches) == 1:
                    detection.update({k: matches[0][k] for k in ("id", "slot", "side", "variant", "slot_source") if k in matches[0]})
        elif previous.get("ambiguous_items") and previous.get("setting") == state.get("setting"):
            # Local occupancy cannot disprove previously observed multiplicity.
            state.update(candidates=previous.get("candidates", []), ambiguous_items=previous["ambiguous_items"], candidates_stale=True)
        with runtime.lock:
            if runtime.tray_failing:
                logger.info("tray perception back")
            runtime.tray_failing = False
            runtime.last_good_tray = state
            runtime.detections = detections
            hand = runtime.hand
        target_box = None
        if hand and hand.get("palm_px"):
            px, py = hand["palm_px"]
            target_box = [px - 40, py - 40, px + 40, py + 40]
        gripper_px, obstacles = gripper_and_obstacles(detections, target_box)
        with runtime.lock:
            if gripper_px is not None:
                runtime.gripper_px = gripper_px
            runtime.other_hand_boxes = obstacles
    except Exception as exc:
        # Once per outage, not once a second. The message names the error type only (never the request headers).
        with runtime.lock:
            first = not runtime.tray_failing
            runtime.tray_failing = True
            previous = runtime.last_good_tray
        if first:
            logger.warning("tray perception failed (%s); posting the last good state as stale", type(exc).__name__)
        if previous:
            state = _stale_copy(previous)
        else:
            state = empty_tray(setting, stale=True)
            state["detector"] = "none"
    with runtime.lock:
        runtime.tray = state
    payload = {
        "setting": state["setting"],
        "slots": state["slots"],
        "return_spot": state["return_spot"],
        "stale": state.get("stale", False),
        "t": state["t"],
    }
    if state.get("detector"):
        payload["detector"] = state["detector"]
    for key in ("candidates", "ambiguous_items", "candidates_stale"):
        if key in state:
            payload[key] = state[key]
    runtime.poster.post("/vision/tray", payload)
    return payload


def classify_lighting(mean_b: float) -> tuple[str, float]:
    """Map frame mean brightness to (lighting_tag, estimated_lux).
    dim: < 60 (~80 lux)
    bright: > 180 (~1200 lux)
    normal: 60-180 (~450 lux)
    """
    if mean_b > 180.0:
        tag = "bright"
        lux = round(min(1800.0, 1000.0 + (mean_b - 180.0) * 10.0), 1)
    elif mean_b < 60.0:
        tag = "dim"
        lux = round(max(20.0, mean_b * 1.5), 1)
    else:
        tag = "normal"
        lux = round(100.0 + (mean_b - 60.0) * (800.0 / 120.0), 1)
    return tag, lux


def publish_lighting(runtime: Runtime) -> dict | None:
    latest = runtime.grabber.latest()
    if latest is None:
        return None
    frame, _t = latest
    mean_b = float(frame.mean())
    tag, lux = classify_lighting(mean_b)
    data = {
        "lighting": tag,
        "lux": lux,
        "brightness": round(mean_b, 1),
        "t": time.time(),
    }
    with runtime.lock:
        runtime.lighting = data
        should_post = runtime.last_posted_lighting != tag
        if should_post:
            runtime.last_posted_lighting = tag
    if should_post:
        runtime.poster.post("/lighting", {"lighting": tag, "lux": lux})
    return data


def _loop(stop: threading.Event, period: float, fn, runtime: Runtime, name: str):
    while not stop.is_set():
        started = time.monotonic()
        try:
            fn(runtime)
        except Exception:
            logger.exception("%s loop failed", name)
        remaining = period - (time.monotonic() - started)
        if remaining > 0:
            stop.wait(remaining)


CLIP_EVENTS = ("picked", "handed", "set_down", "released", "returned", "stopped", "missed")


def _event_key(ev: dict) -> str:
    """One key per event. Every event of a handover shares its command_id, so the id alone is not enough:
    keyed on it, the `command` event hid the picked, handed and released after it and no clip was saved."""
    return f"{ev.get('type')}|{ev.get('command_id')}|{ev.get('t')}"


CLIP_POST_S = 1.5  # ClipManager.record_event's default window after the event


def clip_new_events(runtime: Runtime, events, seen: dict, pending: list, record: bool = True, now: float | None = None) -> None:
    """Queue a clip for each new clip-worthy event, and save the ones whose window after the event has passed.
    `seen` is insertion-ordered and kept short. record=False only marks events seen (the first poll: those
    events predate the frames in the buffer)."""
    for ev in events if isinstance(events, list) else []:
        if not isinstance(ev, dict):
            continue
        key = _event_key(ev)
        if key in seen:
            continue
        seen[key] = True
        if record and ev.get("type") in CLIP_EVENTS:
            pending.append(ev)
    while len(seen) > 500:
        seen.pop(next(iter(seen)))
    now = time.time() if now is None else now
    while pending and float(pending[0].get("t") or 0) + CLIP_POST_S <= now:
        runtime.clips.record_event(pending.pop(0))


def _event_loop(stop: threading.Event, runtime: Runtime):
    seen: dict = {}
    pending: list = []
    primed = False
    while not stop.is_set():
        try:
            getter = getattr(runtime.poster, "get_json", None)
            if getter is not None:
                events = getter("/events/recent?n=20")
                clip_new_events(runtime, events, seen, pending, record=primed)
                primed = primed or isinstance(events, list)
        except Exception:
            logger.exception("clip events failed")
            pending.clear()
        stop.wait(0.5)


def start_loops(runtime: Runtime) -> threading.Event:
    stop = threading.Event()
    threading.Thread(target=_loop, args=(stop, runtime.hand_period, publish_hand, runtime, "hand"), name="hand", daemon=True).start()
    threading.Thread(target=_loop, args=(stop, runtime.tray_period, publish_tray, runtime, "tray"), name="tray", daemon=True).start()
    threading.Thread(target=_loop, args=(stop, runtime.lighting_period, publish_lighting, runtime, "lighting"), name="lighting", daemon=True).start()
    threading.Thread(target=_event_loop, args=(stop, runtime), name="events", daemon=True).start()
    return stop


def remember_clinician(runtime: Runtime, name: str, hand_height_m: float) -> dict:
    data = set_clinician(runtime.heights, name, hand_height_m)
    runtime.heights = data
    runtime.clinician = name
    if runtime.heights_path is not None:
        save_heights(runtime.heights_path, data)
    return data


def _local_detector():
    if os.environ.get("VISION_LOCAL", "1") == "0":
        return None
    from vision.local_detect import LocalDetector

    return LocalDetector()


def build_runtime(
    capture,
    controls: dict | None = None,
    fake_hands=None,
    detector=None,
    controller_url: str | None = None,
    repo: Path | None = None,
    calibration_path: Path | None = None,
    heights_path: Path | None = None,
    fake_calibration: bool = False,
    fake: bool = False,
) -> Runtime:
    repo = repo or ROOT
    controller_url = controller_url or os.environ.get("CONTROLLER_URL", "http://localhost:8000")
    api_key = os.environ.get("PERCEPTRON_API_KEY", "")
    if detector is None:
        detector = PerceptronDetector(
            api_key,
            timeout=float(os.environ.get("VISION_DETECT_TIMEOUT_S") or 6.0),
            max_width=int(os.environ.get("VISION_DETECT_WIDTH") or 640),
        )
    calibration_path = calibration_path or (repo / "vision" / "calibration.json")
    cal = load_calibration(calibration_path)
    if cal is None and fake_calibration:
        from vision.calibrate import synthetic_calibration

        cal = synthetic_calibration()
    heights_path = heights_path or (repo / "vision" / "hand_heights.json")
    grabber = FrameGrabber(capture).start()
    deadline = time.monotonic() + 2.0
    while grabber.latest() is None and time.monotonic() < deadline:
        time.sleep(0.02)
    return Runtime(
        grabber=grabber,
        poster=Poster(controller_url),
        tracker=HandTracker(None if fake_hands is not None else _model(repo)),
        detector=detector,
        repo=repo,
        setting_id=os.environ.get("VISION_SETTING", "surgical"),
        hand_source=fake_hands,
        calibration=cal,
        heights=load_heights(heights_path),
        heights_path=heights_path,
        clinician=os.environ.get("CLINICIAN") or None,
        controls=controls or {},
        include_extra_categories=os.environ.get("VISION_EXTRA_CATEGORIES", "1") != "0",
        local_detector=_local_detector(),
        fake=fake,
    )


def _model(repo: Path):
    from vision.hand import ensure_model

    try:
        return ensure_model(repo)
    except Exception:
        logger.exception("could not download the hand landmarker model")
        return None


def controls_locked(runtime: Runtime) -> bool:
    return exposure_is_locked(runtime.controls)
