"""SO-101 bus helpers shared by the controller's arm (real_arm.py) and the recorder (explore/arm_session.py).

Every function takes a LeRobot MotorsBus or anything shaped like one (sync_read, read, sync_write,
write, enable_torque, disable_torque, calibration), so tests use a fake bus. No LeRobot import here.
"""
from __future__ import annotations

READ_TRIES = 3          # LeRobot reads with zero retries; one dropped reply ("There is no status packet") ends a session
ROLL_LIMIT_DEG = 150.0  # wrist_roll is calibrated over a full turn; stay this far inside the ends
MOTORS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")

# Gripper torque by situation (Torque_Limit, 0-1000 = 0-100%; LeRobot's cap is 500). It drew ~100 mA all the
# time while still, closed 86% of a session, and ran 3-8 C hotter than the other joints.
GRIP_TORQUE_IDLE = 150   # closed on nothing and still: enough to stay shut
GRIP_TORQUE_HOLD = 350   # holding an object: plenty for a spatula or an instrument
GRIP_TORQUE_MOVE = 500   # moving / opening: LeRobot's limit
GRIP_CLOSED_POS = 6.0    # gripper units (0 closed .. 100 open): at or below this the jaws are shut on nothing
GRIP_IDLE_S = 1.5
GRIP_DEAD_ZONE = 3       # encoder steps either side (factory 1): stop chasing sub-degree errors


class ArmFault(RuntimeError):
    """The arm stopped itself (a motor too hot): the controller turns it into an error event and holds."""


def retry_reads(target, tries: int = READ_TRIES):
    """Make sync_read and read on a bus class (MotorsBus) or one bus instance retry a dropped reply
    up to `tries` times. Error-flag replies (overload) still raise at once. Safe to call twice."""
    for name in ("sync_read", "read"):
        fn = getattr(target, name)
        if getattr(fn, "_scrub_retry", False):
            continue

        def retried(*args, _fn=fn, num_retry=0, **kw):
            return _fn(*args, num_retry=max(num_retry, tries), **kw)
        retried._scrub_retry = True
        setattr(target, name, retried)
    return target


def joint_limits(bus) -> dict:
    """Each joint's calibrated range in LeRobot's degrees (gripper 0-100), 1 inside the ends,
    wrist_roll held to +-ROLL_LIMIT_DEG (Oct 17: a goal at 4200 > 4095 steps tripped overload)."""
    out = {}
    for m, c in bus.calibration.items():
        if m == "gripper":
            out[m] = (1.0, 99.0)
            continue
        mid = (c.range_min + c.range_max) / 2
        lo, hi = ((r - mid) * 360 / 4095 for r in (c.range_min, c.range_max))
        out[m] = (lo + 1, hi - 1)
    if "wrist_roll" in out:
        out["wrist_roll"] = (max(out["wrist_roll"][0], -ROLL_LIMIT_DEG), min(out["wrist_roll"][1], ROLL_LIMIT_DEG))
    return out


def clamp_action(action: dict, limits: dict) -> dict:
    """A copy of a LeRobot action ({"shoulder_pan.pos": deg, ...}) or a {motor: value} dict with every
    value inside its limit. A goal past a limit sets the motor's angle error, which later fails LeRobot's
    start-up check."""
    out = dict(action)
    for k, v in out.items():
        m = k[:-4] if k.endswith(".pos") else k
        if m in limits:
            out[k] = min(limits[m][1], max(limits[m][0], v))
    return out


def hold_present(bus, motors=None):
    """Goal_Position := Present_Position (raw steps). Nothing moves, and a stale overload flag clears."""
    raw = bus.sync_read("Present_Position", motors, normalize=False)
    bus.sync_write("Goal_Position", raw, normalize=False)
    return raw


def rest(bus) -> None:
    """Torque off on all six motors (call it at home: the folded pose stays put unpowered)."""
    bus.disable_torque()


def wake(bus):
    """Goal := present, then torque on. Nothing moves."""
    raw = hold_present(bus)
    bus.enable_torque()
    return raw


def gripper_torque_want(st: dict, pos: float, goal: float, holding: bool, now: float) -> int:
    """Torque_Limit for the claw: holding something -> 35%, shut on nothing for GRIP_IDLE_S -> 15%,
    otherwise 50%. pos and goal in gripper units, 0 closed .. 100 open. st keeps the shut timer."""
    if holding and pos > GRIP_CLOSED_POS:
        return GRIP_TORQUE_HOLD
    if pos <= GRIP_CLOSED_POS and goal <= pos + 1.0:
        st["shut"] = st.get("shut") or now
        return GRIP_TORQUE_IDLE if now - st["shut"] > GRIP_IDLE_S else GRIP_TORQUE_MOVE
    st["shut"] = None
    return GRIP_TORQUE_MOVE


def set_gripper_torque(bus, st: dict, want: int) -> bool:
    """Write the claw's Torque_Limit only when the level changes. True if it wrote. Never raises."""
    if want == st.get("torque"):
        return False
    try:
        bus.write("Torque_Limit", "gripper", want)
    except Exception:  # noqa: BLE001 - keep the motor's current limit
        return False
    st["torque"] = want
    return True


def set_dead_zone(bus, steps: int = GRIP_DEAD_ZONE) -> bool:
    """Gripper CW/CCW dead zone (EEPROM, so the claw relaxes for a moment). Skips the write when it is
    already set. True if it wrote."""
    try:
        if all(int(bus.read(r, "gripper", normalize=False)) == steps for r in ("CW_Dead_Zone", "CCW_Dead_Zone")):
            return False
    except Exception:  # noqa: BLE001 - unknown: write it
        pass
    with bus.torque_disabled("gripper"):
        bus.write("CW_Dead_Zone", "gripper", steps)
        bus.write("CCW_Dead_Zone", "gripper", steps)
    return True


def stuck_motors(port: str, names=MOTORS) -> list[str]:
    """Before LeRobot opens the port: motors whose overload/angle flag would make its start-up check
    refuse them. A joint past its range is reported (turn it back by hand); any other flagged motor gets
    a fresh target at its present position, which clears the flag. Only while no process owns the port."""
    import scservo_sdk as scs
    out = []
    ph = scs.PortHandler(port)
    try:
        if not ph.openPort():
            return []
        ph.setBaudRate(1_000_000)
        pk = scs.PacketHandler(0)
        for i, n in enumerate(names, 1):
            _m, comm, err = pk.ping(ph, i)
            if comm != scs.COMM_SUCCESS or not err & 0x30:
                continue
            pos = pk.read2ByteTxRx(ph, i, 56)[0]
            lo, hi = pk.read2ByteTxRx(ph, i, 9)[0], pk.read2ByteTxRx(ph, i, 11)[0]
            pos = -(pos & 0x7FFF) if pos & 0x8000 else pos
            if (lo or hi) and not lo <= pos <= hi:
                out.append(f"{n} past its range ({pos} outside {lo}-{hi}): turn it back by hand (torque is off)")
            else:
                pk.write2ByteTxRx(ph, i, 42, pos)  # a fresh target at the present position clears overload
    except Exception:  # noqa: BLE001
        return []
    finally:
        try:
            ph.closePort()
        except Exception:  # noqa: BLE001
            pass
    return out
