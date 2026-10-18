"""SimArm: the CONTRACTS Arm interface on a MuJoCo SO-101. Scripted pick stands in for the Isaac policy."""
import json
import re
import threading
import time
from pathlib import Path

import mujoco
import numpy as np

from arm import grasp
from sim import ik, scene

RIG = Path(__file__).parent.parent / "arm" / "rig.json"
NAMES = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
HOLD_ANGLE = 0.30  # jaw angle (rad) when squeezing an item
ABOVE_Z, PICK_Z = 0.12, 0.02
SOURCES = ("model", "taught", "taught_adjusted", "ik")
MISS_M = 0.02  # a pick misses when the item is farther than this from where the arm grips


class _Call:
    """One public call: aborted by freeze() (generation change) or by its deadline."""

    def __init__(self, arm, max_s=None):
        self.arm, self.gen = arm, arm._gen
        self.deadline = time.time() + max_s if max_s else None

    def alive(self):
        return self.arm._gen == self.gen and (self.deadline is None or time.time() < self.deadline)

    def sleep(self, s):
        end = time.time() + s
        while time.time() < end:
            if not self.alive():
                return False
            time.sleep(min(0.01, s))
        return self.alive()


class SimArm:
    def __init__(self, realtime=True):
        self.realtime = realtime
        self.lock = threading.RLock()
        self._gen = 0
        self._run = False
        self._thread = None
        self.holding = None
        self._pull_until = 0.0
        self.setting_override = None  # set by set_setting; layout.json is not touched
        self.zone = None              # safe zone override (rig.json shape); None: from layout safe_spot
        self._speed_scale = 1.0       # grasp.SHARP_SPEED while a sharp is held
        self._load()

    # ---- model -----------------------------------------------------------
    def _load(self):
        self.layout = scene.load_layout()
        if self.setting_override in self.layout["setting_items"]:
            self.layout["setting"] = self.setting_override
        self.rig = self._read_rig()
        path = scene.build(self.layout)
        with self.lock:
            self.model = mujoco.MjModel.from_xml_path(str(path))
            self.model.body_gravcomp[:] = 1.0  # position servos hold the pose; skip gravity sag
            self.data = mujoco.MjData(self.model)
            self.site = self.model.site("gripperframe").id
            self.holding = None
            self._mocap = {i: self.model.body_mocapid[self.model.body(f"item_{i}").id] for i in scene.ITEMS}
            self.data.qpos[:6] = self.data.ctrl[:6] = self._pose("home")
            self.data.qpos[5] = self.data.ctrl[5] = self.model.jnt_range[5][1]  # jaw open
            self.data.mocap_pos[self.model.body_mocapid[self.model.body("hand_zone").id]] = self.layout["hand_zone"]
            for i, mid in self._mocap.items():
                self.data.mocap_pos[mid] = scene.item_start(self.layout, i)
            mujoco.mj_forward(self.model, self.data)

    def reload(self):
        """Rebuild the scene from layout.json (after PUT /layout)."""
        self.freeze()
        self._load()

    def _read_rig(self):
        try:
            return json.loads(RIG.read_text())
        except (OSError, ValueError):
            return {}

    def _pose(self, name):
        # arm/rig.json poses are real-arm degrees in the real calibration; the sim's joint axes differ, so only layout.json poses apply
        p = self.layout["poses"].get(name)
        return np.array(p, float) if p else None

    @property
    def handoff_spot(self):
        """Where the controller hands over when no hand is tracked: the layout's hand zone (x, y, z, m)."""
        return [float(v) for v in self.layout["hand_zone"]]

    def _region(self):
        r = self.rig.get("handoff_region") or self.layout["handoff_region"]
        if "min" in r:
            return np.array(r["min"], float), np.array(r["max"], float)
        return (np.array([r[a][0] for a in "xyz"], float), np.array([r[a][1] for a in "xyz"], float))

    # ---- physics thread --------------------------------------------------
    def connect(self):
        if self._run:
            return
        self._run = True
        self._thread = threading.Thread(target=self._physics, daemon=True)
        self._thread.start()

    def disconnect(self):
        self.freeze()
        self._run = False
        if self._thread:
            self._thread.join(2)
            self._thread = None

    def _physics(self):
        t0, s0 = time.time(), None
        while self._run:
            with self.lock:
                if s0 is None:
                    s0 = self.data.time
                n = max(1, int((time.time() - t0 - (self.data.time - s0)) / self.model.opt.timestep)) if self.realtime else 10
                for _ in range(min(n, 50)):
                    mujoco.mj_step(self.model, self.data)
                    if self.holding and self.data.qpos[5] < HOLD_ANGLE:  # item blocks the jaw
                        self.data.qpos[5], self.data.qvel[5] = HOLD_ANGLE, 0.0
                if self.holding:
                    mid = self._mocap[self.holding]
                    self.data.mocap_pos[mid] = self.data.site_xpos[self.site]
                    mujoco.mju_mat2Quat(self.data.mocap_quat[mid], self.data.site_xmat[self.site])
            time.sleep(0.002)

    # ---- low level motion -----------------------------------------------
    def _q(self):
        with self.lock:
            return self.data.qpos[:6].copy()

    def _ctrl(self, q):
        with self.lock:
            self.data.ctrl[:5] = np.asarray(q, float)[:5]

    def _joint_move(self, call, goal, rate=1.2):
        """Straight line in joint space at `rate` rad/s (arm joints only)."""
        q0 = self._q()
        goal = np.array(goal, float)
        r = self.model.jnt_range[:5]  # a pose out of range (e.g. degrees read as radians) never means a 90 s move
        goal[:5] = np.clip(goal[:5], r[:, 0], r[:, 1])
        T = max(float(np.abs(goal[:5] - q0[:5]).max()) / (rate * self._speed_scale), 0.1)
        t0 = time.time()
        while (f := (time.time() - t0) / T) < 1:
            if not call.alive():
                return False
            self._ctrl(q0 + f * (goal - q0))
            time.sleep(0.02)
        self._ctrl(goal)
        return self._settle(call, goal)

    def _settle(self, call, goal, tol=0.03, timeout=1.5):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if not call.alive():
                return False
            if np.abs(self._q()[:5] - goal[:5]).max() < tol:
                return True
            time.sleep(0.02)
        return call.alive()

    def _cart_move(self, call, target, speed):
        """Straight Cartesian line, IK at 50 Hz, speed in m/s. False if unreachable or aborted."""
        target = np.asarray(target, float)
        q = self._q()
        ok, err, qgoal = ik.reachable(target, q)
        if not ok:
            return False
        p0 = ik.fk(q)[0]
        T = max(float(np.linalg.norm(target - p0)) / max(speed * self._speed_scale, 0.02), 0.1)
        t0 = time.time()
        while (f := (time.time() - t0) / T) < 1:
            if not call.alive():
                return False
            q, _ = ik.solve(p0 + f * (target - p0), q, iters=20)
            q[:5] = np.clip(q[:5], self._q()[:5] - 0.15, self._q()[:5] + 0.15)  # joint speed cap
            self._ctrl(q)
            time.sleep(0.02)
        self._ctrl(qgoal)
        return self._settle(call, qgoal)

    def _gripper(self, call, pos):
        """Command gripper to 0 (open) .. 1 (closed) and wait."""
        lo, hi = self.model.jnt_range[5]
        with self.lock:
            self.data.ctrl[5] = hi - pos * (hi - lo)
        return call.sleep(0.6)

    # ---- Arm interface ---------------------------------------------------
    def run_skill(self, instruction, max_s=20.0, source="model", located=None):
        """model: the scripted pick at the item's slot (or its moved spot). taught / taught_adjusted: the
        scripted pick at the tray slot (taught_adjusted shifted by located arm_offset); they close on nothing
        when the item is more than 2 cm off. ik: at located arm_xy, else the item's actual pose."""
        if source not in SOURCES:
            raise ValueError(f"source must be one of {', '.join(SOURCES)}, got {source!r}")
        self.last_source = source
        self.last_located = located
        call = _Call(self, max_s)
        m = re.match(r"\s*(pick|return)\s+(?:up\s+)?(?:the\s+|a\s+)?(.+?)\s*$", instruction.lower())
        if not m:
            return False
        verb, item = m.group(1), re.sub(r"[\s-]+", "_", m.group(2))  # "needle-nose pliers"
        if verb == "return":
            return self._return_held(call, item)
        if source != "model":
            target = self._grasp_target(item, source, located)
            if target is None or self.holding:
                return False
            return self._pick_at(call, item, target)
        slot = scene.slot_position(self.layout, item)
        if slot is None or self.holding or not self._at_slot(item, slot):
            return False
        return self._pick_at(call, item, slot)

    def _grasp_target(self, item, source, located):
        """Where a taught / taught_adjusted / ik pick grips (x, y), or None (not in this setting)."""
        slot = scene.tray_slot(self.layout, item)
        if slot is None:
            return None
        usable = grasp._usable(located) is None
        if source == "ik":
            if usable and located.get("arm_xy"):
                return [float(v) for v in located["arm_xy"][:2]]
            with self.lock:
                return [float(v) for v in self.data.mocap_pos[self._mocap[item]][:2]]
        off = located.get("arm_offset") if source == "taught_adjusted" and usable else None
        if off is not None and np.hypot(off[0], off[1]) <= grasp.MAX_SHIFT_M:
            return [slot[0] + float(off[0]), slot[1] + float(off[1])]
        return list(slot)

    def _pick_at(self, call, item, xy):
        """Top-down pick at xy. When the item is not within MISS_M the jaw closes on nothing (still True:
        the arm played the motion; gripper_position reads shut, as on the real arm)."""
        x, y = xy
        steps = [(x, y, ABOVE_Z), (x, y, PICK_Z)]
        there = self._at_slot(item, xy)
        if not (self._gripper(call, 0.0) and self._cart_move(call, steps[0], 0.25)
                and self._cart_move(call, steps[1], 0.12)):
            return False
        with self.lock:
            self.holding = item if there else None  # set before closing so the item stops the jaw
        if not self._gripper(call, 1.0):
            with self.lock:
                self.holding = None
            return False
        return self._cart_move(call, steps[0], 0.12)

    def set_setting(self, setting):
        """Show another setting's items (surgical or bench; any id in setting_items loads) without writing layout.json.
        Rebuilds the scene (items back in slots, arm home) unless it is already active."""
        if setting not in self.layout["setting_items"]:
            return False
        if self.layout["setting"] != setting:
            self.setting_override = setting
            self.reload()
        return True

    def set_item_pose(self, item, x, y, yaw=0.0):
        """Test bench: lay `item` on the table at (x, y) with `yaw`; picks then target that spot
        (cleared by reload() and when the item is placed). Returns (ok, why)."""
        if item not in self._mocap:
            return False, "unknown item"
        if item not in self.layout["setting_items"][self.layout["setting"]]:
            return False, "not in the current setting"
        if self.holding == item:
            return False, "the arm is holding it"
        for z in (ABOVE_Z, PICK_Z):
            ok, err, _ = ik.reachable([x, y, z])
            if not ok:
                return False, f"unreachable at z={z} (IK error {err * 100:.1f} cm)"
        with self.lock:
            mid = self._mocap[item]
            self.data.mocap_pos[mid] = (x, y, 0.01)
            self.data.mocap_quat[mid] = (np.cos(yaw / 2), 0, 0, np.sin(yaw / 2))
            self.layout.setdefault("_item_xy", {})[item] = [float(x), float(y)]
        return True, None

    def _at_slot(self, item, slot):
        with self.lock:
            p = self.data.mocap_pos[self._mocap[item]]
        return abs(p[0] - slot[0]) < MISS_M and abs(p[1] - slot[1]) < MISS_M and p[2] > 0

    def _place(self, call, xy):
        """Lower the held item at xy, release it there, lift."""
        x, y = xy
        if not (self._cart_move(call, (x, y, ABOVE_Z), 0.25) and self._cart_move(call, (x, y, PICK_Z + 0.01), 0.12)):
            return False
        item = self.holding
        with self.lock:
            self.holding = None
            if item:
                self.data.mocap_pos[self._mocap[item]] = (x, y, 0.01)
                self.layout.get("_item_xy", {}).pop(item, None)  # it is where we put it now
        return self._gripper(call, 0.0) and self._cart_move(call, (x, y, ABOVE_Z), 0.12)

    def _return_held(self, call, item):
        """Put `item` back in its tray slot: pick it from the return spot (or use the held one)."""
        slot = scene.tray_slot(self.layout, item)
        if slot is None:
            return False
        if self.holding and self.holding != item:
            return False
        if not self.holding:
            rx, ry = self.layout["return_spot"]
            with self.lock:
                p = self.data.mocap_pos[self._mocap[item]].copy()
            if not (np.hypot(p[0] - rx, p[1] - ry) < 0.03 and p[2] > 0):
                return False
            above, down = (p[0], p[1], ABOVE_Z), (p[0], p[1], PICK_Z)
            if not (self._gripper(call, 0.0) and self._cart_move(call, above, 0.25)
                    and self._cart_move(call, down, 0.12) and self._gripper(call, 1.0)):
                return False
            with self.lock:
                self.holding = item
            if not self._cart_move(call, above, 0.12):
                return False
        return self._place(call, slot)

    def go_home(self):
        return self._pose_move("home")

    def go_carry(self):
        return self._pose_move("carry")

    def _pose_move(self, name):
        call = _Call(self)
        q = self._pose(name)
        return self._joint_move(call, np.where(np.arange(6) == 5, self._q(), q))

    def move_to(self, x, y, z, speed=0.3):
        lo, hi = self._region()
        p = np.array([x, y, z], float)
        if np.any(p < lo) or np.any(p > hi):
            return False
        return self._cart_move(_Call(self), p, speed)

    def safe_zone(self):
        """The sim's safe zone: self.zone if a test set one, else a 8 cm square at layout safe_spot."""
        if self.zone:
            return self.zone
        x, y = self.layout["safe_spot"]
        return {"center": [float(x), float(y), 0.0], "size": [0.08, 0.08], "yaw_deg": 0.0}

    def _zone_path_blocked(self):
        lo, hi = self._region()
        return grasp.path_enters_box(self.tip(), self.safe_zone()["center"], lo, hi)

    def sharp_mode(self, on):
        self._speed_scale = grasp.SHARP_SPEED if on else 1.0

    def _sharp_speed(self, fn):
        old = self._speed_scale
        self._speed_scale = min(old, grasp.SHARP_SPEED)
        try:
            return fn()
        finally:
            self._speed_scale = old

    def hover_safe_spot(self):
        """Go above the safe zone and hold there, at sharp speed."""
        if self._zone_path_blocked():
            return False
        x, y = self.safe_zone()["center"][:2]
        return self._sharp_speed(lambda: self._cart_move(_Call(self), (x, y, ABOVE_Z), 0.25))

    def set_down_safe_spot(self):
        """Refuses (False) when the straight path to the zone enters the handoff box; sharp speed."""
        if self._zone_path_blocked():
            return False
        call = _Call(self)
        return self._sharp_speed(lambda: self._place(call, self.safe_zone()["center"][:2]))

    def wrist_jpeg(self):
        return None

    def open_gripper(self):
        self._gripper(_Call(self), 0.0)
        with self.lock:
            if self.holding:  # released over the table: the item drops straight down
                self.data.mocap_pos[self._mocap[self.holding]][2] = 0.01
                self.holding = None

    def gripper_position(self):
        lo, hi = self.model.jnt_range[5]
        with self.lock:
            return float(np.clip((hi - self.data.qpos[5]) / (hi - lo), 0, 1))

    def gripper_load(self):
        with self.lock:
            extra = 1.0 if time.time() < self._pull_until else 0.0
            return float(abs(self.data.actuator_force[5])) + extra

    def telemetry(self):
        """Plausible numbers for the ops page: actuator force as load, temperature a flat 30 C plus a little per N."""
        with self.lock:
            f = [float(abs(v)) for v in self.data.actuator_force[:6]]
        temps = {n: round(30.0 + min(f[i], 10.0), 1) for i, n in enumerate(NAMES)}
        return {"temps": temps, "loads": {n: round(f[i], 2) for i, n in enumerate(NAMES)},
                "hottest": max(temps.values()), "cooling": bool(getattr(self, "resting", False)), "t": time.time()}

    def pull(self):
        """Test hook: simulate the clinician tugging the item for half a second."""
        self._pull_until = time.time() + 0.5

    def rest(self):
        """Parked at home with torque off between commands (the real arm cools; the sim just notes it)."""
        self.resting = True

    def wake(self):
        self.resting = False

    def freeze(self):
        self._gen += 1
        with self.lock:
            self.data.ctrl[:5] = self.data.qpos[:5]

    # ---- for the server --------------------------------------------------
    def state(self):
        shown = self.layout["setting_items"].get(self.layout["setting"], [])
        with self.lock:
            q = [float(v) for v in self.data.qpos[:6]]
            items = {i: [round(float(v), 4) for v in self.data.mocap_pos[self._mocap[i]]] for i in shown if i in self._mocap}
        # items: where each item of the current setting is (m, base frame), so the viewer draws what the sim does
        return {"q": q, "names": NAMES, "gripper": self.gripper_position(), "holding": self.holding, "items": items}

    def pose(self):
        """Joint angles plus every mocap body (items, hand) for an offline renderer (video/simcine.py)."""
        with self.lock:
            bodies = {}
            for i in range(self.model.nbody):
                mid = self.model.body_mocapid[i]
                if mid >= 0:
                    bodies[self.model.body(i).name] = [float(v) for v in (*self.data.mocap_pos[mid], *self.data.mocap_quat[mid])]
            return {"t": time.time(), "qpos": [float(v) for v in self.data.qpos[:6]], "mocap": bodies,
                    "holding": self.holding, "setting": self.layout["setting"]}

    def tip(self):
        with self.lock:
            return self.data.site_xpos[self.site].copy()
