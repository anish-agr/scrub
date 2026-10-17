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


def _click_on_image(image_path: Path, prompts: list[str]) -> list[tuple[float, float]]:
    import cv2

    image = cv2.imread(str(image_path))
    if image is None:
        raise SystemExit(f"could not read {image_path}")
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


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Mark slot boxes on a tray photo")
    parser.add_argument("--setting", default="surgical")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--clicks", help="x,y,x,y,... two corners per slot, then the return spot")
    parser.add_argument("--image", help="tray photo to click on, if --clicks is omitted")
    parser.add_argument("--out", help="where to write the JSON (default vision/marked_slots_<setting>.json)")
    args = parser.parse_args(argv)

    repo = Path(args.repo)
    setting = load_setting(repo, args.setting)
    prompts = [item["id"] for item in setting.get("items") or []] + ["return_spot"]
    if args.clicks:
        clicks = _parse_clicks(args.clicks)
    elif args.image:
        clicks = _click_on_image(Path(args.image), prompts)
    else:
        raise SystemExit("pass --clicks or --image")

    marked = labeled_boxes(setting, boxes_from_clicks(clicks))
    text = format_for_evan(marked)
    print(text)
    out = Path(args.out) if args.out else repo / "vision" / f"marked_slots_{args.setting}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(marked, indent=2), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
