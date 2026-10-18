"""Smart pick: taught waypoints shifted by vision, a top-down IK grasp, the grasp check and the sharps rules.

Pure functions (no bus, camera or network). The arms run the skill dicts made here through taught.play,
so every method gets the same 30 Hz playback, joint clamp, claw guard, thermal trip and stop.

Methods (run_skill source): "taught" (plain waypoints), "taught_adjusted" (at-slot waypoints shifted by the
located offset), "ik" (approach above, descend, close, lift from the located arm_xy). "model" is the arm's own.
Located pose: see SPEC / vision/locate.py ({"arm_offset", "offset_mm", "yaw_deg", "arm_xy", "confidence", ...}).

Rig keys read (all optional): grasp_z (m, table grasp height in the base frame, default GRASP_Z),
offset_mm_to_lateral ([a, b]: lateral mm toward arm +y = a*dx + b*dy, default [-1, 0]: the overhead
image's +x is the arm's -y), yaw_to_roll_sign (default 1), carry, home, handoff_region, safe_zone.
"""
from __future__ import annotations

import copy
import math

import numpy as np

from .kinematics import JOINTS

SHARP_SPEED = 0.5        # speed scale while a sharp is held
HAND_KEEPOUT_M = 0.20    # no closer than this to the tracked hand with a sharp
ZONE_MIN_DIST_M = 0.15   # safe zone center at least this far (horizontal) from the handoff box
MIN_CONFIDENCE = 0.3     # located poses below this are ignored
MAX_SHIFT_M = 0.04       # a bigger located shift means the located pose is wrong
MAX_YAW_DEG = 90.0
GRASP_Z = 0.02           # default grasp height above the base plane (m)
GRASP_CLOSED = 0.3       # a jaw closed less than this did not close on anything (rig grasp_closed_fraction)
METHODS = ("model", "taught", "taught_adjusted", "ik")
NOT_AT_SLOT = {"carry", "home"}  # same as taught.NOT_AT_SLOT


def _roll_limit():
    from .hardware import ROLL_LIMIT_DEG  # plain constants; no bus import
    return ROLL_LIMIT_DEG


def _row(joints):
    return [float(joints[n]) for n in JOINTS]


def _usable(located):
    """None when the located pose may be used, else why not."""
    if not located:
        return "no located pose"
    if located.get("found") is False:
        return "item not found"
    if float(located.get("confidence") or 0.0) < MIN_CONFIDENCE:
        return f"low confidence {float(located.get('confidence') or 0.0):.2f}"
    return None


def _pan_per_deg(kin, row):
    """Change of the tip's azimuth (deg) per degree of shoulder_pan at row (sign follows the rig)."""
    out = []
    for d in (-0.5, 0.5):
        r = list(row)
        r[0] += d
        try:
            p = kin.forward(r)
        except ValueError:
            return None
        out.append(math.degrees(math.atan2(p[1], p[0])))
    rate = (out[1] - out[0]) / 1.0
    return rate if abs(rate) > 1e-6 else None


def _nudge_pan(kin, row, dangle_deg):
    """row with shoulder_pan turned so the tip's azimuth changes by dangle_deg; None if it cannot."""
    rate = _pan_per_deg(kin, row)
    if rate is None:
        return None
    r = list(row)
    r[0] += dangle_deg / rate
    return r


def _roll(row, yaw_deg, sign):
    r = list(row)
    yaw = max(-MAX_YAW_DEG, min(MAX_YAW_DEG, float(yaw_deg)))
    lim = _roll_limit()
    r[4] = max(-lim, min(lim, r[4] + sign * yaw))
    return r


def adjust_taught(skill, located, kin) -> dict:
    """A copy of skill with the at-slot waypoints (not carry/home) moved onto the located item.

    arm_offset (m, base frame): FK tip + offset, IK seeded with the waypoint (shoulder_pan nudge if IK fails).
    offset_mm only (no calibration): shoulder_pan nudge for the lateral mm at the waypoint's tip radius.
    yaw_deg: added to wrist_roll (yaw clamped to +-90, roll to +-ROLL_LIMIT_DEG).
    The copy carries "adjust": {"applied": bool, "why": str, "shift_m": float}.
    """
    out = copy.deepcopy(skill)

    def done(applied, why, shift=0.0):
        out["adjust"] = {"applied": applied, "why": why, "shift_m": round(float(shift), 4)}
        return out

    why = _usable(located)
    if why:
        return done(False, why)
    rig = kin.rig
    arm_offset = located.get("arm_offset")
    mm = located.get("offset_mm")
    yaw = located.get("yaw_deg")
    if arm_offset is not None:
        d = np.array([float(arm_offset[0]), float(arm_offset[1]), 0.0])
        shift = float(np.hypot(d[0], d[1]))
    elif mm is not None:
        a, b = rig.get("offset_mm_to_lateral") or (-1.0, 0.0)
        lateral_m = (a * float(mm[0]) + b * float(mm[1])) / 1000.0
        shift = float(np.hypot(float(mm[0]), float(mm[1]))) / 1000.0
    else:
        shift = 0.0
    if shift > MAX_SHIFT_M:
        return done(False, f"located shift {shift * 100:.1f} cm is over {MAX_SHIFT_M * 100:.0f} cm: located pose looks wrong", shift)
    if shift == 0.0 and yaw is None:
        return done(False, "located pose has no offset or yaw")
    sign = float(rig.get("yaw_to_roll_sign", 1))
    for wp in out.get("waypoints") or []:
        if wp.get("name") in NOT_AT_SLOT:
            continue
        row = _row(wp["joints"])
        try:
            tip = kin.forward(row)
        except ValueError:
            return done(False, f"waypoint {wp.get('name')} is outside the joint limits", shift)
        # Roll first: IK keeps the seed's roll, so the shifted tip lands on target with the new roll.
        new = _roll(row, yaw, sign) if yaw is not None else row
        if shift > 0:
            if arm_offset is not None:
                target = tip + d
                q = kin.inverse(target, new, require_region=False) if kin.valid(new) else None
                if q is not None:
                    new = [float(v) for v in q]
                else:
                    da = math.degrees(math.atan2(target[1], target[0]) - math.atan2(tip[1], tip[0]))
                    new = _nudge_pan(kin, new, da)
            else:
                radius = float(np.hypot(tip[0], tip[1]))
                new = _nudge_pan(kin, new, math.degrees(lateral_m / radius)) if radius > 0.02 else None
            if new is None:
                return done(False, f"could not shift waypoint {wp.get('name')}", shift)
        if not kin.valid(new):
            return done(False, f"shifted waypoint {wp.get('name')} is outside the joint limits", shift)
        wp["joints"] = {n: float(v) for n, v in zip(JOINTS, new)}
    return done(True, "shifted by " + ("arm_offset" if arm_offset is not None else "offset_mm" if mm is not None else "yaw only"), shift)


def _seed(kin, rig, seed):
    if seed is None:
        seed = rig.get("carry") or rig.get("home") or [0.0] * 5
    if isinstance(seed, dict):
        seed = _row(seed)
    lo, hi = np.sort(np.vstack([kin.from_urdf(kin.lower), kin.from_urdf(kin.upper)]), axis=0)
    return np.clip(np.asarray(list(seed)[:5], dtype=float), lo + 0.01, hi - 0.01)


def plan_ik(located, kin, rig, *, direction="pick", approach_m=0.06, grasp_z=None, seed=None) -> dict | None:
    """A top-down grasp as a taught skill dict (taught.play runs it), or None when it cannot be planned.

    pick: approach above (open), descend, grip (close), lift, carry (rig carry pose if set).
    return: approach above the slot, descend, open, lift.
    Needs located["arm_xy"]; wrist_roll from yaw_deg; every waypoint must pass kin.valid.
    """
    if _usable(located) or not located.get("arm_xy"):
        return None
    if direction not in ("pick", "return"):
        return None
    x, y = (float(v) for v in located["arm_xy"][:2])
    z = float(rig.get("grasp_z", GRASP_Z) if grasp_z is None else grasp_z)
    q = _seed(kin, rig, seed)
    if located.get("yaw_deg") is not None:
        q = np.asarray(_roll(list(q), located["yaw_deg"], float(rig.get("yaw_to_roll_sign", 1))))
    above = kin.inverse([x, y, z + approach_m], q, require_region=False)
    down = None if above is None else kin.inverse([x, y, z], above, require_region=False)
    if above is None or down is None:
        return None
    above, down = [float(v) for v in above], [float(v) for v in down]
    j = lambda row: {n: float(v) for n, v in zip(JOINTS, row)}  # noqa: E731
    if direction == "pick":
        wps = [{"name": "approach", "joints": j(above), "gripper": 0.0, "speed": 0.3},
               {"name": "descend", "joints": j(down), "gripper": None, "speed": 0.15},
               {"name": "grip", "joints": j(down), "gripper": 1.0, "speed": 0.15},
               {"name": "lift", "joints": j(above), "gripper": None, "speed": 0.2}]
        if rig.get("carry"):
            wps.append({"name": "carry", "joints": j(list(rig["carry"])[:5]), "gripper": None, "speed": 0.3})
    else:
        wps = [{"name": "approach", "joints": j(above), "gripper": None, "speed": 0.3},
               {"name": "descend", "joints": j(down), "gripper": None, "speed": 0.15},
               {"name": "release", "joints": j(down), "gripper": 0.0, "speed": 0.15},
               {"name": "lift", "joints": j(above), "gripper": None, "speed": 0.2}]
    if not all(kin.valid(_row(w["joints"])) for w in wps):
        return None
    return {"item": located.get("item"), "direction": direction, "setting": None, "taught_at": "ik",
            "source": "ik", "waypoints": wps}


def run(method, instruction, located, *, controls, kin, rig, setting, seed=None, report=None) -> bool:
    """Run one pick or return by method "taught", "taught_adjusted" or "ik" through controls
    (goto, set_gripper, stopped) as made by Arm.taught_controls. report (a dict) gets "why".
    Raises ValueError for a bad instruction or method, RuntimeError when the taught skill is missing."""
    from . import taught

    report = report if report is not None else {}
    if method not in ("taught", "taught_adjusted", "ik"):
        raise ValueError(f"grasp.run method must be taught, taught_adjusted or ik, got {method!r}")
    parsed = taught.parse_instruction(instruction)
    if parsed is None:
        raise ValueError(f"Not a pick or return instruction: {instruction!r}")
    goto, set_gripper, stopped = controls
    if method == "ik":
        skill = plan_ik(located, kin, rig, direction=parsed[1], seed=seed)
        if skill is None:
            report["why"] = "ik: no located arm_xy or no valid plan"
            return False
        report["why"] = "ik plan"
    else:
        skill = taught.load(*parsed, setting=setting)
        if skill is None:
            raise RuntimeError(f"No taught skill for {parsed[0]} {parsed[1]}: teach it with python -m arm.teach")
        if method == "taught_adjusted":
            skill = adjust_taught(skill, located, kin)
            report["why"] = skill["adjust"]["why"]
    return bool(taught.play(skill, goto=goto, set_gripper=set_gripper, stopped=stopped))


def gripper_says(position, load, closed_fraction=0.94) -> str:
    """"held", "empty" or "unknown" from the jaw (fraction closed 0..1). Shut at or past closed_fraction
    means it closed on nothing. Load is reported by some arms but its units vary; it never overrides
    the jaw, and with no jaw reading the answer is "unknown"."""
    try:
        p = float(position)
    except (TypeError, ValueError):
        return "unknown"
    if not math.isfinite(p):
        return "unknown"
    if p >= closed_fraction:
        return "empty"
    if p >= GRASP_CLOSED:
        return "held"
    return "unknown"  # never closed: the camera has to say


def _box(region):
    return np.asarray(region["min"], dtype=float), np.asarray(region["max"], dtype=float)


def zone_box_xy(zone):
    """(lo, hi) xy of the zone's axis-aligned bounds (a yawed square's bounding box)."""
    c = np.asarray(zone["center"], dtype=float)[:2]
    sx, sy = (float(v) / 2 for v in zone["size"][:2])
    t = math.radians(float(zone.get("yaw_deg") or 0.0))
    ex = abs(sx * math.cos(t)) + abs(sy * math.sin(t))
    ey = abs(sx * math.sin(t)) + abs(sy * math.cos(t))
    return c - (ex, ey), c + (ex, ey)


def safe_zone_problems(rig) -> list:
    """Problems with rig["safe_zone"] as sentences; [] when ok."""
    zone = rig.get("safe_zone")
    if not zone:
        return ["no safe_zone in rig.json: teach it with python -m arm.teach (key s)"]
    try:
        center = np.asarray(zone["center"], dtype=float)
        size = np.asarray(zone["size"], dtype=float)
        if center.shape != (3,) or size.shape != (2,) or not np.isfinite(center).all() or np.any(size <= 0):
            raise ValueError
        lo_z, hi_z = zone_box_xy(zone)
    except (KeyError, TypeError, ValueError):
        return ["safe_zone needs center [x, y, z] and size [sx, sy] in meters"]
    region = rig.get("handoff_region")
    if not region:
        return []
    lo, hi = _box(region)
    gap = np.maximum(0.0, np.maximum(lo[:2] - center[:2], center[:2] - hi[:2]))
    problems = []
    dist = float(np.hypot(*gap))
    if dist < ZONE_MIN_DIST_M:
        problems.append(f"safe zone center is {dist * 100:.0f} cm from the handoff box; needs {ZONE_MIN_DIST_M * 100:.0f} cm")
    if np.all(lo_z < hi[:2]) and np.all(hi_z > lo[:2]):
        problems.append("safe zone overlaps the handoff box")
    return problems


def segment_crosses_box(a, b, box_min, box_max) -> bool:
    """True when the straight segment a->b (xyz) touches the box (an endpoint inside counts)."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    lo, hi = np.asarray(box_min, dtype=float), np.asarray(box_max, dtype=float)
    t0, t1 = 0.0, 1.0
    d = b - a
    for i in range(len(a)):
        if abs(d[i]) < 1e-12:
            if a[i] < lo[i] or a[i] > hi[i]:
                return False
            continue
        u, v = (lo[i] - a[i]) / d[i], (hi[i] - a[i]) / d[i]
        t0, t1 = max(t0, min(u, v)), min(t1, max(u, v))
        if t0 > t1:
            return False
    return True


def path_enters_box(start, end, box_min, box_max) -> bool:
    """The set-down rule: the straight path start->end enters the handoff box. A start already inside the
    box is leaving it, not crossing (a carry pose sits in the box)."""
    s = np.asarray(start, dtype=float)
    inside = bool(np.all(s >= box_min) and np.all(s <= box_max))
    return not inside and segment_crosses_box(start, end, box_min, box_max)
