"""Recognition bench: Perceptron detect and Gemini image input on saved tray images.

  .venv/bin/python -m explore.recognition.bench                 # default: explore/bench/refs, 3 repeats
  .venv/bin/python -m explore.recognition.bench --images DIR --setting surgical --repeat 2 --out OUT

DIR holds <item_id>/*.jpg (a crop of one item) and optionally whole-tray images named in DIR/labels.json:
  {"tray.jpg": {"items": ["scalpel", "hemostat"], "boxes": {"scalpel": [x1, y1, x2, y2]}}}
With only crops, a synthetic tray is composed from them (boxes known by construction) and marked synthetic.
OCR and MediaPipe are reported as skipped when the folder has no printed text or gloved-hand images.
Keys come from .env (PERCEPTRON_API_KEY, GEMINI_API_KEY) and are never printed. Writes bench.json and bench.md to OUT.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import statistics
import time
from pathlib import Path

import cv2
import httpx
import numpy as np

from vision.geometry import iou
from vision.tray import PerceptronDetector, categories_for, detection_box, load_setting, match_item

ROOT = Path(__file__).resolve().parent.parent.parent
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
IOU_OK = 0.5


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


def summarize(rows: list[dict]) -> dict:
    """rows: {"ok": bool|None, "found": bool, "latency": s|None, "error": str|None}. ok None means no ground truth."""
    done = [r for r in rows if not r.get("error")]
    graded = [r for r in done if r.get("ok") is not None]
    return {
        "calls": len(rows),
        "found_rate": round(sum(1 for r in done if r.get("found")) / len(done), 3) if done else None,
        "accuracy": round(sum(1 for r in graded if r["ok"]) / len(graded), 3) if graded else None,
        "median_latency_s": median([r["latency"] for r in done if r.get("latency") is not None]),
        "failures": [r["error"] for r in rows if r.get("error")],
    }


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


def load_cases(folder: Path, expected: list[str], out: Path) -> list[dict]:
    """Cases: crop (one item), plus whole-tray images from labels.json or a synthetic tray (full and one missing)."""
    cases, crops = [], {}
    for item in expected:
        for f in sorted((folder / item).glob("*.jpg")) if (folder / item).is_dir() else []:
            img = cv2.imread(str(f))
            if img is None:
                continue
            crops.setdefault(item, img)
            h, w = img.shape[:2]
            cases.append({"name": f"crop:{item}", "kind": "crop", "img": img, "expected": [item], "boxes": {}, "synthetic": False})
    labels = folder / "labels.json"
    if labels.exists():
        for name, lab in json.loads(labels.read_text(encoding="utf-8")).items():
            img = cv2.imread(str(folder / name))
            if img is not None:
                cases.append({"name": f"tray:{name}", "kind": "tray", "img": img, "expected": lab["items"],
                              "boxes": lab.get("boxes", {}), "synthetic": False})
    elif crops:
        for tag, keep in [("full", expected)] + [(f"no_{m}", [i for i in expected if i != m]) for m in expected[:1]]:
            img, boxes = compose_tray(crops, keep)
            cv2.imwrite(str(out / f"synthetic_{tag}.jpg"), img)
            cases.append({"name": f"synthetic_tray:{tag}", "kind": "tray", "img": img, "expected": keep, "boxes": boxes, "synthetic": True})
    return cases


# ---------------------------------------------------------------- methods

def run_perceptron(cases, setting, repeat) -> dict:
    det = PerceptronDetector(os.environ.get("PERCEPTRON_API_KEY", ""), timeout=15.0)
    cats = categories_for(setting, include_extras=False)
    rows, detail = [], []
    for c in cases:
        for r in range(repeat):
            h, w = c["img"].shape[:2]
            row = {"case": c["name"], "run": r}
            try:
                t = time.perf_counter()
                dets = det.detect(c["img"], cats)
                row["latency"] = time.perf_counter() - t
                s = score_detect(setting, dets, c["expected"], c["boxes"], (w, h))
                row.update(s, found=all(v["found"] for v in s["items"].values()), ok=all(v["ok"] for v in s["items"].values()) and not s["extra"])
                row["image"] = [w, h]
            except Exception as e:  # noqa: BLE001
                row["error"] = f"{c['name']}: {type(e).__name__} {str(e)[:80]}"
            rows.append(row)
    return {"method": "perceptron_detect", "summary": summarize(rows), "rows": rows}


def gemini(model: str, bgr, prompt: str, schema: dict) -> tuple[dict, float]:
    body = {"contents": [{"parts": [{"inline_data": {"mime_type": "image/jpeg", "data": jpeg_b64(bgr)}}, {"text": prompt}]}],
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


def run_gemini(cases, setting, repeat, model) -> tuple[dict, dict]:
    names = [i["name"] for i in setting["items"]]
    name_schema = {"type": "OBJECT", "properties": {"instruments": {"type": "ARRAY", "items": {"type": "STRING"}}}, "required": ["instruments"]}
    tray_schema = {"type": "OBJECT", "properties": {"present": {"type": "ARRAY", "items": {"type": "STRING", "enum": names}}}, "required": ["present"]}
    name_rows, tray_rows = [], []
    for c in cases:
        for r in range(repeat):
            row = {"case": c["name"], "run": r}
            try:
                if c["kind"] == "crop":
                    out, dt = gemini(model, c["img"], "Name each surgical instrument visible in this image, using its common name.", name_schema)
                    got = sorted({i for n in out["instruments"] if (i := match_item(n, setting))})
                    row.update(latency=dt, said=out["instruments"], found=bool(got), ok=got == c["expected"])
                    name_rows.append(row)
                else:
                    out, dt = gemini(model, c["img"], "This is a surgical instrument tray. Which of these instruments are on it? Only list ones you can see: " + ", ".join(names) + ".", tray_schema)
                    got = sorted({i for n in out["present"] if (i := match_item(n, setting))})
                    s = score_tray(c["expected"], got)
                    row.update(latency=dt, found=not s["missing"], ok=s["ok"], missing=s["missing"], extra=s["extra"])
                    tray_rows.append(row)
            except Exception as e:  # noqa: BLE001
                row["error"] = f"{c['name']}: {type(e).__name__} {str(e)[:80]}"
                (name_rows if c["kind"] == "crop" else tray_rows).append(row)
    return ({"method": "gemini_name_crop", "model": model, "summary": summarize(name_rows), "rows": name_rows},
            {"method": "gemini_check_tray", "model": model, "summary": summarize(tray_rows), "rows": tray_rows})


def markdown(results: list[dict], notes: list[str]) -> str:
    lines = ["| Method | Calls | Found rate | Accuracy | Median latency (s) | Failures |", "| --- | --- | --- | --- | --- | --- |"]
    for r in results:
        s = r["summary"]
        lines.append(f"| {r['method']} | {s['calls']} | {s['found_rate']} | {s['accuracy']} | {s['median_latency_s']} | {len(s['failures'])} |")
    return "\n".join(lines + [""] + [f"- {n}" for n in notes]) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--images", default=str(ROOT / "explore" / "bench" / "refs"))
    ap.add_argument("--setting", default="surgical")
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--out", default=str(ROOT / "explore" / "recognition" / "out"))
    ap.add_argument("--model", default=os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"))
    a = ap.parse_args()
    load_env()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    setting = load_setting(ROOT, a.setting)
    expected = [i["id"] for i in setting["items"]]
    cases = load_cases(Path(a.images), expected, out)
    folder = Path(a.images)
    has_text = any(folder.rglob("*label*")) or any(folder.rglob("*qr*"))
    has_gloves = any(folder.rglob("*glove*")) or any(folder.rglob("*hand*.jpg"))
    notes = [f"{len(cases)} cases, {a.repeat} repeats each. Synthetic cases are composed from real crops, not photographed."]
    notes.append("OCR: run." if has_text else "OCR: skipped, no image with printed text (tray label or QR tag).")
    notes.append("MediaPipe hand landmarker: run." if has_gloves else "MediaPipe hand landmarker: skipped, no image of a gloved hand.")
    results = []
    if os.environ.get("PERCEPTRON_API_KEY"):
        results.append(run_perceptron(cases, setting, a.repeat))
    else:
        notes.append("Perceptron: skipped, PERCEPTRON_API_KEY not set.")
    if os.environ.get("GEMINI_API_KEY"):
        results.extend(run_gemini(cases, setting, a.repeat, a.model))
    else:
        notes.append("Gemini: skipped, GEMINI_API_KEY not set.")
    (out / "bench.json").write_text(json.dumps({"model": a.model, "cases": [c["name"] for c in cases], "notes": notes, "results": results}, indent=1), encoding="utf-8")
    md = markdown(results, notes)
    (out / "bench.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
