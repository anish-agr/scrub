"""Controller-facing SO-101 interface. Blocking methods belong in worker threads.

Only the playback thread accesses the motor bus after connect. freeze() merely
sets an event and never waits for a network call, camera, bus, or mutex.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
import re
import threading
import time

import numpy as np
from dotenv import load_dotenv

from . import hardware, thermal
from .backends import LeRobotBackend, SavedImageBackend, port_holders
from .hardware import ArmFault
from .kinematics import JOINTS, Kinematics
from .motion import CartesianMotion
from .perceptron import APIError
from .sessions import DryPolicySession, PolicySession
from .session_pool import SessionPool
from .streaming import DELAY, HZ, STRIDE, Timeline

# Claw guard, in LeRobot gripper units (0..100), the same numbers explore/arm_session.py records with.
# Closing on something and not moving for GRIP_STALL_S: hold at the contact point plus GRIP_SQUEEZE
# instead of stalling the servo at its torque limit until it overheats or trips overload.
GRIP_STALL_S = 0.3
GRIP_MOVE = 1.0
GRIP_SQUEEZE = 1.5
GRIP_SETTLE = 3.0       # a jaw move counts as done this close to its goal (the calibrated ends are soft)
SETTLE_MAX_DEG = 5.0    # a move also counts as done this close to its goal once the joints stop moving:
SETTLE_STILL_DEG = 0.2  # the servos are P-only (LeRobot sets P 16, I 0), so a loaded joint stops short
SETTLE_STILL_S = 0.3
RELEASED_FRACTION = 0.15  # a put-back is done when the jaw that closed on the item is this open again and still
PREDICT_TRIES = 5       # consecutive failed predicts before a skill gives up and raises
REGRANT = (401, 404, 410)        # expired grant or robot session gone: fresh grant and session, once
RESTART = (409, 422)             # sequence, timestamp or prior chunk refused: reset the session history
TRANSIENT = (None, 429, 500, 502, 503, 504)  # hold and send a fresh frame
THERMAL_EVERY_S = 1.0   # temperatures and loads of all six motors, read by the playback thread
STATE_MARGIN_DEG = 5.0  # a measured joint may sit this far past the URDF limit (folded home: lift -102, elbow 98)
HOME_TOL_DEG = 5.0      # rest() skips the home move when every joint is this close to home
SHUT_FRACTION = 0.94    # jaw at least this closed is shut on nothing (6 of 100 units, hardware.GRIP_CLOSED_POS)


def _status(error):
    """HTTP status from an APIError ("Perceptron HTTP 503"), None for a transport failure."""
    m = re.search(r"HTTP (\d{3})", str(error))
    return int(m.group(1)) if m else None


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
        self._skill_return = False
        self._was_closed = False
        self._grip = {"ref": None, "since": 0.0, "hold": None}
        self._settle = {"anchor": None, "since": 0.0}
        self._gt = {}            # gripper torque level state (hardware.gripper_torque_want)
        self._resting = False    # torque off at home; playback writes nothing until wake()
        self._request = None     # "rest" or "wake", served by the playback thread (the bus owner)
        self._request_done = threading.Event()
        self._request_error = None
        self._telemetry = None
        self._thermal_t = 0.0
        self._cooling = None     # thermal.Cooling while a motor is (or was) at the trip temperature
        self._fault = None       # its ArmFault message
        self._trip = None        # set by playback when the trip stopped a skill or move; raised by the caller
        self.setting = None      # tray setting for taught skills (None: first match)
        self._speed_scale = 1.0  # grasp.SHARP_SPEED while a sharp is held (sharp_mode)
        # Joint limits in LeRobot degrees: the URDF's, tightened at connect by the calibrated range and
        # wrist_roll +-150. Every skill and move row is clamped to them.
        a, b = self.kin.from_urdf(self.kin.lower), self.kin.from_urdf(self.kin.upper)
        self._urdf_lo, self._urdf_hi = np.minimum(a, b), np.maximum(a, b)
        self._set_limits(None)
        self.last_reason = "not connected"
        self.counters = {"accepted": 0, "late": 0, "holds": 0, "ticks": 0, "overruns": 0, "api_errors": 0}

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
                self._clear_overload(port)
                # Camera ids: OpenCV indexes, or on the Mac name parts like "C920" (backends.camera_index).
                self._backend = LeRobotBackend(
                    port, robot_id or os.getenv("SO101_ROBOT_ID", "scrub_follower"),
                    side_index if side_index is not None else os.getenv("SO101_SIDE_CAMERA", "0"),
                    wrist_index if wrist_index is not None else os.getenv("SO101_WRIST_CAMERA", "1"))
        try:
            self._backend.connect()
            bus = self._bus()
            if bus is not None:
                hardware.retry_reads(bus)
                self._set_limits(hardware.joint_limits(bus) if getattr(bus, "calibration", None) else None)
                try:
                    hardware.set_dead_zone(bus)
                except Exception:  # noqa: BLE001 - the factory dead zone still works
                    pass
            state = np.asarray(self._backend.read_joints(), dtype=float)
            self._validate_state(state)
        except Exception:
            self._backend.disconnect()
            raise
        self._resting = False
        self._request = None
        self._state = state
        self._last_sent = state.copy()
        self._grip = {"ref": None, "since": 0.0, "hold": None}
        self._epoch = time.perf_counter()
        self._state_time = self._epoch
        self._shutdown.clear()
        self._error = None
        self.last_reason = "connected"
        self._thread = threading.Thread(target=self._playback, name="scrub-arm-30hz", daemon=True)
        self._thread.start()

    def _bus(self):
        """The LeRobot motor bus behind the backend (or a test's fake bus); None for saved images."""
        bus = getattr(self._backend, "bus", None)
        return bus if bus is not None else getattr(getattr(self._backend, "robot", None), "bus", None)

    @staticmethod
    def _clear_overload(port):
        """Before LeRobot opens the port: clear a stale overload flag (its start-up check would refuse the
        motor) and refuse a joint that sits past its range. Skipped while another process has the port."""
        if port_holders(port):
            return  # LeRobotBackend.connect refuses with the pid
        try:
            stuck = hardware.stuck_motors(port)
        except ImportError:
            return
        if stuck:
            raise RuntimeError("; ".join(stuck))

    def _set_limits(self, calibrated):
        lo = self._urdf_lo + .01
        hi = self._urdf_hi - .01
        for i, m in enumerate(JOINTS):
            if calibrated and m in calibrated:
                lo[i], hi[i] = max(lo[i], calibrated[m][0]), min(hi[i], calibrated[m][1])
        r = JOINTS.index("wrist_roll")
        lo[r], hi[r] = max(lo[r], -hardware.ROLL_LIMIT_DEG), min(hi[r], hardware.ROLL_LIMIT_DEG)
        grip = sorted((self.rig["gripper_open"], self.rig["gripper_closed"]))
        self._lo, self._hi = np.r_[lo, grip[0]], np.r_[hi, grip[1]]

    def _clamp(self, row):
        return np.clip(np.asarray(row, dtype=float), self._lo, self._hi)

    def _validate_state(self, row):
        if (row.shape != (6,) or not np.isfinite(row).all() or not 0 <= row[5] <= 100
                or np.any(row[:5] < self._urdf_lo - STATE_MARGIN_DEG) or np.any(row[:5] > self._urdf_hi + STATE_MARGIN_DEG)):
            raise ValueError("Measured joints exceed configured limits or units")

    def _tick(self, now=None):
        return math.floor(((time.perf_counter() if now is None else now) - self._epoch) * HZ + 1e-7)

    def _ready(self, hot_ok=False):
        if self._thread is None or not self._thread.is_alive():
            raise RuntimeError("Arm is not connected")
        if self._error:
            raise RuntimeError(self._error)
        if self._resting:
            raise RuntimeError("Arm is resting with torque off: wake() first")
        if self._cooling is not None and not hot_ok:
            raise ArmFault(self._fault)
        return not self._frozen.is_set()

    def joints(self):
        with self._lock:
            if self._state is None or time.perf_counter() - self._state_time > .1:
                raise RuntimeError("No fresh arm state")
            return self._state.copy()

    def _guard_grip(self, row, state, now):
        """Keep the jaw inside its configured range and never stall it squeezing (the policy, like the
        leader arm, commands "closed" past the contact point). Called with _lock held; no I/O."""
        row = np.array(row, dtype=float)
        lo, hi = sorted((self.rig["gripper_open"], self.rig["gripper_closed"]))
        row[5] = min(hi, max(lo, row[5]))
        d = 1.0 if self.rig["gripper_closed"] > self.rig["gripper_open"] else -1.0  # closing direction
        g, goal, pos = self._grip, row[5], state[5]
        if g["hold"] is not None:
            if (g["hold"] - goal) * d >= GRIP_SQUEEZE:  # told to open past the contact point: let go
                g["hold"], g["ref"] = None, None
            else:
                if (goal - g["hold"]) * d > 0:
                    row[5] = g["hold"]  # never tighter than the gentle hold
                return row
        if (goal - pos) * d > GRIP_SQUEEZE:  # told to close further than it is
            if g["ref"] is None or abs(pos - g["ref"]) > GRIP_MOVE:
                g["ref"], g["since"] = pos, now  # still closing
            elif now - g["since"] > GRIP_STALL_S:
                g["hold"] = min(hi, max(lo, pos + d * GRIP_SQUEEZE))
                row[5] = g["hold"]
        else:
            g["ref"] = None
        return row

    def _settled(self, state, rows, now):
        """Joints within a degree of the final target, or within SETTLE_MAX_DEG and no longer moving
        (P-only servos under gravity stop short); the jaw too, only if this move changes it."""
        goal, s = rows[-1], self._settle
        if s["anchor"] is None or np.max(abs(state[:5] - s["anchor"][:5])) > SETTLE_STILL_DEG:
            s["anchor"], s["since"] = state.copy(), now
        error = np.max(abs(state[:5] - goal[:5]))
        if error >= 1.0 and not (error < SETTLE_MAX_DEG and now - s["since"] >= SETTLE_STILL_S):
            return False
        # A jaw closing on an item never reaches its goal: the claw guard holding at contact counts as done.
        return (abs(rows[0][5] - goal[5]) <= GRIP_MOVE or abs(state[5] - goal[5]) < GRIP_SETTLE
                or self._grip["hold"] is not None)

    def _commanded_start(self):
        """Measured joints with the commanded jaw. A move starts where the arm is but keeps the grip
        it was told to hold: the measured jaw sits at the contact point, and commanding that lets go."""
        start = self.joints()
        with self._lock:
            start[5] = self._last_sent[5]
        return self._clamp(start)  # the folded home sits a little past the URDF limits

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
                if not self._resting:
                    self._validate_state(state)
                elif state.shape != (6,) or not np.isfinite(state).all():
                    raise ValueError("Bad joint reading")
                now = time.perf_counter()
                # Load is optional. A missing bus reading never becomes fake zero.
                if now - self._load_time >= .1:
                    try:
                        self._load = float(self._backend.read_load())
                        self._load_time = now
                    except Exception:
                        self._load = None
                bus = self._bus()
                sample = self._read_thermal(bus, now)
                if self._request is not None:
                    self._serve_request(bus, state)
                if self._resting:  # torque off: read, never write
                    with self._lock:
                        self._state, self._state_time = state, now
                        self._thermal_update(sample)
                    continue
                with self._lock:
                    self._state, self._state_time = state, now
                    tripped = self._thermal_update(sample)
                    # Hold means resend the last command. Sending the measured joints back would let
                    # the P-only servos sag under gravity every tick and the jaw relax its grip.
                    prev = self._last_sent.copy()
                    row = prev.copy()
                    if self._frozen.is_set():
                        self._finish("frozen")
                    elif tripped:
                        row = state.copy()  # stop where it is, keeping the commanded grip
                        row[5] = prev[5]
                    elif self._mode == "skill":
                        if now >= self._skill_deadline:
                            self._finish("max_s")
                        else:
                            if np.max(abs(state[:5] - anchor[:5])) > self.rig["still_joint_delta_deg"] or abs(state[5] - anchor[5]) > self.rig["still_gripper_delta"]:
                                anchor, still_since = state.copy(), now
                            closed = self._closed_fraction(state[5])
                            still = self._played and now - still_since >= self.rig["still_seconds"]
                            if closed >= self.rig["grasp_closed_fraction"]:
                                self._was_closed = True
                            if self._skill_return:
                                # A put-back grips the item, then lets go in its slot: closing alone is mid-skill.
                                done = still and self._was_closed and closed <= RELEASED_FRACTION
                            else:
                                done = still and closed >= self.rig["grasp_closed_fraction"]
                            if done:
                                self._finish("released_and_still" if self._skill_return else "closed_and_still", True)
                            else:
                                # From the clamped command: after wake() at the folded home the last command is
                                # the measured pose, past the URDF limits, and forward kinematics refuses it.
                                row = self._clamp(self._timeline.command(tick, self._clamp(self._last_sent)))
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
                            # Remain on the final target (and keep holding it after) until joints settle.
                            row = rows[-1]
                            if self._settled(state, rows, now):
                                self._finish("motion_complete", True)
                        elif index >= 0:
                            row = rows[index]
                    row = self._guard_grip(row, state, now)
                    self._last_sent = row.copy()
                    want = None if bus is None else hardware.gripper_torque_want(
                        self._gt, 100 * (1 - self._closed_fraction(state[5])), 100 * (1 - self._closed_fraction(row[5])),
                        self._grip["hold"] is not None, now)
                if want is not None:
                    hardware.set_gripper_torque(bus, self._gt, want)  # writes only when the level changes
                # Recheck after planning. freeze() never waits for this thread.
                if self._frozen.is_set():
                    row = prev
                    with self._lock:
                        self._last_sent = prev.copy()
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

    def _read_thermal(self, bus, now):
        """(temps, loads) every THERMAL_EVERY_S, None between samples or when the read fails."""
        if bus is None or now - self._thermal_t < THERMAL_EVERY_S:
            return None
        self._thermal_t = now
        try:
            return thermal.read_temps(bus), thermal.read_loads(bus)
        except Exception:  # noqa: BLE001 - a missed sample is not a fault; the next one counts
            return None

    def _thermal_update(self, sample):
        """Caller holds _lock. Starts or ends a cool-down; True when the trip stopped a skill or move."""
        if not sample:
            return False
        temps, loads = sample
        tripped = False
        if self._cooling is not None:
            if self._cooling.done(max(temps.values(), default=None)):
                self._cooling = self._fault = None
        elif thermal.too_hot(temps):
            self._cooling = thermal.Cooling()
            self._fault = thermal.fault_message(thermal.too_hot(temps))
            if self._mode in ("skill", "motion"):
                self._trip = self._fault
                self._finish("too_hot")
                tripped = True
        self._telemetry = thermal.telemetry(temps, loads, self._cooling is not None)
        return tripped

    def _serve_request(self, bus, state):
        """rest/wake on the playback thread, the only bus owner."""
        try:
            if self._request == "rest":
                if bus is not None:
                    hardware.rest(bus)
                with self._lock:
                    self._mode, self._motion = "hold", None
                    self._resting = True
            elif self._request == "wake":
                self._validate_state(state)  # moved by hand past its limits while limp: stay off
                if bus is not None:
                    hardware.wake(bus)
                with self._lock:
                    self._last_sent = state.copy()
                    self._grip = {"ref": None, "since": 0.0, "hold": None}
                    self._resting = False
        except Exception as error:  # noqa: BLE001 - handed to the caller of rest()/wake()
            self._request_error = error
        finally:
            self._request = None
            self._request_done.set()

    def _bus_request(self, name):
        self._request_error = None
        self._request_done.clear()
        self._request = name
        if not self._request_done.wait(2):
            self._request = None
            raise RuntimeError(f"Arm did not {name}: playback is not answering")
        if self._request_error is not None:
            raise RuntimeError(f"Arm {name} failed ({type(self._request_error).__name__}: {self._request_error})")

    def _take_trip(self):
        """After a skill or move: if the thermal trip stopped it, go safe and raise ArmFault."""
        with self._lock:
            message, self._trip = self._trip, None
            hold = self._grip["hold"]
            state = self._state.copy()
        if message is None:
            return
        closed = self._closed_fraction(state[5])
        holding = hold is not None or self.rig["grasp_closed_fraction"] <= closed < SHUT_FRACTION
        if not holding and self.rig.get("home") is not None and not self._frozen.is_set():
            try:
                self._pose("home", hot_ok=True)  # empty jaw: fold home to cool; never opens
            except Exception:  # noqa: BLE001 - holding where it stopped is safe too
                pass
        self.last_reason = "too_hot"
        raise ArmFault(message)

    def _slowed(self, rows, scale):
        """The same path in 1/scale times as many 30 Hz rows (scale < 1 slows every joint alike)."""
        if scale >= 1 or len(rows) == 0:
            return rows
        with self._lock:
            path = np.vstack([self._last_sent, rows])
        t = np.linspace(0, len(path) - 1, math.ceil(len(rows) / scale) + 1)[1:]
        return np.column_stack([np.interp(t, np.arange(len(path)), path[:, j]) for j in range(path.shape[1])])

    def _execute(self, rows, hot_ok=False, scale=None):
        if not self._ready(hot_ok):
            return False
        rows = self._slowed(np.asarray(rows, dtype=float), self._speed_scale if scale is None else scale)
        rows = np.array([self._clamp(r) for r in rows])
        with self._lock:
            self._done.clear()
            self._skill_success = False
            self._motion = (self._tick() + 1, rows)
            self._settle = {"anchor": None, "since": 0.0}
            self._mode = "motion"
        deadline = time.perf_counter() + len(rows) / HZ + 3
        timed_out = False
        while not self._done.wait(.02):
            if time.perf_counter() >= deadline:
                self.freeze()
                timed_out = True
                break
        self._take_trip()
        return not timed_out and self._skill_success and not self._frozen.is_set()

    def move_to(self, x, y, z, speed=0.3):
        with self._operation:
            if not self._ready():
                return False
            return CartesianMotion(self.kin, self._commanded_start, self._execute).move_to(x, y, z, speed)

    def _pose_goal(self, name):
        pose = self.rig.get(name)
        if pose is None:
            raise RuntimeError(f"Measure and save the {name} pose in rig.json")
        goal = np.asarray(pose, dtype=float).copy()
        if goal.shape != (6,):
            raise ValueError("Saved poses need six joint values (LeRobot degrees, gripper 0-100)")
        return self._clamp(goal)  # the folded home sits a little past the URDF limits; it settles there unpowered

    def _pose(self, name, hot_ok=False, scale=None):
        goal = self._pose_goal(name)
        start = self._commanded_start()
        goal[5] = start[5]  # moving to a saved pose must never release a held tool
        return self._execute(self.kin.trajectory(start, goal), hot_ok, scale)

    def go_home(self):
        with self._operation:  # allowed while cooling down: home is where it cools
            if not self._ready(hot_ok=True) or not self._pose("home", hot_ok=True):
                raise RuntimeError("Home motion stopped")

    def rest(self):
        """Be at home, then torque off on all six motors. Playback reads (joints, temperatures) but writes
        nothing until wake(). The folded home stays put unpowered (drift under 1 degree)."""
        with self._operation:
            if self._resting:
                return
            if not self._ready(hot_ok=True):
                raise RuntimeError("Arm is stopped")
            here, home = self.joints(), self._pose_goal("home")
            if np.max(abs(here[:5] - home[:5])) > HOME_TOL_DEG and not self._pose("home", hot_ok=True):
                raise RuntimeError("Home motion stopped")
            self._bus_request("rest")

    def wake(self):
        """Goal_Position := Present_Position on all six, then torque on. Nothing moves."""
        with self._operation:
            if self._resting:
                self._bus_request("wake")

    def telemetry(self):
        """{"temps", "loads", "hottest", "cooling", "t"} from the last bus sample, or None."""
        t = self._telemetry
        return None if t is None else {**t, "temps": dict(t["temps"]), "loads": dict(t["loads"])}

    def go_carry(self):
        with self._operation:
            if not self._ready() or not self._pose("carry"):
                raise RuntimeError("Carry motion stopped")

    def set_down_safe_spot(self):
        from . import grasp
        with self._operation:
            # Match the fake-arm contract: the controller emits set_down after
            # this call, without an extra open_gripper. Release only on arrival.
            # Allowed while cooling down: setting a sharp down is the safe thing to do with it.
            if not self._ready(hot_ok=True) or self._zone_path_blocked():
                return False
            if not self._pose("safe_spot", hot_ok=True, scale=min(self._speed_scale, grasp.SHARP_SPEED)):
                return False
            return self._open_gripper()

    def _zone_path_blocked(self):
        """True when the straight path from the tip to the safe zone center enters the handoff box."""
        from . import grasp
        zone, tip = self.rig.get("safe_zone"), self.tip()
        if not zone or tip is None:
            return False
        lo, hi = (np.asarray(self.rig["handoff_region"][k], dtype=float) for k in ("min", "max"))
        if grasp.path_enters_box(tip, zone["center"], lo, hi):
            self.last_reason = "safe_zone_path_crosses_handoff"
            return True
        return False

    def sharp_mode(self, on):
        """Slow every planned move (taught, ik, poses, move_to) to grasp.SHARP_SPEED while a sharp is held."""
        from . import grasp
        self._speed_scale = grasp.SHARP_SPEED if on else 1.0

    def hover_safe_spot(self):
        """Go 8 cm above the safe zone center (or the safe_spot pose's tip) and hold, at sharp speed."""
        from . import grasp
        with self._operation:
            if not self._ready(hot_ok=True) or self._zone_path_blocked():
                return False
            zone = self.rig.get("safe_zone")
            if zone:
                above = np.asarray(zone["center"], dtype=float) + (0, 0, .08)
            elif self.rig.get("safe_spot") is not None:
                above = self.kin.forward(self._pose_goal("safe_spot")[:5]) + (0, 0, .08)
            else:
                return False
            start = self._commanded_start()
            goal = self.kin.inverse(above, start[:5], require_region=False)
            if goal is None:
                self.last_reason = "safe_zone_unreachable"
                return False
            rows = self.kin.trajectory(start, self._clamp(np.r_[goal, start[5]]), .3)
            return self._execute(rows, hot_ok=True, scale=min(self._speed_scale, grasp.SHARP_SPEED))

    def safe_zone(self):
        return self.rig.get("safe_zone")

    def tip(self):
        """Gripper tip [x, y, z] in the arm base frame (FK of the clamped joints), or None."""
        try:
            return [float(v) for v in self.kin.forward(self._clamp(self.joints())[:5])]
        except (RuntimeError, ValueError):
            return None

    def wrist_jpeg(self):
        """The latest wrist camera frame as JPEG bytes, or None (no camera, no frame, no OpenCV)."""
        try:
            import cv2
            raw = (self._backend.capture() or {}).get("wrist")
            if raw is None:
                return None
            if isinstance(raw, (bytes, bytearray)):  # backends hand PNG bytes
                img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
            else:
                img = cv2.cvtColor(np.asarray(raw, dtype=np.uint8), cv2.COLOR_RGB2BGR)
            ok, buf = cv2.imencode(".jpg", img)
            return buf.tobytes() if ok else None
        except Exception:  # noqa: BLE001 - a missing frame is an answer: the controller skips the wrist check
            return None

    def _open_gripper(self):
        if not self._ready(hot_ok=True):
            return False
        start = self._commanded_start()
        goal = start.copy()
        goal[5] = self.rig["gripper_open"]
        return self._execute(self.kin.trajectory(start, goal), hot_ok=True)

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

    def taught_controls(self, deadline=None, max_speed=1.0):
        """goto, set_gripper, stopped for taught.play, through the same 30 Hz playback, trajectories
        (rig speed limits), joint clamp, claw guard and thermal trip as every other move. Caller holds
        _operation."""
        stopped = lambda: self._frozen.is_set() or (deadline is not None and time.perf_counter() >= deadline)  # noqa: E731

        def goto(joints, speed=0.3):
            if stopped():
                return False
            start = self._commanded_start()
            goal = start.copy()
            for i, name in enumerate(JOINTS):
                value = joints.get(name, joints.get(name + ".pos"))
                if value is not None:
                    goal[i] = float(value)
            goal = self._clamp(goal)
            goal[5] = start[5]  # a waypoint never changes the grip; set_gripper does
            return self._execute(self.kin.trajectory(start, goal, min(max(float(speed), .05), max_speed)))

        def set_gripper(fraction_closed):
            if stopped():
                return False
            start = self._commanded_start()
            goal = start.copy()
            f = min(1.0, max(0.0, float(fraction_closed)))
            goal[5] = self.rig["gripper_open"] + f * (self.rig["gripper_closed"] - self.rig["gripper_open"])
            return self._execute(self.kin.trajectory(start, self._clamp(goal), max_speed))

        return goto, set_gripper, stopped

    def _run_taught(self, instruction, max_s, source="taught", located=None):
        from . import grasp, taught
        parsed = taught.parse_instruction(instruction)
        if parsed is None:
            raise ValueError(f"Not a pick or return instruction: {instruction!r}")
        skill = None if source == "ik" else taught.load(*parsed, setting=self.setting)
        if skill is None and source != "ik":
            raise RuntimeError(f"No taught skill for {parsed[0]} {parsed[1]}: teach it with python -m arm.teach")
        with self._operation:
            if not self._ready():
                return False
            deadline = time.perf_counter() + max_s
            goto, set_gripper, stopped = self.taught_controls(deadline)
            if source == "taught":
                ok = bool(taught.play(skill, goto=goto, set_gripper=set_gripper, stopped=stopped))
            else:  # taught_adjusted / ik: same controls, so the same playback, clamp, claw guard, trip, stop
                ok = grasp.run(source, instruction, located, controls=(goto, set_gripper, stopped), kin=self.kin,
                               rig=self.rig, setting=self.setting, seed=self._commanded_start()[:5])
            ok = ok and not self._frozen.is_set()
            self.last_reason = ("taught_done" if ok else "frozen" if self._frozen.is_set()
                                else "max_s" if time.perf_counter() >= deadline else "taught_stopped")
            return ok

    def run_skill(self, instruction, max_s=20.0, source="model", located=None):
        """source: "model" (the deployment), "taught", "taught_adjusted" or "ik" (arm.grasp, using located)."""
        if not instruction or not math.isfinite(max_s) or max_s <= 0:
            raise ValueError("Need an instruction and positive finite max_s")
        if source in ("taught", "taught_adjusted", "ik"):
            return self._run_taught(instruction, max_s, source, located)
        if source != "model":
            raise ValueError(f"source must be model, taught, taught_adjusted or ik, got {source!r}")
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
                self._skill_return = instruction.startswith("return")
                self._was_closed = False
                self._skill_success = False
                self._skill_deadline = deadline
                self._mode = "skill"
            next_capture = self._tick()
            failures, regranted = 0, False
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
                        rtc = self._timeline.rtc(tick, self._clamp(self._last_sent))
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
                    try:
                        reply = session.predict(metadata, images)
                    except APIError as error:
                        # Playback holds meanwhile (no chunk covers now). Bounded by PREDICT_TRIES and max_s.
                        failures += 1
                        code = _status(error)
                        self.counters["api_errors"] += 1
                        if failures >= PREDICT_TRIES or code not in REGRANT + RESTART + TRANSIENT:
                            raise
                        if code in REGRANT:
                            if regranted:
                                raise
                            regranted = True
                            self._sessions.discard(session)
                            session = self._get_session(instruction)
                        elif code in RESTART:
                            session.reset()
                        if code in REGRANT + RESTART:
                            sequence = 0
                            with self._lock:
                                self._timeline.clear()  # no RTC history survives a new or reset session
                        else:
                            sequence += 1  # never resend a number the service may have seen
                        next_capture = self._tick() + 1
                        continue
                    failures = 0
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
            except APIError:
                # The controller turns this into an error event with the HTTP code (CONTRACTS: Arm).
                self.last_reason = "policy_api_error"
                self.freeze()
                raise
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
            self._take_trip()
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
