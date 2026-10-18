"""Measure preview brightness, and log a lighting test to CSV.

`python -m vision.lighting --test` records, for one lighting tag, how often a
hand is seen, how often tray detection returns, and how often that call fails
(the stale rate). One row per run.
"""

from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

from vision.camera import FakeCapture, lock_controls, open_capture

CSV_FIELDS = (
    "t",
    "lighting",
    "seconds",
    "frames",
    "hand_seen",
    "hand_rate",
    "detections",
    "detect_rate",
    "stale",
    "stale_rate",
)


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


def _rate(count: int, frames: int) -> float:
    if frames <= 0:
        return 0.0
    return count / frames


def sample_rates(grabber, detector, hand_source, categories: list[str], seconds: float) -> dict:
    """Watch the camera for `seconds`. A detector exception counts as stale."""
    frames = hands = detections = stale = 0
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        latest = grabber.latest()
        if latest is None:
            time.sleep(0.02)
            continue
        frames += 1
        frame = latest[0]
        try:
            seen = hand_source(frame) if hand_source else None
            if seen:
                hands += 1
        except Exception:
            pass
        try:
            detector.detect(frame, categories)
            detections += 1
        except Exception:
            stale += 1
        time.sleep(0.05)
    return {
        "t": time.time(),
        "frames": frames,
        "hand_seen": hands,
        "hand_rate": _rate(hands, frames),
        "detections": detections,
        "detect_rate": _rate(detections, frames),
        "stale": stale,
        "stale_rate": _rate(stale, frames),
    }


def append_csv(path: Path, lighting: str, seconds: float, sample: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    row = {
        "t": f"{sample['t']:.3f}",
        "lighting": lighting,
        "seconds": f"{seconds:.2f}",
        "frames": sample["frames"],
        "hand_seen": sample["hand_seen"],
        "hand_rate": f"{sample['hand_rate']:.3f}",
        "detections": sample["detections"],
        "detect_rate": f"{sample['detect_rate']:.3f}",
        "stale": sample["stale"],
        "stale_rate": f"{sample['stale_rate']:.3f}",
    }
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow(row)


def check_detect(api_key: str, timeout: float = 8.0) -> dict:
    """One live POST /v1/detect. Returns status and latency. Does not include the key."""
    from vision.tray import PerceptronDetector

    capture = FakeCapture()
    lock_controls(capture, exposure=-6)
    ok, frame = capture.read()
    capture.release()
    if not ok:
        raise RuntimeError("no frame")
    detector = PerceptronDetector(api_key, timeout=timeout)
    started = time.perf_counter()
    try:
        detections = detector.detect(frame, ["hemostat", "scalpel"])
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        return {
            "ok": False,
            "status": status,
            "latency_s": time.perf_counter() - started,
            "detections": 0,
            "error": type(exc).__name__,
        }
    return {
        "ok": True,
        "status": 200,
        "latency_s": detector.last_latency_s if detector.last_latency_s is not None else time.perf_counter() - started,
        "detections": len(detections),
        "error": "",
    }


class _FlakyDetector:
    """Test double: fails on calls whose index is in `fail_on`."""

    def __init__(self, fail_on: set[int] | None = None):
        self.fail_on = fail_on or set()
        self.calls = 0

    def detect(self, _frame, _categories):
        self.calls += 1
        if self.calls in self.fail_on:
            raise RuntimeError("detect down")
        return []


def run_lighting_test(
    grabber,
    detector,
    tracker,
    categories: list[str],
    label: str = "normal",
    duration_s: float = 2.0,
    out_csv: Path | None = None,
) -> dict:
    """Record detection rate, hand-tracking rate, and stale rate for one lighting condition."""
    total_frames = 0
    detection_ok = 0
    hand_ok = 0
    stale_count = 0
    brightnesses = []

    deadline = time.monotonic() + duration_s
    while time.monotonic() < deadline:
        latest = grabber.latest()
        if latest is None:
            time.sleep(0.02)
            continue

        frame = latest[0]
        total_frames += 1
        brightnesses.append(float(frame.mean()))

        # Check detection
        try:
            detections = detector.detect(frame, categories)
            if detections:
                detection_ok += 1
        except Exception:
            stale_count += 1

        # Check hand tracking
        try:
            hands = tracker.detect(frame)
            if hands:
                hand_ok += 1
        except Exception:
            pass

        time.sleep(0.05)

    if total_frames == 0:
        total_frames = 1

    det_rate = detection_ok / total_frames
    hand_rate = hand_ok / total_frames
    stale_rate = stale_count / total_frames
    mean_b = sum(brightnesses) / len(brightnesses) if brightnesses else 0.0

    result = {
        "lighting": label,
        "brightness": round(mean_b, 1),
        "samples": total_frames,
        "detection_rate": round(det_rate, 3),
        "hand_tracking_rate": round(hand_rate, 3),
        "stale_rate": round(stale_rate, 3),
    }

    if out_csv is not None:
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        write_header = not out_csv.exists() or out_csv.stat().st_size == 0
        with out_csv.open("a", encoding="utf-8") as handle:
            if write_header:
                handle.write("lighting,brightness,samples,detection_rate,hand_tracking_rate,stale_rate\n")
            handle.write(
                f"{label},{mean_b:.1f},{total_frames},{det_rate:.3f},{hand_rate:.3f},{stale_rate:.3f}\n"
            )

    return result


def main(argv: list[str] | None = None) -> None:
    import argparse
    import os
    from pathlib import Path

    from dotenv import load_dotenv

    from vision.camera import FakeCapture, FrameGrabber, lock_controls, open_capture
    from vision.hand import HandTracker, synthetic_landmarks
    from vision.service import ROOT
    from vision.tray import FakeDetector, categories_for, fallback_setting

    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Measure lighting or run lighting test mode")
    parser.add_argument("--fake", action="store_true")
    parser.add_argument("--seconds", type=float, default=2.0)
    parser.add_argument("--label", default="normal", help="bright, normal, or dim")
    parser.add_argument("--test", action="store_true", help="record hand, detect, and stale rates")
    parser.add_argument("--test-mode", action="store_true", help="record hand, detect, and stale rates")
    parser.add_argument("--all-conditions", action="store_true", help="test bright, normal, and dim sequentially")
    parser.add_argument("--csv", default="vision/lighting_tests.csv", help="output CSV path")
    parser.add_argument("--check-api", action="store_true", help="one live /v1/detect call; prints status only")
    args = parser.parse_args(argv)

    if args.check_api:
        key = os.environ.get("PERCEPTRON_API_KEY", "").strip()
        if not key:
            print("PERCEPTRON_API_KEY is empty; no live call")
            raise SystemExit(1)
        result = check_detect(key)
        print(
            f"detect ok={result['ok']} status={result['status']} "
            f"latency_s={result['latency_s']:.3f} detections={result['detections']} error={result['error']}"
        )
        return

    if args.test or args.test_mode:
        if args.fake:
            capture = FakeCapture()
            lock_controls(capture, exposure=-6)
            detector = _FlakyDetector()
            hand_source = lambda _frame: [synthetic_landmarks(True)]
        else:
            capture = open_capture(int(os.environ.get("CAMERA_INDEX", "0")))
            if not capture.isOpened():
                raise SystemExit("camera did not open")
            lock_controls(capture)
            from vision.tray import PerceptronDetector

            detector = PerceptronDetector(os.environ.get("PERCEPTRON_API_KEY", ""))
            hand_source = None

        grabber = FrameGrabber(capture).start()
        try:
            if hand_source is None:
                from vision.hand import ensure_model

                tracker = HandTracker(ensure_model(ROOT))

                def hand_source(frame, tracker=tracker):
                    return tracker.detect(frame)

            labels = ("bright", "normal", "dim") if args.all_conditions else (args.label,)
            for index, label in enumerate(labels):
                if args.all_conditions and not args.fake and index:
                    if not sys.stdin.isatty():
                        raise SystemExit(
                            "Change the lamp and run one --label at a time. "
                            "--all-conditions only pauses between lamps in a terminal."
                        )
                    input(f"Set the lamp to {label}, then press Enter. ")
                sample = sample_rates(
                    grabber,
                    detector,
                    hand_source,
                    categories_for(fallback_setting("surgical")),
                    args.seconds,
                )
                append_csv(Path(args.csv), label, args.seconds, sample)
                print(
                    f"{label}: frames {sample['frames']} hand {sample['hand_rate']:.0%} "
                    f"detect {sample['detect_rate']:.0%} stale {sample['stale_rate']:.0%}"
                )
        finally:
            grabber.stop()
        print(f"appended {args.csv}")
        return

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
