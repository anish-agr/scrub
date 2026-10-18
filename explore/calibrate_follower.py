"""Recalibrate the SO-101 follower without the traps we hit on Oct 17.

  .venv/bin/python explore/calibrate_follower.py

1. Checks every motor answers and reads inside one turn (0..4095). A motor that spun past a full
   turn keeps counting until its 12 V power is cycled, and LeRobot's calibration then fails with
   "Magnitude ... exceeds 2047". This says which motor and what to do instead.
2. Backs up the old calibration and moves it aside, so LeRobot calibrates instead of asking
   "ENTER to use the provided file" (a plain ENTER silently keeps the old one).
3. Runs lerobot-calibrate, then checks each joint's new range stays clear of the 0/4095 wrap,
   the edge that made the wrist read 244 deg and go limp.
"""
import shutil
import subprocess
import sys
import time
from pathlib import Path

PORT = "/dev/tty.usbmodem5C821089781"
ROBOT_ID = "scrub_follower"
CAL = Path.home() / ".cache/huggingface/lerobot/calibration/robots/so_follower" / f"{ROBOT_ID}.json"
NAMES = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
WRAP_MARGIN = 100  # ticks (~9 deg) a calibrated end should keep from 0 and 4095


def read_motors() -> dict:
    import scservo_sdk as scs
    ph = scs.PortHandler(PORT)
    if not ph.openPort():
        sys.exit(f"can't open {PORT}: is the follower's USB plugged in, and is nothing else using it?")
    ph.setBaudRate(1_000_000)
    pk = scs.PacketHandler(0)
    out = {}
    try:
        for i, name in enumerate(NAMES, 1):
            pos, comm, _ = pk.read2ByteTxRx(ph, i, 56)
            off, comm2, _ = pk.read2ByteTxRx(ph, i, 31)
            if comm != 0 or comm2 != 0:
                out[name] = None
                continue
            off = -(off & 0x7FF) if off & 0x800 else off
            pos = -(pos & 0x7FFF) if pos & 0x8000 else pos
            out[name] = pos + off  # position with no offset applied
    finally:
        ph.closePort()
    return out


def main() -> None:
    if subprocess.run(["pgrep", "-f", "arm_session.py|lerobot-(record|teleoperate)"], capture_output=True).stdout:
        sys.exit("stop the recorder / teleop first (Ctrl-C in its terminal): it holds the arm's port")

    raw = read_motors()
    silent = [n for n, v in raw.items() if v is None]
    if silent:
        sys.exit(f"no answer from {', '.join(silent)}: check the 12 V power and the cable chain to that motor")
    spun = {n: v for n, v in raw.items() if not 0 <= v <= 4095}
    if spun:
        for n, v in spun.items():
            print(f"{n} reads {v}: it turned past a full revolution and keeps counting until power-up")
        sys.exit("Unplug the follower's 12 V power (the barrel plug, not the USB) for 10 s, plug it back in, "
                 "and run this again. If the gripper cable is wrapped around the wrist, unwind it by hand first.")
    print("all six motors answer and read inside one turn")

    if CAL.exists():
        backup = CAL.with_name(f"{ROBOT_ID}.backup-{time.strftime('%Y%m%d-%H%M%S')}.json")
        shutil.copy2(CAL, backup)
        CAL.unlink()
        print(f"old calibration backed up to {backup.name}")

    print("\nWhen it says 'Move ... to the middle of its range': support the arm (torque is off), set it")
    print("upper arm ~45 deg up, elbow ~90 deg, WRIST STRAIGHT in line with the forearm, roll level, claw")
    print("half open, THEN press ENTER. Then move each joint slowly end to end (wrist flex all the way up")
    print("and all the way down into the folded rest pose; wrist roll about a third of a turn each way,")
    print("not a full turn; claw fully open and closed) and press ENTER.\n")
    venv_bin = Path(sys.executable).parent
    rc = subprocess.call([str(venv_bin / "lerobot-calibrate"), "--robot.type=so101_follower",
                          f"--robot.port={PORT}", f"--robot.id={ROBOT_ID}"])
    if rc != 0 or not CAL.exists():
        sys.exit(f"calibration did not finish (exit {rc}); the backup is next to {CAL}")

    import json
    cal = json.loads(CAL.read_text())
    ok = True
    for name, c in cal.items():
        lo, hi = c["range_min"], c["range_max"]
        span = (hi - lo) * 360 / 4096
        # LeRobot never sweeps wrist_roll: it gets the full 0..4095 turn on purpose.
        near = name != "wrist_roll" and (lo < WRAP_MARGIN or hi > 4095 - WRAP_MARGIN)
        ok &= not near
        print(f"{name:14s} {lo:5d} .. {hi:5d}  ({span:5.0f} deg){'   NEAR THE WRAP: recalibrate with the joint centred' if near else ''}")
    print("calibration looks good" if ok else "a range sits near the 0/4095 wrap: run this again and centre that joint first")


if __name__ == "__main__":
    main()
