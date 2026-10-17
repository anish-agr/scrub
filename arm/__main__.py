"""Offline arm demo: saved PNGs, fake joints and a fake inference session only."""
import argparse
import json
from pathlib import Path
import tempfile

from PIL import Image

from .real_arm import Arm
from .sessions import DryPolicySession


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", required=True)
    parser.add_argument("--self-test", action="store_true", help="create temporary synthetic saved images")
    parser.add_argument("--side-image")
    parser.add_argument("--wrist-image")
    parser.add_argument("--instruction", default="pick the hemostat")
    parser.add_argument("--max-s", type=float, default=4)
    parser.add_argument("--latency-ms", type=float, default=20)
    args = parser.parse_args()
    if args.latency_ms < 0:
        parser.error("latency must be nonnegative")
    if not args.self_test and not (args.side_image and args.wrist_image):
        parser.error("supply --side-image and --wrist-image, or --self-test")
    with tempfile.TemporaryDirectory(prefix="scrub-dry-") as directory:
        side, wrist = args.side_image, args.wrist_image
        if args.self_test:
            side, wrist = str(Path(directory) / "side.png"), str(Path(directory) / "wrist.png")
            Image.new("RGB", (640, 480), (30, 60, 90)).save(side)
            Image.new("RGB", (640, 480), (90, 60, 30)).save(wrist)
        arm = Arm(dry_run=True, side_image=side, wrist_image=wrist,
                  session_factory=lambda instruction: DryPolicySession(instruction, args.latency_ms / 1000))
        try:
            arm.connect()
            success = arm.run_skill(args.instruction, args.max_s)
            print(json.dumps({"dry_run": True, "success": success, "reason": arm.last_reason,
                              "gripper_closed_fraction": arm.gripper_position(),
                              "counters": arm.counters}, indent=2))
        finally:
            arm.disconnect()
    raise SystemExit(0 if success else 1)


if __name__ == "__main__":
    main()
