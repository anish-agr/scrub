"""Recognition bench: Perceptron detect, Gemini tray checks and the MediaPipe glove check on saved images.

  .venv/bin/python -m explore.recognition.bench                      # default: explore/bench/refs, all methods, 3 repeats
  .venv/bin/python -m explore.recognition.bench --images data/recognition/tray1 --methods perceptron,gemini_tray --max-calls 60

Methods (--methods, comma list, default all):
  perceptron        the /v1/detect call vision/tray.py makes, frame shrunk to 640 px wide
  perceptron_small  the same on a 416 px wide frame
  perceptron_crop   the same on the tray region only (union of the slot boxes in settings/<tray>.json, else the central 70%)
  gemini_tray       Gemini checks the tray against the enum of item names
  gemini_ref        the same with one reference image of each item in the prompt before the tray image
  mediapipe_glove   MediaPipe hand landmarker (vision/hand.py settings, local) on glove_* images

DIR holds <item_id>/*.jpg (a crop of one item) and DIR/labels.json written by capture.py:
  {"full_1.jpg": {"items": [...], "boxes": {"scalpel": [x1, y1, x2, y2]}, "label": "full", "light": "normal"}}
Labels: full, no_<item>, alone_<item>, grip_<item>, glove_*. With only crops, a synthetic tray is composed from them.
--max-calls caps the API calls over all API methods (split evenly between them). Gemini waits 3 s between calls and
retries once after 20 s on a 429. Keys come from .env (PERCEPTRON_API_KEY, GEMINI_API_KEY) and are never printed.
Writes bench.json and bench.md to OUT: per method, per item and per light level.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import re
import statistics
import time
from pathlib import Path

import cv2
import httpx
import numpy as np

from vision.geometry import iou
from vision.hand import HandTracker, ensure_model, hand_is_open, model_path
from vision.tray import PerceptronDetector, categories_for, detection_box, load_setting, match_item

ROOT = Path(__file__).resolve().parent.parent.parent
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
IOU_OK = 0.5
METHODS = ["perceptron", "perceptron_small", "perceptron_crop", "gemini_tray", "gemini_ref", "mediapipe_glove"]
API_METHODS = METHODS[:5]
PERCEPTRON_WIDTH = {"perceptron": 640, "perceptron_small": 416, "perceptron_crop": 640}
LIGHTS = ["bright", "normal", "dim", "unknown"]


# ---------------------------------------------------------------- scoring (pure, tested offline)

def median(values: list[float]) -> float | None:
    return round(statistics.median(values), 3) if values else None


def box_sanity(box: list[float] | None, width: int, height: int) -> bool:
    """A real instrument box is inside the image and covers 1% to 100% of it."""
    if not box:
        return False
    x1, y1, x2, y2 = box
    if x2 <= x1 or y2 <= y1 or x1 < -2 or y1 < -2 or x2 > width + 2 or y2 > height + 2:
        return False
    return 0.01 <= (x2 - x1) * (y2 - y1) / float(width * height) <= 1.0


def score_detect(setting: dict, detections: list[dict], expected: list[str], gt_boxes: dict, size: tuple[int, int]) -> dict:
    """Per expected item: found, best IoU against its label (or box sanity without one). Also extras and wrong ids."""
    by_item: dict[str, list[list[float]]] = {}
    for d in detections:
        item, box = match_item(d.get("mention", ""), setting), detection_box(d)
        if item and box:
            by_item.setdefault(item, []).append(box)
    items = {}
    for item in expected:
        boxes = by_item.get(item, [])
        row = {"found": bool(boxes)}
        gt = gt_boxes.get(item)
        if boxes and gt:
            row["iou"] = round(max(iou(b, gt) for b in boxes), 3)
            row["ok"] = row["iou"] >= IOU_OK
        elif boxes:
            row["sane"] = any(box_sanity(b, *size) for b in boxes)
            row["ok"] = row["sane"]
        else:
            row["ok"] = False
        items[item] = row
    extra = sorted(i for i in by_item if i not in expected)
    return {"items": items, "extra": extra}


def score_tray(expected: list[str], present: list[str]) -> dict:
    """Compare the items a method says it sees to the items that are really there."""
    exp, got = set(expected), set(present)
    return {"missing": sorted(exp - got), "extra": sorted(got - exp), "ok": exp == got}


def percentile(values: list[float], q: float) -> float | None:
    """Nearest-rank percentile (q in 0..1)."""
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(q * len(ordered)) - 1)], 3)


def missing_set(all_ids: list[str], present: list[str]) -> list[str]:
    return sorted(set(all_ids) - set(present))


def summarize(rows: list[dict]) -> dict:
    """rows: {"ok": bool|None, "found": bool, "latency": s|None, "error": str|None, "items": {id: {"found", "iou"?}},
    "missing_ok": bool|None, "open": bool|None}. ok None means no ground truth."""
    done = [r for r in rows if not r.get("error")]
    graded = [r for r in done if r.get("ok") is not None]
    lat = [r["latency"] for r in done if r.get("latency") is not None]
    ious = [v["iou"] for r in done for v in (r.get("items") or {}).values() if v.get("iou") is not None]
    miss = [r for r in done if r.get("missing_ok") is not None]
    found_hands = [r for r in done if r.get("found") and "open" in r]
    out = {
        "calls": len(rows),
        "found_rate": round(sum(1 for r in done if r.get("found")) / len(done), 3) if done else None,
        "accuracy": round(sum(1 for r in graded if r["ok"]) / len(graded), 3) if graded else None,
        "iou_mean": round(statistics.mean(ious), 3) if ious else None,
        "missing_accuracy": round(sum(1 for r in miss if r["missing_ok"]) / len(miss), 3) if miss else None,
        "missing_n": len(miss),
        "median_latency_s": median(lat),
        "p90_latency_s": percentile(lat, 0.9),
        "errors": len(rows) - len(done),
        "failures": [r["error"] for r in rows if r.get("error")],
    }
    if found_hands:
        out["open_rate"] = round(sum(1 for r in found_hands if r["open"]) / len(found_hands), 3)
    return out


def by_light(rows: list[dict]) -> dict:
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r.get("light") or "unknown", []).append(r)
    return {k: summarize(groups[k]) for k in LIGHTS + sorted(set(groups) - set(LIGHTS)) if k in groups}


def by_item(rows: list[dict]) -> dict:
    """Per item over the rows where it is expected: found rate and mean IoU."""
    acc: dict[str, dict] = {}
    for r in rows:
        if r.get("error"):
            continue
        for item, v in (r.get("items") or {}).items():
            a = acc.setdefault(item, {"n": 0, "found": 0, "ious": []})
            a["n"] += 1
            a["found"] += 1 if v.get("found") else 0
            if v.get("iou") is not None:
                a["ious"].append(v["iou"])
    return {i: {"n": a["n"], "found_rate": round(a["found"] / a["n"], 3),
                "iou_mean": round(statistics.mean(a["ious"]), 3) if a["ious"] else None} for i, a in sorted(acc.items())}


class Budget:
    """A cap on API calls. take() is False once it is spent."""

    def __init__(self, total: int):
        self.total, self.used = total, 0

    @property
    def left(self) -> int:
        return max(0, self.total - self.used)

    def take(self) -> bool:
        if self.used >= self.total:
            return False
        self.used += 1
        return True

    def share(self, methods_left: int) -> "Budget":
        """An even slice for one method; the caller adds sub.used back to the parent afterwards."""
        return Budget(self.left // max(1, methods_left))


def tray_crop_box(setting: dict, size: tuple[int, int]) -> list[int]:
    """Union of the slot boxes (plus 5%), or the central 70% when there are none or they do not fit the frame."""
    w, h = size
    boxes = [s for i in setting.get("items") or [] if (s := i.get("slot")) and len(s) == 4]
    if boxes:
        x1, y1 = min(b[0] for b in boxes), min(b[1] for b in boxes)
        x2, y2 = max(b[2] for b in boxes), max(b[3] for b in boxes)
        px, py = 0.05 * (x2 - x1), 0.05 * (y2 - y1)
        box = [max(0, int(x1 - px)), max(0, int(y1 - py)), min(w, int(x2 + px)), min(h, int(y2 + py))]
        if box[2] > box[0] and box[3] > box[1] and (box[2] - box[0]) * (box[3] - box[1]) >= 0.05 * w * h:
            return box
    return [int(0.15 * w), int(0.15 * h), int(0.85 * w), int(0.85 * h)]


def offset_detections(dets: list[dict], dx: float, dy: float) -> list[dict]:
    """Shift boxes from a crop back into full-frame pixels."""
    out = []
    for d in dets:
        d = dict(d)
        pb = d.get("point_box")
        if pb:
            d["point_box"] = {k: {**c, "x": float(c["x"]) + dx, "y": float(c["y"]) + dy} if isinstance(c, dict) and "x" in c else c
                              for k, c in pb.items()}
        out.append(d)
    return out


def score_glove(hands: list, width: int, height: int) -> dict:
    """found: a hand was returned. open: vision's rule (every fingertip farther from the wrist than its middle joint)."""
    if not hands:
        return {"found": False, "open": None, "hands": 0}
    return {"found": True, "open": any(hand_is_open(h, width, height) for h in hands), "hands": len(hands)}


# ---------------------------------------------------------------- inputs

def load_env() -> None:
    try:
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k and not k.startswith("#") and v.strip() and k.strip() not in os.environ:
                os.environ[k.strip()] = v.strip().strip("\"'")
    except OSError:
        pass


def jpeg_b64(bgr) -> str:
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    if not ok:
        raise RuntimeError("encode failed")
    return base64.b64encode(buf.tobytes()).decode("ascii")


def compose_tray(crops: dict, expected: list[str], scale: float = 1.5, size=(640, 480)) -> tuple[np.ndarray, dict]:
    """Dark tray background with each crop pasted in its own band. Returns image and the pasted boxes."""
    img = np.full((size[1], size[0], 3), 40, np.uint8)
    boxes, y = {}, 20
    for item in expected:
        if item not in crops:
            continue
        c = cv2.resize(crops[item], None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        h, w = c.shape[:2]
        x = 20 + (size[0] - w - 40) // 2
        if y + h > size[1]:
            break
        img[y:y + h, x:x + w] = c
        boxes[item] = [x, y, x + w, y + h]
        y += h + 20
    return img, boxes



def label_of(name: str, lab: dict) -> str:
    return lab.get("label") or re.sub(r"_\d+$", "", Path(name).stem)


def load_cases(folder: Path, expected: list[str], out: Path) -> list[dict]:
    """Cases: crop (one item), glove_* images, whole-tray images from labels.json, or a synthetic tray (full and one missing).

    Every case has label, light (bright/normal/dim, else unknown) and missing_truth: the item ids that really are
    absent, set for full and no_<item> images only (the "what's missing" test).
    """
    cases, crops = [], {}

    def add(**c):
        c.setdefault("boxes", {})
        c.setdefault("synthetic", False)
        c.setdefault("light", "unknown")
        c.setdefault("missing_truth", None)
        c.setdefault("file", None)
        cases.append(c)

    for item in expected:
        for f in sorted((folder / item).glob("*.jpg")) if (folder / item).is_dir() else []:
            img = cv2.imread(str(f))
            if img is None:
                continue
            crops.setdefault(item, img)
            add(name=f"crop:{item}", kind="crop", img=img, expected=[item], label=f"alone_{item}", file=str(f))
    labels = folder / "labels.json"
    if labels.exists():
        for name, lab in json.loads(labels.read_text(encoding="utf-8")).items():
            img = cv2.imread(str(folder / name))
            if img is None:
                continue
            label = label_of(name, lab)
            light = lab.get("light") if lab.get("light") in LIGHTS else "unknown"
            if label.startswith("glove_"):
                add(name=f"glove:{name}", kind="glove", img=img, expected=lab.get("items", []), label=label, light=light, file=str(folder / name))
            elif lab.get("items"):
                truth = missing_set(expected, lab["items"]) if label == "full" or label.startswith("no_") else None
                add(name=f"tray:{name}", kind="tray", img=img, expected=lab["items"], boxes=lab.get("boxes", {}), label=label,
                    light=light, missing_truth=truth, file=str(folder / name))
    elif crops:
        for tag, keep in [("full", expected)] + [(f"no_{m}", [i for i in expected if i != m]) for m in expected[:1]]:
            img, boxes = compose_tray(crops, keep)
            cv2.imwrite(str(out / f"synthetic_{tag}.jpg"), img)
            add(name=f"synthetic_tray:{tag}", kind="tray", img=img, expected=keep, boxes=boxes, synthetic=True, label=tag,
                missing_truth=missing_set(expected, keep))
    return cases


def collect_refs(cases: list[dict], ids: list[str]) -> dict:
    """One reference image per item from the alone images (refs folder crops or alone_<item> photos). Value: (image, source file)."""
    refs = {}
    for item in ids:
        for c in cases:
            if c["label"] == f"alone_{item}" and c["kind"] in ("crop", "tray"):
                refs[item] = (c["img"], c["file"])
                break
    return refs


# ---------------------------------------------------------------- methods

def base_row(c: dict, r: int) -> dict:
    return {"case": c["name"], "run": r, "label": c["label"], "light": c["light"]}


def row_from_detect(c: dict, setting: dict, dets: list[dict], ids: list[str]) -> dict:
    h, w = c["img"].shape[:2]
    s = score_detect(setting, dets, c["expected"], c["boxes"], (w, h))
    present = sorted({m for d in dets if (m := match_item(d.get("mention", ""), setting)) and detection_box(d)})
    row = {"items": s["items"], "extra": s["extra"], "present": present, "image": [w, h],
           "found": all(v["found"] for v in s["items"].values()), "ok": all(v["ok"] for v in s["items"].values()) and not s["extra"]}
    if c["missing_truth"] is not None:
        row["missing_ok"] = missing_set(ids, present) == c["missing_truth"]
    return row


def row_from_present(c: dict, present: list[str], ids: list[str]) -> dict:
    s = score_tray(c["expected"], present)
    row = {"items": {i: {"found": i in present} for i in c["expected"]}, "found": not s["missing"], "ok": s["ok"],
           "present": sorted(present), "extra": s["extra"]}
    if c["missing_truth"] is not None:
        row["missing_ok"] = missing_set(ids, present) == c["missing_truth"]
    return row


def run_api(method: str, cases: list[dict], repeat: int, budget: Budget, call, extra: dict | None = None) -> dict:
    """Run call(case) -> (fields, latency) over cases x repeat until the budget is spent. Repeat is the outer loop."""
    rows, skipped = [], 0
    for r in range(repeat):
        for c in cases:
            if not budget.take():
                skipped += 1
                continue
            row = base_row(c, r)
            try:
                fields, dt = call(c)
                row.update(fields, latency=dt)
            except Exception as e:  # noqa: BLE001
                row["error"] = f"{c['name']}: {type(e).__name__} {str(e)[:80]}"
            rows.append(row)
    return {"method": method, "skipped_for_budget": skipped, **(extra or {}), "summary": summarize(rows),
            "by_light": by_light(rows), "by_item": by_item(rows), "rows": rows}


def run_perceptron(method: str, cases, setting, repeat, budget, timeout: float) -> dict:
    det = PerceptronDetector(os.environ.get("PERCEPTRON_API_KEY", ""), timeout=timeout, max_width=PERCEPTRON_WIDTH[method])
    cats = categories_for(setting, include_extras=False)
    ids = [i["id"] for i in setting["items"]]

    def call(c):
        img, dx, dy = c["img"], 0, 0
        if method == "perceptron_crop":
            x1, y1, x2, y2 = tray_crop_box(setting, (img.shape[1], img.shape[0]))
            img, dx, dy = img[y1:y2, x1:x2], x1, y1
        t = time.perf_counter()
        dets = det.detect(img, cats)
        dt = time.perf_counter() - t
        return row_from_detect(c, setting, offset_detections(dets, dx, dy), ids), dt

    return run_api(method, cases, repeat, budget, call, {"max_width": PERCEPTRON_WIDTH[method], "timeout_s": timeout})


def gemini(model: str, content: list, schema: dict) -> tuple[dict, float]:
    """content: strings and images (BGR arrays) in order. Returns (parsed JSON, seconds of the successful call)."""
    parts = [{"text": x} if isinstance(x, str) else {"inline_data": {"mime_type": "image/jpeg", "data": jpeg_b64(x)}} for x in content]
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"responseMimeType": "application/json", "responseSchema": schema, "temperature": 0}}
    for attempt in range(2):  # the free tier answers 429 when calls come fast: wait once, then retry
        time.sleep(3.0)
        t = time.perf_counter()
        r = httpx.post(GEMINI_URL.format(model=model), json=body, headers={"x-goog-api-key": os.environ.get("GEMINI_API_KEY", "")}, timeout=30)
        dt = time.perf_counter() - t
        if r.status_code != 429:
            break
        time.sleep(20.0)
    r.raise_for_status()
    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text), dt


def run_gemini(method: str, cases, setting, repeat, budget, model: str, refs: dict) -> dict:
    names = [i["name"] for i in setting["items"]]
    ids = [i["id"] for i in setting["items"]]
    name_of = {i["id"]: i["name"] for i in setting["items"]}
    schema = {"type": "OBJECT", "properties": {"present": {"type": "ARRAY", "items": {"type": "STRING", "enum": names}}}, "required": ["present"]}
    ask = "This is a surgical instrument tray. Which of these instruments are on it? Only list ones you can see: " + ", ".join(names) + "."
    ref_files = {f for _, f in refs.values() if f}
    use = [c for c in cases if method == "gemini_tray" or c["file"] not in ref_files]  # a reference image is never also a test image

    def call(c):
        content = [c["img"], ask]
        if method == "gemini_ref":
            pre = []
            for item, (img, _) in refs.items():
                pre += [f"Reference photo of the {name_of[item]}:", img]
            content = pre + ["Tray photo to check:", c["img"], ask + " Use the reference photos to tell them apart."]
        out, dt = gemini(model, content, schema)
        got = sorted({i for n in out["present"] if (i := match_item(n, setting))})
        return row_from_present(c, got, ids), dt

    extra = {"model": model}
    if method == "gemini_ref":
        extra["reference_items"] = sorted(refs)
    return run_api(method, use, repeat, budget, call, extra)


def run_glove(cases: list[dict], tracker) -> dict:
    """Local, no API. tracker.detect(bgr) returns a list of hands (vision.hand.HandTracker). One untimed warm-up call loads the model."""
    gloves = [c for c in cases if c["kind"] == "glove"]
    rows = []
    if gloves:
        try:
            tracker.detect(gloves[0]["img"])
        except Exception:  # noqa: BLE001
            pass
    for c in gloves:
        row = base_row(c, 0)
        try:
            h, w = c["img"].shape[:2]
            t = time.perf_counter()
            hands = tracker.detect(c["img"])
            row["latency"] = time.perf_counter() - t
            s = score_glove(hands, w, h)
            row.update(found=s["found"], open=s["open"], hands=s["hands"], ok=None)
        except Exception as e:  # noqa: BLE001
            row["error"] = f"{c['name']}: {type(e).__name__} {str(e)[:80]}"
        rows.append(row)
    return {"method": "mediapipe_glove", "summary": summarize(rows), "by_light": by_light(rows), "by_item": {}, "rows": rows}


# ---------------------------------------------------------------- report

def fmt(v) -> str:
    return "-" if v is None else str(v)


def markdown(results: list[dict], notes: list[str]) -> str:
    cols = ["calls", "found_rate", "iou_mean", "missing_accuracy", "median_latency_s", "p90_latency_s", "errors"]
    head = ["Calls", "Found rate", "Box IoU", "Missing accuracy", "Median s", "P90 s", "Errors"]
    sep = "| " + " | ".join(["---"] * (len(head) + 1)) + " |"
    lines = ["## Per method", "", "| Method | " + " | ".join(head) + " |", sep]
    lines += ["| " + " | ".join([r["method"]] + [fmt(r["summary"].get(c)) for c in cols]) + " |" for r in results]
    glove = [r for r in results if "open_rate" in r["summary"]]
    if glove:
        lines += ["", "Open palm rate (of hands found): " + ", ".join(f"{r['method']} {r['summary']['open_rate']}" for r in glove)]
    lines += ["", "## Per light level", "", "| Method | Light | " + " | ".join(head) + " |", "| " + " | ".join(["---"] * (len(head) + 2)) + " |"]
    for r in results:
        for light, s in r["by_light"].items():
            lines.append("| " + " | ".join([r["method"], light] + [fmt(s.get(c)) for c in cols]) + " |")
    lines += ["", "## Per item", "", "| Method | Item | Images | Found rate | Box IoU |", "| --- | --- | --- | --- | --- |"]
    for r in results:
        for item, v in r["by_item"].items():
            lines.append(f"| {r['method']} | {item} | {v['n']} | {v['found_rate']} | {fmt(v['iou_mean'])} |")
    fails = [f for r in results for f in r["summary"]["failures"]]
    if fails:
        lines += ["", "## First errors", ""] + [f"- {f}" for f in fails[:8]]
    return "\n".join(lines + ["", "## Notes", ""] + [f"- {n}" for n in notes]) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--images", default=str(ROOT / "explore" / "bench" / "refs"))
    ap.add_argument("--setting", default="surgical")
    ap.add_argument("--methods", default=",".join(METHODS), help="comma list of: " + ", ".join(METHODS))
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--max-calls", type=int, default=120, help="cap on API calls over all API methods")
    ap.add_argument("--perceptron-timeout", type=float, default=15.0, help="seconds; vision/tray.py uses 6")
    ap.add_argument("--hand-model", default=None, help="hand_landmarker.task (default vision/models, downloaded if missing)")
    ap.add_argument("--out", default=str(ROOT / "explore" / "recognition" / "out"))
    ap.add_argument("--model", default=os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"))
    a = ap.parse_args()
    methods = [m.strip() for m in a.methods.split(",") if m.strip()]
    bad = [m for m in methods if m not in METHODS]
    if bad:
        ap.error(f"unknown methods {bad}; choose from {METHODS}")
    load_env()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    setting = load_setting(ROOT, a.setting)
    ids = [i["id"] for i in setting["items"]]
    folder = Path(a.images)
    cases = load_cases(folder, ids, out)
    tray_cases = [c for c in cases if c["kind"] != "glove"]
    light_counts = {k: sum(1 for c in cases if c["light"] == k) for k in LIGHTS}
    notes = [f"{len(tray_cases)} tray images and {len(cases) - len(tray_cases)} glove images, {a.repeat} repeats each for API methods. "
             f"Images per light level: {light_counts}. Synthetic cases are composed from real crops, not photographed.",
             f"API call cap {a.max_calls}. Perceptron timeout {a.perceptron_timeout} s."]
    results, budget = [], Budget(a.max_calls)
    key_ok = {"perceptron": bool(os.environ.get("PERCEPTRON_API_KEY")), "gemini": bool(os.environ.get("GEMINI_API_KEY"))}
    runnable = []
    for m in methods:
        if m == "mediapipe_glove":
            continue
        need = "perceptron" if m.startswith("perceptron") else "gemini"
        if not key_ok[need]:
            notes.append(f"{m}: skipped, {need.upper()}_API_KEY not set.")
        elif not tray_cases:
            notes.append(f"{m}: skipped, no tray images.")
        else:
            runnable.append(m)
    refs = collect_refs(cases, ids)
    if "gemini_ref" in runnable and not refs:
        runnable.remove("gemini_ref")
        notes.append("gemini_ref: skipped, no reference image of any item (DIR/<item>/*.jpg or alone_<item> images).")
    for n, m in enumerate(runnable):
        sub = budget.share(len(runnable) - n)
        if m.startswith("perceptron"):
            res = run_perceptron(m, tray_cases, setting, a.repeat, sub, a.perceptron_timeout)
        else:
            res = run_gemini(m, tray_cases, setting, a.repeat, sub, a.model, refs)
        budget.used += sub.used
        if res["skipped_for_budget"]:
            notes.append(f"{m}: {res['skipped_for_budget']} calls not made, over the budget share of {sub.total}.")
        results.append(res)
    if "mediapipe_glove" in methods:
        if not any(c["kind"] == "glove" for c in cases):
            notes.append("mediapipe_glove: skipped, no glove_* images.")
        else:
            task = Path(a.hand_model) if a.hand_model else (model_path(ROOT) if model_path(ROOT).exists() else ensure_model(ROOT))
            results.append(run_glove(cases, HandTracker(task)))
    notes.append(f"API calls made: {budget.used} of {a.max_calls}.")
    (out / "bench.json").write_text(json.dumps({"model": a.model, "max_calls": a.max_calls, "calls_made": budget.used,
                                                "cases": [{k: c[k] for k in ("name", "kind", "label", "light")} for c in cases],
                                                "notes": notes, "results": results}, indent=1), encoding="utf-8")
    md = markdown(results, notes)
    (out / "bench.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
