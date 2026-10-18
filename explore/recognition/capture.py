"""Capture labeled photos for the recognition bench.

Live:    .venv/bin/python -m explore.recognition.capture --set tray1 --camera overhead
Import:  .venv/bin/python -m explore.recognition.capture --set tray1 --import ~/Downloads/phone --light normal
Fake:    .venv/bin/python -m explore.recognition.capture --set try --frames explore/recognition/props --data /tmp/rec
         (loops saved images as the camera; the same window and keys, no camera opened)

Files land in data/recognition/<set>/<label>_<n>.jpg with a labels.json that
explore/recognition/bench.py reads (`items` and `boxes`; the other keys are extra).
Camera indexes: overhead = CAMERA_INDEX (env, default 0), side = CAPTURE_SIDE_INDEX
(default 1), wrist = CAPTURE_WRIST_INDEX (default 2). Or pass a number.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "recognition"
LIGHTS = ["bright", "normal", "dim"]
IMPORT_EXTS = {".jpg", ".jpeg", ".png"}
CAMERA_DEFAULTS = {"overhead": ("CAMERA_INDEX", 0), "side": ("CAPTURE_SIDE_INDEX", 1), "wrist": ("CAPTURE_WRIST_INDEX", 2)}
# keys reserved for actions: space, q, l, [ and ]
KEY_CHARS = "1234567890abcdefghijkmnoprstuvwxyz"
FIXED_LABELS = ["glove_blue", "glove_white", "count_sheet_clean", "count_sheet_written", "count_sheet_angle",
                "tray_tag", "pack_label", "pack_label_angle"]


def load_setting(name: str) -> dict:
    return json.loads((ROOT / "settings" / f"{name}.json").read_text(encoding="utf-8"))


def item_ids(setting: dict) -> list[str]:
    return [i["id"] for i in setting["items"]]


def label_list(setting: dict) -> list[str]:
    ids = item_ids(setting)
    return (["full"] + [f"no_{i}" for i in ids] + [f"alone_{i}" for i in ids]
            + [f"grip_{i}" for i in ids] + FIXED_LABELS)


def items_for(label: str, ids: list[str]) -> list[str]:
    """Item ids present in the photo. Props carry no instruments. Gloves are held over a full tray."""
    if label in ("full", "glove_blue", "glove_white"):
        return list(ids)
    if label.startswith("no_") and label[3:] in ids:
        return [i for i in ids if i != label[3:]]
    for prefix in ("alone_", "grip_"):
        if label.startswith(prefix) and label[len(prefix):] in ids:
            return [label[len(prefix):]]
    return []


def key_map(labels: list[str]) -> dict[str, str]:
    """One key per label, in order. Raises if there are more labels than keys."""
    if len(labels) > len(KEY_CHARS):
        raise ValueError(f"{len(labels)} labels, only {len(KEY_CHARS)} keys")
    return dict(zip(KEY_CHARS, labels))


def next_filename(folder: Path, label: str) -> str:
    n = 1
    while (folder / f"{label}_{n}.jpg").exists():
        n += 1
    return f"{label}_{n}.jpg"


def read_labels(folder: Path) -> dict:
    p = folder / "labels.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def update_labels(folder: Path, name: str, entry: dict) -> None:
    labels = read_labels(folder)
    labels[name] = entry
    tmp = folder / "labels.json.tmp"
    tmp.write_text(json.dumps(labels, indent=1), encoding="utf-8")
    os.replace(tmp, folder / "labels.json")


def entry_for(label: str, ids: list[str], camera: str, light: str, t: float | None = None) -> dict:
    if light not in LIGHTS:
        raise ValueError(f"light must be one of {LIGHTS}")
    return {"items": items_for(label, ids), "boxes": {}, "label": label, "camera": camera, "light": light,
            "t": time.time() if t is None else t}


def save_frame(folder: Path, label: str, frame, ids: list[str], camera: str, light: str) -> str:
    import cv2
    folder.mkdir(parents=True, exist_ok=True)
    name = next_filename(folder, label)
    if not cv2.imwrite(str(folder / name), frame):
        raise OSError(f"could not write {folder / name}")
    update_labels(folder, name, entry_for(label, ids, camera, light))
    return name


def match_label(stem: str, labels: list[str]) -> str | None:
    """Longest known label that starts the file stem and ends at the stem end or a separator."""
    s = stem.lower()
    for label in sorted(labels, key=len, reverse=True):
        if s == label or (s.startswith(label) and s[len(label)] in "_- ."):
            return label
    return None


def import_folder(src: Path, folder: Path, labels: list[str], ids: list[str], light: str) -> tuple[list[str], list[str]]:
    """Copy labeled phone photos in as jpg. Returns (saved names, skip messages)."""
    import cv2
    saved, skipped = [], []
    for f in sorted(src.iterdir()):
        if not f.is_file() or f.name.startswith("."):
            continue
        ext = f.suffix.lower()
        if ext == ".heic":
            skipped.append(f"{f.name}: heic is not supported, export as jpg")
            continue
        if ext not in IMPORT_EXTS:
            skipped.append(f"{f.name}: not a jpg, jpeg or png")
            continue
        label = match_label(f.stem, labels)
        if label is None:
            skipped.append(f"{f.name}: name does not start with a known label")
            continue
        img = cv2.imread(str(f))
        if img is None:
            skipped.append(f"{f.name}: could not read the image")
            continue
        saved.append(save_frame(folder, label, img, ids, "phone", light))
    return saved, skipped


def camera_index(camera: str) -> int:
    if camera.isdigit():
        return int(camera)
    if camera not in CAMERA_DEFAULTS:
        raise ValueError("camera must be overhead, side, wrist or a number")
    env, default = CAMERA_DEFAULTS[camera]
    return int(os.environ.get(env, default))


def print_keys(keys: dict[str, str]) -> None:
    print("A label key selects the label and saves a frame. SPACE saves with the current label.")
    print("[ and ] change label, l changes light, q or Esc quits.")
    for k, lab in keys.items():
        print(f"  {k}  {lab}")


class FolderCapture:
    """A fake camera: saved images (jpg, jpeg, png) in name order, looped. For testing without a camera."""

    def __init__(self, src: Path):
        import cv2
        self.frames = [f for f in (cv2.imread(str(p)) for p in sorted(Path(src).iterdir())
                                   if p.suffix.lower() in IMPORT_EXTS) if f is not None]
        self.i = 0

    def isOpened(self) -> bool:  # noqa: N802 - same name as cv2.VideoCapture
        return bool(self.frames)

    def read(self):
        if not self.frames:
            return False, None
        f = self.frames[self.i % len(self.frames)]
        self.i += 1
        return True, f.copy()

    def set(self, *_):
        return True

    def release(self):
        pass


def run_live(folder: Path, labels: list[str], ids: list[str], camera: str, light: str,
             cap=None, show=None, wait_key=None) -> None:
    """The capture loop. cap, show(view) and wait_key() -> int default to the camera and an OpenCV window;
    tests pass a FolderCapture and scripted keys."""
    import cv2
    keys = key_map(labels)
    by_label = {v: k for k, v in keys.items()}
    print_keys(keys)
    gui = show is None
    show = show or (lambda view: cv2.imshow("scrub capture", view))
    wait_key = wait_key or (lambda: cv2.waitKey(1))
    if cap is None:
        cap = cv2.VideoCapture(camera_index(camera))
    if not cap.isOpened():
        raise SystemExit(f"could not open camera {camera}")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cur, counts, msg = 0, {}, ""
    font = cv2.FONT_HERSHEY_SIMPLEX
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.05)
                continue
            view = frame.copy()
            head = f"label: {labels[cur]} [{by_label[labels[cur]]}]   light: {light}   camera: {camera}"
            cv2.putText(view, head, (8, 22), font, 0.6, (0, 255, 0), 2)
            cv2.putText(view, msg, (8, 46), font, 0.6, (0, 255, 0), 2)
            x, y = 8, 70
            for k, lab in keys.items():
                text = f"{k}:{lab}({counts.get(lab, 0)})"
                (w, _), _ = cv2.getTextSize(text, font, 0.4, 1)
                if x + w > view.shape[1] - 8:
                    x, y = 8, y + 16
                cv2.putText(view, text, (x, y), font, 0.4, (255, 255, 0), 1)
                x += w + 10
            show(view)
            k = wait_key() & 0xFF
            ch = chr(k) if 0 < k < 128 else ""
            if k == 27 or ch == "q":
                break
            if ch == "l":
                light = LIGHTS[(LIGHTS.index(light) + 1) % len(LIGHTS)]
                continue
            if ch == "[":
                cur = (cur - 1) % len(labels)
                continue
            if ch == "]":
                cur = (cur + 1) % len(labels)
                continue
            if ch in keys:
                cur = labels.index(keys[ch])
            elif ch != " ":
                continue
            name = save_frame(folder, labels[cur], frame, ids, camera, light)
            counts[labels[cur]] = counts.get(labels[cur], 0) + 1
            msg = f"saved {name}"
            print(msg)
    finally:
        cap.release()
        if gui:
            cv2.destroyAllWindows()


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", required=True, help="folder name under data/recognition/")
    ap.add_argument("--camera", default="overhead", help="overhead, side, wrist or a camera index")
    ap.add_argument("--setting", default="surgical", help="settings/<name>.json (surgical or bench)")
    ap.add_argument("--light", default="normal", choices=LIGHTS)
    ap.add_argument("--import", dest="import_dir", help="folder of phone photos named <label>[_anything].jpg")
    ap.add_argument("--data", default=str(DATA), help="output root (default data/recognition)")
    ap.add_argument("--frames", help="fake camera: loop the saved images in this folder (no camera opened)")
    a = ap.parse_args(argv)
    setting = load_setting(a.setting)
    labels, ids = label_list(setting), item_ids(setting)
    folder = Path(a.data) / a.set
    if a.import_dir:
        saved, skipped = import_folder(Path(a.import_dir).expanduser(), folder, labels, ids, a.light)
        print(f"imported {len(saved)} into {folder}")
        for s in skipped:
            print(f"skipped {s}")
        if skipped:
            print("known labels: " + ", ".join(labels))
        return
    cap = None
    if a.frames:
        cap = FolderCapture(Path(a.frames).expanduser())
        if not cap.isOpened():
            raise SystemExit(f"no jpg or png images in {a.frames}")
    run_live(folder, labels, ids, a.camera if not a.frames else "frames", a.light, cap=cap)


if __name__ == "__main__":
    main()
