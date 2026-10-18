"""Preview page and MJPEG stream on port 8001."""

from __future__ import annotations

import os
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response, StreamingResponse

from vision.service import Runtime, controls_locked, remember_clinician, setting_document
from vision.tray import load_setting
from vision.tray_check import check_tray

TRAY_STALE_S = 3.0  # same as controller/core.py; the floor for /tray_check


def tray_stale_s(detector) -> float:
    """A live detect can take up to its timeout, so a read is stale only after that plus 2 s (8 s at the 6 s
    default). Detectors without a timeout (fake, tests) keep 3 s. VISION_TRAY_STALE_S overrides."""
    override = os.environ.get("VISION_TRAY_STALE_S")
    if override:
        return float(override)
    return max(TRAY_STALE_S, float(getattr(detector, "timeout", 0.0)) + 2.0)

PREVIEW = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Scrub vision</title>
  <style>
    body { margin: 0; background: #111; color: #eee; font-family: sans-serif; }
    p { margin: 0; padding: 8px 12px; }
    img { width: 100%; max-height: calc(100vh - 36px); object-fit: contain; background: #000; }
  </style>
</head>
<body>
  <p>Overhead camera. Exposure and white balance are locked, so a lamp does not make the picture hunt.</p>
  <img src="/stream" alt="tray preview">
</body>
</html>
"""


def create_app(runtime: Runtime) -> FastAPI:
    app = FastAPI(title="Scrub vision")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"])  # the ops page reads /health

    @app.get("/", response_class=HTMLResponse)
    def preview():
        return PREVIEW

    @app.get("/health")
    def health():
        latest = runtime.grabber.latest()
        return {
            "ok": True,
            "camera": latest is not None and bool(getattr(runtime.grabber, "reads_ok", True)),
            "exposure_locked": controls_locked(runtime),
            "controls": runtime.controls,
            "fps": {"overhead": round(getattr(runtime.grabber, "fps", 0.0), 1)},
            "detect_ms": runtime.detect_ms[-1] if runtime.detect_ms else None,
            "detect_p50_ms": sorted(runtime.detect_ms)[len(runtime.detect_ms) // 2] if runtime.detect_ms else None,
        }

    @app.get("/snapshot")
    def snapshot():
        return Response(content=runtime.preview_jpeg(), media_type="image/jpeg")

    @app.get("/stream")
    def stream(frames: int | None = None):
        return StreamingResponse(mjpeg(runtime, frames), media_type="multipart/x-mixed-replace; boundary=frame")

    @app.get("/vision/hand")
    def latest_hand():
        return runtime.hand or {"seen": False}

    @app.get("/vision/tray")
    def latest_tray():
        return runtime.tray or {}

    @app.get("/lighting")
    def latest_lighting():
        return runtime.lighting or {"lighting": "normal", "lux": 450.0, "brightness": 128.0}

    @app.post("/clinician")
    def clinician(body: dict):
        name = str(body["name"])
        height = float(body["hand_height_m"])
        remember_clinician(runtime, name, height)
        return {"ok": True, "clinician": name, "hand_height_m": height}

    @app.post("/gripper")
    def gripper(body: dict):
        px = body.get("px")
        runtime.gripper_px = None if px is None else [float(px[0]), float(px[1])]
        return {"ok": True, "px": runtime.gripper_px}

    @app.get("/tray_check")
    def tray_check(setting: str | None = None):
        """Compare the last tray read to the setting. Does not call Perceptron.

        A slow or failed detect stays on the tray thread and marks the state stale.
        This request returns that state immediately.
        """
        # Same document the tray loop matched against (the controller's, with its aliases), unless one is named.
        setting_doc = load_setting(runtime.repo, setting) if setting else setting_document(runtime)
        with runtime.lock:
            detections = list(runtime.detections)
            tray = runtime.tray
        result = check_tray(setting_doc, detections)
        # No read yet, a failed read, or a read older than tray_stale_s: say stale, so the
        # controller answers "I can't check the tray" instead of "missing everything".
        age = time.time() - float(tray.get("t") or 0) if isinstance(tray, dict) else None
        fresh = age is not None and not tray.get("stale") and age <= tray_stale_s(runtime.detector)
        result["stale"] = not fresh
        return result

    @app.get("/clips")
    def list_clips(case_id: str | None = None):
        """List event clips for a case_id (or all cases) (X4)."""
        if not case_id:
            return runtime.clips.all_clips()
        return runtime.clips.get_clips(case_id)

    @app.post("/clips/record")
    def record_clip(event: dict):
        """Explicitly record a short clip around an event (X4)."""
        clip = runtime.clips.record_event(event)
        return {"ok": True, "clip": clip}

    @app.post("/clips/label")
    def label_clips(body: dict):
        """Label recorded clips for a case using Perceptron (X4)."""
        case_id = body.get("case_id")
        api_key = body.get("api_key")
        if not case_id:
            return {"ok": False, "error": "missing case_id"}
        labeled = runtime.clips.label_case(case_id, api_key=api_key)
        return {"ok": True, "case_id": case_id, "clips": labeled}

    @app.get("/clips/{case_id}/{filename}")
    def get_clip_file(case_id: str, filename: str):
        """Serve a recorded video clip or thumbnail image (X4)."""
        path = runtime.clips.file_path(case_id, filename)
        if path is None or not path.is_file():
            return Response(status_code=404, content="Clip not found")
        media_type = "video/mp4" if filename.endswith(".mp4") else "image/jpeg"
        return Response(content=path.read_bytes(), media_type=media_type)

    return app


def mjpeg(runtime: Runtime, frames: int | None = None):
    sent = 0
    while frames is None or sent < frames:
        payload = runtime.preview_jpeg()
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + payload + b"\r\n"
        sent += 1
        if frames is None or sent < frames:
            time.sleep(0.05)
