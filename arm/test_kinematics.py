import unittest

import numpy as np

from .kinematics import Kinematics
from .motion import CartesianMotion


class KinematicsTests(unittest.TestCase):
    def test_random_reachable_round_trip(self):
        kin = Kinematics()
        rng = np.random.default_rng(26)
        for _ in range(60):
            original = kin.from_urdf(rng.uniform(kin.lower + .05, kin.upper - .05))
            point = kin.forward(original)
            seed = np.clip(kin.to_urdf(original) + rng.normal(0, .3, 5), kin.lower, kin.upper)
            seed[4] = kin.to_urdf(original)[4]
            solved = kin.inverse(point, kin.from_urdf(seed), require_region=False)
            self.assertIsNotNone(solved)
            self.assertTrue(kin.valid(solved))
            self.assertLess(np.linalg.norm(kin.forward(solved) - point), .0011)

    def test_rejections(self):
        kin = Kinematics()
        self.assertIsNone(kin.inverse([20, 20, 20], [0] * 5))
        self.assertIsNone(kin.inverse([float("nan"), 0, .2], [0] * 5))
        self.assertIsNone(kin.inverse([.2, 0, .2], [999] * 5))
        self.assertFalse(kin.in_region([.2, 0, -.1]))
        self.assertIsNone(kin.inverse([5, 5, 5], [0] * 5, require_region=False))

    def test_trajectory_speed_and_region(self):
        kin = Kinematics()
        start = np.array([0, 0, 0, 0, 0, 50.])
        goal = np.array([10, 5, -5, 5, 0, 50.])
        rows = kin.trajectory(start, goal)
        delta = np.diff(np.vstack([start, rows]), axis=0)
        self.assertLessEqual(abs(delta[:, :5]).max() * 30, kin.rig["max_joint_speed_deg_s"] * .3 + 1e-6)
        points = np.array([kin.forward(r[:5]) for r in np.vstack([start, rows])])
        self.assertLessEqual(np.linalg.norm(np.diff(points, axis=0), axis=1).max() * 30, kin.rig["max_cartesian_speed_m_s"] * .3 + 1e-6)
        with self.assertRaises(ValueError):
            kin.trajectory(start, goal, 0)
        with self.assertRaises(ValueError):
            kin.trajectory(start, [999] * 6)

    def test_move_to_executes_only_preflighted_paths(self):
        kin = Kinematics()
        # Find an in-region carry pose using FK, rather than inventing a rig pose.
        rng = np.random.default_rng(7)
        for _ in range(1000):
            start = kin.from_urdf(rng.uniform(kin.lower * .7, kin.upper * .7))
            target = start.copy()
            target[0] += .5
            if kin.valid(target) and kin.in_region(kin.forward(start)) and kin.in_region(kin.forward(target)):
                break
        else:
            self.fail("No synthetic in-region pose")
        sent = []
        mover = CartesianMotion(kin, lambda: np.r_[start, 42.], lambda rows: sent.append(rows) or True)
        point = kin.forward(target)
        self.assertTrue(mover.move_to(*point))
        self.assertLess(np.linalg.norm(kin.forward(sent[0][-1, :5]) - point), .0011)
        self.assertTrue(np.all(sent[0][:, 5] == 42))
        self.assertFalse(mover.move_to(9, 9, 9))
        self.assertEqual(len(sent), 1)
        self.assertFalse(mover.move_to(*point, speed=0))

    def test_joint_mapping_round_trip(self):
        kin = Kinematics()
        kin.signs = np.array([-1, 1, -1, 1, -1])
        kin.offsets = np.array([5, 10, -5, 0, 2])
        q = np.array([.1, -.2, .3, -.4, .5])
        np.testing.assert_allclose(kin.to_urdf(kin.from_urdf(q)), q)


if __name__ == "__main__":
    unittest.main()
