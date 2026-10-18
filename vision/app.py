"""Preview page and MJPEG stream on port 8001."""

from __future__ import annotations

import time

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response, StreamingResponse

from vision.service import Runtime, controls_locked, remember_clinician
from vision.tray import categories_for, load_setting
from vision.tray_check import check_tray

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

    @app.get("/", response_class=HTMLResponse)
    def preview():
        return PREVIEW

    @app.get("/health")
    def health():
        latest = runtime.grabber.latest()
        return {
            "ok": True,
            "camera": latest is not None,
            "exposure_locked": controls_locked(runtime),
            "controls": runtime.controls,
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
        """Compare the tray to the setting's item list (X3)."""
        setting_id = setting or runtime.poster.current_setting(runtime.setting_id)
        setting_doc = load_setting(runtime.repo, setting_id)
        latest = runtime.grabber.latest()
        if latest is not None:
            frame, _ = latest
            categories = categories_for(setting_doc, runtime.include_extra_categories)
            try:
                detections = list(runtime.detector.detect(frame, categories))
            except Exception:
                detections = list(runtime.detections)
        else:
            detections = list(runtime.detections)
        return check_tray(setting_doc, detections)

    @app.get("/clips")
    def list_clips(case_id: str | None = None):
        """List event clips for a case_id (or all cases) (X4)."""
        if not case_id:
            return runtime.clips._case_clips
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
        path = runtime.clips.clips_dir / case_id / filename
        if not path.exists():
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
