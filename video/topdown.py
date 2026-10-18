"""Plane-only geometry and static photo plates; never synthesize task outcomes."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .common import encode, frames, info, provenance, read_json, save_provenance, stamp
from .geometry import homography, tracked_points


def calibration(ws, camera):
    doc = read_json(ws.source("corners.json"))
    if camera not in doc["cameras"]:
        raise ValueError("Run corners for this camera first")
    return doc["cameras"][camera]


def warp(ws, source, camera, output, track=True):
    source, output = ws.source(source), ws.out(output)
    if source == output:
        raise ValueError("Never overwrite a source")
    config = calibration(ws, camera)
    meta, details = provenance(source), info(source)
    points = np.float32(config["points"])
    matrix, size = homography(points, config["width_mm"], config["height_mm"])
    if [details["width"], details["height"]] != config["source_size"]:
        raise ValueError("Corners were measured on a different source resolution")
    if details["media"] == "image":
        result = stamp(cv2.warpPerspective(cv2.imread(str(source)), matrix, size), meta)
        cv2.imwrite(str(output), result)
    else:
        def images():
            current_points, previous = points.copy(), None
            for _t, frame in frames(source):
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                if track and previous is not None:
                    current_points = tracked_points(previous, gray, current_points)
                previous = gray
                transform, _ = homography(current_points, config["width_mm"], config["height_mm"])
                yield stamp(cv2.warpPerspective(frame, transform, size), meta)
        encode(ws, output, images(), details["fps"], audio=source)
    return save_provenance(output, source, **{k:v for k,v in info(output).items() if k in {"width","height","fps","frames","duration_s"}}, operations=meta.get("operations", [])+[
        {"command": "topdown warp", "pixels_per_mm": 2, "track": track,
         "camera": camera, "warning": "Table-plane warp only. Elevated arm/hand geometry is distorted."}])


def align_photo(image, reference):
    sift = cv2.SIFT_create(nfeatures=5000)
    key1, des1 = sift.detectAndCompute(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), None)
    key2, des2 = sift.detectAndCompute(cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY), None)
    if des1 is None or des2 is None:
        raise ValueError("Photo has insufficient SIFT texture")
    pairs = cv2.BFMatcher().knnMatch(des1, des2, k=2)
    good = [a for pair in pairs if len(pair) == 2 for a,b in [pair] if a.distance < .72*b.distance]
    if len(good) < 12:
        raise ValueError("Fewer than 12 reliable photo matches; capture more overlap")
    src = np.float32([key1[m.queryIdx].pt for m in good])
    dst = np.float32([key2[m.trainIdx].pt for m in good])
    matrix, mask = cv2.findHomography(src, dst, cv2.RANSAC, 2.5)
    if matrix is None or mask is None or np.count_nonzero(mask) < 10 or mask.mean() < .4:
        raise ValueError("Photo RANSAC alignment unreliable")
    h, w = image.shape[:2]
    bounds = cv2.perspectiveTransform(np.float32([[[0,0],[w,0],[w,h],[0,h]]]), matrix)[0]
    if not np.isfinite(bounds).all() or not .25*w*h < abs(cv2.contourArea(bounds)) < 4*w*h:
        raise ValueError("Photo homography has implausible scale")
    error = np.linalg.norm(cv2.perspectiveTransform(src[None], matrix)[0] - dst, axis=1)
    if np.median(error[mask.ravel().astype(bool)]) > 2:
        raise ValueError("Photo reprojection error too high")
    return matrix, {"matches": len(good), "inliers": int(np.count_nonzero(mask)),
                    "median_error_px": float(np.median(error[mask.ravel().astype(bool)]))}


def photo_plate(ws, reference, photos, camera, output, empty_scene=False):
    if not empty_scene:
        raise ValueError("Photo plates require --empty-scene: confirm no people/arm and unchanged instrument layout")
    reference, directory, output = ws.source(reference), ws.source(photos), ws.out(output)
    ref = cv2.imread(str(reference))
    if ref is None:
        raise ValueError("Reference photo unreadable")
    config = calibration(ws, camera)
    if str(reference) != config["source"]:
        raise ValueError("Calibrate corners on the exact reference photo before plate alignment")
    plane, size = homography(config["points"], config["width_mm"], config["height_mm"])
    images, reports, synthetic = [], [], False
    for path in sorted(directory.glob("*")):
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            continue
        image = cv2.imread(str(path))
        if image is None:
            raise ValueError("Unreadable plate photo")
        matrix, report = (np.eye(3), {"reference": True}) if path == reference else align_photo(image, ref)
        warped = cv2.warpPerspective(image, plane @ matrix, size)
        valid = cv2.warpPerspective(np.ones(image.shape[:2], np.uint8), plane @ matrix, size,
                                    flags=cv2.INTER_NEAREST).astype(bool)
        sample = warped.astype(np.float32)
        sample[~valid] = np.nan
        images.append(sample)
        reports.append({"photo": path.name, **report})
        synthetic = synthetic or provenance(path).get("synthetic", False)
    if not images:
        raise ValueError("No photos for plate")
    blended = np.nanmedian(np.stack(images), axis=0)
    if not np.isfinite(blended).all():
        raise ValueError("Plate has uncovered pixels; do not inpaint evidence")
    meta = {"kind": "photo_plate", "synthetic": synthetic}
    cv2.imwrite(str(output), stamp(blended.astype(np.uint8), meta))
    cv2.imwrite(str(ws.out("previews/plate-labeled.png")), stamp(blended.astype(np.uint8), meta))
    return save_provenance(output, kind="photo_plate", synthetic=synthetic,
        source_photos=[str(p) for p in sorted(directory.glob("*")) if p.suffix.lower() in {".png", ".jpg", ".jpeg"}],
        operations=[{"command": "topdown photo plate", "method": "SIFT/RANSAC/median",
                     "empty_scene_operator_confirmed": True, "alignment": reports}],
        note="Static illustrative background only, not action footage. Render always adds PHOTO PLATE disclosure.")
