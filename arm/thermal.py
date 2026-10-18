"""Motor temperatures, the cool-down rule and telemetry rows, shared by real_arm.py and explore/arm_session.py.

Rule (explore/research/overheating): stop and fold to rest when any motor reaches COOL_TRIP; resume when
every motor is at or below COOL_RESUME, or when cooling has levelled off for COOL_PLATEAU_S at or below
COOL_TRIP - 5. A powered motor idles at ~45 C (the leader, torque off, reads 45-47 C), so 45 is unreachable.
"""
from __future__ import annotations

import time

COOL_TRIP, COOL_RESUME = 60, 50   # deg C
COOL_PLATEAU_S = 180


def read_temps(bus) -> dict:
    """{motor: deg C} for every motor on the bus. Raises if the read fails."""
    return {k: int(v) for k, v in bus.sync_read("Present_Temperature", normalize=False).items()}


def read_loads(bus) -> dict:
    """{motor: raw signed Present_Load} (0.1% of max torque). Raises if the read fails."""
    return {k: int(v) for k, v in bus.sync_read("Present_Load", normalize=False).items()}


def too_hot(temps: dict, trip=None) -> dict:
    """The motors at or past the trip temperature (COOL_TRIP, read at call time so a bench test can lower it)."""
    trip = COOL_TRIP if trip is None else trip
    return {m: t for m, t in temps.items() if t is not None and t >= trip}


def fault_message(hot: dict) -> str:
    m = max(hot, key=hot.get)
    return f"Too hot: {m} {hot[m]} C. Cooling down."


class Cooling:
    """Tracks one cool-down. done(hottest) is True once the arm may run again."""
    def __init__(self, resume=None, trip=None, plateau_s=None):
        self.resume = COOL_RESUME if resume is None else resume
        self.trip = COOL_TRIP if trip is None else trip
        self.plateau_s = COOL_PLATEAU_S if plateau_s is None else plateau_s
        self.best, self.best_t = None, time.time()

    def done(self, hottest, now=None) -> bool:
        now = time.time() if now is None else now
        if hottest is None:
            return False
        if self.best is None or hottest < self.best:
            self.best, self.best_t = hottest, now
        level = hottest <= self.trip - 5 and now - self.best_t > self.plateau_s
        return hottest <= self.resume or level


def telemetry(temps: dict, loads: dict, cooling: bool, t=None) -> dict:
    """The controller's arm_telemetry shape: {"temps", "loads", "hottest", "cooling", "t"}."""
    return {"temps": dict(temps), "loads": dict(loads), "hottest": max(temps.values(), default=None),
            "cooling": bool(cooling), "t": time.time() if t is None else t}
