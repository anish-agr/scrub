"""Markerless tray geometry, explicit physical scale and optical-flow tracking."""
from __future__ import annotations

import cv2
import numpy as np

from .common import finite, frame_at, info, provenance, read_json, stamp, write_json


def order_corners(points):
    points = np.asarray(points, np.float32)
    if points.shape != (4, 2) or not np.isfinite(points).all():
        raise ValueError("Four finite image points required")
    center = points.mean(axis=0)
    points = points[np.argsort(np.arctan2(points[:, 1]-center[1], points[:, 0]-center[0]))]
    points = np.roll(points, -np.argmin(points.sum(axis=1)), axis=0)
    if not cv2.isContourConvex(points.reshape(-1, 1, 2)) or cv2.contourArea(points) < 100:
        raise ValueError("Corners must be a non-degenerate convex tray quadrilateral")
    return points


def detect_corners(image):
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    light = cv2.inRange(hsv, (0, 0, 120), (179, 100, 255))
    light = cv2.morphologyEx(light, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    contours, _ = cv2.findContours(light, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < image.shape[0]*image.shape[1]*.03:
            continue
        for epsilon in (.01, .02, .03, .04):
            approx = cv2.approxPolyDP(contour, epsilon*cv2.arcLength(contour, True), True)
            if len(approx) == 4 and cv2.isContourConvex(approx):
                points = order_corners(approx.reshape(4, 2))
                # Require actual blue towel around the rectangle, not a white title bar.
                region = np.zeros(image.shape[:2], np.uint8)
                cv2.fillConvexPoly(region, points.astype(np.int32), 255)
                ring = cv2.dilate(region, np.ones((31, 31), np.uint8)) - region
                blue = cv2.inRange(hsv, (85, 65, 30), (135, 255, 255))
                ratio = float(np.count_nonzero(blue[ring > 0])) / max(1, np.count_nonzero(ring))
                if ratio >= .25:
                    candidates.append((area, points))
                break
    if not candidates:
        raise ValueError("No light four-sided tray on blue towel found; use --points or drag-to-fix")
    return max(candidates, key=lambda item: item[0])[1]


def homography(points, width_mm, height_mm):
    width_mm = finite(width_mm, "measured tray width", True)
    height_mm = finite(height_mm, "measured tray height", True)
    # Pixel-center convention spans the measured edge-to-edge extent exactly.
    width, height = int(round(width_mm * 2)), int(round(height_mm * 2))
    if min(width, height) < 20 or max(width, height) > 8192 or width % 2 or height % 2:
        raise ValueError("2 px/mm output needs even dimensions in 20..8192 pixels")
    destination = np.float32([[0, 0], [width-1, 0], [width-1, height-1], [0, height-1]])
    return cv2.getPerspectiveTransform(order_corners(points), destination), (width, height)


def review_corners(image, points):
    """Native OpenCV drag UI. Enter saves; Escape cancels without changing calibration."""
    scale = min(1.0, 1200 / image.shape[1], 800 / image.shape[0])
    points = np.asarray(points, np.float32).copy() * scale
    selected = [None]
    title = "Scrub tray: drag corners; Enter saves; Esc cancels"
    def mouse(event, x, y, flags, _):
        if event == cv2.EVENT_LBUTTONDOWN:
            distances = np.linalg.norm(points - [x, y], axis=1)
            selected[0] = int(np.argmin(distances)) if distances.min() < 40 else None
        elif event == cv2.EVENT_MOUSEMOVE and selected[0] is not None:
            points[selected[0]] = (x, y)
        elif event == cv2.EVENT_LBUTTONUP:
            selected[0] = None
    cv2.namedWindow(title)
    cv2.setMouseCallback(title, mouse)
    try:
        while True:
            preview = cv2.resize(image, None, fx=scale, fy=scale)
            cv2.polylines(preview, [points.astype(np.int32)], True, (0, 255, 255), 2)
            for n, point in enumerate(points.astype(int)):
                cv2.circle(preview, tuple(point), 9, (0, 0, 255), -1)
                cv2.putText(preview, ("TL", "TR", "BR", "BL")[n], tuple(point+[12, -8]),
                            cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 0, 0), 2)
            cv2.imshow(title, preview)
            key = cv2.waitKey(30) & 0xFF
            if key in (10, 13):
                return order_corners(points/scale)
            if key == 27 or cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                raise ValueError("Corner review cancelled; nothing saved")
    finally:
        cv2.destroyWindow(title)


def corners(ws, source, camera, width_mm, height_mm, points=None, headless=False, accept_auto=False):
    if not camera or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in camera):
        raise ValueError("Camera label must contain only letters, digits, underscore or hyphen")
    source = ws.source(source)
    media = info(source)
    image = cv2.imread(str(source)) if media["media"] == "image" else frame_at(source)
    method = "operator points"
    if points is None:
        try:
            points = detect_corners(image)
            method = "color segmentation + largest blue-surrounded quadrilateral"
        except ValueError:
            if headless:
                raise
            h, w = image.shape[:2]
            points = np.float32([[w*.2, h*.2], [w*.8, h*.2], [w*.8, h*.8], [w*.2, h*.8]])
            method = "manual drag; automatic detection failed"
    if headless and not accept_auto:
        raise ValueError("Headless calibration requires --accept-auto; otherwise review by dragging")
    points = order_corners(points) if headless else review_corners(image, points)
    if np.any(points < 0) or np.any(points[:, 0] >= image.shape[1]) or np.any(points[:, 1] >= image.shape[0]):
        raise ValueError("Corner outside source image")
    matrix, size = homography(points, width_mm, height_mm)
    path = ws.out("corners.json")
    doc = read_json(path) if path.exists() else {"schema_version": 1, "cameras": {}}
    doc["cameras"][camera] = {"points": points.tolist(), "width_mm": float(width_mm), "height_mm": float(height_mm),
        "pixels_per_mm": 2, "matrix": matrix.tolist(), "size": list(size), "source": str(source),
        "source_size": [image.shape[1], image.shape[0]], "frame_seconds": 0,
        "reviewed": not headless, "method": method, "kind": provenance(source)["kind"]}
    write_json(path, doc)
    preview = image.copy()
    cv2.polylines(preview, [points.astype(np.int32)], True, (0, 220, 220), 3)
    cv2.imwrite(str(ws.out(f"previews/corners-{camera}.png")), stamp(preview, provenance(source)))
    return {"corners_file": str(path), "camera": camera, **doc["cameras"][camera]}


def tracked_points(previous, current, points):
    """Forward/backward flow; fail closed when the plane can no longer be tracked."""
    # Track texture inside the tray, not four aperture-ambiguous edge pixels.
    region=np.zeros(previous.shape,np.uint8)
    cv2.fillConvexPoly(region,np.asarray(points,np.int32),255)
    region=cv2.erode(region,np.ones((9,9),np.uint8))
    p=cv2.goodFeaturesToTrack(previous,maxCorners=200,qualityLevel=.015,minDistance=8,mask=region)
    if p is None or len(p)<12:
        raise ValueError("Insufficient tray texture for optical flow; use locked-tripod --no-track only if actually locked")
    nxt, status, _ = cv2.calcOpticalFlowPyrLK(previous, current, p, None, winSize=(31, 31), maxLevel=3)
    if nxt is None:
        raise ValueError("Tray tracking lost; split clip and redo corners")
    back, valid, _ = cv2.calcOpticalFlowPyrLK(current, previous, nxt, None, winSize=(31, 31), maxLevel=3)
    if back is None:
        raise ValueError("Inconsistent tray optical flow; split clip and redo corners")
    keep=status.ravel().astype(bool)&valid.ravel().astype(bool)&(np.linalg.norm(back-p,axis=2).ravel()<1.5)
    if np.count_nonzero(keep)<12:
        raise ValueError("Tray texture tracking lost; split clip and redo corners")
    matrix,inliers=cv2.findHomography(p[keep],nxt[keep],cv2.RANSAC,1.5)
    if matrix is None or inliers is None or inliers.mean()<.6:
        raise ValueError("No dominant tray-plane optical flow")
    result=cv2.perspectiveTransform(np.float32(points)[None],matrix)[0]
    if np.max(np.linalg.norm(result-points, axis=1)) > 35:
        raise ValueError("Camera motion too large for plane tracking")
    if not .8<abs(cv2.contourArea(result))/abs(cv2.contourArea(np.float32(points)))<1.2:
        raise ValueError("Tray tracking changed scale implausibly")
    return order_corners(result)
