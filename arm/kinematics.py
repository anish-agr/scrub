"""Position IK from the SO-101 URDF; meters, radians internally, degrees at I/O.

This is not a collision planner or a hardware calibration. Wrist roll is held
at its seed value; position-only IK does not guarantee handle orientation.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np

JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll")
FEATURES = tuple(name + ".pos" for name in JOINTS) + ("gripper.pos",)


def rotation(axis, angle):
    axis = np.asarray(axis, dtype=float)
    axis = axis / np.linalg.norm(axis)
    x, y, z = axis
    cross = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
    return np.eye(3) + math.sin(angle) * cross + (1 - math.cos(angle)) * (cross @ cross)


def origin(element):
    t = np.eye(4)
    if element is not None:
        t[:3, 3] = np.fromstring(element.get("xyz", "0 0 0"), sep=" ")
        roll, pitch, yaw = np.fromstring(element.get("rpy", "0 0 0"), sep=" ")
        t[:3, :3] = rotation([0, 0, 1], yaw) @ rotation([0, 1, 0], pitch) @ rotation([1, 0, 0], roll)
    return t


class Kinematics:
    def __init__(self, rig_path=None):
        self.rig_path = Path(rig_path or Path(__file__).with_name("rig.json"))
        self.rig = json.loads(self.rig_path.read_text())
        root = ET.parse(self.rig_path.parent / self.rig["urdf"]).getroot()
        joints = {j.attrib["name"]: j for j in root.findall("joint")}
        self.origins = [origin(joints[n].find("origin")) for n in JOINTS]
        self.axes = [np.fromstring(joints[n].find("axis").get("xyz"), sep=" ") for n in JOINTS]
        self.lower = np.array([float(joints[n].find("limit").get("lower")) for n in JOINTS])
        self.upper = np.array([float(joints[n].find("limit").get("upper")) for n in JOINTS])
        self.tip = origin(joints["gripper_frame_joint"].find("origin"))
        self.signs = np.asarray(self.rig["joint_signs"], dtype=float)
        self.offsets = np.asarray(self.rig["joint_offsets_deg"], dtype=float)
        self.base_to_urdf = np.asarray(self.rig["base_to_urdf"], dtype=float)
        if self.signs.shape != (5,) or not np.all(np.abs(self.signs) == 1) or self.offsets.shape != (5,):
            raise ValueError("Rig needs five signs (+/-1) and five degree offsets")
        if self.base_to_urdf.shape != (4, 4) or not np.isfinite(self.base_to_urdf).all():
            raise ValueError("Invalid base-to-URDF transform")
        r = self.base_to_urdf[:3, :3]
        if not np.allclose(r.T @ r, np.eye(3)) or not np.isclose(np.linalg.det(r), 1) or not np.allclose(self.base_to_urdf[3], [0, 0, 0, 1]):
            raise ValueError("base_to_urdf must be a rigid transform")

    def to_urdf(self, degrees):
        return np.deg2rad(np.asarray(degrees, dtype=float) * self.signs + self.offsets)

    def from_urdf(self, radians):
        return (np.rad2deg(radians) - self.offsets) / self.signs

    def valid(self, degrees):
        q = self.to_urdf(degrees)
        return q.shape == (5,) and np.isfinite(q).all() and bool(np.all(q >= self.lower - 1e-8) and np.all(q <= self.upper + 1e-8))

    def _chain(self, q):
        t = np.eye(4)
        positions, axes = [], []
        for initial, axis, angle in zip(self.origins, self.axes, q):
            t = t @ initial
            positions.append(t[:3, 3].copy())
            axes.append(t[:3, :3] @ axis)
            turn = np.eye(4)
            turn[:3, :3] = rotation(axis, angle)
            t = t @ turn
        return t @ self.tip, positions, axes

    def forward(self, degrees):
        if not self.valid(degrees):
            raise ValueError("Joints outside URDF limits")
        t, _, _ = self._chain(self.to_urdf(degrees))
        return (np.linalg.inv(self.base_to_urdf) @ t)[:3, 3]

    def in_region(self, point):
        p = np.asarray(point, dtype=float)
        region = self.rig["handoff_region"]
        return p.shape == (3,) and np.isfinite(p).all() and bool(np.all(p >= region["min"]) and np.all(p <= region["max"]))

    def inverse(self, point, seed, *, require_region=True, tolerance=0.001):
        p = np.asarray(point, dtype=float)
        if p.shape != (3,) or not np.isfinite(p).all() or not self.valid(seed):
            return None
        if require_region and not self.in_region(p):
            return None
        target = (self.base_to_urdf @ np.r_[p, 1])[:3]
        initial = self.to_urdf(seed)
        rng = np.random.default_rng(101)
        starts = [initial] + [rng.uniform(self.lower, self.upper) for _ in range(12)]
        for start in starts:
            q = start.copy()
            q[4] = initial[4]  # preserve roll rather than arbitrarily turning a held tool
            for _ in range(180):
                t, positions, axes = self._chain(q)
                error = target - t[:3, 3]
                if np.linalg.norm(error) <= tolerance:
                    return self.from_urdf(q)
                jacobian = np.column_stack([np.cross(a, t[:3, 3] - v) for a, v in zip(axes[:4], positions[:4])])
                delta = jacobian.T @ np.linalg.solve(jacobian @ jacobian.T + 1e-5 * np.eye(3), error)
                q[:4] = np.clip(q[:4] + np.clip(delta, -0.2, 0.2), self.lower[:4], self.upper[:4])
        return None

    def trajectory(self, start, goal, speed=0.3, *, region=False, hz=30):
        """Preflight entire joint-space path; speed is a fraction in (0, 1]."""
        if not math.isfinite(speed) or not 0 < speed <= 1:
            raise ValueError("speed must be a fraction in (0, 1]")
        start, goal = np.asarray(start, dtype=float), np.asarray(goal, dtype=float)
        if start.shape != (6,) or goal.shape != (6,) or not np.isfinite(start).all() or not np.isfinite(goal).all():
            raise ValueError("Need six finite joint values")
        if not self.valid(start[:5]) or not self.valid(goal[:5]) or not (0 <= start[5] <= 100 and 0 <= goal[5] <= 100):
            raise ValueError("Trajectory exceeds joint limits")
        limits = np.array([self.rig["max_joint_speed_deg_s"]] * 5 + [self.rig["max_gripper_speed_per_s"]]) * speed
        if np.any(limits <= 0):
            raise ValueError("Invalid speed limits")
        duration = max(1 / hz, float(np.max(abs(goal - start) / limits)))
        # Refine until both Cartesian and joint finite-difference speeds meet limits.
        for _ in range(8):
            count = math.ceil(duration * hz)
            rows = np.linspace(start, goal, count + 1)
            points = np.array([self.forward(row[:5]) for row in rows])
            if region and not all(self.in_region(p) for p in points):
                raise ValueError("Interpolated path exits handoff region")
            ratio = float(np.max(np.linalg.norm(np.diff(points, axis=0), axis=1)) * hz / (self.rig["max_cartesian_speed_m_s"] * speed))
            if ratio <= 1 + 1e-8:
                return rows[1:]
            duration *= ratio * 1.01
        raise ValueError("Could not bound Cartesian speed")
