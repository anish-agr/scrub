"""Controller-facing SO-101 interface. Blocking methods belong in worker threads.

Only the playback thread accesses the motor bus after connect. freeze() merely
sets an event and never waits for a network call, camera, bus, or mutex.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
import threading
import time

import numpy as np
from dotenv import load_dotenv

from .backends import LeRobotBackend, SavedImageBackend
from .kinematics import Kinematics
from .motion import CartesianMotion
from .sessions import DryPolicySession, PolicySession
from .session_pool import SessionPool
from .streaming import DELAY, HZ, STRIDE, Timeline


class Arm:
    def __init__(self, *, dry_run=False, side_image=None, wrist_image=None,
                 rig_path=None, deployment_id=None, port=None, robot_id=None,
                 side_index=None, wrist_index=None, backend=None, session_factory=None):
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        self.dry_run = dry_run
        self.kin = Kinematics(rig_path)
        self.rig = self.kin.rig
        self.deployment_id = deployment_id or os.getenv("PERCEPTRON_DEPLOYMENT_ID")
        self._backend = backend
        self._backend_args = (side_image, wrist_image, port, robot_id, side_index, wrist_index)
        self._session_factory = session_factory
        self._session = None
        self._lock = threading.Lock()
        self._operation = threading.Lock()
        self._frozen = threading.Event()
        self._sessions = SessionPool(self._new_session,
                                     lambda: (self.deployment_id, self.rig.get("verified_contract_id")),
                                     self._frozen.is_set)
        self._shutdown = threading.Event()
        self._done = threading.Event()
        self._thread = None
        self._timeline = Timeline(self.kin)
        self._mode = "hold"
        self._state = None
        self._state_time = 0.0
        self._load = None
        self._load_time = 0.0
        self._error = None
        self._last_sent = None
        self._motion = None
        self._skill_deadline = 0.0
        self._skill_success = False
        self._played = False
        self.last_reason = "not connected"
        self.counters = {"accepted": 0, "late": 0, "holds": 0, "ticks": 0, "overruns": 0}

    def connect(self):
        if self._thread is not None:
            raise RuntimeError("Arm already connected")
        if not self.dry_run and not self.rig.get("hardware_verified"):
            raise RuntimeError("Rig is unmeasured: complete A3 and verify arm/rig.json before hardware use")
        self._frozen.clear()  # a stop arriving during connect must remain latched
        if self.rig["gripper_open"] == self.rig["gripper_closed"]:
            raise ValueError("Gripper endpoints must differ")
        if self._backend is None:
            side, wrist, port, robot_id, side_index, wrist_index = self._backend_args
            if self.dry_run:
                self._backend = SavedImageBackend(side, wrist)
            else:
                port = port or os.getenv("SO101_PORT")
                if not port:
                    raise RuntimeError("SO101_PORT is required")
                self._backend = LeRobotBackend(
                    port, robot_id or os.getenv("SO101_ROBOT_ID", "scrub_follower"),
                    side_index if side_index is not None else int(os.getenv("SO101_SIDE_CAMERA", "0")),
                    wrist_index if wrist_index is not None else int(os.getenv("SO101_WRIST_CAMERA", "1")))
        try:
            self._backend.connect()
            state = np.asarray(self._backend.read_joints(), dtype=float)
            self._validate_state(state)
        except Exception:
            self._backend.disconnect()
            raise
        self._state = state
        self._last_sent = state.copy()
        self._epoch = time.perf_counter()
        self._state_time = self._epoch
        self._shutdown.clear()
        self._error = None
        self.last_reason = "connected"
        self._thread = threading.Thread(target=self._playback, name="scrub-arm-30hz", daemon=True)
        self._thread.start()

    def _validate_state(self, row):
        if row.shape != (6,) or not np.isfinite(row).all() or not self.kin.valid(row[:5]) or not 0 <= row[5] <= 100:
            raise ValueError("Measured joints exceed configured limits or units")

    def _tick(self, now=None):
        return math.floor(((time.perf_counter() if now is None else now) - self._epoch) * HZ + 1e-7)

    def _ready(self):
        if self._thread is None or not self._thread.is_alive():
            raise RuntimeError("Arm is not connected")
        if self._error:
            raise RuntimeError(self._error)
        return not self._frozen.is_set()

    def joints(self):
        with self._lock:
            if self._state is None or time.perf_counter() - self._state_time > .1:
                raise RuntimeError("No fresh arm state")
            return self._state.copy()

    def _closed_fraction(self, raw):
        return float(np.clip((raw - self.rig["gripper_open"]) /
                             (self.rig["gripper_closed"] - self.rig["gripper_open"]), 0, 1))

    def _finish(self, reason, success=False):
        # Caller holds _lock. Never an I/O operation.
        self.last_reason = reason
        self._mode = "hold"
        self._motion = None
        self._timeline.clear()
        self._skill_success = success
        self._done.set()

    def _playback(self):
        next_tick = 0
        anchor = self._state.copy()
        still_since = time.perf_counter()
        while not self._shutdown.is_set():
            now = time.perf_counter()
            wait = self._epoch + next_tick / HZ - now
            if wait > 0 and self._shutdown.wait(wait):
                break
            tick = self._tick()
            if tick > next_tick:
                self.counters["overruns"] += tick - next_tick
            next_tick = tick + 1  # never burst old rows to catch up
            try:
                state = np.asarray(self._backend.read_joints(), dtype=float)
                self._validate_state(state)
                now = time.perf_counter()
                # Load is optional. A missing bus reading never becomes fake zero.
                if now - self._load_time >= .1:
                    try:
                        self._load = float(self._backend.read_load())
                        self._load_time = now
                    except Exception:
                        self._load = None
                with self._lock:
                    self._state, self._state_time = state, now
                    row = state.copy()
                    if self._frozen.is_set():
                        self._finish("frozen")
                    elif self._mode == "skill":
                        if now >= self._skill_deadline:
                            self._finish("max_s")
                        else:
                            if np.max(abs(state[:5] - anchor[:5])) > self.rig["still_joint_delta_deg"] or abs(state[5] - anchor[5]) > self.rig["still_gripper_delta"]:
                                anchor, still_since = state.copy(), now
                            if self._played and self._closed_fraction(state[5]) >= self.rig["grasp_closed_fraction"] and now - still_since >= self.rig["still_seconds"]:
                                self._finish("closed_and_still", True)
                            else:
                                row = self._timeline.command(tick, self._last_sent, state)
                                if self._timeline.active(tick) is not None:
                                    if not self._played:
                                        anchor, still_since = state.copy(), now
                                    self._played = True
                                else:
                                    self.counters["holds"] += 1
                    elif self._mode == "motion":
                        start, rows = self._motion
                        index = tick - start
                        if index >= len(rows):
                            # Remain on the final target until measured joints settle.
                            row = rows[-1]
                            if np.max(abs(state - row)) < 1.0:
                                self._finish("motion_complete", True)
                                row = state.copy()
                        elif index >= 0:
                            row = rows[index]
                    self._last_sent = row.copy()
                # Recheck after planning. freeze() never waits for this thread.
                if self._frozen.is_set():
                    row = state.copy()
                self._backend.send(row)
                self.counters["ticks"] += 1
            except Exception as error:
                # Never log external exception text, which could contain tokens.
                self._error = f"Arm playback failed ({type(error).__name__}); inspect hardware"
                self._frozen.set()
                with self._lock:
                    self._finish("playback_error")
                # No blind writes after losing valid feedback.
                break

    def _execute(self, rows):
        if not self._ready():
            return False
        with self._lock:
            self._done.clear()
            self._skill_success = False
            self._motion = (self._tick() + 1, rows)
            self._mode = "motion"
        deadline = time.perf_counter() + len(rows) / HZ + 3
        while not self._done.wait(.02):
            if time.perf_counter() >= deadline:
                self.freeze()
                return False
        return self._skill_success and not self._frozen.is_set()

    def move_to(self, x, y, z, speed=0.3):
        with self._operation:
            if not self._ready():
                return False
            return CartesianMotion(self.kin, self.joints, self._execute).move_to(x, y, z, speed)

    def _pose(self, name):
        pose = self.rig.get(name)
        if pose is None:
            raise RuntimeError(f"Measure and save the {name} pose in rig.json")
        start = self.joints()
        goal = np.asarray(pose, dtype=float).copy()
        if goal.shape != (6,):
            raise ValueError("Saved poses need six raw joint values")
        goal[5] = start[5]  # moving to a saved pose must never release a held tool
        return self._execute(self.kin.trajectory(start, goal))

    def go_home(self):
        with self._operation:
            if not self._ready() or not self._pose("home"):
                raise RuntimeError("Home motion stopped")

    def go_carry(self):
        with self._operation:
            if not self._ready() or not self._pose("carry"):
                raise RuntimeError("Carry motion stopped")

    def set_down_safe_spot(self):
        with self._operation:
            # Match the fake-arm contract: the controller emits set_down after
            # this call, without an extra open_gripper. Release only on arrival.
            if not self._ready() or not self._pose("safe_spot"):
                return False
            return self._open_gripper()

    def _open_gripper(self):
        if not self._ready():
            return False
        start = self.joints()
        goal = start.copy()
        goal[5] = self.rig["gripper_open"]
        return self._execute(self.kin.trajectory(start, goal))

    def open_gripper(self):
        with self._operation:
            if not self._open_gripper():
                raise RuntimeError("Gripper release stopped")

    def gripper_position(self):
        return self._closed_fraction(self.joints()[5])

    def gripper_load(self):
        if self._load is None or time.perf_counter() - self._load_time > .3:
            raise RuntimeError("Gripper load unavailable; use explicit got_it release")
        return self._load

    def _new_session(self, instruction):
        if self._session_factory:
            return self._session_factory(instruction)
        if self.dry_run:
            return DryPolicySession(instruction)
        if not self.deployment_id:
            raise RuntimeError("PERCEPTRON_DEPLOYMENT_ID is required")
        return PolicySession(self.deployment_id, instruction, self.rig.get("verified_contract_id"))

    def prepare(self, instructions):
        """Optional, blocking pre-open hook for a controller worker, not its event loop.

        No robot connection or motion is needed. Repeated preparation reuses good
        sessions, drops obsolete instructions, and never clears a freeze.
        """
        with self._operation:
            return self._sessions.prepare(instructions)

    def _get_session(self, instruction):
        self._session = self._sessions.get(instruction)
        return self._session

    def run_skill(self, instruction, max_s=20.0):
        if not instruction or not math.isfinite(max_s) or max_s <= 0:
            raise ValueError("Need an instruction and positive finite max_s")
        with self._operation:
            if not self._ready():
                return False
            deadline = time.perf_counter() + max_s
            session = self._get_session(instruction)
            sequence = 0
            with self._lock:
                self._timeline.clear()
                self._done.clear()
                self._played = False
                self._skill_success = False
                self._skill_deadline = deadline
                self._mode = "skill"
            next_capture = self._tick()
            try:
                # This caller is the inference thread; the only other control
                # thread is _playback. Synchronous predict => one in flight.
                while not self._done.is_set() and not self._frozen.is_set() and time.perf_counter() < deadline:
                    wait = self._epoch + next_capture / HZ - time.perf_counter()
                    if wait > 0 and self._done.wait(wait):
                        break
                    if self._frozen.is_set() or self._done.is_set():
                        break
                    images = self._backend.capture()
                    with self._lock:
                        tick = self._tick()
                        capture_time = self._epoch + tick / HZ
                        state = self._state.copy()
                        if time.perf_counter() - self._state_time > .1:
                            raise RuntimeError("Observation joints are stale")
                        rtc = self._timeline.rtc(tick, self._last_sent, state)
                        gap = bool(self._timeline.chunks) and rtc is None
                    if gap:
                        # Expired chunk: there is no legal prior_start_index.
                        # Reset histories while playback holds, then capture fresh.
                        session.reset()
                        sequence = 0
                        with self._lock:
                            self._timeline.clear()
                        next_capture = self._tick() + 1
                        continue
                    metadata = {"contract_id": session.contract_id,
                                "observation_id": f"scrub-{sequence}-{tick}",
                                "sequence": sequence, "timestamp_seconds": capture_time,
                                "state": state.tolist(), "image_encoding": "png",
                                "capture_age_ms": max(0, (time.perf_counter() - capture_time) * 1000),
                                "deadline_ms": 400.0}
                    if rtc is not None:
                        metadata["rtc"] = rtc
                    if self._frozen.is_set() or self._done.is_set() or time.perf_counter() >= deadline:
                        break
                    reply = session.predict(metadata, images)
                    arrival = time.perf_counter()
                    if self._done.is_set() or self._frozen.is_set() or arrival >= deadline:
                        break
                    with self._lock:
                        if self._mode != "skill" or self._frozen.is_set():
                            break
                        accepted = self._timeline.accept(reply, tick, arrival, capture_time, sequence, rtc)
                    self.counters["accepted" if accepted else "late"] += 1
                    sequence += 1
                    # Stay on the 15-row grid; missed slots are skipped, not burst.
                    next_capture = tick + STRIDE
                    if next_capture <= self._tick():
                        next_capture += ((self._tick() - next_capture) // STRIDE + 1) * STRIDE
            except Exception as error:
                self.last_reason = f"policy_error:{type(error).__name__}"
                self.freeze()
            finally:
                with self._lock:
                    success = self._skill_success and not self._frozen.is_set()
                    reason = self.last_reason if self._done.is_set() or self._frozen.is_set() else "max_s"
                    self._finish(reason, success)
                # Remote cleanup is never on the playback/stop path.
                try:
                    session.reset()
                except Exception:
                    self._sessions.discard(session)
                    self._session = None
            return success

    def freeze(self):
        self._frozen.set()
        self._done.set()

    def resume(self):
        """Explicit operator rearm, never automatic on the next motion call."""
        with self._operation:
            if self._error or self._thread is None or not self._thread.is_alive():
                raise RuntimeError("Reconnect after a playback failure")
            with self._lock:
                self._timeline.clear()
                self._motion = None
                self._mode = "hold"
                self._frozen.clear()

    def disconnect(self):
        self.freeze()
        with self._operation:
            self._shutdown.set()
            if self._thread:
                self._thread.join(timeout=2)
                if self._thread.is_alive():
                    raise RuntimeError("Motor I/O did not stop; inspect hardware before disconnecting")
                self._thread = None
            self._sessions.close()
            self._session = None
            if self._backend:
                self._backend.disconnect()
