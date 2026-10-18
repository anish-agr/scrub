"""Draw slot boxes, detection boxes, and the palm dot on a preview frame."""

from __future__ import annotations

import cv2


def annotate(frame, hand: dict | None, tray: dict | None, detections: list | None):
    image = frame.copy()
    if tray:
        for slot in tray.get("slots") or []:
            box = slot.get("box")
            if not box:
                continue
            color = (0, 180, 0) if slot.get("present") else (0, 0, 210)
            x1, y1, x2, y2 = [int(v) for v in box]
            cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
            label = slot.get("item") or ""
            if not slot.get("present"):
                label = label + " out"
            cv2.putText(image, label, (x1, max(16, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
        return_spot = tray.get("return_spot") or {}
        return_box = return_spot.get("box")
        return_item = return_spot.get("item")
        if return_box:
            x1, y1, x2, y2 = [int(v) for v in return_box]
            if return_item:
                # Highlight occupied return spot
                cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 255), 3)
                cv2.putText(image, f"RETURN: {return_item}", (x1, max(16, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2, cv2.LINE_AA)
            else:
                cv2.rectangle(image, (x1, y1), (x2, y2), (255, 180, 0), 2)
                cv2.putText(image, "return", (x1, max(16, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 180, 0), 1, cv2.LINE_AA)
        if tray.get("stale"):
            cv2.putText(image, "tray stale", (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2, cv2.LINE_AA)

    for detection in detections or []:
        point_box = detection.get("point_box")
        if not point_box:
            continue
        top_left = point_box.get("top_left") or {}
        bottom_right = point_box.get("bottom_right") or {}
        if "x" not in top_left or "x" not in bottom_right:
            continue
        x1, y1 = int(top_left["x"]), int(top_left["y"])
        x2, y2 = int(bottom_right["x"]), int(bottom_right["y"])
        cv2.rectangle(image, (x1, y1), (x2, y2), (0, 220, 255), 1)
        mention = detection.get("mention", "")
        conf = detection.get("confidence")
        if conf is not None and isinstance(conf, (int, float)):
            label = f"{mention} ({conf:.2f})"
        else:
            label = mention
        if label:
            cv2.putText(image, label, (x1, min(y2 + 14, image.shape[0] - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 220, 255), 1, cv2.LINE_AA)

    if hand and hand.get("seen") and hand.get("palm_px"):
        px, py = int(hand["palm_px"][0]), int(hand["palm_px"][1])
        color = (255, 255, 0) if hand.get("open") else (0, 140, 255)

        # Show handoff target if calibrated target exists
        target = hand.get("target")
        target_px = hand.get("target_px")
        if target is not None and target_px and len(target_px) == 2:
            tx, ty = int(target_px[0]), int(target_px[1])
            cv2.line(image, (px, py), (tx, ty), (0, 255, 150), 1, cv2.LINE_AA)
            cv2.circle(image, (tx, ty), 10, (0, 255, 0), 2, cv2.LINE_AA)
            cv2.drawMarker(image, (tx, ty), (0, 255, 0), cv2.MARKER_CROSS, 14, 1, cv2.LINE_AA)
            cv2.putText(image, "target", (tx + 12, ty + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1, cv2.LINE_AA)

        # Draw palm dot on top
        cv2.circle(image, (px, py), 8, color, -1)
        if hand.get("path_clear") is False:
            cv2.putText(image, "path blocked", (px + 12, py), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2, cv2.LINE_AA)
    return image


def jpeg_bytes(frame, quality: int = 70) -> bytes:
    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        return b""
    return encoded.tobytes()
