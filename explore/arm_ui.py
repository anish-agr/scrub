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
HOST = "0.0.0.0"   # teammates can watch from their laptops; only this Mac can press the buttons
TOKEN = __import__("os").environ.get("SCRUB_UI_TOKEN")  # optional: lets another machine use /control
HTML = Path(__file__).with_name("arm_ui.html")

S = {"mode": "teleop", "phase": "starting", "task": None, "episode": None, "session_done": 0,
     "session_total": None, "phase_started": time.time(), "phase_s": None, "loop_hz": None,
     "joints": {}, "gripper": None, "guard": {"holding": False, "at": None},
     "dataset": None, "log": deque(maxlen=30), "waiting": []}
frames: dict = {}                 # camera name -> latest RGB frame
cam_ticks: dict = {}              # camera name -> deque of hardware read times
loop_ticks: deque = deque(maxlen=60)
cam_counts: dict = {}             # camera name -> hardware frames read since start
events: dict = {}
stalls: dict = {}                 # camera name -> stalls this episode
down: set = set()                 # cameras not sending frames right now
ep = {"t0": None, "obs": 0, "cam0": {}, "pending": None,  # wall-clock evidence for the episode
      "open": False, "start": None, "index": None, "why": None}  # telemetry: episode in progress, why it ended
cfg = {"root": None, "episode_s": None, "reset_s": None, "cams": {}}
lock = threading.Lock()


def _tevent(kind: str, **fields) -> None:
    """Telemetry event row (explore/thermal_log.py). Never raises."""
    try:
        import thermal_log
        thermal_log.event(kind, **fields)
    except Exception:  # noqa: BLE001
        pass


def _episode_begin(index) -> None:
    try:
        import thermal_log
        thermal_log.EP.update(active=True, **{k: (dict(v) if isinstance(v, dict) else v)
                                               for k, v in thermal_log.EP_RESET.items()})
        ep.update(open=True, start=time.perf_counter(), index=index, why=None)
        _tevent("episode_start", episode=index, task=S["task"], root=str(cfg["root"]) if cfg["root"] else None)
    except Exception:  # noqa: BLE001
        pass


def _episode_finish(default: str = "done") -> None:
    """episode_end row, once per episode. The reason is the first of: an explicit cause (camera_down,
    cooldown, a guard discard), the page/keyboard flags (rerecord, stop), the time cap, else `default`."""
    try:
        if not ep["open"]:
            return
        import thermal_log
        ep["open"] = False
        dur = time.perf_counter() - ep["start"]
        if ep["why"]:
            reason = ep["why"]
        elif events.get("rerecord_episode"):
            reason = "rerecord"
        elif events.get("stop_recording"):
            reason = "stop"
        elif cfg["episode_s"] and dur >= cfg["episode_s"] - 0.5:
            reason = "timeout"
        else:
            reason = default
        E = thermal_log.EP
        E["active"] = False
        _tevent("episode_end", episode=ep["index"], reason=reason, duration_s=round(dur, 2),
                frames=ep["obs"], grasps=E["grasps"], empty_closes=E["empty_closes"],
                peak_temps=dict(E["peak_temps"]), lift_m=round(E["lift_max"], 3), lifted=E["lifted"],
                pulled=E["pulled"], released=E["released"],
                handoff_success=bool(E["grasps"] and E["lifted"] and E["pulled"]))
    except Exception:  # noqa: BLE001
        pass


def note(line: str) -> None:
    S["log"].append(time.strftime("%H:%M:%S ") + line)
    _speak_for(line)


def _speak_for(line: str) -> None:
    """The arm says the moments that matter, through arm_voice (ElevenLabs, or the Mac voice)."""
    try:
        import arm_voice
    except ImportError:
        return
    low = line.lower()
    nice = lambda s: s.replace("_flex", "").replace("_", " ")  # noqa: E731
    if low.startswith("recording episode"):
        n, total = S["session_done"] + 1, S["session_total"]
        arm_voice.say(f"Recording. Episode {n} of {total}." if total else "Recording.")
    elif low.startswith("reset the environment"):
        arm_voice.say("Saved. Reset the tray.")
    elif low.startswith("re-record episode"):
        arm_voice.say("Let's do that one again.")
    elif low.startswith("stop recording"):
        arm_voice.say("That's a wrap. Saving.")
    elif "camera down" in low:
        arm_voice.say(f"I lost the {line.split()[0]} camera. Reconnecting.", key="cam-down", every=20)
    elif "camera back" in low:
        arm_voice.say(f"{line.split()[0].capitalize()} camera is back.", key="cam-back", every=20)
    elif low.startswith("episode discarded"):
        why = line[line.find("(") + 1:line.rfind(")")] if "(" in line else ""
        arm_voice.say(f"Throwing that episode away. {nice(why).capitalize()}." if why else "Throwing that episode away.",
                      key="discard", every=10)
    elif low.startswith("claw guard: holding"):
        arm_voice.say("Got it. Holding.", key="claw", every=15)
    elif low.startswith("session restarted"):
        arm_voice.say("I'm back.")
    elif low.startswith("reference saved"):
        arm_voice.say("Setup photo saved.")
    elif "too hot" in low:
        joint = nice(line.split()[0])
        arm_voice.say(f"My {joint} is getting hot. Holding still to cool down.", key="hot-" + joint, every=60)
    elif low.startswith("teleop ready"):
        arm_voice.say("Ready. Move the leader arm and I'll follow.")


def camera_stall(index) -> None:
    name = cfg["cams"].get(index, str(index))
    stalls[name] = stalls.get(name, 0) + 1
    note(f"{name} camera stalled")


def map_camera(index, role: str) -> None:
    """A replugged camera came back under a new OpenCV index."""
    cfg["cams"][index] = role


def discard_episode(reason: str) -> None:
    """Throw away the episode being recorded (it is re-recorded after the reset)."""
    if S["phase"] == "recording" and events and not events.get("rerecord_episode"):
        events["rerecord_episode"] = True
        events["exit_early"] = True
        ep["why"] = ep["why"] or reason
        note(f"episode discarded ({reason})")


def camera_down(index, is_down: bool) -> None:
    """While a camera is down, a recording episode is thrown away and re-recorded."""
    name = cfg["cams"].get(index, str(index))
    if is_down and name not in down:
        down.add(name)
        note(f"{name} camera DOWN: reconnecting; episodes are discarded until it is back")
    elif not is_down and name in down:
        down.discard(name)
        note(f"{name} camera back")
    if is_down and S["phase"] == "recording" and events and not events.get("rerecord_episode"):
        events["rerecord_episode"] = True
        events["exit_early"] = True
        ep["why"] = ep["why"] or "camera_down"
        note("episode discarded (camera down)")


def phase(name: str, seconds=None) -> None:
    if name != S["phase"]:
        _tevent("phase", **{"from": S["phase"], "to": name})
    S["phase"], S["phase_started"], S["phase_s"] = name, time.time(), seconds


class _LogHandler(logging.Handler):
    def emit(self, record):
        msg = record.getMessage()
        if len(msg) < 300 and "\n" not in msg:
            note(msg)


def cadence_path():
    return Path(f"{cfg['root']}-cadence.json") if cfg["root"] else None


def _end_episode() -> None:
    """Close the recording window: control-loop rate and each camera's real fps, by the wall clock."""
    if ep["t0"] is None:
        return
    dt = time.perf_counter() - ep["t0"]
    if dt > 0.5:
        ep["pending"] = {
            "measured_fps": round(ep["obs"] / dt, 2), "seconds": round(dt, 2), "frames_observed": ep["obs"],
            "camera_fps": {k: round((cam_counts.get(k, 0) - ep["cam0"].get(k, 0)) / dt, 1) for k in cam_counts},
            "camera_stalls": dict(stalls), "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    ep["t0"] = None


def _write_cadence(index: int) -> None:
    """One entry per saved episode in <root>-cadence.json, the file arm.train's check reads."""
    entry, path = ep.pop("pending", None), cadence_path()
    ep["pending"] = None
    if not entry or not path:
        return
    try:
        data = json.loads(path.read_text()) if path.exists() else {"episodes": []}
    except ValueError:
        data = {"episodes": []}
    data["episodes"] = [e for e in data["episodes"] if e.get("episode_index") != index]
    data["episodes"].append({"episode_index": index, **entry})
    data["episodes"].sort(key=lambda e: e["episode_index"])
    path.write_text(json.dumps(data, indent=1))
    bad = [k for k, v in entry["camera_fps"].items() if v < 29]
    note(f"episode {index}: loop {entry['measured_fps']} Hz" + (f", slow camera: {', '.join(bad)}" if bad else ""))


def reference_path() -> Path:
    return Path(f"{cfg['root']}-reference-side.jpg") if cfg["root"] else Path.home() / "scrub-reference-side.jpg"


def save_reference() -> bool:
    with lock:
        f = frames.get("side")
    if f is None:
        return False
    cv2.imwrite(str(reference_path()), cv2.cvtColor(f, cv2.COLOR_RGB2BGR))
    note(f"reference saved: {reference_path()}")
    return True


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
        note("teleop ready")
    elif mode == "preview":
        phase("preview")
        note("PREVIEW: nothing is recorded yet. Check the cameras and tray, then Start recording")

    get_obs = SOFollower.get_observation

    def observed(self):
        obs = get_obs(self)
        loop_ticks.append(time.perf_counter())
        if ep["t0"] is not None:
            ep["obs"] += 1
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
        cam_counts[name] = cam_counts.get(name, 0) + 1
        return frame
    OpenCVCamera._read_from_hardware = counted

    if mode == "record":
        import lerobot.scripts.lerobot_record as rec
        from lerobot.datasets.lerobot_dataset import LeRobotDataset

        say = rec.log_say

        def said(text, *a, **kw):
            if text.startswith("Recording episode"):
                S["episode"] = int(text.split()[-1])
                stalls.clear()
                ep.update(t0=time.perf_counter(), obs=0, cam0=dict(cam_counts), pending=None)
                phase("recording", cfg["episode_s"])
                _episode_begin(S["episode"])
            elif text.startswith("Reset"):
                _end_episode()
                _episode_finish()
                phase("resetting", cfg["reset_s"])
            elif text.startswith("Re-record"):
                _episode_finish()
                _tevent("episode_discarded", episode=ep["index"], reason=ep["why"] or "rerecord")
                ep.update(t0=None, pending=None)
            elif text.startswith("Stop recording"):
                _end_episode()
                _episode_finish()
                phase("saving")
            return say(text, *a, **kw)
        rec.log_say = said

        save = LeRobotDataset.save_episode

        def saved(self, *a, **kw):
            _end_episode()  # the last episode has no reset phase
            _episode_finish()
            index = self.meta.total_episodes  # the index this save will get
            phase("saving")
            cad = dict(ep["pending"] or {})
            out = save(self, *a, **kw)
            S["session_done"] += 1
            _write_cadence(index)
            _tevent("episode_saved", episode=index, frames=cad.get("frames_observed"),
                    duration_s=cad.get("seconds"), cadence=cad or None, session_done=S["session_done"])
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
    start_server()
    restarts = int(__import__("os").environ.get("SCRUB_RESTARTS", "0"))
    if restarts:
        note(f"session restarted after a disconnect ({restarts}x)")


_server = [None]


def lan_ip() -> str | None:
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sk:
            sk.connect(("8.8.8.8", 80))  # no packet sent; picks the outgoing interface
            return sk.getsockname()[0]
    except OSError:
        return None


def start_server() -> None:
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    srv.daemon_threads = True
    _server[0] = srv
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    ip = lan_ip()
    print(f"recorder page: http://localhost:{PORT}" + (f"  (team: http://{ip}:{PORT}, API: /api)" if ip else ""),
          flush=True)


def stop_server() -> None:
    if _server[0]:
        _server[0].shutdown()
        _server[0].server_close()
        _server[0] = None


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


def _last_cadence():
    path = cadence_path()
    try:
        return json.loads(path.read_text())["episodes"][-1] if path and path.exists() else None
    except (ValueError, IndexError, KeyError):
        return None


def status() -> dict:
    _attach_log()
    with lock:
        cams = {k: {"brightness": round(float(v[::8, ::8].mean())), "fps": _rate(cam_ticks.get(k, deque()))}
                for k, v in frames.items()}
        out = {k: (list(v) if isinstance(v, deque) else v) for k, v in S.items()}
    out.update(cameras=cams, loop_hz=_rate(loop_ticks), dataset=_dataset(), now=time.time(),
               reference=reference_path().exists(), last_episode=_last_cadence())
    warn = []
    for k, c in cams.items():
        if c["brightness"] < 25:
            warn.append(f"{k.capitalize()} camera is dark (brightness {c['brightness']})")
        if c["fps"] is not None and c["fps"] < 25:
            warn.append(f"{k.capitalize()} camera {c['fps']:.0f} fps (needs 30)")
    for k in sorted(down):
        warn.insert(0, f"{k.upper()} CAMERA DOWN: reconnecting" +
                    (" (episodes are discarded until it is back)" if out["mode"] == "record" else ""))
    for k, n in stalls.items():
        warn.append(f"{k.capitalize()} camera stalled {n}x" +
                    (" this episode: re-record it" if out["mode"] == "record" else ""))
    if out["loop_hz"] is not None and out["loop_hz"] < 27 and out["phase"] in ("recording", "resetting", "teleop"):
        warn.append(f"Control loop {out['loop_hz']:.0f} Hz (needs 30)")
    for m, v in (S.get("motors") or {}).items():
        if (v.get("temp_c") or 0) >= 55:
            warn.insert(0, f"{m} motor {v['temp_c']} C: rest the arm with torque off")
        if v.get("limp"):
            warn.insert(0, f"{m} torque OFF: it wrapped past its calibrated range, recalibrate the follower")
        if v.get("held"):
            warn.append(f"{m} blocked: holding instead of pushing (move the leader back to free it)")
    gh = S.get("grip_health") or {}
    if (gh.get("temp_c") or 0) >= 55:
        warn.insert(0, f"Gripper {gh['temp_c']} C: let it rest open (eases itself open at 62 C)")
    if (gh.get("load") or 0) > 300:
        warn.append(f"Gripper straining (load {gh['load']}): close the leader only until the claw touches")
    out["warnings"] = [f"Waiting for {w}" for w in S["waiting"]] + warn
    return out


def control(action: str) -> bool:
    ok = _control(action)
    _tevent("control", action=action, accepted=bool(ok), phase=S["phase"])
    return ok


def _control(action: str) -> bool:
    if action == "start" and S["mode"] == "preview":
        import os
        import signal
        (Path.home() / "scrub-logs" / "start-recording").touch()
        note("page: start recording")
        threading.Timer(0.2, lambda: os.kill(os.getpid(), signal.SIGINT)).start()  # end the preview
        return True
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


API = {
    "GET /status": "everything on the page as JSON: mode, phase, task, episode, session_done/total, "
                   "phase_started/phase_s/now, loop_hz, cameras {name: fps, brightness}, joints, gripper, "
                   "guard, dataset, last_episode (cadence), warnings, log",
    "GET /stream/side, /stream/wrist": "MJPEG camera previews (15 fps)",
    "GET /reference.jpg": "the saved setup photo",
    "GET /frame/side.jpg, /frame/wrist.jpg": "the latest camera frame as one JPEG",
    "POST /control {action: next|rerecord|stop}": "like the arrow keys; recording Mac only (or X-Scrub-Token)",
    "POST /reference": "save the side camera as the setup photo; recording Mac only",
    "files": "<root>-cadence.json per-episode timing; ~/scrub-logs/arm-*.log every run",
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")  # other pages may read; buttons stay local (_local)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.path = urlsplit(self.path).path  # the page adds ?t= to retry streams
        if self.path in ("/", "/index.html"):
            self._send(200, HTML.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/status":
            self._send(200, json.dumps(status()).encode(), "application/json")
        elif self.path == "/api":
            self._send(200, json.dumps(API, indent=1).encode(), "application/json")
        elif self.path == "/reference.jpg":
            p = reference_path()
            self._send(200, p.read_bytes(), "image/jpeg") if p.exists() else self._send(404, b"none", "text/plain")
        elif self.path.startswith("/frame/") and self.path.endswith(".jpg"):
            with lock:
                f = frames.get(self.path[len("/frame/"):-4])
            if f is None:
                return self._send(404, b"no frame", "text/plain")
            ok, jpg = cv2.imencode(".jpg", cv2.cvtColor(f, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 80])
            self._send(200, jpg.tobytes(), "image/jpeg")
        elif self.path.startswith("/stream/"):
            self._stream(self.path.split("/")[-1])
        else:
            self._send(404, b"not found", "text/plain")

    def _local(self) -> bool:
        if self.client_address[0] in ("127.0.0.1", "::1"):
            return True
        return bool(TOKEN) and self.headers.get("X-Scrub-Token") == TOKEN

    def do_POST(self):
        self.path = urlsplit(self.path).path
        if not self._local():
            return self._send(403, b'{"ok": false, "reason": "controls only from the recording Mac"}',
                              "application/json")
        if self.path == "/reference":
            return self._send(200, json.dumps({"ok": save_reference()}).encode(), "application/json")
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
