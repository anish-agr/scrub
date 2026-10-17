"""Preview page and MJPEG stream on port 8001."""

from __future__ import annotations

import time

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response, StreamingResponse

from vision.service import Runtime, controls_locked, remember_clinician

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

    return app


def mjpeg(runtime: Runtime, frames: int | None = None):
    sent = 0
    while frames is None or sent < frames:
        payload = runtime.preview_jpeg()
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + payload + b"\r\n"
        sent += 1
        if frames is None or sent < frames:
            time.sleep(0.05)
