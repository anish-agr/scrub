"""Save real camera clips of every station Run (the arm driving itself), without touching the arm.

  .venv/bin/python explore/run_clips.py                  # watch http://localhost:8090, clips in ~/scrub-clips
  .venv/bin/python explore/run_clips.py --station http://localhost:8090 --out ~/scrub-clips --post 3

The station never records frames in Run mode. This reads only its GET /status and GET /frame/<cam>.jpg
(the same frames its page shows), so the station, the arm and the dataset are not affected. While
status.state is "running", and for --post seconds after, it writes per run:
  run-<time>-<driver>/side.mp4, wrist.mp4   each camera at 30 fps (a frame is repeated if the camera lags)
  run-<time>-<driver>/both.mp4             side by side, labeled with the clock, driver and phase
  run-<time>-<driver>/run.json             the station's run info and the phase timeline
It waits quietly while the station is down or restarting.
"""
import argparse
import json
import threading
import time
from pathlib import Path

import cv2
import httpx
import numpy as np

FPS = 30
CAMS = ("side", "wrist")


class Grabber(threading.Thread):
    """Latest JPEG from /frame/<cam>.jpg, polled at about 30 Hz while `on` is set."""

    def __init__(self, base, cam):
        super().__init__(daemon=True, name=f"grab-{cam}")
        self.base, self.cam, self.on, self.frame = base, cam, threading.Event(), None
        self.lock = threading.Lock()

    def run(self):
        with httpx.Client(timeout=1.0) as c:
            while True:
                if not self.on.wait(0.5):
                    continue
                t0 = time.perf_counter()
                try:
                    r = c.get(f"{self.base}/frame/{self.cam}.jpg")
                    if r.status_code == 200:
                        img = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
                        if img is not None:
                            with self.lock:
                                self.frame = img
                except httpx.HTTPError:
                    pass
                time.sleep(max(0.0, 1 / FPS - (time.perf_counter() - t0)))

    def latest(self):
        with self.lock:
            return self.frame


def label(img, lines):
    for i, txt in enumerate(lines):
        y = 30 + 28 * i
        cv2.putText(img, txt, (14, y), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(img, txt, (14, y), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 1, cv2.LINE_AA)


class Clip:
    def __init__(self, out_root, run):
        driver = (run or {}).get("driver") or "run"
        self.dir = Path(out_root).expanduser() / f"run-{time.strftime('%Y%m%d-%H%M%S')}-{driver}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.driver, self.run, self.timeline, self.writers, self.frames = driver, run, [], {}, 0
        self.t0 = time.time()

    def _writer(self, name, shape):
        if name not in self.writers:
            h, w = shape[:2]
            self.writers[name] = cv2.VideoWriter(str(self.dir / f"{name}.mp4"), cv2.VideoWriter_fourcc(*"avc1"), FPS, (w, h))
        return self.writers[name]

    def write(self, imgs, phase):
        if not all(i is not None for i in imgs.values()):
            return
        for cam, img in imgs.items():
            self._writer(cam, img.shape).write(img)
        h = min(i.shape[0] for i in imgs.values())
        both = np.hstack([cv2.resize(i, (int(i.shape[1] * h / i.shape[0]), h)) for i in imgs.values()])
        label(both, [f"Scrub, {time.strftime('%H:%M:%S')}  {self.driver} (arm driving itself)", f"phase: {phase or '-'}",
                     "real camera frames, side (left) and wrist (right)"])
        self._writer("both", both.shape).write(both)
        self.frames += 1

    def note(self, phase, detail):
        if not self.timeline or self.timeline[-1]["phase"] != phase:
            self.timeline.append({"t": round(time.time() - self.t0, 2), "phase": phase, "detail": detail})

    def close(self, last_run):
        for w in self.writers.values():
            w.release()
        meta = {"driver": self.driver, "started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.t0)),
                "seconds": round(time.time() - self.t0, 1), "frames": self.frames, "fps": FPS,
                "run": last_run or self.run, "timeline": self.timeline,
                "note": "Frames from the station's GET /frame (its page view, JPEG quality 70); a frame repeats when the camera lags."}
        (self.dir / "run.json").write_text(json.dumps(meta, indent=2, default=str))
        print(f"saved {self.dir} ({self.frames} frames, {meta['seconds']} s)", flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--station", default="http://localhost:8090")
    p.add_argument("--out", default="~/scrub-clips")
    p.add_argument("--post", type=float, default=3.0, help="seconds to keep recording after the run ends")
    a = p.parse_args()
    base = a.station.rstrip("/")
    grabs = {c: Grabber(base, c) for c in CAMS}
    for g in grabs.values():
        g.start()
    clip, run, until, up = None, None, 0.0, None
    print(f"watching {base} for runs; clips go to {Path(a.out).expanduser()}", flush=True)
    with httpx.Client(timeout=1.0) as c:
        next_status, tick = 0.0, time.perf_counter()
        while True:
            now = time.time()
            if now >= next_status:
                next_status = now + 0.25
                try:
                    s = c.get(f"{base}/status").json()
                    if up is not True:
                        print("station up", flush=True)
                    up = True
                except (httpx.HTTPError, ValueError):
                    s = None
                    if up is not False:
                        print("station not answering; waiting", flush=True)
                    up = False
                running = bool(s) and s.get("state") == "running"
                run = (s or {}).get("run") or run
                if running and clip is None:
                    for g in grabs.values():
                        g.on.set()
                    clip = Clip(a.out, run)
                    print(f"run started ({clip.driver}): recording to {clip.dir}", flush=True)
                if clip is not None:
                    ds = (run or {}).get("driver_status") or {}
                    clip.note(ds.get("phase") or (s or {}).get("state"), ds.get("detail"))
                    if running:
                        until = now + a.post
            if clip is not None:
                ds = (run or {}).get("driver_status") or {}
                clip.write({cam: g.latest() for cam, g in grabs.items()}, ds.get("phase"))
                if time.time() > until:
                    clip.close(run)
                    clip = None
                    for g in grabs.values():
                        g.on.clear()
                        g.frame = None
            tick += 1 / FPS  # paced to the wall clock so a clip plays at real speed
            time.sleep(max(0.0, tick - time.perf_counter()))
            if time.perf_counter() - tick > 1:
                tick = time.perf_counter()  # fell behind (laptop asleep): don't burst


if __name__ == "__main__":
    main()
