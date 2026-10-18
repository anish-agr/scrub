"""Fit the camera-to-table mapping from the gripper tip in the picture. No printed marker.

The tip is the small orange jaw in the sim render (color), or a compact bright blob (shape).
The arm positions are the true tip coordinates. `python -m vision.calibrate` is the manual path.
"""

from __future__ import annotations

import argparse

import cv2

from vision.calibrate import calibration_from_points


def find_gripper_tip(bgr: np.ndarray) -> tuple[float, float] | None:
    """Pixel of the gripper tip. Orange first (the sim jaw), then the tightest bright blob."""
    if bgr is None or bgr.size == 0:
        return None
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    orange = cv2.inRange(hsv, (5, 140, 140), (28, 255, 255))
    tip = _blob_center(orange)
    if tip is not None:
        return tip
    bright = cv2.inRange(hsv, (0, 0, 210), (180, 40, 255))
    return _blob_center(bright, min_area=8, max_area=400)


def _blob_center(mask: np.ndarray, min_area: float = 6, max_area: float = 2500) -> tuple[float, float] | None:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    best_area = 0.0
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area or area > max_area or area <= best_area:
            continue
        best = contour
        best_area = area
    if best is None:
        return None
    moments = cv2.moments(best)
    if moments["m00"] == 0:
        return None
    return moments["m10"] / moments["m00"], moments["m01"] / moments["m00"]


def paint_tip(frame: np.ndarray, pixel: tuple[float, float], radius: int = 5) -> np.ndarray:
    """Draw the sim jaw color at a pixel. Tests use this on a rendered or blank overhead frame."""
    image = frame.copy()
    cv2.circle(image, (int(round(pixel[0])), int(round(pixel[1]))), radius, (0, 140, 255), -1)
    return image


def fit_tip_points(image_points, arm_points, hand_height_m: float = 0.18) -> dict:
    calibration = calibration_from_points(image_points, arm_points, hand_height_m=hand_height_m)
    calibration["max_error_mm"] = round(float(calibration["max_error_m"]) * 1000.0, 2)
    calibration["source"] = "gripper_tip"
    return calibration


def calibrate_frames(frames_and_tips: list[tuple[np.ndarray, list[float]]], hand_height_m: float = 0.18) -> dict:
    """Each pair is an overhead frame and the true gripper tip in meters (x, y, z)."""
    image_points = []
    arm_points = []
    for frame, tip in frames_and_tips:
        pixel = find_gripper_tip(frame)
        if pixel is None:
            raise RuntimeError("gripper tip not visible")
        image_points.append([pixel[0], pixel[1]])
        arm_points.append([float(tip[0]), float(tip[1]), float(tip[2]) if len(tip) > 2 else 0.0])
    if len(image_points) < 4:
        raise RuntimeError("need at least 4 gripper points")
    return fit_tip_points(image_points, arm_points, hand_height_m)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Fit calibration.json from gripper-tip pixels")
    parser.add_argument("--out", default="vision/calibration.json")
    parser.add_argument("--hand-height", type=float, default=0.18)
    args = parser.parse_args(argv)
    print("Automatic fit needs overhead frames and true tip positions from the sim.")
    print("Use vision.auto_calibrate.calibrate_frames from a test, or python -m vision.calibrate to type points.")
    print(f"would write {args.out} at hand height {args.hand_height}")


if __name__ == "__main__":
    main()
