"""Event clip recording and Perceptron video/caption labeling (X4).

Vision maintains a rolling frame buffer and saves short video clips (.mp4)
around each Event per case_id. After the case, POST /clips/label captions each
clip with Perceptron from 5 frames spread over the clip plus the controller's event ("hemostat handed
to the surgeon's right hand, 6.4 s"). Without a key, or when the call fails, the fallback label is used
("scalpel set at the safe spot, 14:02"). label_source says which one.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

import cv2
import httpx
import numpy as np

logger = logging.getLogger("vision.clips")
ROOT = Path(__file__).resolve().parent.parent

CHAT_COMPLETIONS_URL = "https://api.perceptron.inc/v1/chat/completions"
BUFFER_WIDTH = 640  # frames are kept at this width: 150 full 1280x720 frames would be over 400 MB
_SAFE = re.compile(r"[^A-Za-z0-9._-]")


def safe_name(text: str) -> str:
    """A file or folder name that stays inside clips/ (no slashes, no "..")."""
    name = _SAFE.sub("_", str(text)).strip(".") or "x"
    return name[:120]


def format_event_label(event: dict, timestamp: float | None = None) -> str:
    """Format a clean clinical action label for an event: e.g. 'scalpel set at the safe spot, 14:02'."""
    ev_type = event.get("type", "event")
    item = (event.get("item") or "instrument").replace("_", " ")
    t = timestamp or event.get("t") or time.time()
    time_str = time.strftime("%H:%M", time.localtime(t))

    action_map = {
        "set_down": f"{item} set at the safe spot",
        "picked": f"{item} picked from tray",
        "handed": f"{item} presented to clinician",
        "waiting_for_pull": f"{item} waiting for pull",
        "released": f"{item} released on pull",
        "returned": f"{item} returned to tray",
        "missed": f"grasp missed for {item}",
        "stopped": "emergency stop triggered",
        "error": "arm error held for reset",
        "count": "instrument count verified",
    }
    action = action_map.get(ev_type, f"{item} {ev_type}")
    return f"{action}, {time_str}"


CAPTION_MODEL = "perceptron-mk1.5"
CAPTION_FRAMES = 5  # frames sent per clip, spread over the whole clip (the API needs at least 2)
CAPTION_TIMEOUT_S = 20.0  # labeling runs after the case, so a slow call is fine
CAPTION_MAX_CHARS = 120

_EVENT_PHRASE = {
    "set_down": "set the item down at the safe spot",
    "picked": "picked the item up from the tray",
    "handed": "held the item out at the hand-off spot for the clinician",
    "waiting_for_pull": "is holding the item, waiting for the clinician to pull it",
    "released": "opened the gripper after the clinician pulled the item",
    "returned": "put the item back in its tray slot",
    "missed": "tried to grasp the item and missed",
    "stopped": "was stopped (emergency stop)",
    "error": "stopped on an arm error",
}


def build_caption_prompt(clip: dict[str, Any]) -> str:
    """The caption request for one clip, with the controller's event as context."""
    event = clip.get("event") or {}
    ev_type = event.get("type") or clip.get("event_type") or "event"
    item = (event.get("item") or clip.get("item") or "instrument").replace("_", " ")
    phrase = _EVENT_PHRASE.get(ev_type, f"logged '{ev_type}'")
    lines = [
        f"These frames are in time order from a {clip.get('duration_s') or 3} s overhead camera clip of a "
        "robot arm that passes surgical instruments to a clinician.",
        f"The controller logged this event: the arm {phrase}. Item: {item}. Event type: {ev_type}.",
    ]
    rth = event.get("request_to_hand_s")
    if isinstance(rth, (int, float)):
        lines.append(f"The clinician asked for it {float(rth):.1f} s before the hand-off.")
    lines.append(
        f"Write one short log line, lowercase, under 15 words, that starts with the item name, for example "
        f"\"{item} handed to the surgeon's right hand\" or \"{item} returned to its tray slot\". "
        "Describe only what the frames show: which hand took it, where it was placed, or if it was dropped. "
        "The controller can be wrong. If the gripper is empty, the arm does not move, or the frames do not "
        f"show the logged event, say what they do show, for example \"arm at rest, no {item} in the gripper\". "
        "No times, no quotes, no extra sentences."
    )
    return "\n".join(lines)


def build_caption_payload(frames: list[tuple[int, bytes]], prompt: str) -> dict[str, Any]:
    """A chat completions body: the frames as one `video_frames` part (timestamp_ms each), then the prompt."""
    parts = [
        {"image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpg).decode("ascii")},
         "timestamp_ms": int(ms)}
        for ms, jpg in frames
    ]
    return {
        "model": CAPTION_MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "video_frames", "video_frames": {"frames": parts}},
            {"type": "text", "text": prompt},
        ]}],
        "reasoning_effort": "low",
        "max_completion_tokens": 1024,  # reasoning counts here: 256 ran out before the answer once
        "temperature": 0.2,
    }


def sample_clip_frames(clip: dict[str, Any], n: int = CAPTION_FRAMES) -> list[tuple[int, bytes]]:
    """n JPEG frames spread over the clip's .mp4, with their offsets in ms. Falls back to the thumbnail
    (sent twice: the API wants at least two frames), then to a black frame."""
    frames: list[np.ndarray] = []
    fps = 10.0
    path = clip.get("path")
    if path and Path(path).is_file():
        cap = cv2.VideoCapture(str(path))
        fps = cap.get(cv2.CAP_PROP_FPS) or fps
        while True:
            ok, f = cap.read()
            if not ok:
                break
            frames.append(f)
        cap.release()
    out: list[tuple[int, bytes]] = []
    if len(frames) >= 2:
        n = max(2, min(n, len(frames)))
        for i in [round(k * (len(frames) - 1) / (n - 1)) for k in range(n)]:
            ok, enc = cv2.imencode(".jpg", frames[i], [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                out.append((int(i * 1000 / fps), enc.tobytes()))
    if len(out) >= 2:
        return out
    thumb = clip.get("thumbnail")
    if thumb and Path(thumb).is_file():
        jpg = Path(thumb).read_bytes()
    else:
        jpg = cv2.imencode(".jpg", np.zeros((480, 640, 3), dtype=np.uint8))[1].tobytes()
    return [(0, jpg), (0, jpg)]


_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
_TAGS = re.compile(r"<[^>]+>")


def caption_from_response(body: dict) -> str | None:
    """The first line of the reply, without think blocks, tags or quotes; None when there is none."""
    choices = body.get("choices") if isinstance(body, dict) else None
    if not choices:
        return None
    content = (choices[0].get("message") or {}).get("content") or ""
    if isinstance(content, list):  # content parts
        content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
    text = _TAGS.sub("", _THINK.sub("", str(content))).strip()
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    line = line.strip(" \"'`*").rstrip(".").strip()
    return line[:CAPTION_MAX_CHARS].rstrip() or None


def with_request_to_hand(caption: str, clip: dict[str, Any]) -> str:
    """Append the controller's request-to-hand time (", 6.4 s") when the event has one."""
    rth = (clip.get("event") or {}).get("request_to_hand_s")
    if isinstance(rth, (int, float)) and not re.search(r"\d s$", caption):
        return f"{caption}, {float(rth):.1f} s"
    return caption


class ClipManager:
    """Manages rolling video frame buffer, recording clips for events, and labeling via Perceptron."""

    def __init__(self, clips_dir: Path | None = None, max_buffer_frames: int = 150):
        self.clips_dir = clips_dir or (ROOT / "vision" / "clips")
        self.clips_dir.mkdir(parents=True, exist_ok=True)
        self.buffer: deque[tuple[float, np.ndarray]] = deque(maxlen=max_buffer_frames)
        self._lock = threading.Lock()
        self._case_clips: dict[str, list[dict[str, Any]]] = {}
        self._load_existing_metadata()

    def _load_existing_metadata(self) -> None:
        if not self.clips_dir.exists():
            return
        for case_folder in self.clips_dir.iterdir():
            if case_folder.is_dir():
                meta_file = case_folder / "metadata.json"
                if meta_file.exists():
                    try:
                        data = json.loads(meta_file.read_text(encoding="utf-8"))
                        if isinstance(data, list):
                            self._case_clips[case_folder.name] = data
                    except Exception:
                        pass

    def add_frame(self, frame: np.ndarray, timestamp: float | None = None) -> None:
        """Add a frame to the rolling buffer."""
        t = timestamp if timestamp is not None else time.time()
        h, w = frame.shape[:2]
        # Smaller copy for wide frames; a plain copy otherwise (callers reuse their frame).
        small = cv2.resize(frame, (BUFFER_WIDTH, int(h * BUFFER_WIDTH / w))) if w > BUFFER_WIDTH else frame.copy()
        with self._lock:
            if self.buffer and self.buffer[-1][0] == t:
                return  # the hand and tray loops both add the grabber's latest frame
            self.buffer.append((t, small))

    def record_event(
        self,
        event: dict,
        pre_s: float = 1.5,
        post_s: float = 1.5,
        fps: float = 10.0,
    ) -> dict[str, Any] | None:
        """Extract a clip around an event from the rolling buffer and save as .mp4."""
        event_t = float(event.get("t") or time.time())
        case_id = safe_name(event.get("case_id") or f"case-{int(event_t)}")
        ev_type = safe_name(event.get("type") or "event")
        item = safe_name(event.get("item") or "arm")

        with self._lock:
            buffer_copy = list(self.buffer)

        # Filter frames within [event_t - pre_s, event_t + post_s]
        frames_in_window = [
            frame for (t, frame) in buffer_copy
            if (event_t - pre_s) <= t <= (event_t + post_s)
        ]

        # If buffer had fewer frames or timing differs (e.g. test mode), take available frames
        if not frames_in_window:
            if buffer_copy:
                frames_in_window = [f for (_, f) in buffer_copy[-int((pre_s + post_s) * fps):]]
            else:
                # Create a placeholder frame
                frames_in_window = [np.zeros((480, 640, 3), dtype=np.uint8) for _ in range(int(fps))]

        case_dir = self.clips_dir / case_id
        case_dir.mkdir(parents=True, exist_ok=True)

        clip_id = f"{case_id}_{ev_type}_{item}_{int(event_t)}"
        filename = f"{ev_type}_{item}_{int(event_t)}.mp4"
        clip_path = case_dir / filename
        thumb_path = case_dir / f"{ev_type}_{item}_{int(event_t)}.jpg"

        # Write video using OpenCV VideoWriter
        h, w = frames_in_window[0].shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(clip_path), fourcc, fps, (w, h))
        for f in frames_in_window:
            # Resize if needed
            if f.shape[:2] != (h, w):
                f = cv2.resize(f, (w, h))
            writer.write(f)
        writer.release()

        # Save thumbnail (middle frame)
        mid_idx = len(frames_in_window) // 2
        cv2.imwrite(str(thumb_path), frames_in_window[mid_idx])

        duration_s = len(frames_in_window) / fps
        clip_info: dict[str, Any] = {
            "clip_id": clip_id,
            "case_id": case_id,
            "event": event,
            "event_type": ev_type,
            "item": event.get("item"),
            "timestamp": event_t,
            "filename": filename,
            "path": str(clip_path),
            "thumbnail": str(thumb_path),
            "duration_s": round(duration_s, 2),
            "frame_count": len(frames_in_window),
            "label": None,
            "labeled_at": None,
        }

        with self._lock:
            clips = self._case_clips.setdefault(case_id, [])
            clips.append(clip_info)
            self._save_case_metadata(case_id)

        logger.info("recorded clip %s for %s (%d frames)", filename, case_id, len(frames_in_window))
        return clip_info

    def _save_case_metadata(self, case_id: str) -> None:
        case_dir = self.clips_dir / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        meta_file = case_dir / "metadata.json"
        clips = self._case_clips.get(case_id, [])
        meta_file.write_text(json.dumps(clips, indent=2), encoding="utf-8")

    def label_clip(
        self,
        clip: dict[str, Any],
        prompt: str | None = None,
        api_key: str | None = None,
        timeout: float = CAPTION_TIMEOUT_S,
    ) -> str:
        """Caption a clip with Perceptron from several frames of the clip, or use the fallback label.

        Sets label, label_source ("perceptron" or "fallback"), caption_latency_ms (the API round trip,
        None when no call was made), caption_frames, caption_error and labeled_at on the clip, saves the
        case metadata, and returns the label."""
        key = os.environ.get("PERCEPTRON_API_KEY", "").strip() if api_key is None else api_key.strip()
        label: str | None = None
        latency_ms: int | None = None
        error: str | None = None
        frames: list[tuple[int, bytes]] = []

        if key:
            started = time.perf_counter()
            try:
                frames = sample_clip_frames(clip)
                payload = build_caption_payload(frames, prompt or build_caption_prompt(clip))
                resp = httpx.post(
                    CHAT_COMPLETIONS_URL,
                    json=payload,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    timeout=timeout,
                )
                latency_ms = round((time.perf_counter() - started) * 1000)
                body = resp.json() if resp.status_code == 200 else {}
                caption = caption_from_response(body)
                if caption:
                    label = with_request_to_hand(caption, clip)
                elif resp.status_code == 200:
                    finish = ((body.get("choices") or [{}])[0] or {}).get("finish_reason")
                    error = f"empty caption (finish_reason {finish})"
                else:
                    error = f"HTTP {resp.status_code}"
            except Exception as exc:
                latency_ms = round((time.perf_counter() - started) * 1000)
                error = type(exc).__name__
                logger.warning("Perceptron caption call failed: %s; using the fallback label", exc)
        else:
            error = "PERCEPTRON_API_KEY unset"

        source = "perceptron" if label else "fallback"
        if not label:
            event = clip.get("event") or {"type": clip.get("event_type"), "item": clip.get("item")}
            label = format_event_label(event, clip.get("timestamp"))

        clip["label"] = label
        clip["label_source"] = source
        clip["caption_latency_ms"] = latency_ms
        clip["caption_frames"] = len(frames) if source == "perceptron" else 0
        clip["caption_error"] = error if source == "fallback" else None
        clip["labeled_at"] = time.time()

        case_id = clip.get("case_id")
        if case_id:
            with self._lock:
                self._save_case_metadata(case_id)

        return label

    def label_case(self, case_id: str, api_key: str | None = None) -> list[dict[str, Any]]:
        """Label all recorded clips for a specific case."""
        with self._lock:
            clips = list(self._case_clips.get(case_id, []))

        labeled_list = []
        for clip in clips:
            self.label_clip(clip, api_key=api_key)
            labeled_list.append(clip)

        return labeled_list

    def get_clips(self, case_id: str) -> list[dict[str, Any]]:
        """Return all clips for a case."""
        with self._lock:
            return list(self._case_clips.get(case_id, []))

    def all_clips(self) -> dict[str, list[dict[str, Any]]]:
        with self._lock:
            return {case_id: list(clips) for case_id, clips in self._case_clips.items()}

    def file_path(self, case_id: str, filename: str) -> Path | None:
        """The clip or thumbnail file, or None for a name that would leave clips/."""
        if safe_name(case_id) != case_id or safe_name(filename) != filename:
            return None
        if not filename.endswith((".mp4", ".jpg")):
            return None
        return self.clips_dir / case_id / filename
