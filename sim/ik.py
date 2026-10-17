"""Reference inverse kinematics for the SO-101 (damped least squares).

Reference implementation for Anish's A7 `move_to`; Anish owns the real one.
Frames: arm base frame, meters, x forward, y left, z up (matches CONTRACTS).
Quirk of this MJCF: a POSITIVE shoulder_pan swings the gripper toward -y (right).
Joint order: shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper.
Only the first four joints move; wrist_roll and gripper are copied from q0.

    q, err = solve([x, y, z], q0)        # err = final position error in meters
    ok, err, q = reachable([x, y, z])    # multi-start solve, ok if err < tol
"""
import threading
from pathlib import Path

import mujoco
import numpy as np

MODEL_XML = Path(__file__).parent / "models" / "so101" / "so101_new_calib.xml"
_m = mujoco.MjModel.from_xml_path(str(MODEL_XML))
_d = mujoco.MjData(_m)
_lock = threading.RLock()  # the shared MjData scratch is not thread safe
_site = _m.site("gripperframe").id
LIMITS = _m.jnt_range[:6].copy()
TOL = 0.005  # reachable if solved to within 5 mm
TOOL_DOWN = -0.8  # preferred z component of the gripper finger direction (site x axis)


def fk(q):
    """Return (position, tool direction) of the gripperframe for joints q."""
    with _lock:
        _d.qpos[:6] = q
        mujoco.mj_kinematics(_m, _d)
        mujoco.mj_comPos(_m, _d)
        return _d.site_xpos[_site].copy(), _d.site_xmat[_site].reshape(3, 3)[:, 0].copy()


def solve(target, q0=None, tool_dz=TOOL_DOWN, w_tool=0.05, iters=150, lam=0.02):
    with _lock:
        return _solve(target, q0, tool_dz, w_tool, iters, lam)


def _solve(target, q0, tool_dz, w_tool, iters, lam):
    """Damped least squares on 3 position rows plus one soft tool-pitch row.

    Set w_tool=0 to ignore tool pitch. Returns (q[6], position_error_m).
    """
    target = np.asarray(target, float)
    q = np.zeros(6) if q0 is None else np.array(q0, float)
    jp, jr = np.zeros((3, _m.nv)), np.zeros((3, _m.nv))
    for _ in range(iters):
        pos, d = fk(q)
        err = target - pos
        mujoco.mj_jacSite(_m, _d, jp, jr, _site)
        J = jp[:, :4]
        e = err
        if w_tool > 0:  # d(d_z)/dq = (w x d)_z with w the angular Jacobian
            row = jr[0, :4] * d[1] - jr[1, :4] * d[0]
            J = np.vstack([J, w_tool * row])
            e = np.append(err, w_tool * (tool_dz - d[2]))
        dq = J.T @ np.linalg.solve(J @ J.T + lam**2 * np.eye(len(e)), e)
        q[:4] = np.clip(q[:4] + np.clip(dq, -0.3, 0.3), LIMITS[:4, 0], LIMITS[:4, 1])
        if np.linalg.norm(err) < 5e-4 and (w_tool == 0 or abs(tool_dz - d[2]) < 0.3):
            break
    return q, float(np.linalg.norm(target - fk(q)[0]))


def reachable(target, q0=None, tol=TOL):
    """Multi-start solve. Returns (ok, error_m, q[6]); prefers a downward tool."""
    x, y, z = target
    pan = float(np.arctan2(-y, x))
    base = np.zeros(6) if q0 is None else np.array(q0, float)
    best = (np.inf, base)
    for w in (0.05, 0.0):
        for lift, elbow, wrist in ((0.3, 0.8, 0.5), (0.8, 0.5, 0.2), (-0.5, 1.2, 0.9), (0, 0, 0)):
            s = base.copy()
            s[:4] = [pan, lift, elbow, wrist]
            q, err = solve(target, s, w_tool=w)
            if err < best[0]:
                best = (err, q)
            if err < tol:
                return True, err, q
    return bool(best[0] < tol), float(best[0]), best[1]
