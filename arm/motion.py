"""A7 motion planning with injected joint reader/trajectory executor."""
from __future__ import annotations

import numpy as np

from .kinematics import Kinematics


class CartesianMotion:
    def __init__(self, kinematics: Kinematics, read_joints, execute):
        self.kinematics = kinematics
        self.read_joints = read_joints
        self.execute = execute

    def move_to(self, x, y, z, speed=0.3):
        kin = self.kinematics
        point = [x, y, z]
        if not kin.in_region(point):
            return False
        start = np.asarray(self.read_joints(), dtype=float)
        goal = kin.inverse(point, start[:5])
        if goal is None:
            return False
        try:
            # The full interpolated path, not just its endpoint, must remain
            # inside the measured handoff box. Carry must already be in it.
            rows = kin.trajectory(start, np.r_[goal, start[5]], speed, region=True)
        except ValueError:
            return False
        return self.execute(rows)
