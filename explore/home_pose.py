"""The follower's home (parking) pose: save it, and test resting there with torque off.

  .venv/bin/python explore/home_pose.py save    # the follower's current pose becomes home (recorder stopped)
  .venv/bin/python explore/home_pose.py show    # saved home vs where the arm is now
  .venv/bin/python explore/home_pose.py test    # wake (torque on, holding) -> rest (torque off): does it stay put?

Home is where the arm parks between commands with torque off, so the servos cool instead of heating
(holding still with torque on warmed every motor ~5 C in 4 min). It must be a pose that stays put
unpowered: folded, resting on its stops. Saved to explore/home_pose.json (raw steps and degrees);
arm_session.py folds to it on cool-down and turns torque off when a session ends near it.
For the real arm, Anish's arm/rig.json "home" takes the same six raw values.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PORT = "/dev/tty.usbmodem5C821089781"
FILE = Path(__file__).with_name("home_pose.json")
CAL = Path.home() / ".cache/huggingface/lerobot/calibration/robots/so_follower/scrub_follower.json"
NAMES = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]


def _bus():
    import scservo_sdk as scs
    ph = scs.PortHandler(PORT)
    if not ph.openPort():
        sys.exit(f"can't open {PORT}: stop the recorder first (it owns the port)")
    ph.setBaudRate(1_000_000)
    return scs, ph, scs.PacketHandler(0)


def _to_units(raw: dict) -> dict:
    """LeRobot units: degrees around the calibrated middle; gripper 0 (closed) .. 100 (open)."""
    cal = json.loads(CAL.read_text())
    out = {}
    for n, v in raw.items():
        c = cal[n]
        if n == "gripper":
            out[n] = round((v - c["range_min"]) / (c["range_max"] - c["range_min"]) * 100, 1)
        else:
            out[n] = round((v - (c["range_min"] + c["range_max"]) / 2) * 360 / 4095, 1)
    return out


def read_pose(pk, ph) -> dict:
    raw = {}
    for i, n in enumerate(NAMES, 1):
        v, comm, _ = pk.read2ByteTxRx(ph, i, 56)
        if comm != 0:
            sys.exit(f"{n} (id {i}) didn't answer: check the follower's 12 V power")
        raw[n] = -(v & 0x7FFF) if v & 0x8000 else v
    return raw


def save() -> None:
    scs, ph, pk = _bus()
    try:
        raw = read_pose(pk, ph)
    finally:
        ph.closePort()
    deg = _to_units(raw)
    FILE.write_text(json.dumps({"saved": time.strftime("%Y-%m-%d %H:%M"), "raw": raw, "deg": deg}, indent=1) + "\n")
    print("home saved:", deg)
    print("raw for arm/rig.json \"home\":", [raw[n] for n in NAMES])


def show() -> None:
    home = json.loads(FILE.read_text())
    scs, ph, pk = _bus()
    try:
        now = _to_units(read_pose(pk, ph))
    finally:
        ph.closePort()
    for n in NAMES:
        print(f"{n:14s} home {home['deg'][n]:7.1f}   now {now[n]:7.1f}   off by {now[n] - home['deg'][n]:+6.1f}")


def test(hold_s: float = 5.0) -> None:
    """Wake at the present pose (no motion), hold, rest; report drift and temperatures."""
    scs, ph, pk = _bus()
    try:
        before = read_pose(pk, ph)
        temps0 = {n: pk.read1ByteTxRx(ph, i, 63)[0] for i, n in enumerate(NAMES, 1)}
        for i, n in enumerate(NAMES, 1):  # wake: target = where it is, then torque on (nothing moves)
            pk.write2ByteTxRx(ph, i, 42, before[n] & 0xFFFF if before[n] >= 0 else before[n])
        for i in range(1, 7):
            pk.write1ByteTxRx(ph, i, 40, 1)
        print(f"awake: torque on, holding for {hold_s:.0f} s")
        time.sleep(hold_s)
        held = read_pose(pk, ph)
        for i in range(1, 7):  # rest: torque off
            pk.write1ByteTxRx(ph, i, 40, 0)
        print("resting: torque off; checking it stays put for 3 s")
        time.sleep(3)
        after = read_pose(pk, ph)
        torque = {n: pk.read1ByteTxRx(ph, i, 40)[0] for i, n in enumerate(NAMES, 1)}
        temps1 = {n: pk.read1ByteTxRx(ph, i, 63)[0] for i, n in enumerate(NAMES, 1)}
    finally:
        ph.closePort()
    b, h, a = _to_units(before), _to_units(held), _to_units(after)
    print(f"{'motor':14s} {'start':>7s} {'awake':>7s} {'rested':>7s} {'drift':>6s} torque temp")
    worst = 0.0
    for n in NAMES:
        d = a[n] - b[n]
        worst = max(worst, abs(d)) if n != "gripper" else worst
        print(f"{n:14s} {b[n]:7.1f} {h[n]:7.1f} {a[n]:7.1f} {d:+6.1f}   {torque[n]}    {temps0[n]}->{temps1[n]}")
    print("PASS: stays put with torque off" if worst <= 3 else
          f"CHECK: a joint moved {worst:.1f} deg after torque off; pick a more folded home")


if __name__ == "__main__":
    {"save": save, "show": show, "test": test}[sys.argv[1] if len(sys.argv) > 1 else "show"]()
