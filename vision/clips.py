"""Event clip recording and Perceptron video/caption labeling (X4).

Vision maintains a rolling frame buffer and saves short video clips (.mp4)
around each Event per case_id. After the case, Perceptron's vision-language
model (or fallback clinical labeler) labels each clip (e.g. "scalpel set at the safe spot, 14:02")
for display in the case replay.
"""

from __future__ import annotations

import base64
import json
import logging
import os
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
        with self._lock:
            # Store a copy or reference
            self.buffer.append((t, frame.copy()))

    def record_event(
        self,
        event: dict,
        pre_s: float = 1.5,
        post_s: float = 1.5,
        fps: float = 10.0,
    ) -> dict[str, Any] | None:
        """Extract a clip around an event from the rolling buffer and save as .mp4."""
        event_t = float(event.get("t") or time.time())
        case_id = str(event.get("case_id") or f"case-{int(event_t)}")
        ev_type = str(event.get("type") or "event")
        item = event.get("item") or "arm"

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
        timeout: float = 6.0,
    ) -> str:
        """Label a clip using Perceptron chat completions (or clinical fallback if key unset)."""
        key = os.environ.get("PERCEPTRON_API_KEY", "").strip() if api_key is None else api_key.strip()
        label: str | None = None

        if key:
            # Call Perceptron Chat Completions API with key frame
            try:
                thumb_path = clip.get("thumbnail")
                if thumb_path and Path(thumb_path).exists():
                    frame_bytes = Path(thumb_path).read_bytes()
                else:
                    # Create blank frame
                    ok, encoded = cv2.imencode(".jpg", np.zeros((480, 640, 3), dtype=np.uint8))
                    frame_bytes = encoded.tobytes()

                data_url = "data:image/jpeg;base64," + base64.b64encode(frame_bytes).decode("ascii")
                task_prompt = prompt or (
                    "Provide a concise, human-friendly label for the medical robot action in this clip. "
                    "Example: 'scalpel set at the safe spot, 14:02'."
                )
                payload = {
                    "model": "perceptron-mk1.5",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "image_url", "image_url": {"url": data_url}},
                                {"type": "text", "text": task_prompt},
                            ],
                        }
                    ],
                    "vision_config": {
                        "enable_thinking": True,
                        "annotation_format": "clip",
                    },
                }
                resp = httpx.post(
                    CHAT_COMPLETIONS_URL,
                    json=payload,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    timeout=timeout,
                )
                if resp.status_code == 200:
                    body = resp.json()
                    choices = body.get("choices") or []
                    if choices:
                        msg = choices[0].get("message") or {}
                        content = msg.get("content") or ""
                        if content.strip():
                            label = content.strip()
            except Exception as exc:
                logger.warning("Perceptron caption call failed: %s; using clinical fallback", exc)

        # Fallback to structured clinical action format if API not available or empty
        if not label:
            event = clip.get("event") or {"type": clip.get("event_type"), "item": clip.get("item")}
            label = format_event_label(event, clip.get("timestamp"))

        clip["label"] = label
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
