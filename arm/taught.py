"""Taught skills: hand-taught joint waypoints per item and direction, the labeled backup to the model.

A skill file is arm/skills/<setting>/<item>-<direction>.json:
  {"item", "direction": "pick"|"return", "setting", "taught_at",
   "waypoints": [{"name", "joints": {shoulder_pan: deg, ...}, "gripper": fraction_closed or null, "speed": 0..1}],
   "slot_offset_ref": optional}
Pick: approach above the slot, descend, close, lift to carry. Return: carry, descend over the slot, open, lift, home.

Check: python -m arm.taught --check [--setting surgical] [--fake]
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import sys

from .kinematics import JOINTS, Kinematics

SKILLS_DIR = Path(__file__).with_name("skills")
SETTINGS_DIR = Path(__file__).resolve().parents[1] / "settings"
DIRECTIONS = ("pick", "return")
NOT_AT_SLOT = {"carry", "home"}  # waypoint names the slot offset never shifts
CHECK_SPEED = 0.15  # replay speed cap for --check, a fraction of the rig's joint speed limit


def skill_path(setting, item, direction, root=None) -> Path:
    if direction not in DIRECTIONS:
        raise ValueError(f"direction must be pick or return, got {direction!r}")
    return Path(root or SKILLS_DIR) / setting / f"{item}-{direction}.json"


def _settings(root=None):
    # Example skills are for tests; they are only used when asked for by name.
    base = Path(root or SKILLS_DIR)
    return sorted(p.name for p in base.iterdir() if p.is_dir() and not p.name.startswith("example")) if base.is_dir() else []


def load(item, direction, setting=None, root=None) -> dict | None:
    """The skill dict, or None when it is not taught or the file is unreadable."""
    for name in [setting] if setting else _settings(root):
        path = skill_path(name, item, direction, root)
        if path.is_file():
            try:
                return json.loads(path.read_text())
            except (OSError, ValueError):
                return None
    return None


def available(setting=None, root=None) -> dict:
    """{item: {"pick", "return"}} for every skill file found."""
    found = {}
    for name in [setting] if setting else _settings(root):
        for path in sorted((Path(root or SKILLS_DIR) / name).glob("*.json")):
            item, _, direction = path.stem.rpartition("-")
            if item and direction in DIRECTIONS:
                found.setdefault(item, set()).add(direction)
    return found


def _instructions():
    """{instruction text: item id} from settings/*.json (the strings the controller sends to run_skill)."""
    table = {}
    for path in sorted(SETTINGS_DIR.glob("*.json")):
        if path.name.endswith(".local.json"):
            continue
        try:
            items = json.loads(path.read_text()).get("items") or []
        except (OSError, ValueError):
            continue
        for it in items:
            for key in ("pick_instruction", "return_instruction"):
                if it.get(key) and it.get("id"):
                    table[it[key].strip().lower()] = it["id"]
    return table


def parse_instruction(instruction) -> tuple | None:
    """'pick the hemostat' -> ("hemostat", "pick"); 'return the mayo scissors' -> ("mayo_scissors", "return")."""
    text = " ".join(str(instruction or "").lower().split())
    match = re.fullmatch(r"(pick|return)(?: up)?(?: the)? (.+)", text)
    if not match:
        return None
    item = _instructions().get(text) or re.sub(r"[^a-z0-9]+", "_", match.group(2)).strip("_")
    return (item, match.group(1)) if item else None


def _shifted(joints, offset):
    if offset is None:
        return joints
    nudge = {"shoulder_pan": float(offset)} if isinstance(offset, (int, float)) else offset
    return {k: v + float(nudge.get(k, 0.0)) for k, v in joints.items()}


def play(skill, *, goto, set_gripper, stopped, offset=None) -> bool:
    """Play waypoints in order. goto(joints_deg, speed) blocks until reached; False on stop or fault.

    offset: optional slot correction from calibrated vision, computed by the caller. A number is a
    shoulder_pan nudge in degrees; a dict is {joint: degrees}. It shifts every waypoint except those
    named carry or home (the at-slot ones: approach, descend, grip, lift). Off (None) by default.
    """
    for wp in skill.get("waypoints") or []:
        if stopped():
            return False
        joints = {k: float(v) for k, v in wp["joints"].items()}
        if wp.get("name") not in NOT_AT_SLOT:
            joints = _shifted(joints, offset)
        if not goto(joints, float(wp.get("speed", 0.3))) or stopped():
            return False
        if wp.get("gripper") is not None and (not set_gripper(float(wp["gripper"])) or stopped()):
            return False
    return True


def validate(skill, kin=None, grasp=0.3) -> list:
    """Problems with a skill as plain sentences; [] means it passes."""
    kin = kin or Kinematics()
    problems = []
    if skill.get("direction") not in DIRECTIONS:
        problems.append("direction must be pick or return")
    if not skill.get("item"):
        problems.append("item is missing")
    waypoints = skill.get("waypoints") or []
    if len(waypoints) < 3:
        problems.append(f"needs at least 3 waypoints, has {len(waypoints)}")
    for i, wp in enumerate(waypoints, 1):
        joints = wp.get("joints") or {}
        if set(joints) != set(JOINTS):
            problems.append(f"waypoint {i}: joints must be exactly {', '.join(JOINTS)}")
            continue
        row = [joints[n] for n in JOINTS]
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in row) or not kin.valid(row):
            problems.append(f"waypoint {i}: joints outside limits")
        g = wp.get("gripper")
        if g is not None and not (isinstance(g, (int, float)) and 0 <= g <= 1):
            problems.append(f"waypoint {i}: gripper must be null or 0..1")
        s = wp.get("speed", 0.3)
        if not (isinstance(s, (int, float)) and 0 < s <= 1):
            problems.append(f"waypoint {i}: speed must be in (0, 1]")
    grips = [wp.get("gripper") for wp in waypoints if isinstance(wp.get("gripper"), (int, float))]
    if skill.get("direction") == "pick" and not any(g >= grasp for g in grips):
        problems.append(f"pick never closes the gripper (needs a waypoint with gripper >= {grasp})")
    if skill.get("direction") == "return" and not any(g <= 0.1 for g in grips):
        problems.append("return never opens the gripper (needs a waypoint with gripper <= 0.1)")
    return problems


def arm_controls(arm, max_speed=1.0):
    """goto, set_gripper, stopped for a connected arm.real_arm.Arm, through its guarded 30 Hz playback."""
    import numpy as np

    def goto(joints, speed):
        start = arm._commanded_start()
        goal = start.copy()
        goal[:5] = [joints[n] for n in JOINTS]
        return arm._execute(arm.kin.trajectory(start, goal, min(speed, max_speed)))

    def set_gripper(fraction):
        start = arm._commanded_start()
        goal = start.copy()
        goal[5] = float(np.clip(arm.rig["gripper_open"] + fraction * (arm.rig["gripper_closed"] - arm.rig["gripper_open"]), 0, 100))
        return arm._execute(arm.kin.trajectory(start, goal, max_speed))

    return goto, set_gripper, arm._frozen.is_set


def _items(setting):
    path = SETTINGS_DIR / f"{setting}.json"
    try:
        return [it["id"] for it in json.loads(path.read_text()).get("items") or []]
    except (OSError, ValueError, KeyError):
        return []


def check(setting="surgical", *, root=None, kin=None, arm=None, write=print) -> bool:
    """List, validate and replay every skill for a setting. Real replay needs a connected arm and no instrument."""
    kin = kin or Kinematics()
    have = available(setting, root)
    items = _items(setting) or sorted(have)
    ok = bool(have)
    if not have:
        write(f"setting {setting}: no skills taught yet")
    write(f"setting {setting}: skills in {Path(root or SKILLS_DIR) / setting}")
    for item in items + sorted(set(have) - set(items)):
        for direction in DIRECTIONS:
            if direction not in have.get(item, set()):
                write(f"  {item} {direction}: not taught")
                continue
            skill = load(item, direction, setting, root)
            problems = ["file is not valid JSON"] if skill is None else validate(skill, kin, kin.rig.get("grasp_closed_fraction", 0.3))
            if problems:
                ok = False
                write(f"  {item} {direction}: FAIL " + "; ".join(problems))
                continue
            if arm is None:
                calls = []
                played = play(skill, goto=lambda j, s: calls.append(("goto", j, s)) or True,
                              set_gripper=lambda g: calls.append(("gripper", g)) or True, stopped=lambda: False)
                write(f"  {item} {direction}: ok, {len(skill['waypoints'])} waypoints, dry playback {len(calls)} steps")
            else:
                goto, set_gripper, stopped = arm_controls(arm, CHECK_SPEED)
                arm.go_home()
                played = play(skill, goto=goto, set_gripper=set_gripper, stopped=stopped)
                write(f"  {item} {direction}: {'ok' if played else 'FAIL'}, replayed at speed {CHECK_SPEED} with no instrument")
            ok = ok and played
    return ok


def main(argv=None):
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    parser = argparse.ArgumentParser(description="Validate taught skills and replay them slowly with no instrument.")
    parser.add_argument("--check", action="store_true", required=True)
    parser.add_argument("--setting", default="surgical")
    parser.add_argument("--fake", action="store_true", help="validate and dry playback only; never opens a port")
    parser.add_argument("--rig", type=Path, default=None)
    args = parser.parse_args(argv)
    kin = Kinematics(args.rig)
    if args.fake or not os.getenv("SO101_PORT"):
        ok = check(args.setting, kin=kin)
    else:
        from .real_arm import Arm

        print("Replaying on the real arm. Remove every instrument from the gripper and the tray area.")
        arm = Arm(rig_path=args.rig)
        arm.connect()
        try:
            ok = check(args.setting, kin=kin, arm=arm)
            arm.go_home()
        finally:
            arm.disconnect()
    print("PASS" if ok else "FAIL")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main(sys.argv[1:])
