"""Persistent SO-101 recording station: one process, cameras/arms/dataset opened once, teleop always live.

  .venv/bin/python explore/station/station.py --task "pick the spatula"
  .venv/bin/python explore/station/station.py --task "pick the spatula" --root ~/scrub-dataset --port 8090

Page: http://localhost:8090 (teammates can watch on http://<this Mac>:8090; buttons only work on this Mac).
Enter in the terminal = start / save toggle. Ctrl-C = discard any open episode, park, finalize, exit.

Unlike explore/arm_session.py (which restarts lerobot-record per batch), this runs its own 30 Hz loop with
LeRobot's pieces: SOFollower + SOLeader connected once, LeRobotDataset created/resumed once, frames built
with build_dataset_frame exactly like lerobot_record.record_loop, so episodes land in the same dataset
(~/scrub-dataset, repo "local/scrub", 30 fps, cameras side + wrist at 640x480). The safety guards from
arm_session.py (joint stall, gripper, gentle mode, park, temperature reads, telemetry) patch SOFollower.
"""
from __future__ import annotations

import argparse
import faulthandler
import json
import logging
import os
import queue
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
EXPLORE = HERE.parent
for p in (str(EXPLORE.parent), str(EXPLORE)):
    if p not in sys.path:
        sys.path.insert(0, p)

import arm_session as A  # noqa: E402  (guards, ease, camera lookup, home pose)
import arm_ui  # noqa: E402  (only its S dict, which the guards read and write)
import thermal_log  # noqa: E402

FPS = 30
REPO = "local/scrub"
COOL_TRIP, COOL_RESUME, TEMP_WARN = 60, 50, 55   # deg C
COOL_PLATEAU_S = 180                             # cooled but stuck <= 55 C this long: done anyway
ERROR_AFTER = 10                                 # consecutive failed loops before the state is "error"
HTML = HERE / "station.html"
LOCAL = ("127.0.0.1", "::1", "::ffff:127.0.0.1")


# --------------------------------------------------------------------------------------------- hardware

def make_hardware(follower: str, leader: str, side: str, wrist: str):
    """SOFollower (side + wrist cameras by name) and SOLeader, configured like arm_session's lerobot-record."""
    from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig
    from lerobot.robots.so_follower import SOFollower
    from lerobot.robots.so_follower.config_so_follower import SO101FollowerConfig
    from lerobot.teleoperators.so_leader import SOLeader
    from lerobot.teleoperators.so_leader.config_so_leader import SO101LeaderConfig

    cams = {}
    for role, spec in (("side", side), ("wrist", wrist)):
        idx = A.find_camera(spec)
        if idx is None:
            raise SystemExit(f"{role} camera {spec!r} not found (or ambiguous) in {A.camera_names()}")
        A.CAM_SPECS[idx] = (role, spec)          # tolerate_camera_stalls finds it again after a replug
        arm_ui.cfg["cams"][idx] = role
        cams[role] = OpenCVCameraConfig(index_or_path=idx, width=640, height=480, fps=30)
        print(f"{role} camera: index {idx} ({spec})", flush=True)
    robot = SOFollower(SO101FollowerConfig(
        port=follower, id="scrub_follower", use_degrees=True, disable_torque_on_disconnect=False,
        max_relative_target=15.0, cameras=cams))  # LeRobot only accepts a float (int -> TypeError)
    teleop = SOLeader(SO101LeaderConfig(port=leader, id="scrub_leader", use_degrees=True))
    return robot, teleop


def tolerate_status_errors() -> None:
    """A motor sitting a hair past its calibrated range (the elbow at home: 3041 vs max 3037) flags an
    angle error on every reply. LeRobot then raises on writes the motor already carried out, and
    disable_torque()/enable_torque() stop at that motor, so KILL, Motors on and Reconnect failed
    (Oct 18). Keep the write (it was delivered), log the flag once per motor/register, retry real
    comm failures twice."""
    from lerobot.motors.motors_bus import MotorsBus
    write = MotorsBus.write
    seen = set()

    def tolerant(self, data_name, motor, value, *, normalize=True, num_retry=0):
        try:
            return write(self, data_name, motor, value, normalize=normalize, num_retry=max(num_retry, 2))
        except RuntimeError as e:  # comm succeeded; the reply carried a status flag
            if (motor, data_name) not in seen:
                seen.add((motor, data_name))
                print(f"bus: {motor} flagged '{str(e).strip()[-60:]}' on {data_name} write (applied, continuing)",
                      flush=True)
    MotorsBus.write = tolerant


def broadcast_torque_off(bus) -> None:
    """Torque off on every motor in one broadcast packet (ID 254, no reply), so no flag can block it."""
    try:
        bus.packet_handler.write1ByteTxOnly(bus.port_handler, 254, 40, 0)
    except Exception:  # noqa: BLE001
        pass


def reconnect_hardware(robot, teleop) -> None:
    """Best effort: reopen both motor buses without touching the cameras or the dataset."""
    for dev in (robot, teleop):
        try:
            dev.bus.disconnect(False)
        except Exception:  # noqa: BLE001 - already gone
            pass
    robot.bus.connect()
    A.hardware.hold_present(robot.bus)       # goal = present before configure re-enables torque: no jump
    robot.configure()
    A.hardware.hold_present(robot.bus)
    teleop.bus.connect()
    teleop.configure()


def dataset_features(robot) -> dict:
    """Exactly the features lerobot_record.record() builds."""
    from lerobot.datasets.pipeline_features import aggregate_pipeline_dataset_features, create_initial_features
    from lerobot.datasets.utils import combine_feature_dicts
    from lerobot.processor import make_default_processors
    t, _r, o = make_default_processors()
    return combine_feature_dicts(
        aggregate_pipeline_dataset_features(pipeline=t, initial_features=create_initial_features(
            action=robot.action_features), use_videos=True),
        aggregate_pipeline_dataset_features(pipeline=o, initial_features=create_initial_features(
            observation=robot.observation_features), use_videos=True))


def open_dataset(root, robot, repo=REPO, fps=FPS, vcodec="libsvtav1", streaming=True, encoder_threads=2,
                 log=print):
    """Resume root if it has episodes; move aside a meta-only (0 episode) or stray folder; else create."""
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from lerobot.utils.control_utils import sanity_check_dataset_robot_compatibility
    root = Path(root).expanduser()
    feats = dataset_features(robot)
    ncam = len(getattr(robot, "cameras", {}) or {})
    if (root / "meta" / "info.json").exists() and A.dataset_episodes(root) > 0:
        ds = LeRobotDataset(repo, root=root, batch_encoding_size=1, vcodec=vcodec, streaming_encoding=streaming,
                            encoder_queue_maxsize=30, encoder_threads=encoder_threads)
        if ncam:
            ds.start_image_writer(num_processes=0, num_threads=4 * ncam)
        sanity_check_dataset_robot_compatibility(ds, robot, fps, feats)
        log(f"dataset: resumed {root} ({ds.meta.total_episodes} episodes)")
        return ds
    if root.exists():
        # A session that died before its first save leaves only meta/info.json; resuming that sends
        # LeRobot to the Hub (404). Same rule as arm_session.py.
        aside = root.with_name(f"{root.name}.incomplete-{time.strftime('%H%M%S')}")
        root.rename(aside)
        log(f"dataset: {root} had no saved episodes, moved it to {aside.name}")
    ds = LeRobotDataset.create(repo, fps, root=root, robot_type=robot.name, features=feats, use_videos=True,
                               image_writer_processes=0, image_writer_threads=4 * ncam, batch_encoding_size=1,
                               vcodec=vcodec, streaming_encoding=streaming, encoder_queue_maxsize=30,
                               encoder_threads=encoder_threads)
    log(f"dataset: created {root}")
    return ds


def _rate(ticks) -> float | None:
    now = time.perf_counter()
    t = [x for x in list(ticks) if x > now - 2]
    return round((len(t) - 1) / (t[-1] - t[0]), 1) if len(t) > 2 and t[-1] > t[0] else None


# ---------------------------------------------------------------------------------------------- station

class Station:
    """The loop, the state machine and everything the page shows. Hardware comes in through arguments
    (fakes in the test). All robot/dataset calls happen on the loop thread; controls are queued to it."""

    def __init__(self, robot, teleop, dataset, task: str, root, fps: int = FPS, reconnect=reconnect_hardware,
                 cooling_factory=None):
        from lerobot.processor import make_default_processors
        from lerobot.utils.constants import ACTION, OBS_STR
        self.robot, self.teleop, self.ds = robot, teleop, dataset
        self.task, self.root, self.fps = task, Path(root).expanduser(), fps
        self.reconnect_fn = reconnect
        self.cooling_factory = cooling_factory or (lambda: A.thermal.Cooling(
            resume=COOL_RESUME, trip=COOL_TRIP, plateau_s=COOL_PLATEAU_S))
        self.tproc, self.rproc, self.oproc = make_default_processors()
        self.OBS, self.ACT = OBS_STR, ACTION
        self.state = "idle"                      # idle recording homing parked cooling killed error
        self.killed = False                      # torque off by KILL (survives a cool-down)
        self.saving = False
        self.cooling = None                      # arm.thermal.Cooling while cooling down
        self.cool_since = None
        self.error = None
        self.fail = 0
        self.frames = 0                          # frames in the open episode
        self.ep_index = None
        self.ep_t0 = None
        self.ep_cam0: dict = {}
        self.session_saved = 0
        self.pending_discard = None              # set by the guards (from inside send_action)
        self.down: set = set()                   # camera roles not sending frames
        self.stalls: dict = {}
        self.cam_new: dict = {}                  # role -> new frames seen since start
        self.cam_ticks: dict = {}
        self.cam_last: dict = {}
        self.loop_ticks: deque = deque(maxlen=90)
        self.frames_ui: dict = {}
        self.joints: dict = {}
        self.gripper = None
        self.log: deque = deque(maxlen=60)
        self.lock = threading.Lock()
        self.q: queue.Queue = queue.Queue()
        self.stop_evt = threading.Event()
        self.loop_thread = None
        self.beat = 0.0
        self.temp_t = 0.0
        self.save_thread = None
        self._jpeg: dict = {}
        self.closed = False
        arm_ui.S.update(phase="teleop", parked=False, motors={}, park_req=None)
        arm_ui.S.pop("park_req", None)
        self._install_hooks()
        thermal_log.get({"source": "station", "pid": os.getpid(), "task": task, "root": str(self.root),
                         "mode": "station", "settings": {"COOL_TRIP": COOL_TRIP, "COOL_RESUME": COOL_RESUME}})

    # ---- hooks the guards call (they look these up on arm_ui / arm_session at call time)
    def _install_hooks(self) -> None:
        A.COOL_TRIP = 999                        # never let the guard end the process at 60 C ...
        A._start_cooldown = self._guard_cooldown  # ... and if it trips anyway (arm.thermal's trip), we handle it
        arm_ui.note = self.note
        arm_ui.discard_episode = lambda reason: self._flag_discard(reason)
        arm_ui.camera_down = self._camera_down
        arm_ui.camera_stall = self._camera_stall

    def _guard_cooldown(self, temps: dict) -> None:
        self.note(f"guard: motor at {max(v for v in temps.values() if v is not None)} C")
        motors = arm_ui.S.get("motors") or {}
        for m, t in temps.items():
            motors.setdefault(m, {})["temp_c"] = t
        arm_ui.S["motors"] = motors              # the loop's check sees it and starts the cool-down

    def _flag_discard(self, reason: str) -> None:
        if self.state == "recording" and not self.pending_discard:
            self.pending_discard = reason

    def _role(self, index) -> str:
        return arm_ui.cfg["cams"].get(index, str(index))

    def _camera_down(self, index, is_down: bool) -> None:
        role = self._role(index)
        if is_down and role not in self.down:
            self.down.add(role)
            self.note(f"{role} camera DOWN: reconnecting; recording is blocked until it is back")
        elif not is_down and role in self.down:
            self.down.discard(role)
            self.note(f"{role} camera back")
        if is_down:
            self._flag_discard("camera_down")

    def _camera_stall(self, index) -> None:
        role = self._role(index)
        self.stalls[role] = self.stalls.get(role, 0) + 1

    # ---- messages and telemetry
    def note(self, msg: str) -> None:
        line = time.strftime("%H:%M:%S ") + msg
        self.log.append(line)
        print(line, flush=True)

    @staticmethod
    def event(kind: str, **f) -> None:
        thermal_log.event(kind, **f)

    @staticmethod
    def row(row: dict) -> None:
        try:
            thermal_log.get().write(row)
        except Exception:  # noqa: BLE001 - telemetry never stops the arm
            pass

    # ---- controls
    def control(self, action: str, task: str | None = None, timeout: float = 3.0) -> dict:
        """Thread-safe: runs on the loop thread (immediately if the loop isn't running)."""
        loop_alive = self.loop_thread is not None and self.loop_thread.is_alive()
        if not loop_alive or threading.current_thread() is self.loop_thread:
            return self._do(action, task)
        if action == "kill" and time.perf_counter() - self.beat > 0.3:
            self._kill_now()                     # the loop is stuck (a hung read): cut torque from here
        done, out = threading.Event(), {}
        self.q.put((action, task, done, out))
        if not done.wait(timeout):
            return {"ok": False, "msg": "station busy, try again", "state": self.state}
        return out

    def _do(self, action: str, task=None) -> dict:
        ok, msg = self._dispatch(action, task)
        if msg:
            self.note(msg)
        self.event("control", action=action, accepted=bool(ok), state=self.state, msg=msg)
        return {"ok": bool(ok), "msg": msg, "state": self.state}

    def _dispatch(self, action: str, task):
        if action == "toggle":
            if self.state == "recording":
                action = "save"
            elif self.state == "idle":
                action = "start"
            else:
                return False, f"start/save: not available while {self.state}"
        if action == "start":
            return self._start()
        if action == "save":
            if self.state != "recording":
                return False, "save: nothing is recording"
            return self._save(), None
        if action == "discard":
            if self.state != "recording":
                return False, "discard: nothing is recording"
            self._discard("user")
            return True, None
        if action == "kill":
            self._kill()
            return True, None
        if action == "home":
            if self.state == "recording":
                return False, "home: not while recording (save or discard first)"
            if self.state in ("killed", "error") or self.killed:
                return False, f"home: motors are off ({self.state}); press Motors on first"
            if self.state in ("cooling", "parked", "homing"):
                return False, f"home: already {self.state}"
            arm_ui.S["park_req"] = "home"
            self.state = "homing"
            return True, "going home, then motors off"
        if action == "wake":
            return self._wake()
        if action == "task":
            t = (task or "").strip()
            if not t:
                return False, "task: empty"
            if self.state == "recording":
                return False, "task: finish this episode first"
            self.task = t
            return True, f"task: {t!r}"
        if action == "reconnect":
            return self._reconnect()
        return False, f"unknown action {action!r}"

    def _start(self):
        if self.state != "idle":
            return False, f"start: not while {self.state}" + (" (press Motors on)" if self.state == "parked" else "")
        if self.saving:
            return False, "start: still saving the last episode"
        if self.down:
            return False, f"start: {', '.join(sorted(self.down))} camera down"
        if not (self.task or "").strip():
            return False, "start: set a task first"
        self.ep_index = self.ds.meta.total_episodes
        self.frames, self.ep_t0, self.pending_discard = 0, time.perf_counter(), None
        self.ep_cam0 = dict(self.cam_new)
        self.stalls.clear()
        thermal_log.EP.update(active=True, **{k: (dict(v) if isinstance(v, dict) else v)
                                               for k, v in thermal_log.EP_RESET.items()})
        self.state = "recording"
        arm_ui.S["phase"] = "recording"
        self.event("episode_start", episode=self.ep_index, task=self.task, root=str(self.root))
        return True, f"RECORDING episode {self.ep_index}: {self.task}"

    def _end(self, reason: str) -> dict:
        """episode_end row; back to idle teleop. Returns the episode's cadence numbers."""
        dur = time.perf_counter() - (self.ep_t0 or time.perf_counter())
        E = thermal_log.EP
        E["active"] = False
        self.event("episode_end", episode=self.ep_index, reason=reason, duration_s=round(dur, 2), frames=self.frames,
                   grasps=E["grasps"], empty_closes=E["empty_closes"], peak_temps=dict(E["peak_temps"]),
                   lift_m=round(E["lift_max"], 3), lifted=E["lifted"], pulled=E["pulled"], released=E["released"],
                   handoff_success=bool(E["grasps"] and E["lifted"] and E["pulled"]))
        cad = {"measured_fps": round(self.frames / dur, 2) if dur > 0 else None, "seconds": round(dur, 2),
               "frames_observed": self.frames,
               "camera_fps": {k: round((self.cam_new.get(k, 0) - self.ep_cam0.get(k, 0)) / dur, 1) if dur > 0 else None
                              for k in self.cam_new},
               "camera_stalls": dict(self.stalls), "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        if self.state == "recording":
            self.state = "idle"
        arm_ui.S["phase"] = "teleop"
        self.pending_discard = None
        return cad

    def _discard(self, reason: str) -> None:
        if self.state != "recording":
            return
        idx, n = self.ep_index, self.frames
        self._end(reason)
        try:
            self.ds.clear_episode_buffer()
        except Exception as e:  # noqa: BLE001
            self.note(f"discard: clearing the buffer failed ({type(e).__name__}: {e})")
        self.event("episode_discarded", episode=idx, reason=reason, frames=n)
        self.note(f"episode {idx} discarded ({reason}, {n} frames)")

    def _save(self) -> bool:
        if self.frames == 0:
            self._discard("empty")
            return False
        idx, n = self.ep_index, self.frames
        cad = self._end("saved")
        self.saving = True
        self.note(f"saving episode {idx} ({n} frames, {cad['seconds']} s)...")

        def run():
            try:
                self.ds.save_episode()
                self.session_saved += 1
                self._write_cadence(idx, cad)
                self.event("episode_saved", episode=idx, frames=n, duration_s=cad["seconds"], cadence=cad,
                           session_done=self.session_saved, total=self.ds.meta.total_episodes)
                self.note(f"episode {idx} saved ({self.ds.meta.total_episodes} in the dataset)")
            except Exception as e:  # noqa: BLE001
                self.note(f"SAVE FAILED for episode {idx}: {type(e).__name__}: {e}")
                try:
                    self.ds.clear_episode_buffer()
                except Exception:  # noqa: BLE001
                    pass
                self.event("episode_discarded", episode=idx, reason=f"save_error: {type(e).__name__}", frames=n)
            finally:
                self.saving = False
        self.save_thread = threading.Thread(target=run, daemon=True, name="save")
        self.save_thread.start()
        return True

    def _write_cadence(self, index: int, entry: dict) -> None:
        """<root>-cadence.json, the per-episode timing file arm.train's check reads (same as arm_ui)."""
        path = Path(f"{self.root}-cadence.json")
        try:
            data = json.loads(path.read_text()) if path.exists() else {"episodes": []}
        except ValueError:
            data = {"episodes": []}
        data["episodes"] = [e for e in data["episodes"] if e.get("episode_index") != index]
        data["episodes"].append({"episode_index": index, **entry})
        data["episodes"].sort(key=lambda e: e["episode_index"])
        path.write_text(json.dumps(data, indent=1))

    def _kill_now(self) -> None:
        self.killed = True
        broadcast_torque_off(self.robot.bus)  # first: one packet, no reply needed
        try:
            self.robot.bus.disable_torque()
        except Exception as e:  # noqa: BLE001
            broadcast_torque_off(self.robot.bus)
            self.note(f"KILL: per-motor torque off errored ({type(e).__name__}); broadcast torque off sent")

    def _kill(self) -> None:
        self._kill_now()
        self._discard("kill")
        arm_ui.S.pop("park_req", None)
        if self.state != "cooling":
            self.state = "killed"
        self.event("kill", state=self.state)
        self.note("KILL: motors off. A raised arm drops. Press Motors on to resume")

    def _wake(self):
        if self.state == "cooling":
            return False, "motors on: cooling down first (see temperatures)"
        if self.state == "error":
            return False, "motors on: press Reconnect first"
        if self.state == "killed" or self.killed:
            try:
                A.hardware.wake(self.robot.bus)  # Goal = Present (raw), then torque on: nothing moves
            except Exception as e:  # noqa: BLE001
                return False, f"motors on failed ({type(e).__name__}: {e})"
            self.killed = False
            arm_ui.S["park_req"] = "wake"        # resets the guard's park state; big gaps catch up slowly
            self.state = "idle"
            return True, "motors on: holding, then following the leader"
        if self.state in ("parked", "homing"):
            arm_ui.S["park_req"] = "wake"
            self.state = "idle"
            return True, "motors on: following the leader"
        return False, f"motors on: already on ({self.state})"

    def _reconnect(self):
        if self.state == "recording":
            return False, "reconnect: not while recording"
        try:
            self.reconnect_fn(self.robot, self.teleop)
        except Exception as e:  # noqa: BLE001
            self.error = f"reconnect failed: {type(e).__name__}: {e}"
            self.state = "error"
            return False, self.error
        self.error, self.fail, self.killed = None, 0, False
        arm_ui.S["park_req"] = "wake"
        arm_ui.S["parked"] = False
        self.state = "idle"
        return True, "reconnected: following the leader"

    # ---- the loop
    def sending(self) -> bool:
        return not self.killed and self.state not in ("killed", "error")

    def tick(self) -> None:
        self.beat = now = time.perf_counter()
        while True:
            try:
                action, task, done, out = self.q.get_nowait()
            except queue.Empty:
                break
            out.update(self._do(action, task))
            done.set()
        if self.state == "error":
            return
        arm_ui.S["phase"] = "recording" if self.state == "recording" else "teleop"
        try:
            obs = self.robot.get_observation()
            act = self.teleop.get_action()
            obs_p = self.oproc(obs)
            act_p = self.tproc((act, obs))
            if self.sending():
                self.robot.send_action(self.rproc((act_p, obs)))
            self.fail = 0
        except Exception as e:  # noqa: BLE001 - retry_bus_reads already retried; count and carry on
            self.fail += 1
            if self.fail in (1, ERROR_AFTER) or self.fail % 30 == 0:
                self.note(f"loop error {self.fail}x: {type(e).__name__}: {str(e)[:160]}")
            if self.fail >= ERROR_AFTER:
                self.error = f"arm or leader not answering ({type(e).__name__}): check USB/power, then Reconnect"
                self._discard("error")
                self.state = "error"
                self.event("station_error", error=f"{type(e).__name__}: {str(e)[:200]}")
            return
        self.loop_ticks.append(now)
        arm_ui.loop_ticks.append(now)            # the guard's sample rows log this loop rate
        if self.pending_discard and self.state == "recording":
            self._discard(self.pending_discard)
        if self.state == "recording":
            try:
                frame = {**self._build(obs_p, self.OBS), **self._build(act_p, self.ACT), "task": self.task}
                self.ds.add_frame(frame)
                self.frames += 1
            except Exception as e:  # noqa: BLE001
                self.note(f"frame error: {type(e).__name__}: {e}")
                self._discard("frame_error")
        self._update_ui(obs)
        self._park_sync()
        self._thermal(now)

    def _build(self, values: dict, prefix: str) -> dict:
        from lerobot.datasets.utils import build_dataset_frame
        return build_dataset_frame(self.ds.features, values, prefix=prefix)

    def _update_ui(self, obs: dict) -> None:
        import numpy as np
        now = time.perf_counter()
        with self.lock:
            for k, v in obs.items():
                if isinstance(v, np.ndarray) and v.ndim == 3:
                    if v is not self.cam_last.get(k):
                        self.cam_new[k] = self.cam_new.get(k, 0) + 1
                        self.cam_ticks.setdefault(k, deque(maxlen=90)).append(now)
                        self.cam_last[k] = v
                    self.frames_ui[k] = v
            self.joints = {k[:-4]: round(float(v), 1) for k, v in obs.items()
                           if k.endswith(".pos") and k != "gripper.pos"}
            if "gripper.pos" in obs:
                self.gripper = round(float(obs["gripper.pos"]), 1)

    def _park_sync(self) -> None:
        parked = bool(arm_ui.S.get("parked"))
        if self.state == "homing" and parked:
            self.state = "parked"
            self.note("parked at home, motors off")
            self.event("station_parked")

    def temps(self) -> dict:
        return {m: v.get("temp_c") for m, v in (arm_ui.S.get("motors") or {}).items()}

    def _thermal(self, now: float) -> None:
        # The guard reads temperatures every 2 s while it drives the arm. Parked or killed it doesn't
        # publish them, so read them here and keep the temperature site fed.
        own = self.state in ("parked", "killed", "cooling") or self.killed or bool(arm_ui.S.get("parked"))
        if own and now - self.temp_t >= 2.0:
            self.temp_t = now
            try:
                raw = self.robot.bus.sync_read("Present_Temperature", normalize=False)
                temps = {k: int(v) for k, v in raw.items()}
                motors = arm_ui.S.get("motors") or {}
                for m, t in temps.items():
                    motors.setdefault(m, {})["temp_c"] = t
                arm_ui.S["motors"] = motors
                self.row({"kind": "cooling" if self.state == "cooling" else "sample", "phase": self.state,
                          "temps": temps, "motors": {m: {"temp": t} for m, t in temps.items()}})
            except Exception as e:  # noqa: BLE001
                self.note(f"temperature read failed ({type(e).__name__})")
        vals = [t for t in self.temps().values() if isinstance(t, (int, float))]
        hottest = max(vals) if vals else None
        if hottest is None:
            return
        thermal_log.track_temps(self.temps())
        if self.cooling is None and hottest >= COOL_TRIP:
            self._discard("cooldown")
            self.cooling, self.cool_since = self.cooling_factory(), time.time()
            self.event("cooldown_trip", temps=self.temps(), hottest=hottest)
            if not self.killed and not arm_ui.S.get("parked"):
                arm_ui.S["park_req"] = "home"
            self.state = "cooling"
            self.note(f"COOL-DOWN: hottest motor {hottest} C: going home, motors off; resumes at {COOL_RESUME} C")
        elif self.cooling is not None and self.cooling.done(hottest):
            self.cooling = None
            self.event("cooldown_done", hottest=hottest, minutes=round((time.time() - self.cool_since) / 60, 1))
            self.state = "killed" if self.killed else ("parked" if arm_ui.S.get("parked") else "idle")
            self.note(f"cooled to {hottest} C: press Motors on to continue")

    def run(self) -> None:
        """30 Hz until stop(); LeRobot's timing (precise_sleep for the rest of each 1/fps)."""
        from lerobot.utils.robot_utils import precise_sleep
        self.loop_thread = threading.current_thread()
        while not self.stop_evt.is_set():
            t0 = time.perf_counter()
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001 - the station never dies from one bad tick
                self.note(f"tick error: {type(e).__name__}: {e}")
            precise_sleep(max(1 / self.fps - (time.perf_counter() - t0), 0.0))

    def start_thread(self) -> threading.Thread:
        t = threading.Thread(target=self.run, daemon=True, name="station-loop")
        self.loop_thread = t
        t.start()
        return t

    def stop(self) -> None:
        self.stop_evt.set()
        if self.loop_thread is not None and self.loop_thread is not threading.current_thread():
            self.loop_thread.join(timeout=5)

    def close(self, park_timeout: float = 20.0) -> None:
        """Discard an open episode, park, finalize the dataset, disconnect with torque off at home."""
        if self.closed:
            return
        self.closed = True
        self.stop()
        self.loop_thread = None                  # controls now run inline
        self._discard("exit")
        if self.save_thread is not None:
            self.save_thread.join(timeout=120)
        try:
            if self.sending() and not arm_ui.S.get("parked") and self.state != "cooling":
                arm_ui.S["park_req"] = "home"
                self.state = "homing"
            end = time.perf_counter() + park_timeout
            while self.sending() and not arm_ui.S.get("parked") and time.perf_counter() < end:
                t0 = time.perf_counter()
                self.tick()
                time.sleep(max(0.0, 1 / self.fps - (time.perf_counter() - t0)))
        except BaseException as e:  # noqa: BLE001 - a second Ctrl-C skips parking, not the finalize
            self.note(f"exit: parking skipped ({type(e).__name__})")
        try:
            from lerobot.datasets.video_utils import VideoEncodingManager
            VideoEncodingManager(self.ds).__exit__(None, None, None)  # LeRobot's own teardown (closes encoder, finalize)
            self.ds.finalize()
            self.ds.stop_image_writer()
            self.note(f"dataset finalized: {self.ds.meta.total_episodes} episodes in {self.root}")
        except Exception as e:  # noqa: BLE001
            self.note(f"dataset finalize failed: {type(e).__name__}: {e}")
        for dev in (self.robot, self.teleop):
            try:
                dev.disconnect()                 # SOFollower: safe_disconnect turns torque off at home
            except Exception as e:  # noqa: BLE001
                self.note(f"disconnect {type(dev).__name__}: {type(e).__name__}")
        self.event("session_end", reason="exit", episodes_saved=self.session_saved)
        thermal_log.flush()

    # ---- what the page shows
    def status(self) -> dict:
        with self.lock:
            cams = {k: {"fps": _rate(self.cam_ticks.get(k, ())), "down": k in self.down,
                        "stalls": self.stalls.get(k, 0)} for k in self.frames_ui}
            joints, grip = dict(self.joints), self.gripper
        for k in self.down:
            cams.setdefault(k, {"fps": None, "down": True, "stalls": self.stalls.get(k, 0)})
        motors = arm_ui.S.get("motors") or {}
        temps = self.temps()
        vals = [t for t in temps.values() if isinstance(t, (int, float))]
        hz = _rate(self.loop_ticks)
        rec = self.state == "recording"
        warn = []
        if self.state == "killed" or self.killed:
            warn.append("KILLED: motors are off. If the arm was raised it dropped. Motors on resumes.")
        if self.state == "error":
            warn.append(f"ERROR: {self.error}")
        if self.cooling is not None:
            warn.append(f"COOLING DOWN: hottest {max(vals) if vals else '?'} C, Start unlocks at {COOL_RESUME} C")
        for k in sorted(self.down):
            warn.append(f"{k.upper()} CAMERA DOWN: reconnecting")
        for m, v in motors.items():
            t = v.get("temp_c")
            if isinstance(t, (int, float)) and t >= TEMP_WARN:
                warn.append(f"{m} {t} C: rest the arm (Home + motors off)")
            if v.get("limp"):
                warn.append(f"{m} torque OFF: outside its calibrated range, recalibrate")
            if v.get("held"):
                warn.append(f"{m} blocked: holding instead of pushing")
        if hz is not None and hz < 27 and self.state in ("idle", "recording"):
            warn.append(f"Control loop {hz:.0f} Hz (needs 30)")
        for k, c in cams.items():
            if c["fps"] is not None and c["fps"] < 25 and not c["down"]:
                warn.append(f"{k} camera {c['fps']:.0f} fps (needs 30)")
        if self.saving:
            warn.append("Saving the last episode...")
        try:
            total = self.ds.meta.total_episodes
        except Exception:  # noqa: BLE001
            total = None
        return {"state": self.state, "task": self.task, "episode_index": self.ep_index if rec else total,
                "episodes_total": total, "episodes_session": self.session_saved,
                "recording_s": round(time.perf_counter() - self.ep_t0, 1) if rec and self.ep_t0 else 0.0,
                "frames": self.frames if rec else 0, "saving": self.saving, "loop_hz": hz, "cameras": cams,
                "joints": joints, "gripper": grip, "temps": temps, "hottest": max(vals) if vals else None,
                "parked": bool(arm_ui.S.get("parked")), "killed": self.killed, "error": self.error,
                "cooling": self.cooling is not None, "guard": arm_ui.S.get("guard"),
                "grip_health": arm_ui.S.get("grip_health"), "root": str(self.root), "warnings": warn,
                "log": list(self.log), "now": time.time()}

    def jpeg(self, name: str):
        import cv2
        with self.lock:
            f = self.frames_ui.get(name)
        if f is None:
            return None
        hit = self._jpeg.get(name)
        if hit and hit[0] is f:
            return hit[1]
        ok, buf = cv2.imencode(".jpg", cv2.cvtColor(f, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 70])
        if not ok:
            return None
        self._jpeg[name] = (f, buf.tobytes())
        return self._jpeg[name][1]


# ------------------------------------------------------------------------------------------------- web

def make_handler(st: Station):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path in ("/", "/index.html"):
                self._send(200, HTML.read_bytes(), "text/html; charset=utf-8")
            elif path == "/status":
                self._send(200, json.dumps(st.status(), default=str).encode(), "application/json")
            elif path.startswith("/stream/"):
                self._stream(path.rsplit("/", 1)[-1])
            elif path.startswith("/frame/") and path.endswith(".jpg"):
                jpg = st.jpeg(path[len("/frame/"):-4])
                self._send(200, jpg, "image/jpeg") if jpg else self._send(404, b"no frame", "text/plain")
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            path = urlsplit(self.path).path
            if self.client_address[0] not in LOCAL:
                return self._send(403, b'{"ok": false, "msg": "controls only from the station Mac"}',
                                  "application/json")
            if path != "/control":
                return self._send(404, b"not found", "text/plain")
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                body = {}
            out = st.control(str(body.get("action", "")), body.get("task"))
            self._send(200, json.dumps(out).encode(), "application/json")

        def _stream(self, name: str):
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                while not st.closed:
                    jpg = st.jpeg(name)
                    if jpg:
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                         + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
                    time.sleep(1 / 15)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
    return Handler


def serve(st: Station, port: int, host: str = "0.0.0.0") -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer((host, port), make_handler(st))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True, name="http").start()
    return srv


def stdin_loop(st: Station, stream=None) -> None:
    """Enter in the terminal = start / save toggle."""
    stream = stream or sys.stdin
    while True:
        try:
            line = stream.readline()
        except (OSError, ValueError):
            return
        if not line:                             # EOF
            return
        st.control("toggle")


# ------------------------------------------------------------------------------------------------ main

def start_log() -> Path:
    logs = Path.home() / "scrub-logs"
    logs.mkdir(exist_ok=True)
    path = logs / time.strftime("station-%Y%m%d-%H%M%S.log")
    log = open(path, "a", buffering=1)
    sys.stdout, sys.stderr = A.Tee(sys.stdout, log), A.Tee(sys.stderr, log)
    faulthandler.enable(log)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
    print(f"log: {path}", flush=True)
    return path


def wait_for_devices(a) -> None:
    shown = None
    while True:
        missing = A.missing_devices(a)
        if not missing:
            return
        if missing != shown:
            print("waiting for: " + ", ".join(missing), flush=True)
            shown = missing
        time.sleep(1)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--task", default="pick the spatula", help="instruction stored with each frame")
    p.add_argument("--root", default=str(Path.home() / "scrub-dataset"))
    p.add_argument("--repo", default=REPO)
    p.add_argument("--port", type=int, default=8090)
    p.add_argument("--side", default="C920", help="side camera name part (or OpenCV index)")
    p.add_argument("--wrist", default="icspring", help="wrist camera name part (or OpenCV index)")
    p.add_argument("--follower", default=A.FOLLOWER)
    p.add_argument("--leader", default=A.LEADER)
    p.add_argument("--ease-s", type=float, default=3.0)
    p.add_argument("--no-browser", action="store_true")
    a = p.parse_args()
    start_log()
    A.lenient_motor_check()
    A.retry_bus_reads()
    tolerate_status_errors()
    while True:  # a port just released by another recorder, or a motor blip: wait and try again
        wait_for_devices(a)
        try:
            A.ease(a.follower, a.leader, a.ease_s)
            break
        except (ConnectionError, RuntimeError, OSError) as e:
            print(f"arm not ready ({type(e).__name__}: {str(e).strip().splitlines()[0][:120] if str(e).strip() else ''}): "
                  "retrying in 3 s", flush=True)
            time.sleep(3)
    A.clamp_follower()     # innermost: the gripper guard sees and sends clamped goals
    A.guard_gripper()
    A.guard_joints()       # outermost: safety, park, temperatures, telemetry
    A.tolerate_camera_stalls()
    robot, teleop = make_hardware(a.follower, a.leader, a.side, a.wrist)
    robot.connect()
    teleop.connect()
    try:
        ds = open_dataset(a.root, robot, repo=a.repo)
    except Exception:
        robot.disconnect()
        teleop.disconnect()
        raise
    st = Station(robot, teleop, ds, a.task, a.root)
    srv = serve(st, a.port)
    st.note(f"station ready: http://localhost:{a.port}  task {a.task!r}  dataset {a.root} "
            f"({ds.meta.total_episodes} episodes). Enter = start/save, Ctrl-C = exit")
    threading.Thread(target=stdin_loop, args=(st,), daemon=True, name="stdin").start()
    if not a.no_browser:
        import webbrowser
        webbrowser.open(f"http://localhost:{a.port}")
    try:
        st.run()
    except KeyboardInterrupt:
        st.note("Ctrl-C: discarding any open episode, parking, finalizing")
    finally:
        st.close()
        srv.shutdown()


if __name__ == "__main__":
    main()
