"""Camera aim checker for the SO-101 rig. Frame the side/wrist cameras like the training demos.

File mode (never touches a camera):
  .venv/bin/python explore/dataset/aim.py --dataset DIR --side-image cam0.jpg --wrist-image cam1.jpg
  .venv/bin/python explore/dataset/aim.py --dataset DIR --side-image cam0.jpg --ref-side dataset:side:0:0 --analyze
Live mode (if arm_session.py runs, reads its :8090 streams; if another recorder runs, refuses):
  .venv/bin/python explore/dataset/aim.py --live --side C920 --wrist icspring

Reference spec: a jpg path, a name in explore/dataset/refs/, 'arm_session' (recorder's saved ref), or dataset:CAM:FILE:FRAME.
Page: http://localhost:8096 (8000-8090 belong to other tools).
"""
import argparse
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
REFS = HERE / "refs"
PORT = 8096
SLOTS = ("side", "wrist")
SHARP_MIN = 60.0          # Laplacian variance at 640 px wide; below this is blurry
BRIGHT_RANGE = (50, 200)  # mean gray


# ---------- camera safety ----------
def recorders_running() -> list[str]:
    out = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout
    me = os.getpid()
    hits = []
    for line in out.splitlines():
        pid, _, cmd = line.strip().partition(" ")
        if pid.isdigit() and int(pid) != me and re.search(r"arm_session\.py|lerobot-record|lerobot\.record", cmd) \
                and "aim.py" not in cmd and not cmd.startswith(("grep", "rg ")):
            hits.append(f"{pid} {cmd[:100]}")
    return hits


def camera_names() -> list[str]:
    # same approach as explore/arm_session.py: OpenCV's macOS order is AVFoundation devices sorted by uniqueID
    import AVFoundation as AVF
    devs = AVF.AVCaptureDevice.devicesWithMediaType_(AVF.AVMediaTypeVideo)
    return [str(d.localizedName()) for d in sorted(devs, key=lambda d: str(d.uniqueID()))]


def camera_index(spec: str) -> int:
    if spec.isdigit():
        return int(spec)
    names = camera_names()
    hits = [i for i, n in enumerate(names) if spec.lower() in n.lower()]
    if len(hits) != 1:
        raise RuntimeError(f"camera {spec!r} matches {len(hits)} of {names}")
    return hits[0]


ARM = "http://localhost:8090"  # explore/arm_session.py recorder page, serves camera streams read-only


def arm_session_up() -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(ARM + "/status", timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


class Live:
    """Camera frames. If a recorder runs, only its MJPEG stream is read (camera never opened here)."""
    def __init__(self, spec: str, slot: str = "side"):
        busy = recorders_running()
        if busy:
            if not arm_session_up():
                raise RuntimeError("refusing to open cameras, a recorder is running and its stream at "
                                   + ARM + " is not reachable: " + "; ".join(busy))
            self.cap = cv2.VideoCapture(f"{ARM}/stream/{slot}")
            if not self.cap.isOpened():
                raise RuntimeError(f"cannot read {ARM}/stream/{slot}")
            self.frame, self.stop = None, False
            threading.Thread(target=self._run, daemon=True).start()
            return
        self.cap = cv2.VideoCapture(camera_index(spec))
        if not self.cap.isOpened():
            raise RuntimeError(f"cannot open camera {spec!r}")
        self.frame, self.stop = None, False
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while not self.stop:
            ok, f = self.cap.read()
            if ok:
                self.frame = f
            else:
                time.sleep(0.05)

    def close(self):
        self.stop = True
        time.sleep(0.1)
        self.cap.release()


# ---------- frame sources ----------
def dataset_frame(root: Path, cam: str, file: int, frame: int):
    p = root / "videos" / f"observation.images.{cam}" / "chunk-000" / f"file-{file:03d}.mp4"
    if not p.exists():
        raise RuntimeError(f"missing {p}")
    c = cv2.VideoCapture(str(p))
    try:
        n = int(c.get(cv2.CAP_PROP_FRAME_COUNT))
        c.set(cv2.CAP_PROP_POS_FRAMES, max(0, min(frame, max(n - 1, 0))))
        ok, f = c.read()
    finally:
        c.release()
    if not ok:
        raise RuntimeError(f"cannot decode {p} frame {frame}")
    return f


def load_image(path: str):
    f = cv2.imread(path)
    if f is None:
        raise RuntimeError(f"cannot read image {path}")
    return f


def resolve_ref(spec: str, root: Path | None):
    if spec.startswith("dataset:"):
        _, cam, file, frame = spec.split(":")
        if root is None:
            raise RuntimeError("no --dataset given")
        return dataset_frame(root, cam, int(file), int(frame))
    if spec == "arm_session":  # the reference saved in the recorder page
        import urllib.request
        with urllib.request.urlopen(ARM + "/reference.jpg", timeout=3) as r:
            img = cv2.imdecode(np.frombuffer(r.read(), np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError("no reference at " + ARM + "/reference.jpg")
        return img
    p = Path(spec)
    if not p.exists():
        p = REFS / (spec if spec.endswith(".jpg") else spec + ".jpg")
    return load_image(str(p))


# ---------- analysis ----------
def small(img, w=640):
    h = int(img.shape[0] * w / img.shape[1])
    return cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)


def tilt(img):
    g = cv2.cvtColor(small(img), cv2.COLOR_BGR2GRAY)
    g = cv2.GaussianBlur(g, (5, 5), 0)
    e = cv2.Canny(g, 50, 150)
    h, w = g.shape
    lines = cv2.HoughLinesP(e, 1, np.pi / 360, 60, minLineLength=w // 5, maxLineGap=10)
    out, angs, wts = [], [], []
    if lines is not None:
        for x1, y1, x2, y2 in lines[:, 0]:
            a = math.degrees(math.atan2(y2 - y1, x2 - x1))
            a = (a + 45) % 90 - 45  # fold: horizontals and verticals both vote for roll, in [-45, 45)
            L = math.hypot(x2 - x1, y2 - y1)
            angs.append(a); wts.append(L)
            out.append([x1 / w, y1 / h, x2 / w, y2 / h, round(a, 2), L])
    if not angs:
        return {"deg": None, "lines": [], "n": 0}
    order = np.argsort(angs)
    cw = np.cumsum(np.array(wts)[order])
    deg = float(np.array(angs)[order][np.searchsorted(cw, cw[-1] / 2)])  # length weighted median
    out.sort(key=lambda r: -r[5])
    return {"deg": round(deg, 2), "n": len(angs), "lines": [r[:5] for r in out[:8]]}


def exposure(img):
    s = small(img)
    g = cv2.cvtColor(s, cv2.COLOR_BGR2GRAY)
    sharp = float(cv2.Laplacian(g, cv2.CV_64F).var())
    br = float(g.mean())
    return {
        "sharp": round(sharp, 1), "sharp_ok": sharp >= SHARP_MIN,
        "bright": round(br, 1), "bright_ok": BRIGHT_RANGE[0] <= br <= BRIGHT_RANGE[1],
        "clipped_pct": round(float((g >= 250).mean() * 100), 1),
    }


def align(live, ref):
    """Homography live->ref from ORB matches. Reports how the live camera differs from the reference."""
    # live may be 16:9 while the dataset is 4:3: center-crop live to the ref aspect, then match sizes
    rh, rw = ref.shape[:2]
    lh, lw = live.shape[:2]
    if abs(lw / lh - rw / rh) > 0.02:
        if lw / lh > rw / rh:
            nw = int(lh * rw / rh); x0 = (lw - nw) // 2; live = live[:, x0:x0 + nw]
        else:
            nh = int(lw * rh / rw); y0 = (lh - nh) // 2; live = live[y0:y0 + nh]
    H0, W0 = live.shape[:2]
    if ref.shape[:2] != (H0, W0):
        ref = cv2.resize(ref, (W0, H0), interpolation=cv2.INTER_AREA)
    sc = 960 / W0 if W0 > 960 else 1.0
    a = cv2.cvtColor(cv2.resize(live, None, fx=sc, fy=sc), cv2.COLOR_BGR2GRAY)
    b = cv2.cvtColor(cv2.resize(ref, None, fx=sc, fy=sc), cv2.COLOR_BGR2GRAY)
    orb = cv2.ORB_create(2000)
    ka, da = orb.detectAndCompute(a, None)
    kb, db = orb.detectAndCompute(b, None)
    res = {"ok": False, "reason": "not enough features"}
    if da is None or db is None or len(ka) < 12 or len(kb) < 12:
        return res
    m = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(da, db, k=2)
    good = [p[0] for p in m if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
    res.update(matches=len(good))
    if len(good) < 10:
        res["reason"] = f"only {len(good)} good matches, scenes differ too much"
        return res
    src = np.float32([ka[g.queryIdx].pt for g in good]).reshape(-1, 1, 2)  # live
    dst = np.float32([kb[g.trainIdx].pt for g in good]).reshape(-1, 1, 2)  # ref
    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
    if H is None:
        res["reason"] = "homography failed"
        return res
    inl = int(mask.sum())
    c = np.array([[[a.shape[1] / 2, a.shape[0] / 2]]], np.float32)
    # move needed: where the live center lands in the ref = how far the scene sits from where it was
    cc = cv2.perspectiveTransform(c, H)[0, 0]
    dx, dy = (cc[0] - c[0, 0, 0]) / sc, (cc[1] - c[0, 0, 1]) / sc
    rot = math.degrees(math.atan2(H[1, 0], H[0, 0]))
    scale = math.sqrt(abs(np.linalg.det(H[:2, :2])))
    ratio = inl / len(good)
    shift_pct = math.hypot(dx, dy) / W0 * 100
    aligned = inl >= 15 and ratio > 0.4 and shift_pct < 2 and abs(rot) < 1.5 and abs(scale - 1) < 0.03
    score = 0.0
    if inl >= 15 and ratio > 0.3:
        score = max(0.0, 100 - shift_pct * 8 - abs(rot) * 6 - abs(scale - 1) * 300)
    res.update(ok=True, reason="", inliers=inl, inlier_ratio=round(ratio, 2),
               shift_x=round(dx, 1), shift_y=round(dy, 1), shift_px=round(math.hypot(dx, dy), 1),
               rotation_deg=round(rot, 2), scale=round(scale, 3), score=round(score), aligned=aligned,
               trusted=bool(inl >= 15 and ratio > 0.3))
    if not res["trusted"]:
        res["reason"] = "match set too weak to trust the numbers"
    return res


def analyze(img, ref=None):
    r = {"size": [img.shape[1], img.shape[0]], "tilt": tilt(img), **exposure(img)}
    r["tilt_ok"] = r["tilt"]["deg"] is not None and abs(r["tilt"]["deg"]) <= 1.5
    if ref is not None:
        r["align"] = align(img, ref)
    return r


def jpg(img, w=960, q=80) -> bytes:
    if img.shape[1] > w:
        img = small(img, w)
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])[1].tobytes()


# ---------- server state ----------
class Slot:
    def __init__(self, name):
        self.name, self.kind, self.desc = name, "none", ""
        self.static = None
        self.live = None
        self.ref = None
        self.ref_desc = ""
        self.error = ""

    def frame(self):
        if self.live is not None:
            return self.live.frame
        return self.static


class App:
    def __init__(self, dataset: Path | None, allow_live: bool):
        self.dataset, self.allow_live = dataset, allow_live
        self.slots = {n: Slot(n) for n in SLOTS}
        self.lock = threading.Lock()

    def set_source(self, name, kind, value="", file=0, frame=0):
        s = self.slots[name]
        with self.lock:
            s.error = ""
            try:
                if s.live is not None:
                    s.live.close(); s.live = None
                if kind == "image":
                    s.static, s.kind, s.desc = load_image(value), "image", value
                elif kind == "dataset":
                    s.static = dataset_frame(self.dataset, name, int(file), int(frame))
                    s.kind, s.desc = "dataset", f"{name} file {file} frame {frame}"
                elif kind == "live":
                    if not self.allow_live:
                        raise RuntimeError("live mode not enabled, start with --live")
                    s.live, s.static = Live(value, name), None
                    s.kind, s.desc = "live", value
                else:
                    raise RuntimeError(f"unknown kind {kind}")
            except Exception as e:
                s.error = str(e)
                print(f"[{name}] {e}", flush=True)

    def set_ref(self, name, spec):
        s = self.slots[name]
        try:
            s.ref, s.ref_desc, s.error = resolve_ref(spec, self.dataset), spec, ""
        except Exception as e:
            s.error = str(e)

    def close(self):
        for s in self.slots.values():
            if s.live is not None:
                s.live.close()


def make_api(app: App):
    from fastapi import FastAPI, Response
    from fastapi.responses import HTMLResponse, JSONResponse
    api = FastAPI()

    @api.get("/", response_class=HTMLResponse)
    def index():
        return (HERE / "aim.html").read_text()

    @api.get("/api/state")
    def state():
        refs = sorted(p.stem for p in REFS.glob("*.jpg"))
        return {"slots": {n: {"kind": s.kind, "desc": s.desc, "ref": s.ref_desc, "error": s.error,
                              "has_ref": s.ref is not None} for n, s in app.slots.items()},
                "refs": refs, "dataset": str(app.dataset) if app.dataset else "", "live": app.allow_live,
                "recorders": recorders_running(), "sharp_min": SHARP_MIN, "bright_range": BRIGHT_RANGE}

    @api.post("/api/source")
    def source(b: dict):
        app.set_source(b["slot"], b["kind"], b.get("value", ""), b.get("file", 0), b.get("frame", 0))
        return state()

    @api.post("/api/ref")
    def ref(b: dict):
        app.set_ref(b["slot"], b["spec"])
        return state()

    @api.get("/api/frame/{slot}.jpg")
    def frame(slot: str):
        f = app.slots[slot].frame()
        if f is None:
            return Response(status_code=204)
        return Response(jpg(f), media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @api.get("/api/ref/{slot}.jpg")
    def refimg(slot: str):
        r = app.slots[slot].ref
        if r is None:
            return Response(status_code=204)
        f = app.slots[slot].frame()
        if f is not None and r.shape[:2] != f.shape[:2]:
            r = cv2.resize(r, (f.shape[1], f.shape[0]))
        return Response(jpg(r), media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @api.get("/api/analyze/{slot}")
    def an(slot: str):
        s = app.slots[slot]
        f = s.frame()
        if f is None:
            return JSONResponse({"error": s.error or "no frame"})
        return analyze(f, s.ref)

    @api.post("/api/save_ref")
    def save_ref(b: dict):
        s = app.slots[b["slot"]]
        f = s.frame()
        name = re.sub(r"[^A-Za-z0-9_-]", "", b.get("name", ""))[:40]
        if f is None or not name:
            return JSONResponse({"error": "need a frame and a name (letters, digits, - _)"}, 400)
        REFS.mkdir(exist_ok=True)
        path = REFS / f"{name}.jpg"
        path.write_bytes(jpg(f, 640, 80))
        app.set_ref(b["slot"], name)
        return {"saved": str(path), "bytes": path.stat().st_size}

    return api


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dataset", help="LeRobot dataset root (videos/observation.images.side|wrist)")
    p.add_argument("--image", action="append", default=[], help="SLOT=PATH, e.g. side=cam0.jpg")
    p.add_argument("--side-image"); p.add_argument("--wrist-image")
    p.add_argument("--ref-side"); p.add_argument("--ref-wrist")
    p.add_argument("--live", action="store_true", help="open cameras (refused if a recorder runs)")
    p.add_argument("--side", help="live side camera name part, e.g. C920")
    p.add_argument("--wrist", help="live wrist camera name part, e.g. icspring")
    p.add_argument("--analyze", action="store_true", help="print JSON for the given images and exit, no server")
    p.add_argument("--port", type=int, default=PORT)
    a = p.parse_args()

    if a.live:
        busy = recorders_running()
        if busy and arm_session_up():
            print("recorder running: reading its streams at " + ARM + " (cameras not opened here)", flush=True)
        elif busy:
            sys.exit("refusing live mode, cameras may be in use by a recorder:\n  " + "\n  ".join(busy)
                     + "\nstop it first, or use --image/--dataset (file mode).")
    ds = Path(a.dataset) if a.dataset else None
    app = App(ds, a.live)
    imgs = dict(i.split("=", 1) for i in a.image)
    if a.side_image: imgs["side"] = a.side_image
    if a.wrist_image: imgs["wrist"] = a.wrist_image
    for n, v in imgs.items():
        app.set_source(n, "image", v)
    for n, v in (("side", a.side), ("wrist", a.wrist)):
        if v and a.live:
            app.set_source(n, "live", v)
        elif ds and n not in imgs:
            app.set_source(n, "dataset", file=0, frame=0)
    for n, v in (("side", a.ref_side), ("wrist", a.ref_wrist)):
        if v:
            app.set_ref(n, v)
        elif ds and n not in imgs:
            pass
    if a.analyze:
        for n, s in app.slots.items():
            if s.frame() is not None:
                print(n, json.dumps({"source": s.desc, "ref": s.ref_desc, **analyze(s.frame(), s.ref)}, indent=1))
            elif s.error:
                print(n, "error:", s.error)
        return
    import uvicorn
    try:
        uvicorn.run(make_api(app), host="127.0.0.1", port=a.port, log_level="warning")
    finally:
        app.close()


if __name__ == "__main__":
    main()
