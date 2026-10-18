"""On-device tray identifier for Scrub. Everything runs locally (Apple Vision OCR + torchvision on MPS).

  .venv/bin/python explore/bench/identify.py --source file:PATH --setting bench
  .venv/bin/python explore/bench/identify.py --source arm_session          # MJPEG from the recorder, GET only
  .venv/bin/python explore/bench/identify.py --source file:PATH --once     # print one state as JSON and exit

Serves identify.html on port 8097. Reference crops live in refs/<item_id>/*.jpg, the empty tray in refs/_empty.jpg.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
REFS = HERE / "refs"
EMPTY = REFS / "_empty.jpg"
STREAM_URL = "http://localhost:8090/stream/side"
PORT = 8097


# ---------------------------------------------------------------- settings / calibration

def load_setting(setting_id: str) -> dict:
    return json.loads((ROOT / "settings" / f"{setting_id}.json").read_text(encoding="utf-8"))


def load_calibration():
    path = ROOT / "vision" / "calibration.json"
    try:
        cal = json.loads(path.read_text(encoding="utf-8"))
        return np.array(cal["homography"], dtype=np.float64) if cal.get("homography") else None
    except Exception:
        return None


def pixel_to_arm(h, u, v):
    p = h @ np.array([u, v, 1.0])
    return [round(float(p[0] / p[2]), 4), round(float(p[1] / p[2]), 4)]


def norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def item_labels(item: dict) -> list[str]:
    raw = [item["id"], item.get("name", "")] + list(item.get("aliases") or [])
    out = []
    for r in raw:
        n = norm(r)
        if n and n not in out:
            out.append(n)
    return out


def match_text(text: str, setting: dict):
    """Return (item_id, factor) or None. Exact label 1.0, phrase in text 0.9, fuzzy ratio*0.9,
    a single word that belongs to exactly one item (PLIERS) 0.7."""
    t = norm(text)
    if len(t) < 3:
        return None
    best = None
    for item in setting["items"]:
        for lab in item_labels(item):
            if len(lab) < 3:
                continue
            f = 0.0
            if t == lab:
                f = 1.0
            elif re.search(rf"\b{re.escape(lab)}\b", t):
                f = 0.9
            else:
                r = difflib.SequenceMatcher(None, t, lab).ratio()
                if r >= 0.85:
                    f = r * 0.9
            if f and (best is None or f > best[1]):
                best = (item["id"], f)
    if best:
        return best
    toks = set(t.split())
    owners = {}
    for item in setting["items"]:
        for lab in item_labels(item):
            if toks and toks <= set(lab.split()) and len(t) >= 4:
                owners[item["id"]] = 0.7
    return next(iter(owners.items())) if len(owners) == 1 else None


# ---------------------------------------------------------------- OCR (Apple Vision)

def ocr(bgr):
    import Quartz
    import Vision
    from Foundation import NSData

    ok, png = cv2.imencode(".png", bgr)
    data = NSData.dataWithBytes_length_(png.tobytes(), len(png))
    src = Quartz.CGImageSourceCreateWithData(data, None)
    img = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setUsesLanguageCorrection_(False)
    Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(img, None).performRequests_error_([req], None)
    h, w = bgr.shape[:2]
    out = []
    for o in req.results() or []:
        c = o.topCandidates_(1)[0]
        b = o.boundingBox()
        x1, x2 = b.origin.x * w, (b.origin.x + b.size.width) * w
        y1, y2 = (1 - b.origin.y - b.size.height) * h, (1 - b.origin.y) * h
        out.append({"text": str(c.string()), "conf": float(c.confidence()), "box": [x1, y1, x2, y2]})
    return out


# ---------------------------------------------------------------- appearance embeddings

class Embedder:
    def __init__(self):
        import torch
        import torchvision

        self.torch = torch
        self.dev = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
        m = torchvision.models.resnet50(weights=torchvision.models.ResNet50_Weights.IMAGENET1K_V2)
        m.fc = torch.nn.Identity()
        self.model = m.eval().to(self.dev)
        self.mean = torch.tensor([0.485, 0.456, 0.406], device=self.dev).view(1, 3, 1, 1)
        self.std = torch.tensor([0.229, 0.224, 0.225], device=self.dev).view(1, 3, 1, 1)

    @staticmethod
    def prep(crop):
        h, w = crop.shape[:2]
        s = max(h, w)
        pt, pl = (s - h) // 2, (s - w) // 2
        sq = cv2.copyMakeBorder(crop, pt, s - h - pt, pl, s - w - pl, cv2.BORDER_REPLICATE)
        return cv2.cvtColor(cv2.resize(sq, (224, 224), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)

    def embed(self, crops):
        if not crops:
            return np.zeros((0, 2048), np.float32)
        t = self.torch
        x = t.from_numpy(np.stack([self.prep(c) for c in crops])).to(self.dev).permute(0, 3, 1, 2).float() / 255.0
        with t.no_grad():
            f = self.model((x - self.mean) / self.std)
            f = t.nn.functional.normalize(f, dim=1)
        return f.cpu().numpy()


def pad_box(box, shape, frac=0.08, minpad=6):
    h, w = shape[:2]
    x1, y1, x2, y2 = box
    p = max(minpad, frac * max(x2 - x1, y2 - y1))
    return [int(max(0, x1 - p)), int(max(0, y1 - p)), int(min(w, x2 + p)), int(min(h, y2 + p))]


# ---------------------------------------------------------------- identifier

class Identifier:
    def __init__(self, setting_id="bench", thr=0.75, roi=None, use_embedder=True):
        self.setting_id = setting_id
        self.setting = load_setting(setting_id)
        self.thr = thr
        self.roi = roi  # [x1,y1,x2,y2] pixels or None
        self.calib = load_calibration()
        self.lock = threading.RLock()
        self.embedder = Embedder() if use_embedder else None
        self.ref_cache: dict[str, tuple[float, np.ndarray]] = {}
        self.empty = cv2.imread(str(EMPTY)) if EMPTY.exists() else None
        self.last_frame = None
        self.last_blobs: list[dict] = []
        self.last_state: dict | None = None
        self.last_jpeg: bytes | None = None
        self.source = ""

    def set_setting(self, setting_id):
        with self.lock:
            self.setting = load_setting(setting_id)
            self.setting_id = setting_id

    # ---- references
    def ref_files(self, item_id):
        d = REFS / item_id
        return sorted(d.glob("*.jpg")) if d.is_dir() else []

    def ref_counts(self):
        return {i["id"]: len(self.ref_files(i["id"])) for i in self.setting["items"]}

    def ref_embeddings(self, item_id) -> np.ndarray:
        files = self.ref_files(item_id)
        key = tuple((str(f), f.stat().st_mtime) for f in files)
        cached = self.ref_cache.get(item_id)
        if cached and cached[0] == key:
            return cached[1]
        emb = self.embedder.embed([cv2.imread(str(f)) for f in files]) if files else np.zeros((0, 2048), np.float32)
        self.ref_cache[item_id] = (key, emb)
        return emb

    def enroll(self, blob_index, item_id):
        with self.lock:
            if self.last_frame is None or not (0 <= blob_index < len(self.last_blobs)):
                raise ValueError("no such blob")
            if item_id not in {i["id"] for i in self.setting["items"]}:
                raise ValueError("unknown item id")
            x1, y1, x2, y2 = pad_box(self.last_blobs[blob_index]["box"], self.last_frame.shape)
            d = REFS / item_id
            d.mkdir(parents=True, exist_ok=True)
            path = d / f"{int(time.time() * 1000)}.jpg"
            cv2.imwrite(str(path), self.last_frame[y1:y2, x1:x2], [cv2.IMWRITE_JPEG_QUALITY, 95])
            return str(path.relative_to(HERE))

    def delete_refs(self, item_id):
        with self.lock:
            n = 0
            for f in self.ref_files(item_id):
                f.unlink()
                n += 1
            self.ref_cache.pop(item_id, None)
            return n

    def save_empty(self):
        with self.lock:
            if self.last_frame is None:
                raise ValueError("no frame yet")
            REFS.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(EMPTY), self.last_frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
            self.empty = self.last_frame.copy()

    def clear_empty(self):
        with self.lock:
            EMPTY.unlink(missing_ok=True)
            self.empty = None

    # ---- stage 1: blobs
    def find_blobs(self, frame):
        H, W = frame.shape[:2]
        rx1, ry1, rx2, ry2 = self.roi or [0, 0, W, H]
        rx1, ry1, rx2, ry2 = int(max(0, rx1)), int(max(0, ry1)), int(min(W, rx2)), int(min(H, ry2))
        roi = frame[ry1:ry2, rx1:rx2]
        blur = cv2.GaussianBlur(roi, (5, 5), 0)
        if self.empty is not None and self.empty.shape == frame.shape:
            ref = cv2.GaussianBlur(self.empty[ry1:ry2, rx1:rx2], (5, 5), 0)
            diff = cv2.absdiff(blur, ref).max(axis=2)
            mask = (diff > 35).astype(np.uint8) * 255
            mode = "empty_ref"
        else:
            # no reference: contrast against a heavily smoothed background (silver tray is smooth)
            g = cv2.cvtColor(blur, cv2.COLOR_BGR2GRAY)
            k = 21  # small enough to follow tray reflections, large enough to keep tool bodies
            bg = cv2.medianBlur(g, k)
            d = cv2.absdiff(g, bg).astype(np.float32)
            s = cv2.cvtColor(blur, cv2.COLOR_BGR2HSV)[:, :, 1].astype(np.float32)
            sbg = cv2.medianBlur(s.astype(np.uint8), k).astype(np.float32)
            d = np.maximum(d, np.abs(s - sbg) * 0.7)
            mask = (d > 22).astype(np.uint8) * 255
            mode = "edge_sat"
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 9)))
        n, _lab, stats, _c = cv2.connectedComponentsWithStats(mask)
        area_roi = mask.shape[0] * mask.shape[1]
        blobs = []
        for i in range(1, n):
            x, y, w, h, a = stats[i]
            if max(w, h) < 25 or a < 0.0015 * area_roi or a > 0.6 * area_roi:
                continue
            blobs.append({"box": [int(x + rx1), int(y + ry1), int(x + w + rx1), int(y + h + ry1)], "area": int(a), "kind": "seg"})
        blobs.sort(key=lambda b: (b["box"][1], b["box"][0]))
        return blobs, mode

    # ---- full cycle
    def process(self, frame, source=""):
        with self.lock:
            return self._process(frame, source)

    def _process(self, frame, source):
        t0 = time.perf_counter()
        H, W = frame.shape[:2]
        timings = {}
        t = time.perf_counter()
        blobs, seg_mode = self.find_blobs(frame)
        timings["segment"] = (time.perf_counter() - t) * 1000

        # OCR over the ROI
        t = time.perf_counter()
        rx1, ry1, rx2, ry2 = [int(v) for v in (self.roi or [0, 0, W, H])]
        texts = ocr(frame[ry1:ry2, rx1:rx2])
        for o in texts:
            o["box"] = [o["box"][0] + rx1, o["box"][1] + ry1, o["box"][2] + rx1, o["box"][3] + ry1]
        timings["ocr"] = (time.perf_counter() - t) * 1000

        for b in blobs:
            b.update(item=None, by=None, confidence=0.0, text=None)
        ocr_hits = []
        for o in texts:
            m = match_text(o["text"], self.setting)
            if m:
                ocr_hits.append((o, m[0], round(o["conf"] * m[1], 3)))
        for o, item_id, conf in sorted(ocr_hits, key=lambda x: -x[2]):
            cx, cy = (o["box"][0] + o["box"][2]) / 2, (o["box"][1] + o["box"][3]) / 2
            target, best_d = None, 1e9
            for b in blobs:
                if b["kind"] != "seg":
                    continue
                bx1, y1, bx2, y2 = b["box"]
                pad = 0.35 * max(bx2 - bx1, y2 - y1) + 15
                if bx1 - pad <= cx <= bx2 + pad and y1 - pad <= cy <= y2 + pad:
                    d = np.hypot(cx - (bx1 + bx2) / 2, cy - (y1 + y2) / 2)
                    if d < best_d:
                        target, best_d = b, d
            if target is None:  # label with no object near it: the label itself is the detection
                x1, y1, x2, y2 = o["box"]
                target = {"box": [int(x1), int(y1), int(x2), int(y2)], "area": 0, "kind": "text",
                          "item": None, "by": None, "confidence": 0.0, "text": None}
                blobs.append(target)
            if target["by"] is None or conf > target["confidence"]:
                target.update(item=item_id, by="ocr", confidence=conf, text=o["text"])
        # one blob per item: keep the best OCR claim
        claimed = {}
        for i, b in enumerate(blobs):
            if b["by"] == "ocr":
                j = claimed.get(b["item"])
                if j is None or b["confidence"] > blobs[j]["confidence"]:
                    if j is not None:
                        blobs[j].update(item=None, by=None, confidence=0.0)
                    claimed[b["item"]] = i
                else:
                    b.update(item=None, by=None, confidence=0.0)

        # appearance
        t = time.perf_counter()
        scores_dbg = []
        if self.embedder is not None:
            cand = [i for i, b in enumerate(blobs) if b["by"] is None and b["kind"] == "seg"]
            refs = {it["id"]: self.ref_embeddings(it["id"]) for it in self.setting["items"] if it["id"] not in claimed}
            refs = {k: v for k, v in refs.items() if len(v)}
            if cand and refs:
                emb = self.embedder.embed([frame[slice(*pad_box(blobs[i]["box"], frame.shape)[1::2]),
                                                slice(*pad_box(blobs[i]["box"], frame.shape)[0::2])] for i in cand])
                pairs = []
                for ci, i in enumerate(cand):
                    for item_id, r in refs.items():
                        pairs.append((float((r.astype(np.float64) * emb[ci].astype(np.float64)).sum(axis=1).max()), i, item_id))
                scores_dbg = sorted(pairs, reverse=True)
                used_b, used_i = set(), set()
                for s, i, item_id in scores_dbg:
                    if s < self.thr or i in used_b or item_id in used_i:
                        continue
                    blobs[i].update(item=item_id, by="appearance", confidence=round(s, 3))
                    used_b.add(i)
                    used_i.add(item_id)
        timings["embed_match"] = (time.perf_counter() - t) * 1000

        for i, b in enumerate(blobs):
            b["index"] = i
            b["center_px"] = [round((b["box"][0] + b["box"][2]) / 2, 1), round((b["box"][1] + b["box"][3]) / 2, 1)]
            b["arm_xy"] = pixel_to_arm(self.calib, *b["center_px"]) if self.calib is not None else None
        ident = {b["item"]: b for b in blobs if b["item"]}

        items, slots = [], []
        for it in self.setting["items"]:
            b = ident.get(it["id"])
            slot = it.get("slot") if isinstance(it.get("slot"), list) and len(it["slot"]) == 4 else None
            present = b is not None
            if present and slot:
                cx, cy = b["center_px"]
                present = slot[0] <= cx <= slot[2] and slot[1] <= cy <= slot[3]
            items.append({
                "id": it["id"], "name": it.get("name", it["id"]), "present": b is not None,
                "box": b["box"] if b else None, "center_px": b["center_px"] if b else None,
                "arm_xy": b["arm_xy"] if b else None,
                "confidence": b["confidence"] if b else 0.0, "by": b["by"] if b else None,
                "refs": len(self.ref_files(it["id"])),
            })
            slots.append({"item": it["id"], "present": present,
                          "confidence": b["confidence"] if present else 0.5,
                          "box": slot or (b["box"] if b else None)})
        timings["total"] = (time.perf_counter() - t0) * 1000
        now = time.time()
        state = {
            "t": now, "source": source or self.source, "setting": self.setting_id,
            "frame": [W, H], "roi": self.roi, "segmentation": seg_mode,
            "items": items,
            "unknown": [{"index": b["index"], "box": b["box"], "center_px": b["center_px"], "arm_xy": b["arm_xy"]}
                        for b in blobs if b["item"] is None],
            "blobs": [{k: b[k] for k in ("index", "box", "kind", "item", "by", "confidence", "text")} for b in blobs],
            "ocr_text": [{"text": o["text"], "conf": round(o["conf"], 3), "box": [round(v) for v in o["box"]]} for o in texts],
            "calibrated": self.calib is not None, "has_empty_ref": self.empty is not None,
            "tray_state": {"setting": self.setting_id, "slots": slots,
                           "return_spot": {"item": None, "confidence": 0.0, "box": None}, "t": now},
            "timings_ms": {k: round(v, 1) for k, v in timings.items()},
            "top_appearance_scores": [[round(s, 3), i, it] for s, i, it in scores_dbg[:6]],
        }
        self.last_frame, self.last_blobs, self.last_state = frame.copy(), blobs, state
        self.last_jpeg = self.annotate(frame, blobs)
        return state

    def annotate(self, frame, blobs):
        im = frame.copy()
        if self.roi:
            x1, y1, x2, y2 = [int(v) for v in self.roi]
            cv2.rectangle(im, (x1, y1), (x2, y2), (200, 160, 0), 1)
        for b in blobs:
            x1, y1, x2, y2 = b["box"]
            col = (60, 160, 40) if b["item"] else (40, 40, 220)
            if b["kind"] == "text":
                col = (200, 120, 0) if not b["item"] else (60, 160, 40)
            cv2.rectangle(im, (x1, y1), (x2, y2), col, 2)
            label = f'{b["index"]}: ' + (f'{b["item"]} {b["confidence"]:.2f} {b["by"]}' if b["item"] else "unknown")
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            ty = max(th + 4, y1)
            cv2.rectangle(im, (x1, ty - th - 4), (x1 + tw + 4, ty), col, -1)
            cv2.putText(im, label, (x1 + 2, ty - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
        return cv2.imencode(".jpg", im, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()


# ---------------------------------------------------------------- sources

class FileSource:
    def __init__(self, path):
        self.path = path
        self.frame = cv2.imread(path)
        if self.frame is None:
            sys.exit(f"cannot read image {path}")
        self.name = f"file:{path}"

    def get(self):
        return self.frame.copy()


class MJPEGSource:
    """Read-only GET of the recorder's MJPEG stream; keeps only the newest frame."""

    def __init__(self, url=STREAM_URL):
        self.url, self.name = url, "arm_session"
        self.frame, self.stamp = None, 0.0
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            try:
                buf = b""
                with urllib.request.urlopen(self.url, timeout=5) as r:
                    while True:
                        chunk = r.read(16384)
                        if not chunk:
                            raise EOFError("stream ended")
                        buf += chunk
                        while True:
                            a = buf.find(b"\xff\xd8")
                            b = buf.find(b"\xff\xd9", a + 2) if a >= 0 else -1
                            if a < 0 or b < 0:
                                break
                            img = cv2.imdecode(np.frombuffer(buf[a:b + 2], np.uint8), cv2.IMREAD_COLOR)
                            buf = buf[b + 2:]
                            if img is not None:
                                self.frame, self.stamp = img, time.time()
                        if len(buf) > 4_000_000:
                            buf = b""
            except Exception as e:
                print("stream error:", e, flush=True)
                time.sleep(1)

    def get(self):
        t0 = time.time()
        while self.frame is None and time.time() - t0 < 5:
            time.sleep(0.05)
        return None if self.frame is None else self.frame.copy()


class CameraSource:
    def __init__(self, spec):
        ps = subprocess.run(["ps", "-axo", "command"], capture_output=True, text=True).stdout
        if any("arm_session.py" in l or "record" in l and "python" in l for l in ps.splitlines()
               if "identify.py" not in l and "grep" not in l):
            sys.exit("a recorder (arm_session.py) is running; use --source arm_session instead")
        import AVFoundation as AVF
        devs = sorted(AVF.AVCaptureDevice.devicesWithMediaType_(AVF.AVMediaTypeVideo), key=lambda d: str(d.uniqueID()))
        names = [str(d.localizedName()) for d in devs]
        hits = [i for i, n in enumerate(names) if spec.lower() in n.lower()]
        if len(hits) != 1:
            sys.exit(f"camera {spec!r} matches {len(hits)} of {names}")
        self.cap = cv2.VideoCapture(hits[0])
        self.name = f"camera:{names[hits[0]]}"

    def get(self):
        ok, f = self.cap.read()
        return f if ok else None


def make_source(spec):
    if spec == "arm_session":
        return MJPEGSource()
    if spec.startswith("camera:"):
        return CameraSource(spec[7:])
    if spec.startswith("file:"):
        return FileSource(spec[5:])
    sys.exit("--source must be arm_session, camera:NAME or file:PATH")


# ---------------------------------------------------------------- server

def post_tray(url, state):
    try:
        req = urllib.request.Request(url.rstrip("/") + "/vision/tray", data=json.dumps(state).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=2).read()
    except Exception as e:
        print("controller post failed:", e, flush=True)


def build_app(idf, src, args):
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse, JSONResponse, Response

    app = FastAPI()
    dirty = threading.Event()
    dirty.set()

    def loop():
        while True:
            t0 = time.time()
            try:
                if not (src.name.startswith("file:") and not dirty.is_set()):
                    dirty.clear()
                    f = src.get()
                    if f is not None:
                        st = idf.process(f, src.name)
                        if args.controller:
                            post_tray(args.controller, st["tray_state"])
            except Exception as e:
                print("cycle error:", repr(e), flush=True)
            time.sleep(max(0.05, 1.0 / args.hz - (time.time() - t0)))

    threading.Thread(target=loop, daemon=True).start()

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (HERE / "identify.html").read_text(encoding="utf-8")

    @app.get("/api/state")
    def state():
        return JSONResponse(idf.last_state or {"t": None, "source": src.name, "setting": idf.setting_id, "items": [],
                                               "blobs": [], "unknown": [], "timings_ms": {}, "frame": None,
                                               "has_empty_ref": idf.empty is not None, "roi": idf.roi,
                                               "setting_items": []})

    @app.get("/api/items")
    def items():
        return {"setting": idf.setting_id, "items": [{"id": i["id"], "name": i.get("name", i["id"])} for i in idf.setting["items"]]}

    @app.get("/api/frame.jpg")
    def frame():
        if idf.last_jpeg is None:
            raise HTTPException(404, "no frame yet")
        return Response(idf.last_jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.post("/api/enroll")
    def enroll(body: dict):
        try:
            p = idf.enroll(int(body["blob_index"]), str(body["item_id"]))
        except (ValueError, KeyError) as e:
            raise HTTPException(400, str(e))
        dirty.set()
        return {"ok": True, "saved": p}

    @app.post("/api/empty")
    def empty(body: dict | None = None):
        try:
            if body and body.get("clear"):
                idf.clear_empty()
            else:
                idf.save_empty()
        except ValueError as e:
            raise HTTPException(400, str(e))
        dirty.set()
        return {"ok": True}

    @app.post("/api/roi")
    def roi(body: dict):
        r = body.get("roi")
        if r is not None:
            if len(r) != 4 or r[2] - r[0] < 20 or r[3] - r[1] < 20:
                raise HTTPException(400, "roi must be [x1,y1,x2,y2], at least 20 px")
            r = [int(v) for v in r]
        idf.roi = r
        dirty.set()
        return {"ok": True, "roi": r}

    @app.post("/api/refs/delete")
    def refs_delete(body: dict):
        n = idf.delete_refs(str(body["item_id"]))
        dirty.set()
        return {"ok": True, "deleted": n}

    @app.post("/api/setting")
    def setting(body: dict):
        try:
            idf.set_setting(str(body["setting"]))
        except Exception as e:
            raise HTTPException(400, str(e))
        dirty.set()
        return {"ok": True}

    return app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="arm_session")
    ap.add_argument("--setting", default="bench")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--hz", type=float, default=1.0)
    ap.add_argument("--thr", type=float, default=0.75, help="appearance cosine threshold")
    ap.add_argument("--roi", type=int, nargs=4, metavar=("X1", "Y1", "X2", "Y2"))
    ap.add_argument("--controller", default=None, help="base URL; POSTs TrayState to <url>/vision/tray (default off)")
    ap.add_argument("--once", action="store_true", help="process one frame, print JSON, exit")
    args = ap.parse_args()
    src = make_source(args.source)
    idf = Identifier(args.setting, args.thr, args.roi)
    if args.once:
        f = src.get()
        print(json.dumps(idf.process(f, src.name), indent=1))
        return
    import uvicorn
    uvicorn.run(build_app(idf, src, args), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
