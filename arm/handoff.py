"""Lift and pulled-out detection for a grasp, shared by explore/arm_session.py and the controller's arm."""
from __future__ import annotations

LIFT_M = 0.03            # gripper tip this much higher than at the grab = lifted off the table
PULL_PEAK_MIN = 60       # a grasp whose |load| peaked at least this was really squeezing something
PULL_DROP = 0.3          # then |load| falling below this share of the peak (and <= 25) ...
PULL_S = 0.3             # ... for this long, while the claw is still told to hold = pulled out by a hand


def tip_z(kin, joints_deg):
    """Gripper tip height (m) from the five arm joints (degrees) with arm.kinematics.Kinematics. Angles a
    little past the model's limits (the folded rest pose) are clamped."""
    import numpy as np
    t, _, _ = kin._chain(np.clip(kin.to_urdf(list(joints_deg)[:5]), kin.lower, kin.upper))
    return float((np.linalg.inv(kin.base_to_urdf) @ t)[2, 3])


def track_lift(grasp: dict, z: float):
    """grasp keeps z0, lift_max and lifted_this_grasp for one grasp. Returns the rise (m) the first time
    the tip passes LIFT_M above where it grabbed, else None."""
    if grasp.get("z0") is None:
        grasp["z0"] = z
    rise = z - grasp["z0"]
    grasp["lift_max"] = max(grasp.get("lift_max", 0.0), rise)
    if rise >= LIFT_M and not grasp.get("lifted_this_grasp"):
        grasp["lifted_this_grasp"] = True
        return rise
    return None


def pulled_out(grasp: dict, load, now: float, holding: bool) -> bool:
    """grasp keeps peak and low_since. True once |load| has collapsed below PULL_DROP of a real squeeze
    for PULL_S while the claw is still told to hold: a hand took the item."""
    if load is None:
        return False
    grasp["peak"] = max(grasp.get("peak") or 0, abs(load))
    low = abs(load) <= max(25, PULL_DROP * grasp["peak"])
    if holding and grasp["peak"] >= PULL_PEAK_MIN and low:
        grasp["low_since"] = grasp.get("low_since") or now
        return now - grasp["low_since"] >= PULL_S
    grasp["low_since"] = None
    return False
