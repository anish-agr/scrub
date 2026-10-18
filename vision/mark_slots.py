"""Click each slot and the return spot. Prints boxes for Evan to put in settings/."""

from __future__ import annotations

import json
from pathlib import Path

from vision.tray import load_setting


def boxes_from_clicks(clicks: list[tuple[float, float]]) -> list[list[float]]:
    boxes = []
    for index in range(0, len(clicks) - 1, 2):
        x1, y1 = clicks[index]
        x2, y2 = clicks[index + 1]
        boxes.append([min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)])
    return boxes


def labeled_boxes(setting: dict, boxes: list[list[float]]) -> dict:
    """boxes are one per item, in order, then the return spot."""
    items = setting.get("items") or []
    needed = len(items) + 1
    if len(boxes) < needed:
        raise ValueError(f"need {needed} boxes ({len(items)} slots plus the return spot), got {len(boxes)}")
    slots = {}
    for item, box in zip(items, boxes):
        slots[item["id"]] = [int(round(v)) for v in box]
    return_spot = [int(round(v)) for v in boxes[len(items)]]
    return {"setting": setting.get("id"), "slots": slots, "return_spot": return_spot}


def apply_marks(setting: dict, marked: dict) -> dict:
    """Settings file with slot and return_spot filled. Other fields stay as they were."""
    updated = json.loads(json.dumps(setting))
    slots = marked["slots"]
    for item in updated.get("items") or []:
        item["slot"] = slots[item["id"]]
    updated["return_spot"] = marked["return_spot"]
    return updated


def scripted_clicks(n_items: int) -> list[tuple[float, float]]:
    """Two corners per item, then the return spot. Used by --fake."""
    clicks: list[tuple[float, float]] = []
    for index in range(n_items + 1):
        x1 = 30 + index * 150
        y1 = 40 if index < n_items else 320
        clicks.append((float(x1), float(y1)))
        clicks.append((float(x1 + 110), float(y1 + 70)))
    return clicks


def save_frame(capture, path: Path) -> Path:
    ok, frame = capture.read()
    if not ok or frame is None:
        raise RuntimeError("camera returned no frame")
    path.parent.mkdir(parents=True, exist_ok=True)
    import cv2

    if not cv2.imwrite(str(path), frame):
        raise RuntimeError(f"could not write {path}")
    return path


def grab_live_frame(path: Path, index: int = 0, fake: bool = False) -> Path:
    from vision.camera import FakeCapture, open_capture

    if fake:
        capture = FakeCapture()
    else:
        capture = open_capture(index)
        if not capture.isOpened():
            raise SystemExit(f"could not open camera {index}")
    try:
        return save_frame(capture, path)
    finally:
        release = getattr(capture, "release", None)
        if release:
            release()


def format_for_evan(marked: dict) -> str:
    lines = [f"Send these boxes to Evan for settings/{marked['setting']}.json", ""]
    for item_id, box in marked["slots"].items():
        lines.append(f"{item_id} {box}")
    lines.append(f"return_spot {marked['return_spot']}")
    return "\n".join(lines)


def _parse_clicks(text: str) -> list[tuple[float, float]]:
    numbers = [float(part) for part in text.replace(",", " ").split()]
    if len(numbers) % 2 != 0:
        raise ValueError("clicks must be x,y pairs")
    return list(zip(numbers[0::2], numbers[1::2]))


def apply_boxes_to_setting(setting: dict, marked: dict) -> dict:
    """Return a copy of the setting document with slot and return_spot boxes filled in."""
    updated = json.loads(json.dumps(setting))
    slots = marked.get("slots", {})
    for item in updated.get("items") or []:
        if item["id"] in slots:
            item["slot"] = slots[item["id"]]
    if "return_spot" in marked:
        updated["return_spot"] = marked["return_spot"]
    return updated


def _fake_clicks(num_items: int) -> list[tuple[float, float]]:
    clicks = []
    default_boxes = [
        (100.0, 80.0, 240.0, 140.0),
        (260.0, 80.0, 400.0, 140.0),
        (420.0, 80.0, 560.0, 140.0),
    ]
    for i in range(num_items):
        b = default_boxes[i % len(default_boxes)]
        clicks.extend([(b[0], b[1]), (b[2], b[3])])
    # return spot
    clicks.extend([(400.0, 300.0), (520.0, 380.0)])
    return clicks


def _click_on_frame(image, prompts: list[str]) -> list[tuple[float, float]]:
    import cv2

    clicks: list[tuple[float, float]] = []
    window = "mark slots"

    def on_mouse(event, x, y, _flags, _param):
        if event == cv2.EVENT_LBUTTONDOWN:
            clicks.append((float(x), float(y)))

    cv2.namedWindow(window)
    cv2.setMouseCallback(window, on_mouse)
    needed = len(prompts) * 2
    while len(clicks) < needed:
        shown = image.copy()
        prompt = prompts[len(clicks) // 2]
        corner = "top-left" if len(clicks) % 2 == 0 else "bottom-right"
        cv2.putText(shown, f"{prompt} {corner}", (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        for x, y in clicks:
            cv2.circle(shown, (int(x), int(y)), 4, (0, 255, 255), -1)
        cv2.imshow(window, shown)
        if cv2.waitKey(20) == 27:
            break
    cv2.destroyWindow(window)
    return clicks


def _write_setting(out: Path, document: dict) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _mark_one(repo: Path, setting_id: str, clicks: list[tuple[float, float]], out: Path) -> dict:
    setting = load_setting(repo, setting_id)
    marked = labeled_boxes(setting, boxes_from_clicks(clicks))
    document = apply_marks(setting, marked)
    _write_setting(out, document)
    print(format_for_evan(marked))
    print(f"wrote {out}")
    return document


def _click_on_image(image_path: Path, prompts: list[str]) -> list[tuple[float, float]]:
    import cv2

    image = cv2.imread(str(image_path))
    if image is None:
        raise SystemExit(f"could not read {image_path}")
    return _click_on_frame(image, prompts)


def _grab_live_frame(fake: bool = False):
    import os
    from vision.camera import FakeCapture, open_capture

    if fake:
        capture = FakeCapture()
    else:
        index = int(os.environ.get("CAMERA_INDEX", "0"))
        capture = open_capture(index)
    ok, frame = capture.read()
    if hasattr(capture, "release"):
        capture.release()
    if not ok or frame is None:
        raise RuntimeError("could not grab live frame")
    return frame


def mark_setting(
    setting_id: str,
    repo: Path,
    clicks: list[tuple[float, float]] | None = None,
    image_path: Path | None = None,
    live_frame=None,
    fake: bool = False,
    out_path: Path | None = None,
    write_settings: bool = False,
) -> dict:
    setting = load_setting(repo, setting_id)
    items = setting.get("items") or []
    prompts = [item["id"] for item in items] + ["return_spot"]

    if clicks is not None:
        c = clicks
    elif fake:
        c = _fake_clicks(len(items))
    elif image_path is not None:
        c = _click_on_image(image_path, prompts)
    elif live_frame is not None:
        c = _click_on_frame(live_frame, prompts)
    else:
        frame = _grab_live_frame(fake=False)
        c = _click_on_frame(frame, prompts)

    marked = labeled_boxes(setting, boxes_from_clicks(c))
    setting_format = apply_boxes_to_setting(setting, marked)

    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(marked, indent=2), encoding="utf-8")
        print(f"wrote {out_path}")

    if write_settings:
        settings_file = repo / "settings" / f"{setting_id}.json"
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        settings_file.write_text(json.dumps(setting_format, indent=2), encoding="utf-8")
        print(f"wrote {settings_file}")

    return marked


def main(argv: list[str] | None = None) -> None:
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Mark slot boxes on a tray photo or live frame")
    parser.add_argument("--setting", default="surgical")
    parser.add_argument("--all", action="store_true", help="process the surgical and bench settings (dental is hidden; use --setting dental)")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--clicks", help="x,y,x,y,... two corners per slot, then the return spot")
    parser.add_argument("--image", help="saved tray photo to click on")
    parser.add_argument("--live", action="store_true", help="grab one frame from the overhead camera, then click")
    parser.add_argument("--fake", action="store_true", help="write boxes for all three trays, no camera and no window")
    parser.add_argument("--write-settings", action="store_true", help="write boxes directly to settings/<id>.json in settings format")
    parser.add_argument("--out", help="JSON file, or a directory when --fake writes all three")
    args = parser.parse_args(argv)

    repo = Path(args.repo)
    if args.fake:
        out_path = Path(args.out) if args.out else repo / "vision" / "marked"
        if out_path.suffix == ".json" and not args.all:
            # Single file output
            setting = load_setting(repo, args.setting)
            clicks = scripted_clicks(len(setting.get("items") or []))
            _mark_one(repo, args.setting, clicks, out_path)
            return
        folder = out_path
        folder.mkdir(parents=True, exist_ok=True)
        for setting_id in ("surgical", "bench"):
            setting = load_setting(repo, setting_id)
            frame_path = folder / f"{setting_id}.jpg"
            grab_live_frame(frame_path, fake=True)
            clicks = scripted_clicks(len(setting.get("items") or []))
            _mark_one(repo, setting_id, clicks, folder / f"{setting_id}.json")
            if args.write_settings:
                apply_boxes_to_setting(setting, labeled_boxes(setting, boxes_from_clicks(clicks)))
        return

    settings_to_run = ["surgical", "bench"] if args.all else [args.setting]
    for s in settings_to_run:
        setting = load_setting(repo, s)
        prompts = [item["id"] for item in setting.get("items") or []] + ["return_spot"]
        image_path = Path(args.image) if args.image else None
        if args.live:
            index = int(os.environ.get("CAMERA_INDEX", "0"))
            image_path = image_path or repo / "vision" / "marked" / f"{s}.jpg"
            grab_live_frame(image_path, index=index, fake=False)
            print(f"saved {image_path}")
        if args.clicks:
            if image_path is not None:
                import cv2

                if cv2.imread(str(image_path)) is None:
                    raise SystemExit(f"could not read {image_path}")
            clicks = _parse_clicks(args.clicks)
        elif image_path is not None:
            clicks = _click_on_image(image_path, prompts)
        else:
            raise SystemExit("pass --fake, --clicks, --image, or --live")

        out = Path(args.out) if (args.out and not args.all) else repo / "vision" / "marked" / f"{s}.json"
        _mark_one(repo, s, clicks, out)
        if args.write_settings:
            marked = labeled_boxes(setting, boxes_from_clicks(clicks))
            setting_doc = apply_marks(setting, marked)
            _write_setting(repo / "settings" / f"{s}.json", setting_doc)


if __name__ == "__main__":
    main()
