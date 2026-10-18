"""Live recording dashboard for arm_session.py: http://localhost:8090

Runs in the same process as LeRobot. Hooks (installed by install()) read what the robot already
captures, so the cameras are never opened twice:
  SOFollower.get_observation   camera frames, joints, loop rate
  OpenCVCamera._read_from_hardware   real camera fps
  lerobot_record.log_say / LeRobotDataset.save_episode   phase (recording, reset, saving)
  lerobot_record.init_keyboard_listener   the events dict, so the page's buttons work like the arrow keys
"""
import json
import logging
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import cv2
import numpy as np

PORT = 8090
HTML = Path(__file__).with_name("arm_ui.html")

S = {"mode": "teleop", "phase": "starting", "task": None, "episode": None, "session_done": 0,
     "session_total": None, "phase_started": time.time(), "phase_s": None, "loop_hz": None,
     "joints": {}, "gripper": None, "guard": {"holding": False, "at": None},
     "dataset": None, "log": deque(maxlen=30)}
frames: dict = {}                 # camera name -> latest RGB frame
cam_ticks: dict = {}              # camera name -> deque of hardware read times
loop_ticks: deque = deque(maxlen=60)
events: dict = {}
cfg = {"root": None, "episode_s": None, "reset_s": None, "cams": {}}
lock = threading.Lock()


def note(line: str) -> None:
    S["log"].append(time.strftime("%H:%M:%S ") + line)


def phase(name: str, seconds=None) -> None:
    S["phase"], S["phase_started"], S["phase_s"] = name, time.time(), seconds


class _LogHandler(logging.Handler):
    def emit(self, record):
        msg = record.getMessage()
        if len(msg) < 300 and "\n" not in msg:
            note(msg)


_handler = _LogHandler(level=logging.INFO)


def _attach_log() -> None:
    root = logging.getLogger()  # LeRobot's init_logging replaces the root handlers: re-attach
    if _handler not in root.handlers:
        root.addHandler(_handler)


def install(mode: str, task, episodes, episode_s, reset_s, root, cams: dict) -> None:
    from lerobot.cameras.opencv.camera_opencv import OpenCVCamera
    from lerobot.robots.so_follower.so_follower import SOFollower

    S["mode"], S["task"] = mode, task
    S["session_total"] = episodes if mode == "record" else None
    cfg.update(root=root, episode_s=episode_s, reset_s=reset_s, cams={v: k for k, v in cams.items()})
    if mode == "teleop":
        phase("teleop")

    get_obs = SOFollower.get_observation

    def observed(self):
        obs = get_obs(self)
        loop_ticks.append(time.perf_counter())
        with lock:
            for k, v in obs.items():
                if isinstance(v, np.ndarray) and v.ndim == 3:
                    frames[k] = v
            S["joints"] = {k[:-4]: round(float(v), 1) for k, v in obs.items()
                           if k.endswith(".pos") and k != "gripper.pos"}
            if "gripper.pos" in obs:
                S["gripper"] = round(float(obs["gripper.pos"]), 1)
        return obs
    SOFollower.get_observation = observed

    read_hw = OpenCVCamera._read_from_hardware

    def counted(self):
        frame = read_hw(self)
        name = cfg["cams"].get(self.config.index_or_path, str(self.config.index_or_path))
        cam_ticks.setdefault(name, deque(maxlen=60)).append(time.perf_counter())
        return frame
    OpenCVCamera._read_from_hardware = counted

    if mode == "record":
        import lerobot.scripts.lerobot_record as rec
        from lerobot.datasets.lerobot_dataset import LeRobotDataset

        say = rec.log_say

        def said(text, *a, **kw):
            if text.startswith("Recording episode"):
                S["episode"] = int(text.split()[-1])
                phase("recording", cfg["episode_s"])
            elif text.startswith("Reset"):
                phase("resetting", cfg["reset_s"])
            elif text.startswith("Stop recording"):
                phase("saving")
            return say(text, *a, **kw)
        rec.log_say = said

        save = LeRobotDataset.save_episode

        def saved(self, *a, **kw):
            phase("saving")
            out = save(self, *a, **kw)
            S["session_done"] += 1
            return out
        LeRobotDataset.save_episode = saved

        listen = rec.init_keyboard_listener

        def listener():
            lst, ev = listen()
            events.clear()
            events.update(ev)
            return lst, events  # same dict LeRobot reads, now also driven by the page
        rec.init_keyboard_listener = listener

    _attach_log()
    threading.Thread(target=ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever,
                     daemon=True).start()
    print(f"recorder page: http://localhost:{PORT}", flush=True)


def _rate(ticks: deque) -> float | None:
    t = list(ticks)
    t = [x for x in t if x > time.perf_counter() - 2]
    return round((len(t) - 1) / (t[-1] - t[0]), 1) if len(t) > 2 else None


def _dataset() -> dict | None:
    root = cfg["root"]
    if not root:
        return None
    try:
        info = json.loads((Path(root) / "meta" / "info.json").read_text())
        return {"root": str(root), "episodes": info.get("total_episodes"), "frames": info.get("total_frames")}
    except Exception:  # noqa: BLE001 - no dataset yet
        return {"root": str(root), "episodes": 0, "frames": 0}


def status() -> dict:
    _attach_log()
    with lock:
        cams = {k: {"brightness": round(float(v[::8, ::8].mean())), "fps": _rate(cam_ticks.get(k, deque()))}
                for k, v in frames.items()}
        out = {k: (list(v) if isinstance(v, deque) else v) for k, v in S.items()}
    out.update(cameras=cams, loop_hz=_rate(loop_ticks), dataset=_dataset(), now=time.time())
    warn = []
    for k, c in cams.items():
        if c["brightness"] < 25:
            warn.append(f"{k.capitalize()} camera is dark (brightness {c['brightness']})")
        if c["fps"] is not None and c["fps"] < 25:
            warn.append(f"{k.capitalize()} camera {c['fps']:.0f} fps (needs 30)")
    if out["loop_hz"] is not None and out["loop_hz"] < 27 and out["phase"] in ("recording", "resetting", "teleop"):
        warn.append(f"Control loop {out['loop_hz']:.0f} Hz (needs 30)")
    out["warnings"] = warn
    return out


def control(action: str) -> bool:
    if not events or S["phase"] not in ("recording", "resetting"):
        return False
    if action == "rerecord":
        events["rerecord_episode"] = True
    elif action == "stop":
        events["stop_recording"] = True
    elif action != "next":
        return False
    events["exit_early"] = True
    note(f"page: {action}")
    return True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.path = urlsplit(self.path).path  # the page adds ?t= to retry streams
        if self.path in ("/", "/index.html"):
            self._send(200, HTML.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/status":
            self._send(200, json.dumps(status()).encode(), "application/json")
        elif self.path.startswith("/stream/"):
            self._stream(self.path.split("/")[-1])
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if self.path != "/control":
            return self._send(404, b"not found", "text/plain")
        n = int(self.headers.get("Content-Length") or 0)
        try:
            action = json.loads(self.rfile.read(n) or b"{}").get("action", "")
        except ValueError:
            action = ""
        self._send(200, json.dumps({"ok": control(action)}).encode(), "application/json")

    def _stream(self, name: str):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            while True:
                with lock:
                    f = frames.get(name)
                if f is not None:
                    ok, jpg = cv2.imencode(".jpg", cv2.cvtColor(f, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 70])
                    if ok:
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg.tobytes() + b"\r\n")
                time.sleep(1 / 15)  # 15 fps preview keeps the CPU for recording
        except (BrokenPipeError, ConnectionResetError):
            pass
