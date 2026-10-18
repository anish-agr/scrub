"""FastAPI app for the sim: camera streams, state, reachability, layout. Port 8002."""
import json
import queue
import threading
import time
from pathlib import Path

import mujoco
from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
import io

from sim import ik, scene

HERE = Path(__file__).parent
SIZE = (480, 640)  # h, w: same as the real cameras


class Grabber:
    """Renders camera frames. OpenGL on macOS only works on the thread that made the
    context, so frames are rendered on the thread that calls `serve()` (the main thread)."""

    def __init__(self, arm):
        self.arm, self.owner = arm, threading.current_thread()
        self._q, self._r, self._model = queue.Queue(), None, None
        self._running = False

    def _render(self, cam):
        a = self.arm
        if self._r is None or self._model is not a.model:
            self._r, self._model = mujoco.Renderer(a.model, *SIZE), a.model
        with a.lock:
            self._r.update_scene(a.data, camera=cam)
        buf = io.BytesIO()
        Image.fromarray(self._r.render()).save(buf, "JPEG", quality=80)
        return buf.getvalue()

    def frame(self, cam, timeout=8.0):
        """JPEG bytes, or None if nobody is serving renders."""
        if threading.current_thread() is self.owner:
            return self._render(cam)
        if not self._running:
            return None
        box = {"ev": threading.Event()}
        self._q.put((cam, box))
        return box["jpg"] if box["ev"].wait(timeout) and "jpg" in box else None

    def serve(self, stop=lambda: False):
        """Run on the owner thread; answers frame requests until stop() is true."""
        self._running = True
        while not stop():
            try:
                cam, box = self._q.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                box["jpg"] = self._render(cam)
            except Exception as e:  # keep serving
                print("render failed:", e)
            box["ev"].set()
        self._running = False


def create_app(arm, grabber=None):
    app = FastAPI(title="Scrub sim")
    app.add_middleware(CORSMiddleware, allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
                       allow_methods=["*"], allow_headers=["*"])
    app.state.grabber = grabber or Grabber(arm)

    @app.get("/stream")
    def stream(cam: str = "overhead"):
        name = "wrist" if cam == "wrist" else "overhead"
        first = app.state.grabber.frame(name)
        if first is None:
            raise HTTPException(503, "no renderer running (use python -m sim without --view)")

        def gen():
            jpg = first
            while jpg:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n"
                time.sleep(1 / 15)
                jpg = app.state.grabber.frame(name)
        return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")

    @app.get("/state")
    def state():
        return arm.state()

    @app.get("/pose")
    def pose():
        """Joint angles and item/hand poses, for recording a run to re-render (video/simcine.py)."""
        return arm.pose()

    def _reach(p):
        ok, err, q = ik.reachable(p)
        return {"reachable": ok, "error_m": err, "q": [float(v) for v in q]}

    @app.get("/reach")
    def reach(x: float = Query(...), y: float = Query(...), z: float = Query(...)):
        return _reach([x, y, z])

    @app.post("/reach/batch")
    def reach_batch(body: dict = Body(...)):
        return {"results": [_reach(p) for p in body.get("points", [])]}

    @app.post("/scene/reset")
    def scene_reset():
        """Put every item back in its slot and the arm at home (a person resetting the tray)."""
        arm.reload()
        return {"ok": True}

    @app.post("/scene/setting")
    def scene_setting(body: dict = Body(...)):
        """{"setting": "bench"}: switch which setting's items are on the table (in memory only)."""
        if not arm.set_setting(body.get("setting")):
            raise HTTPException(404, f"no setting {body.get('setting')!r}")
        return {"ok": True, "setting": arm.layout["setting"]}

    @app.post("/scene/items")
    def scene_items(body: dict = Body(...)):
        """Move items to table positions (arm frame m, yaw rad); picks then target those spots.
        /scene/reset clears it. Body: {"items": [{"id", "x", "y", "yaw"}]}."""
        results = []
        for it in body.get("items", []):
            try:
                x, y, yaw = float(it["x"]), float(it["y"]), float(it.get("yaw") or 0.0)
                ok, why = arm.set_item_pose(str(it["id"]), x, y, yaw)
            except (KeyError, TypeError, ValueError, AttributeError):
                ok, why = False, "need id, x, y (numbers)"
            results.append({"id": it.get("id") if isinstance(it, dict) else None, "ok": ok, "why": why})
        return {"results": results}

    @app.get("/layout")
    def get_layout():
        return scene.load_layout()

    @app.put("/layout")
    def put_layout(layout: dict = Body(...)):
        need = {"setting", "table", "tray", "slots", "setting_items", "return_spot", "safe_spot",
                "hand_zone", "handoff_region", "poses", "overhead_cam"}
        if need - layout.keys():
            raise HTTPException(422, f"missing keys: {sorted(need - layout.keys())}")
        scene.LAYOUT.write_text(json.dumps(layout, indent=2) + "\n")
        arm.reload()
        return layout

    app.mount("/models", StaticFiles(directory=HERE / "models", check_dir=False), name="models")
    app.mount("/web", StaticFiles(directory=HERE / "web", html=True, check_dir=False), name="web")
    return app
