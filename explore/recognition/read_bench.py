"""Reading (OCR) bench: vision/reading.py on the printable props, scored against props/truth.json.

  .venv/bin/python -m explore.recognition.read_bench [--methods perceptron,gemini] [--variants render,camera]
      [--images DIR] [--max-calls 40] [--out explore/recognition/out] [--name read_bench] [--no-qr]

Every number from the props folder is SYNTHETIC: `render` is the PNG as drawn, `camera` is the same PNG
put through a simulated overhead camera (placed on a table at 1280x720, turned a little, blurred, noisy,
dimmed, JPEG 70). Real photos of the printed props come later: name them like the capture labels
(count_sheet_written_1.jpg ...) and pass --images data/recognition/<set> with a truth.json beside them,
or let the bench score only what it can (tray, rows) from the label.

Writes <out>/read_bench.json and read_bench.md. Keys from .env, never printed.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from pathlib import Path

import cv2
import numpy as np

from vision import reading

HERE = Path(__file__).resolve().parent
PROPS = HERE / "props"
ROOT = HERE.parents[1]
TODAY = "2026-10-18"


# ---------------------------------------------------------------- images

def camera_sim(bgr: np.ndarray, seed: int = 0, angle: float = 4.0, size=(1280, 720), fill: float = 0.9,
               dim: float = 0.75, blur: float = 1.2, noise: float = 6.0, quality: int = 70) -> np.ndarray:
    """The prop as an overhead camera might see it: on a table, small in the frame, soft, noisy and dim."""
    rng = np.random.default_rng(seed)
    w, h = size
    table = np.full((h, w, 3), (150, 165, 175), np.float32) + rng.normal(0, 4, (h, w, 3))
    ph, pw = bgr.shape[:2]
    s = min(fill * h / ph, fill * w / pw)
    prop = cv2.resize(bgr, (max(1, int(pw * s)), max(1, int(ph * s))), interpolation=cv2.INTER_AREA)
    ph, pw = prop.shape[:2]
    m = cv2.getRotationMatrix2D((pw / 2, ph / 2), angle, 1.0)
    m[0, 2] += (w - pw) / 2
    m[1, 2] += (h - ph) / 2
    mask = cv2.warpAffine(np.ones((ph, pw), np.float32), m, (w, h))
    warped = cv2.warpAffine(prop.astype(np.float32), m, (w, h))
    img = table * (1 - mask[..., None]) + warped * mask[..., None]
    img = cv2.GaussianBlur(img, (0, 0), blur) * dim + rng.normal(0, noise, img.shape)
    img = np.clip(img, 0, 255).astype(np.uint8)
    ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return cv2.imdecode(enc, cv2.IMREAD_COLOR)


# ---------------------------------------------------------------- scoring

def _id(name: str | None) -> str | None:
    return None if name is None else str(name).strip().lower().replace(" ", "_").replace("-", "_")


def score_count_sheet(truth: dict, res: dict) -> dict:
    """tray right, rows right (same item set, nothing invented), and each filled cell right."""
    want = {i["id"]: i for i in truth["items"]}
    got = {i["item"]: i for i in res.get("items") or []}
    cells = right = 0
    for iid, t in want.items():
        g = got.get(iid) or {}
        for k in ("expected", "initial", "closing"):
            cells += 1
            right += g.get(k) == t.get(k)
    return {"ok": bool(res.get("ok")), "tray": res.get("tray") == truth["tray_id"], "rows": set(got) == set(want),
            "cells": cells, "cells_right": right, "exact": bool(res.get("ok")) and set(got) == set(want) and right == cells
            and res.get("tray") == truth["tray_id"]}


def score_tray_tag(truth: dict, res: dict) -> dict:
    good = res.get("tray") == truth["tray_id"]
    return {"ok": bool(res.get("ok")), "tray": good, "exact": good, "cells": 1, "cells_right": int(good)}


def score_pack(truth: dict, res: dict) -> dict:
    """Each truth label matched by lot; item, expiry and the expired flag must be right."""
    got = {str(lab.get("lot") or "").replace(" ", "").upper(): lab for lab in res.get("labels") or []}
    cells = right = 0
    expired_ok = True
    for t in truth["labels"]:
        g = got.get(t["lot"].upper())
        cells += 4
        if not g:
            expired_ok = expired_ok and not t["expired"]
            continue
        right += 1  # lot
        right += _id(g.get("item")) == _id(t["item"])
        right += g.get("expires") == t["expires"]
        right += bool(g.get("expired")) == bool(t["expired"])
        expired_ok = expired_ok and bool(g.get("expired")) == bool(t["expired"])
    n_extra = max(0, len(res.get("labels") or []) - len(truth["labels"]))
    return {"ok": bool(res.get("ok")), "cells": cells, "cells_right": right, "expired_flag": expired_ok,
            "extra_labels": n_extra, "exact": bool(res.get("ok")) and right == cells and not n_extra}


SCORERS = {"count_sheet": score_count_sheet, "tray_tag": score_tray_tag, "pack_labels": score_pack}


# ---------------------------------------------------------------- run

def load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass


def backend(method: str):
    key = {"perceptron": "PERCEPTRON_API_KEY", "gemini": "GEMINI_API_KEY"}[method]
    k = os.environ.get(key, "").strip()
    if not k:
        return None
    return reading.PerceptronOCR(k) if method == "perceptron" else reading.GeminiOCR(k)


def read_one(kind: str, img, truth: dict, backends) -> dict:
    if kind == "count_sheet":
        setting = reading.load_setting_merged(ROOT, truth["tray_id"])
        return reading.read_count_sheet(img, setting, backends=backends, repo=ROOT)
    if kind == "tray_tag":
        return reading.read_tray_tag(img, backends=backends, repo=ROOT)
    setting = reading.load_setting_merged(ROOT, "surgical")
    return reading.read_pack_label(img, setting, today=truth.get("reference_date") or TODAY, backends=backends)


def run(cases: list[dict], methods: list[str], max_calls: int, make=backend) -> list[dict]:
    rows, calls = [], 0
    for c in cases:
        for m in methods:
            b = make(m)
            if b is None:
                rows.append({**_meta(c), "method": m, "skipped": "no key"})
                continue
            if calls >= max_calls:
                rows.append({**_meta(c), "method": m, "skipped": "budget"})
                continue
            t0 = time.perf_counter()
            res = read_one(c["kind"], c["img"], c["truth"], [b])
            calls += sum(1 for a in res.get("attempts") or [] if a.get("method") != "qr")
            ms = round((time.perf_counter() - t0) * 1000)
            score = SCORERS[c["kind"]](c["truth"], res)
            rows.append({**_meta(c), "method": m, "answered_by": res.get("method"), "latency_ms": ms,
                         "error": res.get("error"), **score})
            print(f"{c['name']:<40} {c['variant']:<7} {m:<10} by={res.get('method')!s:<10} {ms:>6} ms "
                  f"exact={score['exact']} cells {score['cells_right']}/{score['cells']}")
    return rows


def _meta(c: dict) -> dict:
    return {"file": c["name"], "kind": c["kind"], "variant": c["variant"]}


def load_cases(folder: Path, variants: list[str]) -> list[dict]:
    truth = json.loads((folder / "truth.json").read_text())["files"]
    cases = []
    for i, (name, t) in enumerate(sorted(truth.items())):
        img = cv2.imread(str(folder / name))
        if img is None:
            continue
        for v in variants:
            cases.append({"name": name, "kind": t["kind"], "truth": t, "variant": v,
                          "img": img if v == "render" else camera_sim(img, seed=i)})
    return cases


def summarize(rows: list[dict]) -> list[dict]:
    out = []
    keys = sorted({(r["kind"], r["variant"], r["method"]) for r in rows if "skipped" not in r})
    for kind, variant, method in keys:
        g = [r for r in rows if (r["kind"], r["variant"], r["method"]) == (kind, variant, method) and "skipped" not in r]
        lat = [r["latency_ms"] for r in g]
        out.append({"kind": kind, "variant": variant, "method": method, "n": len(g),
                    "exact": sum(r["exact"] for r in g), "cells_right": sum(r["cells_right"] for r in g),
                    "cells": sum(r["cells"] for r in g), "answered_by": sorted({str(r["answered_by"]) for r in g}),
                    "median_ms": round(statistics.median(lat)) if lat else None, "max_ms": max(lat) if lat else None})
    return out


def markdown(summary: list[dict], rows: list[dict]) -> str:
    lines = ["# Reading bench (SYNTHETIC: rendered props, and the same renders through a simulated camera)", "",
             "| Kind | Variant | Method | Images | Exact | Cells right | Answered by | Median ms | Max ms |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for s in summary:
        lines.append(f"| {s['kind']} | {s['variant']} | {s['method']} | {s['n']} | {s['exact']}/{s['n']} | "
                     f"{s['cells_right']}/{s['cells']} | {', '.join(s['answered_by'])} | {s['median_ms']} | {s['max_ms']} |")
    misses = [r for r in rows if "skipped" not in r and not r["exact"]]
    if misses:
        lines += ["", "Not exact:", ""]
        lines += [f"- {r['file']} ({r['variant']}, {r['method']}): cells {r['cells_right']}/{r['cells']}"
                  + (f", error {r['error']}" if r.get("error") else "") for r in misses]
    skipped = [r for r in rows if "skipped" in r]
    if skipped:
        lines += ["", f"Skipped: {len(skipped)} ({', '.join(sorted({r['skipped'] for r in skipped}))})."]
    return "\n".join(lines) + "\n"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--images", default=str(PROPS), help="folder with truth.json and the images it names")
    ap.add_argument("--methods", default="perceptron,gemini")
    ap.add_argument("--variants", default="render,camera", help="render, camera (simulated overhead camera)")
    ap.add_argument("--only", default="", help="comma list of kinds: count_sheet, tray_tag, pack_labels")
    ap.add_argument("--max-calls", type=int, default=40)
    ap.add_argument("--out", default=str(HERE / "out"))
    ap.add_argument("--name", default="read_bench", help="output file stem")
    ap.add_argument("--no-qr", action="store_true", help="skip QR decoding so tray tags go through OCR")
    a = ap.parse_args(argv)
    load_env()
    if a.no_qr:
        reading.decode_qr = lambda bgr: []
    cases = load_cases(Path(a.images), [v for v in a.variants.split(",") if v])
    if a.only:
        cases = [c for c in cases if c["kind"] in a.only.split(",")]
    rows = run(cases, [m for m in a.methods.split(",") if m], a.max_calls)
    summary = summarize(rows)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{a.name}.json").write_text(json.dumps({"synthetic": Path(a.images).resolve() == PROPS.resolve(),
                                                    "no_qr": a.no_qr, "summary": summary, "rows": rows}, indent=1))
    (out / f"{a.name}.md").write_text(markdown(summary, rows))
    print(f"wrote {out / (a.name + '.md')}")


if __name__ == "__main__":
    main()
