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
    error = reprojection_error_m(homography, image_points, arm_points)
    return {
        "image_points": [[float(p[0]), float(p[1])] for p in image_points],
        "arm_points": [[float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 0.0] for p in arm_points],
        "hand_height_m": hand_height_m,
        "standoff_m": STANDOFF_M,
        "max_error_m": error,
        "homography": homography.tolist(),
    }


def save_calibration(path: Path, calibration: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(calibration, indent=2), encoding="utf-8")


def load_calibration(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Fit vision/calibration.json from gripper points")
    parser.add_argument("--pairs", help="JSON file with image_points and arm_points")
    parser.add_argument("--out", default="vision/calibration.json")
    parser.add_argument("--hand-height", type=float, default=0.18)
    args = parser.parse_args(argv)

    if args.pairs:
        payload = json.loads(Path(args.pairs).read_text(encoding="utf-8"))
        image_points = payload["image_points"]
        arm_points = payload["arm_points"]
        height = float(payload.get("hand_height_m", args.hand_height))
    else:
        print("Type one point per line: pixel_x pixel_y arm_x arm_y arm_z")
        print("Need 6 to 8 points. Blank line finishes.")
        image_points = []
        arm_points = []
        while True:
            line = input("> ").strip()
            if not line:
                break
            parts = [float(part) for part in line.split()]
            if len(parts) != 5:
                print("expected 5 numbers")
                continue
            image_points.append(parts[:2])
            arm_points.append(parts[2:])
        height = args.hand_height

    calibration = calibration_from_points(image_points, arm_points, height)
    save_calibration(Path(args.out), calibration)
    print(f"max error {calibration['max_error_m'] * 100:.2f} cm")
    print(f"wrote {args.out}")
    if calibration["max_error_m"] > 0.02:
        print("error is over 2 cm; remeasure the points")


if __name__ == "__main__":
    main()
