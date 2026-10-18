"""Torque-off, hand-guided pose teaching. Never sends a motor position target."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from dotenv import load_dotenv
import numpy as np

from .kinematics import JOINTS, Kinematics

DEFAULT_RIG = Path(__file__).with_name("rig.json")


class TeachBackend:
    def __init__(self, port, robot_id):
        self.port, self.robot_id = port, robot_id
        self.robot = None

    def connect(self):
        from .backends import port_holders
        busy = port_holders(self.port)
        if busy:  # torque off under a running controller would drop a raised arm and its tool
            raise RuntimeError(f"{self.port} is open in another process (pid {', '.join(map(str, busy))}): "
                               "stop the controller, teleop or recording first")
        from lerobot.robots.so_follower.config_so_follower import SO101FollowerConfig
        from lerobot.robots.so_follower.so_follower import SO101Follower

        self.robot = SO101Follower(SO101FollowerConfig(
            port=self.port, id=self.robot_id, use_degrees=True, cameras={}))
        if not self.robot.calibration:
            raise RuntimeError("Saved calibration is required; teach never calibrates or sets up motors")
        # Do NOT call robot.connect(): its configure step can enable torque.
        # This read-only tool owns the bus directly and keeps every motor limp.
        self.robot.bus.connect()
        self.robot.bus.disable_torque()
        if not self.robot.is_calibrated:
            raise RuntimeError("Saved calibration does not match motor calibration")

    def read_joints(self):
        values = self.robot.bus.sync_read("Present_Position")
        return np.array([values[name] for name in (*JOINTS, "gripper")], dtype=float)

    def close(self):
        if self.robot is not None and self.robot.bus.is_connected:
            self.robot.bus.disconnect(disable_torque=True)


class FakeTeachBackend:
    def __init__(self, joints=None):
        self.joints = np.asarray(joints if joints is not None else [0, 0, 0, 0, 0, 100], dtype=float)
        self.connected = False

    def connect(self):
        self.connected = True

    def read_joints(self):
        return self.joints.copy()

    def close(self):
        self.connected = False


class Teacher:
    def __init__(self, rig_path, backend):
        self.path = Path(rig_path)
        self.kin = Kinematics(self.path)
        self.backend = backend
        self.expected = self.path.read_text()
        self.corners = {}

    def sample(self):
        row = np.asarray(self.backend.read_joints(), dtype=float)
        if row.shape != (6,) or not np.isfinite(row).all() or not self.kin.valid(row[:5]) or not 0 <= row[5] <= 100:
            raise ValueError("Measured joint values violate configured units/limits; nothing saved")
        return row

    def save(self, update):
        # Preserve every unrelated setting and refuse to overwrite another
        # agent/operator's edits made since this teaching session started.
        if self.path.is_symlink() or self.path.read_text() != self.expected:
            raise RuntimeError("rig.json changed elsewhere; restart teach before saving")
        rig = json.loads(self.expected)
        rig.update(update)
        # Teaching new poses/region invalidates old hardware acceptance. Human
        # verification, not this script, is what enables hardware motion.
        rig["hardware_verified"] = False
        text = json.dumps(rig, indent=2) + "\n"
        temporary = self.path.with_name(self.path.name + ".teach.tmp")
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(temporary, self.path)
        self.expected = text
        self.kin.rig = rig

    def pose(self, name):
        if name not in {"home", "carry", "safe_spot"}:
            raise ValueError("Unknown pose")
        row = self.sample()
        self.save({name: row.tolist()})
        return row.tolist()

    def corner(self, name):
        if name not in {"a", "b"}:
            raise ValueError("Use corner a or b")
        point = self.kin.forward(self.sample()[:5])
        self.corners[name] = point
        if set(self.corners) == {"a", "b"}:
            lower = np.minimum(self.corners["a"], self.corners["b"])
            upper = np.maximum(self.corners["a"], self.corners["b"])
            if np.any(upper - lower < .01):
                raise ValueError("Opposite region corners need at least 1 cm separation on every axis; region not saved")
            self.save({"handoff_region": {"min": lower.tolist(), "max": upper.tolist()}})
        return point.tolist()


def interact(teacher, *, read=input, write=print):
    write("Support the EMPTY arm throughout. Torque stays OFF, including on exit.")
    write("Move by hand, then type: h home, c carry, s safe-spot, a/b opposite handoff corners, p read, q quit.")
    write("Corner XYZ comes from FK: verify joint signs/offsets and base transform against physical measurements first.")
    while True:
        try:
            key = read("teach> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break
        if key == "q":
            break
        try:
            if key in {"h", "c", "s"}:
                name = {"h": "home", "c": "carry", "s": "safe_spot"}[key]
                write({"saved": name, "joints": teacher.pose(name)})
            elif key in {"a", "b"}:
                write({"corner": key, "xyz": teacher.corner(key), "region_saved": len(teacher.corners) == 2})
            elif key == "p":
                row = teacher.sample()
                write({"joints": row.tolist(), "fk_xyz": teacher.kin.forward(row[:5]).tolist()})
            elif key:
                write("Unknown key; nothing saved")
        except (ValueError, RuntimeError) as error:
            write(str(error))


PICK_NAMES = ("approach", "descend", "grip", "lift", "carry")
RETURN_NAMES = ("carry", "descend", "release", "lift", "home")


class SkillTeacher:
    """Waypoints for one taught skill (arm/taught.py), saved to arm/skills/<setting>/<item>-<direction>.json."""

    def __init__(self, backend, item, direction, setting="surgical", *, rig_path=DEFAULT_RIG, root=None, speed=0.3):
        from .taught import skill_path

        self.path = skill_path(setting, item, direction, root)
        self.kin = Kinematics(rig_path)
        self.backend = backend
        self.item, self.direction, self.setting, self.speed = item, direction, setting, speed
        self.waypoints = []

    def add(self, gripper=None):
        row = np.asarray(self.backend.read_joints(), dtype=float)
        if row.shape != (6,) or not np.isfinite(row).all() or not self.kin.valid(row[:5]):
            raise ValueError("Measured joint values violate configured units/limits; waypoint not saved")
        names = PICK_NAMES if self.direction == "pick" else RETURN_NAMES
        n = len(self.waypoints)
        wp = {"name": names[n] if n < len(names) else f"wp{n + 1}",
              "joints": {j: round(float(v), 2) for j, v in zip(JOINTS, row[:5])},
              "gripper": gripper, "speed": self.speed}
        self.waypoints.append(wp)
        return wp

    def undo(self):
        return self.waypoints.pop() if self.waypoints else None

    def save(self):
        """Write the file (even with problems, so the work is kept) and return the validation problems."""
        import time

        from .taught import validate

        skill = {"item": self.item, "direction": self.direction, "setting": self.setting,
                 "taught_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "waypoints": self.waypoints}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(json.dumps(skill, indent=2) + "\n")
        os.replace(temporary, self.path)
        return validate(skill, self.kin, self.kin.rig.get("grasp_closed_fraction", 0.3))


def interact_skill(teacher, *, read=None, write=None):
    read, write = read or input, write or print
    write("Support the EMPTY arm throughout. Torque stays OFF, including on exit.")
    write(f"Teaching {teacher.item} {teacher.direction}. Move by hand, then type:")
    write("Enter save waypoint, g save with gripper closed, o save with gripper open, u undo, p read, q save file and quit.")
    write("Pick: approach above the slot, descend, g, lift, carry. Return: carry, descend over the slot, o, lift, home.")
    while True:
        try:
            key = read("skill> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            write("Quit without saving")
            return None
        try:
            if key == "q":
                problems = teacher.save()
                write({"saved": str(teacher.path), "waypoints": len(teacher.waypoints)})
                for problem in problems:
                    write(f"Check failed: {problem}")
                return teacher.path
            if key in {"", "g", "o"}:
                write({"waypoint": teacher.add({"": None, "g": 1.0, "o": 0.0}[key])})
            elif key == "u":
                write({"removed": teacher.undo()})
            elif key == "p":
                write({"joints": teacher.backend.read_joints().tolist()})
            else:
                write("Unknown key; nothing saved")
        except (ValueError, RuntimeError, OSError) as error:
            write(str(error))


def skill_main(argv):
    parser = argparse.ArgumentParser(prog="python -m arm.teach skill", description="Teach a pick or return skill.")
    parser.add_argument("item")
    parser.add_argument("direction", choices=("pick", "return"))
    parser.add_argument("--setting", default="surgical")
    parser.add_argument("--rig", type=Path, default=DEFAULT_RIG)
    parser.add_argument("--port", default=os.getenv("SO101_PORT"))
    parser.add_argument("--robot-id", default=os.getenv("SO101_ROBOT_ID", "scrub_follower"))
    parser.add_argument("--speed", type=float, default=0.3, help="playback speed saved with each waypoint, 0..1")
    parser.add_argument("--supported-and-empty", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skills-dir", type=Path, help="write here instead of arm/skills (required with --dry-run)")
    parser.add_argument("--joints", nargs=6, type=float)
    args = parser.parse_args(argv)
    if not 0 < args.speed <= 1:
        parser.error("--speed must be in (0, 1]")
    if args.dry_run and not args.skills_dir:
        parser.error("Dry-run must use --skills-dir pointing to a test folder")
    if not args.dry_run and (not args.port or not args.supported_and_empty):
        parser.error("Set --port and --supported-and-empty before disabling motor torque")
    if not args.dry_run and args.joints:
        parser.error("--joints is only for dry-run")
    backend = FakeTeachBackend(args.joints) if args.dry_run else TeachBackend(args.port, args.robot_id)
    teacher = SkillTeacher(backend, args.item, args.direction, args.setting,
                           rig_path=args.rig, root=args.skills_dir, speed=args.speed)
    try:
        backend.connect()
        interact_skill(teacher)
    except (ValueError, RuntimeError, OSError) as error:
        print(f"Teach stopped ({type(error).__name__}); support the arm and inspect setup", file=sys.stderr)
        raise SystemExit(1) from None
    finally:
        backend.close()


def main(argv=None):
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["skill"]:
        return skill_main(argv[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rig", type=Path, default=DEFAULT_RIG)
    parser.add_argument("--port", default=os.getenv("SO101_PORT"))
    parser.add_argument("--robot-id", default=os.getenv("SO101_ROBOT_ID", "scrub_follower"))
    parser.add_argument("--supported-and-empty", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--joints", nargs=6, type=float)
    args = parser.parse_args(argv)
    if args.dry_run and args.rig.resolve() == DEFAULT_RIG.resolve():
        parser.error("Dry-run must use --rig pointing to a separate test copy")
    if not args.dry_run and (not args.port or not args.supported_and_empty):
        parser.error("Set --port and --supported-and-empty before disabling motor torque")
    if not args.dry_run and args.joints:
        parser.error("--joints is only for dry-run")
    teacher_backend = FakeTeachBackend(args.joints) if args.dry_run else TeachBackend(args.port, args.robot_id)
    # All metadata errors are caught before changing motor state.
    teacher = Teacher(args.rig, teacher_backend)
    try:
        teacher_backend.connect()
        interact(teacher)
    except (ValueError, RuntimeError, OSError) as error:
        print(f"Teach stopped ({type(error).__name__}); support the arm and inspect setup", file=sys.stderr)
        raise SystemExit(1) from None
    finally:
        teacher_backend.close()


if __name__ == "__main__":
    main()
