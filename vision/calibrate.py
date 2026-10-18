"""Fit a homography from overhead pixels to the arm's table plane."""

from __future__ import annotations

import json
import math
from pathlib import Path

import cv2
import numpy as np

STANDOFF_M = 0.04


def fit_homography(image_points, arm_points):
    """image_points are pixels. arm_points are meters; only x and y are used."""
    if len(image_points) < 4 or len(image_points) != len(arm_points):
        raise ValueError("need the same number of image and arm points, at least 4")
    src = np.array(image_points, dtype=np.float32)
    dst = np.array([[point[0], point[1]] for point in arm_points], dtype=np.float32)
    homography, _mask = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
    if homography is None:
        raise RuntimeError("homography fit failed")
    return homography


def apply_homography(homography, x: float, y: float) -> tuple[float, float]:
    point = np.array([x, y, 1.0], dtype=np.float64)
    mapped = np.asarray(homography, dtype=np.float64) @ point
    mapped = mapped / mapped[2]
    return float(mapped[0]), float(mapped[1])


def pixel_to_arm(homography, px: float, py: float) -> tuple[float, float]:
    return apply_homography(homography, px, py)


def arm_to_pixel(homography, x: float, y: float) -> tuple[float, float]:
    inverse = np.linalg.inv(np.asarray(homography, dtype=np.float64))
    return apply_homography(inverse, x, y)


def short_of_palm(x: float, y: float, z: float, standoff_m: float = STANDOFF_M) -> list[float]:
    """A point a few cm closer to the arm base than the palm, at the saved hand height."""
    distance = math.hypot(x, y)
    if distance < 1e-6:
        return [0.0, 0.0, z]
    scale = max(distance - standoff_m, 0.0) / distance
    return [x * scale, y * scale, z]


def reprojection_error_m(homography, image_points, arm_points) -> float:
    errors = []
    for pixel, arm in zip(image_points, arm_points):
        x, y = pixel_to_arm(homography, pixel[0], pixel[1])
        errors.append(math.hypot(x - arm[0], y - arm[1]))
    return max(errors) if errors else 0.0


def rms_error_m(homography, image_points, arm_points) -> float:
    errors = []
    for pixel, arm in zip(image_points, arm_points):
        x, y = pixel_to_arm(homography, pixel[0], pixel[1])
        errors.append((x - arm[0]) ** 2 + (y - arm[1]) ** 2)
    return math.sqrt(sum(errors) / len(errors)) if errors else 0.0


def synthetic_calibration(hand_height_m: float = 0.18) -> dict:
    """Synthetic calibration mapping the synthetic hand palm [335, 353] to [0.22, -0.10, hand_height_m]."""
    cx, cy = 335.0, 353.0
    ax, ay = 0.25641, -0.11655
    image_points = [
        [cx - 100.0, cy - 100.0],
        [cx + 100.0, cy - 100.0],
        [cx + 100.0, cy + 100.0],
        [cx - 100.0, cy + 100.0],
    ]
    arm_points = [
        [ax + 100.0 * 0.0005, ay - 100.0 * 0.0005, hand_height_m],
        [ax + 100.0 * 0.0005, ay + 100.0 * 0.0005, hand_height_m],
        [ax - 100.0 * 0.0005, ay + 100.0 * 0.0005, hand_height_m],
        [ax - 100.0 * 0.0005, ay - 100.0 * 0.0005, hand_height_m],
    ]
    return calibration_from_points(image_points, arm_points, hand_height_m=hand_height_m)


def palm_target(calibration: dict | None, palm_px, height_m: float):
    if not calibration or not palm_px or not calibration.get("homography"):
        return None
    homography = np.array(calibration["homography"], dtype=np.float64)
    x, y = pixel_to_arm(homography, palm_px[0], palm_px[1])
    standoff = float(calibration.get("standoff_m", STANDOFF_M))
    return short_of_palm(x, y, height_m, standoff)


def target_pixel(calibration: dict | None, palm_px, height_m: float):
    """Pixel of the standoff point. Falls back to the palm pixel."""
    target = palm_target(calibration, palm_px, height_m)
    if target is None or not calibration or not calibration.get("homography"):
        return palm_px
    homography = np.array(calibration["homography"], dtype=np.float64)
    px, py = arm_to_pixel(homography, target[0], target[1])
    return [px, py]


def calibration_from_points(image_points, arm_points, hand_height_m: float = 0.18) -> dict:
    homography = fit_homography(image_points, arm_points)
    max_err = reprojection_error_m(homography, image_points, arm_points)
    rms_err = rms_error_m(homography, image_points, arm_points)
    return {
        "image_points": [[float(p[0]), float(p[1])] for p in image_points],
        "arm_points": [[float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 0.0] for p in arm_points],
        "hand_height_m": hand_height_m,
        "standoff_m": STANDOFF_M,
        "max_error_m": max_err,
        "rms_error_m": rms_err,
        "homography": homography.tolist(),
    }


def format_fit(calibration: dict) -> str:
    """One line, error in centimeters."""
    cm = float(calibration["max_error_m"]) * 100.0
    return f"max error {cm:.2f} cm"


def load_pairs(path: Path) -> tuple[list, list, float]:
    """Read explore page 42's pairs.json. Extra fields are ignored. Arm x,y are meters."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    image_points = [[float(point[0]), float(point[1])] for point in payload["image_points"]]
    height = payload.get("hand_height_m")
    arm_points = []
    for point in payload["arm_points"]:
        x, y = float(point[0]), float(point[1])
        z = float(point[2]) if len(point) > 2 else float(height if height is not None else 0.18)
        arm_points.append([x, y, z])
    if height is None:
        height = arm_points[0][2] if arm_points else 0.18
    return image_points, arm_points, float(height)


def parse_guided_lines(lines: list[str]) -> tuple[list, list]:
    """Each line is pixel_x pixel_y arm_x arm_y arm_z. Blank lines are skipped."""
    image_points = []
    arm_points = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        parts = [float(part) for part in line.replace(",", " ").split()]
        if len(parts) != 5:
            raise ValueError("expected pixel_x pixel_y arm_x arm_y arm_z")
        image_points.append(parts[:2])
        arm_points.append(parts[2:])
    return image_points, arm_points


def fake_calibration() -> dict:
    """A stand-in fit so `python -m vision --fake` can post a hand target.

    The synthetic palm (about 335, 353 on a 640x480 frame) maps near the
    controller's saved handoff spot, inside arm/rig.json's handoff region.
    """
    image_points = [[335, 353], [435, 353], [435, 253], [235, 253], [300, 300], [380, 320]]
    arm_points = [
        [0.264, -0.120, 0.18],
        [0.344, -0.120, 0.18],
        [0.344, -0.040, 0.18],
        [0.184, -0.040, 0.18],
        [0.236, -0.080, 0.18],
        [0.300, -0.090, 0.18],
    ]
    return calibration_from_points(image_points, arm_points, hand_height_m=0.18)


def save_calibration(path: Path, calibration: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(calibration, indent=2), encoding="utf-8")


def load_calibration(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _read_guided(hand_height: float) -> tuple[list, list, float]:
    print("Gripper points. One per line: pixel_x pixel_y arm_x arm_y arm_z")
    print("Arm x,y,z are meters. 6 to 8 points. A blank line finishes.")
    lines = []
    index = 1
    while True:
        try:
            line = input(f"point {index}> ")
        except EOFError:
            break
        if not line.strip():
            break
        lines.append(line)
        index += 1
    image_points, arm_points = parse_guided_lines(lines)
    return image_points, arm_points, hand_height


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Fit vision/calibration.json from gripper points")
    parser.add_argument("--pairs", help="JSON from explore page 42 (image_points, arm_points, hand_height_m)")
    parser.add_argument("--points", help="text file of guided lines: pixel_x pixel_y arm_x arm_y arm_z")
    parser.add_argument("--out", default="vision/calibration.json")
    parser.add_argument("--hand-height", type=float, default=0.18)
    args = parser.parse_args(argv)

    if args.pairs:
        image_points, arm_points, height = load_pairs(Path(args.pairs))
        if any(abs(float(p[0])) > 20.0 or abs(float(p[1])) > 20.0 for p in arm_points):
            arm_points = [[p[0] / 1000.0, p[1] / 1000.0, (p[2] / 1000.0 if len(p) > 2 else 0.0)] for p in arm_points]
    elif args.points:
        image_points, arm_points = parse_guided_lines(Path(args.points).read_text(encoding="utf-8").splitlines())
        height = args.hand_height
    else:
        image_points, arm_points, height = _read_guided(args.hand_height)

    calibration = calibration_from_points(image_points, arm_points, height)
    save_calibration(Path(args.out), calibration)
    print(format_fit(calibration))
    print(f"wrote {args.out}")
    if calibration["max_error_m"] > 0.02:
        print("error is over 2 cm; remeasure the points")


if __name__ == "__main__":
    main()
