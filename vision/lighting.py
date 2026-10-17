"""Measure preview brightness so Brandon can compare bright, normal, and dim."""

from __future__ import annotations

import time

from vision.camera import FakeCapture, lock_controls, open_capture


def mean_brightness(grabber, seconds: float = 2.0) -> float:
    samples = []
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        latest = grabber.latest()
        if latest is not None:
            samples.append(float(latest[0].mean()))
        time.sleep(0.05)
    if not samples:
        raise RuntimeError("no frames")
    return sum(samples) / len(samples)


def main(argv: list[str] | None = None) -> None:
    import argparse
    import os

    from dotenv import load_dotenv

    from vision.camera import FrameGrabber
    from vision.service import ROOT

    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Print mean brightness for one lighting condition")
    parser.add_argument("--fake", action="store_true")
    parser.add_argument("--seconds", type=float, default=2.0)
    parser.add_argument("--label", default="now", help="bright, normal, or dim")
    args = parser.parse_args(argv)

    if args.fake:
        capture = FakeCapture()
        lock_controls(capture, exposure=-6)
    else:
        capture = open_capture(int(os.environ.get("CAMERA_INDEX", "0")))
        if not capture.isOpened():
            raise SystemExit("camera did not open")
        lock_controls(capture)
    grabber = FrameGrabber(capture).start()
    try:
        value = mean_brightness(grabber, args.seconds)
    finally:
        grabber.stop()
    print(f"{args.label}: mean brightness {value:.1f}")
    print("Run once each for bright, normal, and dim. Locked exposure should make bright clearly higher, with no flicker back down.")


if __name__ == "__main__":
    main()
