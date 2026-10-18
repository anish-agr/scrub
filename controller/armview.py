"""Read-only views of the arm and the cameras, for the nurse console and explore pages.

GET /arm/pose            joints, gripper, tip from forward kinematics, tip projected into the overhead image
GET /arm/camera/{name}   one JPEG from the arm's side or wrist camera (needs Arm.camera_jpeg(name))
GET /arm/stream/{name}   the same as MJPEG, about 10 frames a second
GET /camera/overhead     vision's /snapshot through the controller (same origin, CORS)
GET /calibration         vision/calibration.json

Nothing here moves the arm or writes anything.
"""
import asyncio
import json
import os
import time
from pathlib import Path

import httpx
from fastapi import HTTPException
from fastapi.responses import Response, StreamingResponse

ROOT = Path(__file__).resolve().parent.parent
CALIBRATION = ROOT / "vision" / "calibration.json"
CAMERAS = ("side", "wrist")


def _vision_url() -> str:
    return os.environ.get("VISION_URL", "http://localhost:8001").rstrip("/")


def _calibration() -> dict | None:
    try:
        return json.loads(CALIBRATION.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _to_pixel(homography, x: float, y: float) -> list[float] | None:
    """Arm table-plane meters to overhead pixels (inverse of vision's pixel-to-arm homography)."""
    try:
        import numpy as np
        inv = np.linalg.inv(np.asarray(homography, dtype=float))
        p = inv @ np.array([x, y, 1.0])
        return [round(float(p[0] / p[2]), 1), round(float(p[1] / p[2]), 1)]
    except Exception:  # noqa: BLE001 - a bad file means no pixel, not a crash
        return None


def pose(arm) -> dict:
    out = {"available": False, "joints_deg": None, "gripper": None, "tip_m": None, "tip_px": None,
           "calibrated": False, "reason": None, "t": time.time()}
    joints = getattr(arm, "joints", None)
    if joints is None:
        out["reason"] = "this arm has no joint readout (fake arm)"
        return out
    try:
        q = [float(v) for v in joints()]
    except Exception as e:  # noqa: BLE001 - not connected, stale state
        out["reason"] = str(e) or type(e).__name__
        return out
    out["available"] = True
    out["joints_deg"] = [round(v, 2) for v in q[:5]]
    try:
        out["gripper"] = round(float(arm.gripper_position()), 3)
    except Exception:  # noqa: BLE001
        pass
    kin = getattr(arm, "kin", None)
    if kin is not None:
        try:
            out["tip_m"] = [round(float(v), 4) for v in kin.forward(q[:5])]
        except Exception as e:  # noqa: BLE001 - joints outside URDF limits
            out["reason"] = f"forward kinematics: {e}"
    cal = _calibration()
    if cal and cal.get("homography"):
        out["calibrated"] = True
        if out["tip_m"]:
            out["tip_px"] = _to_pixel(cal["homography"], out["tip_m"][0], out["tip_m"][1])
    return out


def routes(app, ctl) -> None:
    def frame(name: str) -> bytes:
        if name not in CAMERAS:
            raise HTTPException(404, f"no camera {name!r}; the arm has {', '.join(CAMERAS)}")
        grab = getattr(ctl.arm, "camera_jpeg", None)
        if grab is None:
            raise HTTPException(404, "this arm does not share camera frames yet (needs Arm.camera_jpeg(name))")
        try:
            data = grab(name)
        except Exception as e:  # noqa: BLE001 - camera unplugged or stale
            raise HTTPException(503, f"{name} camera: {e}")
        if not data:
            raise HTTPException(503, f"{name} camera: no frame yet")
        return data

    @app.get("/arm/pose")
    async def arm_pose():
        return await asyncio.to_thread(pose, ctl.arm)

    @app.get("/arm/camera/{name}")
    async def arm_camera(name: str):
        data = await asyncio.to_thread(frame, name)
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.get("/arm/stream/{name}")
    async def arm_stream(name: str):
        await asyncio.to_thread(frame, name)  # fail fast with the reason

        async def gen():
            while True:
                try:
                    data = await asyncio.to_thread(frame, name)
                except HTTPException:
                    await asyncio.sleep(0.5)
                    continue
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + data + b"\r\n"
                await asyncio.sleep(0.1)
        return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")

    @app.get("/camera/overhead")
    async def overhead():
        try:
            async with httpx.AsyncClient(timeout=1.5) as client:
                r = await client.get(_vision_url() + "/snapshot")
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise HTTPException(502, f"vision at {_vision_url()} not answering: {type(e).__name__}")
        return Response(r.content, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.get("/calibration")
    async def calibration():
        cal = _calibration()
        if cal is None:
            raise HTTPException(404, "no vision/calibration.json yet (B6)")
        return cal
