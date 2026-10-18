"""Preview page and MJPEG stream on port 8001."""

from __future__ import annotations

import json
import os
import time
from email.parser import BytesParser
from email.policy import HTTP

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from vision import reading
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

    # Reading (OCR). Each call takes a JPEG body, a multipart file, or {"source": "overhead"}. The OCR call runs
    # in the thread pool, so the event loop and the camera, hand and tray threads keep going.
    app.state.reads = {}
    readers = {
        "count_sheet": lambda img, setting, today: reading.read_count_sheet(img, setting, backends=app.state.read_backends, repo=runtime.repo),
        "tray_tag": lambda img, setting, today: reading.read_tray_tag(img, backends=app.state.read_backends, repo=runtime.repo),
        "pack_label": lambda img, setting, today: reading.read_pack_label(img, setting, today, backends=app.state.read_backends),
    }
    app.state.read_backends = None  # None: Perceptron then Gemini, from the keys in the environment

    @app.post("/read/{kind}")
    async def read(kind: str, request: Request):
        if kind not in readers:
            return JSONResponse({"ok": False, "error": f"unknown reader {kind}"}, status_code=404)
        try:
            image, fields = await read_input(request)
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        if image is None:
            if fields.get("source") != "overhead":
                return JSONResponse({"ok": False, "error": "send a JPEG, a multipart file, or {\"source\": \"overhead\"}"}, status_code=400)
            latest = runtime.grabber.latest()
            if latest is None:
                return JSONResponse({"ok": False, "error": "no overhead frame yet"}, status_code=503)
            image = latest[0]
        sid = fields.get("setting") or request.query_params.get("setting")
        if sid and sid not in reading.known_settings(runtime.repo):
            return JSONResponse({"ok": False, "error": f"unknown setting {sid}"}, status_code=404)
        today = fields.get("today") or request.query_params.get("today")

        def work():
            setting = reading.load_setting_merged(runtime.repo, sid) if sid else setting_document(runtime)
            return readers[kind](image, setting, today)

        try:
            result = await run_in_threadpool(work)
        except ValueError as exc:  # unreadable image, bad date
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        result["kind"], result["t"] = kind, time.time()
        app.state.reads[kind] = result
        return result

    @app.get("/read/last")
    def read_last():
        """The last result of each reader since vision started."""
        return app.state.reads

    return app


async def read_input(request: Request):
    """(image bytes or None, fields). JSON body: fields only. multipart: the first file part plus text fields.
    Anything else: the raw body is the image."""
    raw_ctype = request.headers.get("content-type") or ""
    ctype = raw_ctype.lower()
    body = await request.body()
    if ctype.startswith("application/json"):
        try:
            data = json.loads(body or b"{}")
        except ValueError:
            raise ValueError("body is not JSON") from None
        return None, data if isinstance(data, dict) else {}
    if ctype.startswith("multipart/form-data"):
        msg = BytesParser(policy=HTTP).parsebytes(b"Content-Type: " + raw_ctype.encode() + b"\r\n\r\n" + body)
        image, fields = None, {}
        for part in msg.iter_parts():
            payload = part.get_payload(decode=True) or b""
            if part.get_filename() is not None or part.get_content_type().startswith("image/"):
                image = image or payload
            elif part.get_param("name", header="content-disposition"):
                fields[part.get_param("name", header="content-disposition")] = payload.decode("utf-8", "replace").strip()
        if not image:
            raise ValueError("multipart body has no file")
        return image, fields
    if not body:
        return None, {}
    return body, {}


def mjpeg(runtime: Runtime, frames: int | None = None):
    sent = 0
    while frames is None or sent < frames:
        payload = runtime.preview_jpeg()
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + payload + b"\r\n"
        sent += 1
        if frames is None or sent < frames:
            time.sleep(0.05)
