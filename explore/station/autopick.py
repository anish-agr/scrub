"""AutoPick: a station driver that finds the scalpel handle with the side camera and picks it up.

Runs inside the recording station's Run mode (explore/station/station.py, driver interface agreed with
the station owner): the station calls start(st), then tick(st, obs) every loop and sends the returned
action through its normal path, so max_relative_target, the joint and gripper guards, KILL, Home and the
cool-down all still apply. Nothing is recorded to the dataset while a driver runs.

What it learned, and from where (explore/station/autopick_calib.json):
- Camera -> table: a homography from the follower's blue jaw tape in the side camera to the jaw's
  position from the URDF model, fitted on near-table frames of episodes 10-13 (held-out error 0.5-2.8 cm).
- Grasp: the height and joint style of the scalpel-handle demos that really lifted it (episodes 4, 8,
  12, 13). The nearest demo's joints seed the position IK, so the wrist approaches like the operator did.

Sequence: detect (Perceptron /v1/detect "scalpel handle" on the side frame, midpoint refined from the
handle's dark pixels) -> approach 6 cm above the midpoint, jaw open -> descend -> close -> lift 12 cm ->
then, by mode (POST args {"mode": ...}):
  handoff (default): hold it up and wait for a hand (gripper load jump or the jaw being moved), keep holding
    3 s, open, close slowly to check: the jaw shuts -> it was taken -> home, motors off ({"done": "home"});
    something stops the jaw -> still there -> offer again. Nobody in 45 s -> home holding it, torque off.
  hold: pause at the handoff spot, glide home still holding -> {"done": "off"} (torque off, still gripping).
Every segment is a minimum-jerk joint move capped at ~25 deg/s (slower when motors are warm), so motion is
smooth and holding time, the main heat source, stays short.
"""
from __future__ import annotations

import json
import math
import threading
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
JOINTS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]
MAX_DEG_S = 45.0          # PEAK joint speed of each move (minimum-jerk peaks at 1.875x its average)
MJ_PEAK = 1.875
WARM_C, WARM_SLOW = 52, 1.6   # above this, every move takes 1.6x longer
JAW_OPEN, JAW_CLOSE = 35.0, 2.0   # the gripper guard stops the close at the handle and holds gently
HANDOFF_HOLD_S = 3.0      # pause at the handoff spot so someone can see / take it
OFFER_XYZ = (0.20, -0.10, 0.22)  # where it holds the handle up for a hand (m, arm frame: -y = camera right)
OFFER_TIMEOUT_S = 45.0    # nobody took it: go home holding it, motors off (holding still heats the servos)
GRAB_LOAD = 35            # gripper |load| change (or 4x the baseline noise) that means a hand took hold
GRAB_JAW = 1.2            # ... or the jaw moving this much while we hold it still
GRAB_SUSTAIN_S = 0.15
GRAB_JOINT_DEG = 2.0      # ... or a pull pushing any arm joint this far off where it is held
AFTER_GRAB_S = 0.3        # the hand has it: let go almost at once
RELEASE_S = 0.8           # jaw open this long for the hand to take it
OPEN_S = 0.4              # how long the jaw takes to open on release
SQUEEZE = 1.5             # once the jaw stalls on the handle, hold this far past the contact point
EMPTY_JAW = 8.0           # a jaw that stops at or below this closed on nothing (empty reads 4.5-6.5, the handle 9-11)
MIN_MOVE_S = 0.8


def load_calib(path=HERE / "autopick_calib.json") -> dict:
    return json.loads(Path(path).read_text())


def pixel_to_table(H, u: float, v: float) -> np.ndarray:
    p = np.asarray(H, float) @ np.array([u, v, 1.0])
    return p[:2] / p[2]


def _dark_rod(bgr, box):
    """The darkest elongated shape inside a box: (score, u, v, angle, darkness) or None."""
    import cv2
    x1, y1, x2, y2 = [int(round(t)) for t in box]
    x1, y1 = max(0, x1), max(0, y1)
    roi = cv2.cvtColor(bgr[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    if roi.size == 0:
        return None
    thr = min(np.percentile(roi, 25), float(np.median(roi)) - 25)
    mask = cv2.morphologyEx((roi < thr).astype(np.uint8), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    n, lab, st_, cen = cv2.connectedComponentsWithStats(mask, connectivity=8)
    best = None
    cx, cy = roi.shape[1] / 2, roi.shape[0] / 2
    for i in range(1, n):
        if st_[i, cv2.CC_STAT_AREA] < 12:
            continue
        ys, xs = np.nonzero(lab == i)
        pts = np.c_[xs, ys].astype(float)
        w, vec = np.linalg.eigh(np.cov(pts.T))
        if math.sqrt(max(w[1], 1e-6) / max(w[0], 1e-6)) < 2.5:
            continue
        dark = 255.0 - float(roi[ys, xs].mean())
        dist = math.hypot(cen[i][0] - cx, cen[i][1] - cy) / max(cx, cy)
        score = len(xs) * dark * (1.0 - 0.3 * dist)
        if best is None or score > best[0]:
            c, d = pts.mean(0), vec[:, 1]
            best = (score, x1 + c[0], y1 + c[1], float(math.degrees(math.atan2(d[1], d[0]))), dark)
    return best


def handle_midpoint(bgr, box):
    """Midpoint and angle (deg, image) of the handle inside a detection box (the box can cover two rods)."""
    r = _dark_rod(bgr, box)
    if r is None:
        x1, y1, x2, y2 = box
        return (x1 + x2) / 2, (y1 + y2) / 2, None
    return r[1], r[2], r[3]


CANDIDATES = ["scalpel handle", "tweezers", "forceps", "scissors"]
HANDLE_DARK = 150   # the handle is black (darkness ~170+); steel tools read ~100-140


GEMINI_MODELS = ("gemini-3.1-flash-lite", "gemini-3-flash-preview")
GEMINI_PROMPT = ("This is a robot's view of a surgical tray. Find the {label}: a straight, flat, black (dark) metal "
                 "handle with no blade, on the white sheet. Not tweezers/forceps (two arms joined at one end), not "
                 "scissors (finger rings), not the robot. Return JSON {{\"box_2d\": [ymin, xmin, ymax, xmax]}} "
                 "normalized to 0-1000, of the {label} only, or {{\"box_2d\": null}} if there is none.")


# Spend cap: every call's tokens and cost go to SPEND_FILE; at SPEND_CAP_USD Gemini is skipped (Perceptron only).
SPEND_CAP_USD = 20.0
SPEND_FILE = Path.home() / "scrub-logs" / "gemini-spend.jsonl"
PRICE_PER_M = {"gemini-3.1-flash-lite": (0.25, 1.50), "gemini-3-flash-preview": (0.50, 3.00)}  # USD in / out
_spend_lock = threading.Lock()


def gemini_spent() -> float:
    """Total USD recorded in SPEND_FILE (0 if none)."""
    try:
        return sum(json.loads(line).get("usd", 0.0) for line in SPEND_FILE.read_text().splitlines() if line.strip())
    except FileNotFoundError:
        return 0.0


def _record_spend(model: str, usage: dict) -> float:
    pin, pout = PRICE_PER_M.get(model, max(PRICE_PER_M.values()))
    tin = usage.get("promptTokenCount", 0)
    tout = usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0)  # thinking bills as output
    usd = (tin * pin + tout * pout) / 1e6
    with _spend_lock:
        SPEND_FILE.parent.mkdir(parents=True, exist_ok=True)
        with SPEND_FILE.open("a") as f:
            f.write(json.dumps({"t": time.time(), "model": model, "in": tin, "out": tout, "usd": round(usd, 6)}) + "\n")
    return usd


def gemini_box(bgr, label="scalpel handle", timeout=15.0):
    """Box [x1, y1, x2, y2] (pixels) of the label from Gemini, or None. Perceptron's labels flip with the
    lighting (the handle comes back as tweezers/forceps); Gemini with a description of the handle got it
    right on every saved frame (Flash-Lite ~4 s)."""
    import base64
    import cv2
    import requests
    from dotenv import dotenv_values
    key = dotenv_values(ROOT / ".env").get("GEMINI_API_KEY")
    if not key or gemini_spent() >= SPEND_CAP_USD:
        return None
    h, w = bgr.shape[:2]
    body = {"contents": [{"parts": [
        {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(cv2.imencode(".jpg", bgr)[1]).decode()}},
        {"text": GEMINI_PROMPT.format(label=label)}]}], "generationConfig": {"response_mime_type": "application/json"}}
    for model in GEMINI_MODELS:
        try:
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                              headers={"x-goog-api-key": key}, json=body, timeout=timeout)
            r.raise_for_status()
            _record_spend(model, r.json().get("usageMetadata") or {})
            out = json.loads(r.json()["candidates"][0]["content"]["parts"][-1]["text"])
            out = out[0] if isinstance(out, list) and out else out
            b = out.get("box_2d") if isinstance(out, dict) else None
            if not b:
                return None
            y1, x1, y2, x2 = [float(t) for t in b]
            return [x1 * w / 1000, y1 * h / 1000, x2 * w / 1000, y2 * h / 1000]
        except Exception:  # noqa: BLE001 - busy/slow model: try the next, then Perceptron
            continue
    return None


# Local detector (no network): the handle is the dark, long, thin shape on the white sheet inside the reach.
# Measured on 12 saved side frames through the calibrated map: handle 16.8-19.2 cm long, elongation 15-37,
# gray 57-71; tray rim, scissors, steel tools (gray ~100) and the leader all fall outside.
LOCAL_LEN_CM = (11.0, 22.0)  # handle 16.8-19.2 cm through the calibrated map; >= 11 still finds it with an end clipped
LOCAL_MIN_ELONG = 12.0
LOCAL_MAX_RATIO = 0.38  # object brightness / the surface around it: black handle ~0.25-0.3, steel ~0.43+
                        # (relative, so a brighter or dimmer room shifts both alike)


_reach_cache: dict = {}


def reach_mask(H, workspace, shape, margin=0.10):  # wide enough to keep a whole object whose middle is in reach
    """uint8 mask of pixels whose table point (through H) is inside the workspace (+ margin), so the search
    follows the camera wherever it is put; cached per calibration."""
    key = (json.dumps(np.asarray(H, float).round(9).tolist()), json.dumps(workspace), shape[:2])
    if key not in _reach_cache:
        h, w = shape[:2]
        uu, vv = np.meshgrid(np.arange(w, dtype=float), np.arange(h, dtype=float))
        P = np.stack([uu.ravel(), vv.ravel(), np.ones(uu.size)]).T @ np.asarray(H, float).T
        z = P[:, 2]
        ok = np.abs(z) > 1e-9
        x = np.where(ok, P[:, 0] / np.where(ok, z, 1), 1e9)
        y = np.where(ok, P[:, 1] / np.where(ok, z, 1), 1e9)
        inside = ((x >= workspace["x"][0] - margin) & (x <= workspace["x"][1] + margin) &
                  (y >= workspace["y"][0] - margin) & (y <= workspace["y"][1] + margin))
        # the horizon: beyond it the map flips sign; keep only the side the arm's own base maps from
        base = np.asarray(H, float) @ np.array([w / 2, h - 1, 1.0])
        inside &= np.sign(z) == np.sign(base[2])
        _reach_cache.clear()
        _reach_cache[key] = inside.reshape(h, w).astype(np.uint8)
    return _reach_cache[key]


def local_detect(bgr, H, workspace):
    """(u, v, angle, box) of the handle from pixels alone, or None. ~10 ms."""
    import cv2
    H = np.asarray(H, float)

    def tab(u, v):
        p = H @ np.array([u, v, 1.0])
        return p[:2] / p[2]
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    bg = cv2.medianBlur(g, 31)
    m = ((cv2.subtract(bg, g) > 45) & (g < 0.6 * bg)).astype(np.uint8)  # clearly darker than its surroundings
    m &= reach_mask(H, workspace, g.shape)
    raw = m.astype(bool)  # only pixels the calibration puts on the reachable table
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    # a faint handle breaks into pieces along its length: join small gaps (ellipse 7x7 bridges ~6 px; 9x9 merged it with a neighbour)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
    n, lab, st_, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    best = None
    for i in range(1, n):
        if st_[i, cv2.CC_STAT_AREA] < 150:
            continue
        ys, xs = np.nonzero(lab == i)
        pts = np.c_[xs, ys].astype(float)
        c = pts.mean(0)
        xy = tab(*c)
        if not (workspace["x"][0] <= xy[0] <= workspace["x"][1] and workspace["y"][0] <= xy[1] <= workspace["y"][1]):
            continue
        w, vec = np.linalg.eigh(np.cov(pts.T))
        elong = math.sqrt(w[1] / max(w[0], 1e-6))
        d = vec[:, 1]
        proj = (pts - c) @ d
        length = float(np.linalg.norm(tab(*(c + proj.min() * d)) - tab(*(c + proj.max() * d)))) * 100
        dk = raw[ys, xs]  # only the truly dark pixels (joining gaps adds lighter ones)
        if dk.sum() < 30:
            continue
        ratio = float(g[ys[dk], xs[dk]].mean()) / max(1.0, float(bg[ys[dk], xs[dk]].mean()))
        if elong < LOCAL_MIN_ELONG or not LOCAL_LEN_CM[0] <= length <= LOCAL_LEN_CM[1] or ratio > LOCAL_MAX_RATIO:
            continue
        score = elong * len(xs)
        if best is None or score > best[0]:
            box = [float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())]
            mid = c + d * (proj.min() + proj.max()) / 2  # halfway between the two ends, not the pixel average
            best = (score, float(mid[0]), float(mid[1]), float(math.degrees(math.atan2(d[1], d[0]))), box)
    return None if best is None else best[1:]


FRAMES_DIR = Path.home() / "scrub-logs" / "autopick-frames"  # every detection: frame + box, for fine-tuning later
ATTEMPTS_DIR = FRAMES_DIR / "attempts"  # every pick: frames, detection, target, grip, outcome (training data)


def save_example(bgr, box, label, source) -> None:
    try:
        import cv2
        FRAMES_DIR.mkdir(parents=True, exist_ok=True)
        stem = time.strftime("%Y%m%d-%H%M%S")
        cv2.imwrite(str(FRAMES_DIR / f"{stem}.jpg"), bgr)
        with (FRAMES_DIR / "labels.jsonl").open("a") as f:
            f.write(json.dumps({"file": f"{stem}.jpg", "label": label, "box": [round(t) for t in box],
                                "source": source}) + "\n")
    except Exception:  # noqa: BLE001 - never block a pick on logging
        pass


def _centre(b):
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def gemini_vote(bgr, label="scalpel handle", agree_px=20.0, tries=3):
    """Ask Gemini until two answers agree (centres within agree_px); a one-off wrong box (it once boxed
    the scissors) is outvoted. None if no two agree."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(2) as ex:  # the first two at once: ~2 s instead of ~4
        first = [b for b in ex.map(lambda _: gemini_box(bgr, label), range(2)) if b is not None]
    if len(first) == 2 and math.dist(_centre(first[0]), _centre(first[1])) <= agree_px:
        return [(first[0][i] + first[1][i]) / 2 for i in range(4)]
    boxes = list(first)
    for _ in range(tries - 2):
        b = gemini_box(bgr, label)
        if b is None:
            continue
        for o in boxes:
            if math.dist(_centre(o), _centre(b)) <= agree_px:
                return [(o[i] + b[i]) / 2 for i in range(4)]
        boxes.append(b)
    return None


def detect_handle(bgr, detector=None, label="scalpel handle", in_reach=None, use_gemini=True):
    """(u, v, angle, box) of the handle's midpoint in the side frame, or None.
    The detector's labels flip with lighting (the handle comes back as "tweezers", "forceps" or "thin rod"),
    so every instrument box is a candidate and the handle is the one holding the darkest long thin shape.
    A box the detector itself calls the label gets a small bonus; in_reach(u, v) drops out-of-reach ones."""
    if use_gemini and detector is None:
        box = gemini_vote(bgr, label)
        r = _dark_rod(bgr, box) if box is not None else None
        # Gemini once boxed the steel scissors: only trust a box holding a dark rod
        if r is not None and r[4] >= HANDLE_DARK and (in_reach is None or in_reach(r[1], r[2])):
            save_example(bgr, box, label, "gemini")
            return r[1], r[2], r[3], box
    if detector is None:
        from dotenv import dotenv_values
        from vision.tray import PerceptronDetector
        detector = PerceptronDetector(dotenv_values(ROOT / ".env").get("PERCEPTRON_API_KEY"), timeout=15)
    from vision.tray import detection_box
    cats = [label] + [c for c in CANDIDATES if c != label]
    best = None
    for d in detector.detect(bgr, cats):
        if d.get("mention") not in cats:
            continue
        box = detection_box(d)
        r = _dark_rod(bgr, box)
        if r is None or r[4] < HANDLE_DARK:
            continue
        if in_reach is not None and not in_reach(r[1], r[2]):
            continue
        score = r[4] * (1.15 if d.get("mention") == label else 1.0)
        if best is None or score > best[0]:
            best = (score, r[1], r[2], r[3], box)
    return None if best is None else best[1:]


def min_jerk(s: float) -> float:
    s = min(1.0, max(0.0, s))
    return s * s * s * (10 - 15 * s + 6 * s * s)


class AutoPick:
    name = "autopick"

    def __init__(self, args: dict | None = None, calib: dict | None = None, detector=None, kin=None):
        args = dict(args or {})
        self.mode = args.get("mode", "handoff")
        if self.mode not in ("handoff", "hold", "offer", "calibrate", "look"):
            raise ValueError("mode must be 'handoff' (wait for a hand, release, go home) or 'hold' (bring it home)")
        self.detector_kind = args.get("detector", "local")
        if self.detector_kind not in ("local", "gemini"):
            raise ValueError("detector must be 'local' (on this Mac) or 'gemini' (cloud, then Perceptron)")
        offer = args.get("offer_xyz", OFFER_XYZ)
        try:
            self.offer_xyz = [float(v) for v in offer]
            assert len(self.offer_xyz) == 3
        except Exception:  # noqa: BLE001
            raise ValueError("offer_xyz must be [x, y, z] in metres") from None
        label = args.get("label", "scalpel handle")
        if not isinstance(label, str) or not label.strip():
            raise ValueError("label must be a non-empty string")
        self.cal = calib or load_calib()
        self.detector, self.label = detector, label.strip()
        if kin is None:
            import sys
            if str(ROOT) not in sys.path:
                sys.path.insert(0, str(ROOT))
            from arm.kinematics import Kinematics
            kin = Kinematics()
        self.kin = kin
        self._aborted = False
        self._phase, self._detail, self._progress = "idle", "", 0.0
        self.plan: list[dict] = []
        self.seg = 0
        self.seg_t0 = None
        self.start_pose = None
        self.found = None
        self._detect_thread = None
        self.grip_hold = None     # jaw target once the handle stopped the jaw (gentle squeeze)
        self.missed = False
        self.handed = False
        self.hand = None          # handoff state: offer -> grabbed -> release -> check -> home
        self._jaw_hist = []

    # ---- interface
    def start(self, st) -> None:
        self._aborted = False
        self.start_pose = {m: float(st.joints[m]) for m in JOINTS}
        self.start_pose["gripper"] = float(st.gripper if st.gripper is not None else JAW_OPEN)
        if self.mode == "calibrate":
            self.cal_run = Calibrate(self, st)
            self._phase, self._detail = "calibrate", "mapping the camera to the table with the jaw tape"
            return
        if self.mode == "offer":  # test the hand detection: grip in place and wait for a hand
            self.grip_hold = max(0.0, self.start_pose["gripper"] - SQUEEZE)
            self.plan = [{"name": "grip", "from": dict(self.start_pose), "to": {**self.start_pose, "gripper": self.grip_hold},
                          "dur": MIN_MOVE_S, "hold": 0.2, "detail": "gripping in place"}]
            self.mode, self._phase = "handoff", "grip"
            return
        self._phase, self._detail, self._progress = "detect", "looking for the " + self.label, 0.0
        frame = self._frame(st)
        self._detect_thread = threading.Thread(target=self._detect, args=(st, frame), daemon=True, name="autopick-detect")
        self._detect_thread.start()

    def tick(self, st, obs):
        if self._aborted:
            return None
        if self.mode == "calibrate":
            out = self.cal_run.tick(st, time.perf_counter())
            self._phase, self._detail, self._progress = self.cal_run.phase, self.cal_run.detail, self.cal_run.progress
            return out
        if self._phase == "detect":
            return {}  # hold everything while the detector runs on its own thread
        if self._phase == "failed":
            return {"done": "home"}
        if self._phase == "seen":
            return {"done": "home"}
        if not self.plan:
            return None
        now = time.perf_counter()
        if self.hand is not None and self.hand != "done":
            return self._handoff_tick(st, now)
        if self.seg_t0 is None:
            self.seg_t0 = now
        seg = self.plan[self.seg]
        f = min_jerk((now - self.seg_t0) / seg["dur"])
        pose = {k: seg["from"][k] + (seg["to"][k] - seg["from"][k]) * f for k in seg["to"]}
        self._track_jaw(st, now, seg, pose["gripper"])
        if self.grip_hold is not None and seg["to"]["gripper"] <= JAW_CLOSE + 0.01:
            pose["gripper"] = self.grip_hold  # gentle squeeze at the contact point, no guard tug-of-war
        self._phase, self._detail = seg["name"], seg.get("detail", "")
        self._progress = (self.seg + min(1.0, (now - self.seg_t0) / seg["dur"])) / len(self.plan)
        if now - self.seg_t0 >= seg["dur"] + seg.get("hold", 0.0):
            if seg["name"] == "grip":
                self._log(st, event="gripped", jaw=st.gripper, contact=self.grip_hold is not None,
                          joints={m: float(st.joints[m]) for m in JOINTS}, frames=("wrist@grip", "side@grip"))
            if seg["name"] == "grip" and self.grip_hold is None and not self.missed:
                if self.mode == "handoff":
                    # the magnets under the jaw tape hold a thin handle while the jaw reads nearly shut, so a
                    # small reading is not proof of a miss: offer it anyway; the hand at the offer decides
                    self.grip_hold = JAW_CLOSE
                    st.note(f"autopick: jaw reads {st.gripper} (thin grip or empty); offering it anyway")
                else:
                    self._missed(st, pose)  # closed on nothing: don't carry an empty jaw home
            self.seg += 1
            self.seg_t0 = None
            if self.seg >= len(self.plan) and self.mode == "handoff" and not self.missed and self.hand != "done":
                if self.hand is None:
                    self._offer_start(st, now, pose)
                return self._hold_action(pose)
            if self.seg >= len(self.plan) and self.handed:
                self._phase, self._progress = "handed over", 1.0
                st.note("autopick: handed over; home, motors off, ready for the next one")
                return {"done": "home"}
            if self.seg >= len(self.plan):
                self._phase, self._progress = ("missed" if self.missed else "done"), 1.0
                if self.missed:
                    st.note("autopick: missed the handle; home, motors off")
                    return {"done": "home"}
                st.note("autopick: done, holding the item at home; motors off")
                return {"done": "off"}
            nxt = self.plan[self.seg]
            st.note(f"autopick: {nxt['name']} ({nxt['dur']:.1f} s)")
        return self._hold_action(pose)

    def abort(self) -> None:
        self._aborted = True
        self._phase = "aborted"

    def status(self) -> dict:
        out = {"phase": self._phase, "detail": self._detail, "progress": round(self._progress, 2)}
        if self.found:
            out["target"] = self.found
        return out

    # ---- handoff: wait for a hand, release, check the jaw is empty, go home
    @staticmethod
    def _grip_load():
        try:
            import arm_ui
            v = (arm_ui.S.get("motors") or {}).get("gripper", {}).get("load")
            if v is None:
                return None
            v = int(v)
            return float(v - 1024 if 1023 < v < 2048 else abs(v))  # raw sign-magnitude, bit 10 = direction
        except Exception:  # noqa: BLE001
            return None

    def _offer_start(self, st, now, pose) -> None:
        self.hand, self.offer_pose = "offer", dict(pose)
        self.h_t0, self.h_base, self.h_since = now, [], None
        self._phase, self._detail = "offer", "holding it up: take it from the jaw"
        st.note("autopick: offering the handle; take hold of it")

    def _set(self, st, state, now, msg) -> None:
        self.hand, self.h_t0 = state, now
        self._phase, self._detail = state, msg
        st.note("autopick: " + msg)

    def _handoff_tick(self, st, now):
        pose = dict(self.offer_pose)
        el = now - self.h_t0
        jaw, load = (float(st.gripper) if st.gripper is not None else None), self._grip_load()
        if self.hand == "offer":
            pose["gripper"] = self.grip_hold if self.grip_hold is not None else JAW_CLOSE
            if el < 1.0:  # learn the still baseline first
                if jaw is not None:
                    self.h_base.append((jaw, load))
                return self._hold_action(pose)
            jb = float(np.median([b[0] for b in self.h_base])) if self.h_base else jaw
            lb = [b[1] for b in self.h_base if b[1] is not None]
            l0, ln = (float(np.median(lb)), float(np.std(lb))) if lb else (None, 0.0)
            self._detail = (f"take it from the jaw | jaw {jaw} (base {jb:.1f}) load {load} (base {l0}, noise {ln:.0f})"
                            if jb is not None else "take it from the jaw")
            if load is not None and l0 is not None:
                self.h_peak = max(getattr(self, "h_peak", 0.0), abs(load - l0))
            here = {m: float(st.joints[m]) for m in JOINTS}
            if not hasattr(self, "h_jbase") or el < 1.0:
                self.h_jbase = here
            pulled = max(abs(here[m] - self.h_jbase[m]) for m in JOINTS) >= GRAB_JOINT_DEG
            moved = (jaw is not None and jb is not None and abs(jaw - jb) >= GRAB_JAW) or pulled
            tugged = load is not None and l0 is not None and abs(load - l0) >= max(GRAB_LOAD, 4 * ln)
            if moved or tugged:
                self.h_since = self.h_since or now
                if now - self.h_since >= GRAB_SUSTAIN_S:
                    self.found = {**(self.found or {}), "grab": {"jaw": jaw, "jaw_base": jb, "load": load, "load_base": l0,
                                                                "arm_pulled": pulled}}
                    self._log(st, event="hand", **self.found["grab"], frames=("side@hand", "wrist@hand"))
                    self._set(st, "grabbed", now, f"hand detected (jaw {jb:.1f}->{jaw:.1f}, load {l0}->{load}); "
                                                  "letting go")
            else:
                self.h_since = None
            if el > OFFER_TIMEOUT_S:  # nobody came: home holding it, motors off
                self.mode, self.hand = "hold", "done"
                home = {m: float(self.cal["home_deg"][m]) for m in JOINTS}
                to = {**home, "gripper": pose["gripper"]}
                dur = max(MIN_MOVE_S, max(abs(to[m] - pose[m]) for m in JOINTS) * MJ_PEAK / MAX_DEG_S)
                self.plan.append({"name": "home", "from": pose, "to": to, "dur": round(dur, 2), "hold": 0.5,
                                  "detail": "nobody took it: home, still holding"})
                self.seg, self.seg_t0 = len(self.plan) - 1, None
                self._log(st, event="result", result="timeout", jaw=jaw, load_peak=getattr(self, "h_peak", 0.0),
                          frames=("wrist@timeout",))
                st.note(f"autopick: nobody took it in time (biggest load change {getattr(self, 'h_peak', 0):.0f}, "
                        f"load reading {'missing' if load is None else 'ok'}); going home holding it, then motors off")
            return self._hold_action(pose)
        if self.hand == "grabbed":
            pose["gripper"] = self.grip_hold if self.grip_hold is not None else JAW_CLOSE
            if el >= AFTER_GRAB_S:
                self._set(st, "release", now, "letting go")
            return self._hold_action(pose)
        if self.hand == "release":
            g0 = self.grip_hold if self.grip_hold is not None else JAW_CLOSE
            pose["gripper"] = g0 + (JAW_OPEN - g0) * min_jerk(el / OPEN_S)
            if el >= OPEN_S + RELEASE_S:
                self._jaw_hist.clear()
                self._set(st, "check", now, "checking the jaw is empty")
            return self._hold_action(pose)
        if self.hand == "check":
            cmd = JAW_OPEN + (JAW_CLOSE - JAW_OPEN) * min_jerk(el / 0.8)
            pose["gripper"] = cmd
            if jaw is not None and jaw <= EMPTY_JAW + 1.0:  # closed on nothing: it's gone
                home = {m: float(self.cal["home_deg"][m]) for m in JOINTS}
                to = {**home, "gripper": EMPTY_JAW}
                frm = {**self.offer_pose, "gripper": jaw}
                dur = max(MIN_MOVE_S, max(abs(to[m] - frm[m]) for m in JOINTS) * MJ_PEAK / MAX_DEG_S)
                self.plan.append({"name": "home", "from": frm, "to": to, "dur": round(dur, 2), "hold": 0.3,
                                  "detail": "taken: going home"})
                self.seg, self.seg_t0, self.hand, self.handed = len(self.plan) - 1, None, "done", True
                self.found = {**(self.found or {}), "result": "handed over"}
                self._log(st, event="result", result="handed over", jaw=jaw)
                st.note("autopick: it's gone from the jaw; going home to wait")
                return self._hold_action(pose)
            if jaw is not None:
                self._jaw_hist.append((now, jaw))
            recent = [g for t, g in self._jaw_hist if now - t <= 0.4]
            stalled = len(recent) >= 6 and max(recent) - min(recent) < 0.6
            if el > 1.0 and stalled and jaw > EMPTY_JAW + 1.0:  # something stopped the jaw: still there
                self.grip_hold = max(0.0, jaw - SQUEEZE)
                self._offer_start(st, now, {**self.offer_pose, "gripper": self.grip_hold})
            return self._hold_action(pose)
        return self._hold_action(pose)

    def plan_names(self):
        return [p["name"] for p in self.plan]

    def _missed(self, st, pose) -> None:
        """Replace the rest of the plan with: open, lift clear, home."""
        self.missed = True
        self.found = {**(self.found or {}), "result": "missed"}
        self._log(st, event="result", result="missed", jaw=st.gripper)
        cal = self.cal
        cur = dict(pose)
        lift = dict(self.plan[self.seg + 1]["to"]) if self.seg + 1 < len(self.plan) else dict(cur)
        home = {m: float(cal["home_deg"][m]) for m in JOINTS}
        rest = []
        for name, arm, jaw in (("open", cur, JAW_OPEN), ("clear", lift, JAW_OPEN), ("home", home, EMPTY_JAW)):
            to = {**{m: arm[m] for m in JOINTS}, "gripper": jaw}
            span = max(abs(to[m] - cur[m]) for m in JOINTS)
            dur = max(MIN_MOVE_S, span * MJ_PEAK / MAX_DEG_S, abs(jaw - cur["gripper"]) * MJ_PEAK / 60.0)
            rest.append({"name": name, "from": dict(cur), "to": to, "dur": round(dur, 2), "hold": 0.2,
                         "detail": "missed: " + name})
            cur = to
        self.plan = self.plan[: self.seg + 1] + rest
        st.note("autopick: the jaw closed on nothing; opening and going home")

    def _track_jaw(self, st, now, seg, commanded) -> None:
        """During the grip: the jaw is told to close past where it is, yet stops moving above EMPTY_JAW,
        so the handle is in it. From then on hold a gentle squeeze instead of pushing to fully shut."""
        if self.grip_hold is not None or seg["name"] != "grip" or st.gripper is None:
            return
        jaw = float(st.gripper)
        if commanded > jaw - 3.0:  # not yet asking for more than it has: still closing freely
            self._jaw_hist.clear()
            return
        self._jaw_hist.append((now, jaw))
        recent = [g for t, g in self._jaw_hist if now - t <= 0.3]
        if len(recent) >= 5 and max(recent) - min(recent) < 0.6 and min(recent) > EMPTY_JAW:
            self.grip_hold = max(0.0, min(recent) - SQUEEZE)
            self.found = {**(self.found or {}), "jaw_contact": round(min(recent), 1)}
            st.note(f"autopick: handle in the jaw at {min(recent):.1f}; holding a gentle squeeze at {self.grip_hold:.1f}")

    # ---- training data: one folder per pick attempt
    def _log(self, st=None, **kw) -> None:
        try:
            if not hasattr(self, "att_dir"):
                self.att_dir = ATTEMPTS_DIR / time.strftime("%Y%m%d-%H%M%S")
                self.att_dir.mkdir(parents=True, exist_ok=True)
                self.att = {"label": self.label, "mode": self.mode, "detector": self.detector_kind,
                            "calib": self.cal.get("table_H_from"), "events": []}
            self.att["events"].append({"t": round(time.time(), 2), **{k: v for k, v in kw.items() if k != "frames"}})
            for name in kw.get("frames", ()):
                jpg = st.jpeg(name.split("@")[0]) if st is not None and hasattr(st, "jpeg") else None
                if jpg:
                    (self.att_dir / f"{name.replace('@', '-')}.jpg").write_bytes(jpg)
            (self.att_dir / "attempt.json").write_text(json.dumps(self.att, indent=1, default=str))
        except Exception:  # noqa: BLE001 - never block the arm on logging
            pass

    # ---- internals
    @staticmethod
    def _hold_action(pose: dict) -> dict:
        return {f"{k}.pos": float(v) for k, v in pose.items()}

    def _frame(self, st):
        """Latest side-camera frame as BGR."""
        import cv2
        jpg = st.jpeg("side") if hasattr(st, "jpeg") else None
        if jpg:
            return cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
        img = getattr(st, "last_obs", {}).get("side")
        return None if img is None else cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)

    def _detect(self, st, frame) -> None:
        try:
            if frame is None:
                raise RuntimeError("no side-camera frame")
            ws = self.cal["workspace_m"]

            def in_reach(u, v):
                x, y = pixel_to_table(self.cal["table_H"], u, v)
                return ws["x"][0] <= x <= ws["x"][1] and ws["y"][0] <= y <= ws["y"][1]
            if self.detector_kind == "local" and self.detector is None:
                hit = local_detect(frame, self.cal["table_H"], ws)
                if hit is not None:
                    save_example(frame, hit[3], self.label, "local")
            else:
                hit = detect_handle(frame, self.detector, self.label, in_reach)
            if self._aborted:
                return
            if hit is None:
                raise RuntimeError(f"no {self.label} in view within reach (outside the table area the arm can reach?)")
            u, v, ang, box = hit
            xy = pixel_to_table(self.cal["table_H"], u, v)
            ws = self.cal["workspace_m"]
            if not (ws["x"][0] <= xy[0] <= ws["x"][1] and ws["y"][0] <= xy[1] <= ws["y"][1]):
                raise RuntimeError(f"{self.label} at {np.round(xy, 3).tolist()} m is outside the reachable table area")
            self.found = {"pixel": [round(u), round(v)], "angle_deg": ang and round(ang), "xy_m": np.round(xy, 3).tolist(),
                          "box": [round(t) for t in box]}
            if self.mode == "look":  # check detection only: say what and where, never move
                self._phase, self._detail = "seen", (f"{self.label} midpoint at x {xy[0]:.3f} m, y {xy[1]:.3f} m "
                                                     f"(pixel {u:.0f}, {v:.0f}); no pick")
                st.note("autopick look: " + self._detail)
                save_example(frame, box, self.label, "local-look")
                return
            self.plan = self._make_plan(st, xy)
            self._log(st, event="detected", pixel=[u, v], angle_img=ang, box=[float(t) for t in box],
                      xy_m=[float(xy[0]), float(xy[1])], grasp=self.plan[self.plan_names().index("grip")]["to"],
                      frames=("side@detect",))
            st.note(f"autopick: {self.label} box {[round(t) for t in box]} midpoint px ({u:.0f}, {v:.0f}) -> "
                    f"x {xy[0]:.3f} m, y {xy[1]:.3f} m; picking it up")
            self._phase = self.plan[0]["name"]
        except Exception as e:  # noqa: BLE001
            self._phase, self._detail = "failed", str(e)
            st.note(f"autopick: stopped ({e})")

    def _ik(self, xyz, seed):
        q = self.kin.inverse(np.asarray(xyz, float), np.asarray(seed, float), require_region=False)
        if q is None or not self.kin.valid(q):
            raise RuntimeError(f"no reachable joint pose for {np.round(xyz, 3).tolist()}")
        return {m: float(v) for m, v in zip(JOINTS, q)}

    def _make_plan(self, st, xy) -> list[dict]:
        cal = self.cal
        demo = min(cal["demos"], key=lambda d: np.linalg.norm(np.array(d["tip_m"][:2]) - xy))
        seed = demo["grasp_deg"][:5]
        zg = cal["grasp_z_m"]
        grasp = self._ik([xy[0], xy[1], zg], seed)
        approach = self._ik([xy[0], xy[1], zg + cal["approach_dz_m"]], list(grasp.values()))
        lift = self._ik([xy[0], xy[1], zg + cal["lift_dz_m"]], list(grasp.values()))
        home = {m: float(cal["home_deg"][m]) for m in JOINTS}
        temps = st.temps() if callable(getattr(st, "temps", None)) else (getattr(st, "temps", None) or {})
        slow = WARM_SLOW if max([t for t in temps.values() if isinstance(t, (int, float))], default=0) >= WARM_C else 1.0
        steps = [  # name, arm pose, gripper, extra hold
            ("raise", lift, JAW_OPEN, 0.0, "high above the handle, clear of the tray"),
            ("approach", approach, JAW_OPEN, 0.3, "above the handle, jaw open"),
            ("descend", grasp, JAW_OPEN, 0.3, "jaw around the handle"),
            ("grip", grasp, JAW_CLOSE, 0.5, "squeezing the handle"),
            ("lift", lift, JAW_CLOSE, 0.0, "lifting it off the table"),
        ]
        if self.mode == "handoff":
            steps.append(("present", self._ik(self.offer_xyz, list(lift.values())), JAW_CLOSE, 0.3,
                          "up and to the side for a hand"))
        if self.mode == "hold":
            steps += [("handoff", lift, JAW_CLOSE, HANDOFF_HOLD_S, "holding it up for a hand"),
                      ("home", home, JAW_CLOSE, 0.5, "back home, still holding")]
        plan, cur = [], dict(self.start_pose)
        for name, arm, jaw, hold, detail in steps:
            to = {**arm, "gripper": jaw}
            span = max(abs(to[m] - cur[m]) for m in JOINTS)
            dur = max(MIN_MOVE_S, span * MJ_PEAK / MAX_DEG_S, abs(jaw - cur["gripper"]) * MJ_PEAK / 60.0) * slow
            plan.append({"name": name, "from": dict(cur), "to": to, "dur": round(dur, 2), "hold": hold, "detail": detail})
            cur = to
        return plan


# ---- calibrate: the arm maps the side camera to the table by itself (no network, no person)
CAL_XS = (0.15, 0.20, 0.25, 0.30)
CAL_YS = (-0.14, -0.08, -0.02, 0.04, 0.10)
CAL_Z = (0.08, 0.045)      # jaw tip heights (m), extrapolated down to the grasp height. The jaw tape hides magnets:
                           # at 0.0 (2.5 cm over the table) it pulled an instrument up, so stay ~6+ cm above
CAL_SETTLE_S = 0.6


CAL_WIGGLE = 25.0          # jaw opening for the find-myself wiggle


def jaw_by_motion(closed_bgr, open_bgr, closed2_bgr=None, open2_bgr=None):
    """Pixel of the jaw from frames with the jaw closed vs open: whatever changed is the moving jaw finger.
    Works with any tape colour and background. With a second closed/open pair, only pixels that change in
    step with the jaw both times AND look the same in both closed frames count, so a person walking past
    or the arm still settling is ignored. None if too little or too much changed."""
    import cv2
    g = lambda im: cv2.GaussianBlur(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), (5, 5), 0)  # noqa: E731
    a, b = g(closed_bgr), g(open_bgr)
    m = cv2.absdiff(a, b) > 30
    if closed2_bgr is not None and open2_bgr is not None:
        a2, b2 = g(closed2_bgr), g(open2_bgr)
        m &= (cv2.absdiff(a2, b2) > 30) & (cv2.absdiff(a, a2) < 15) & (cv2.absdiff(b, b2) < 20)
    m = m.astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab, st_, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    if n < 2:
        return None
    i = max(range(1, n), key=lambda k: st_[k, cv2.CC_STAT_AREA])
    area = st_[i, cv2.CC_STAT_AREA]
    if not 60 <= area <= 0.05 * m.size:  # nothing moved, or a person/the whole view moved
        return None
    # the jaw tape (black) where the finger was in the closed frame: a fixed spot on the fingertip
    near = cv2.dilate((lab == i).astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool)
    tape = near & (cv2.cvtColor(closed_bgr, cv2.COLOR_BGR2GRAY) < 60)
    if tape.sum() >= 30:
        ty, tx = np.nonzero(tape)
        tip = ty >= np.percentile(ty, 70)  # the bottom of the tape is the fingertip; far out, 3 px is ~2 cm
        return float(tx[tip].mean()), float(ty[tip].mean())
    ys, xs = np.nonzero(lab == i)
    low = ys >= np.percentile(ys, 80)  # no tape found: the fingertip end of the moving region
    return float(xs[low].mean()), float(ys[low].mean())


def blue_tape(bgr):
    """Pixel centroid of the jaw's blue tape (largest blue blob below the background), or None."""
    import cv2
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, (100, 120, 60), (125, 255, 255))
    m[: int(bgr.shape[0] * 0.3)] = 0  # a blue object on the far shelf
    n, _lab, st_, cen = cv2.connectedComponentsWithStats(m, connectivity=8)
    best = max(range(1, n), key=lambda i: st_[i, cv2.CC_STAT_AREA], default=None)
    if best is None or st_[best, cv2.CC_STAT_AREA] < 120:
        return None
    return float(cen[best][0]), float(cen[best][1])


class Calibrate:
    """Visit a grid over the tray at two heights with the jaw closed, find the tape at each stop, fit the
    pixel -> table homography at the grasp height, save it to autopick_calib.json (old one kept), go home."""

    def __init__(self, ap: AutoPick, st):
        self.ap, self.kin, self.cal = ap, ap.kin, ap.cal
        self.samples: list[dict] = []
        self.phase, self.detail, self.progress = "calibrate", "", 0.0
        seed = list(self.cal["demos"][0]["grasp_deg"][:5])
        cur = {m: float(st.joints[m]) for m in JOINTS}
        cur["gripper"] = float(st.gripper if st.gripper is not None else JAW_CLOSE)
        self.stops = []  # (pose, capture?, (x, y, z))
        for i, x in enumerate(CAL_XS):
            for y in (CAL_YS if i % 2 == 0 else CAL_YS[::-1]):
                for z, cap in ((CAL_Z[0], True), (CAL_Z[1], True), (CAL_Z[0], False)):
                    try:
                        q = self.kin.inverse(np.array([x, y, z]), np.array(seed), require_region=False)
                    except Exception:  # noqa: BLE001
                        q = None
                    if q is None or not self.kin.valid(q):
                        continue
                    seed = list(q)
                    self.stops.append(({**{m: float(v) for m, v in zip(JOINTS, q)}, "gripper": JAW_CLOSE}, cap, (x, y, z)))
        home = {m: float(self.cal["home_deg"][m]) for m in JOINTS}
        self.stops.append(({**home, "gripper": JAW_CLOSE}, False, None))
        self.cur, self.i, self.t0, self.done_fit = cur, 0, None, False
        self.stamp = time.strftime("%Y%m%d-%H%M%S")

    def tick(self, st, now):
        if self.i >= len(self.stops):
            if not self.done_fit:
                self.done_fit = True
                self._fit(st)
            return {"done": "home"}
        to, cap, xyz = self.stops[self.i]
        if self.t0 is None:
            self.t0, self.frm = now, dict(self.cur)
            span = max(abs(to[m] - self.frm[m]) for m in JOINTS)
            self.dur = max(0.6, span * MJ_PEAK / MAX_DEG_S)
        el = now - self.t0
        f = min_jerk(el / self.dur)
        pose = {k: self.frm[k] + (to[k] - self.frm[k]) * f for k in to}
        self.progress = self.i / len(self.stops)
        self.phase, self.detail = "calibrate", f"stop {self.i + 1}/{len(self.stops)}, {len(self.samples)} tape sightings"
        if cap and el >= self.dur + CAL_SETTLE_S:
            # find-myself wiggle: frame closed, open the jaw, frame open, close again
            # closed, open, closed, open: frames taken 0.35 s into each 0.7 s half (jaw moved and settled)
            w = el - self.dur - CAL_SETTLE_S
            if not hasattr(self, "_shot"):
                self._shot = {"closed": self.ap._frame(st), "joints": {m: float(st.joints[m]) for m in JOINTS}}
            half, k = 0.7, int(w // 0.7)
            frac = (w - k * half) / 0.35
            opening = k % 2 == 0  # halves 0, 2 open the jaw; 1, 3 close it
            lo, hi = (JAW_CLOSE, CAL_WIGGLE) if opening else (CAL_WIGGLE, JAW_CLOSE)
            jaw = lo + (hi - lo) * min_jerk(frac)
            names = ("open", "closed2", "open2")
            if k < 3 and w - k * half >= 0.6 and names[k] not in self._shot:
                self._shot[names[k]] = self.ap._frame(st)
            if k >= 3:
                jaw = JAW_CLOSE + (CAL_WIGGLE - JAW_CLOSE) * (1 - min_jerk(frac))  # close again
            if w >= 4 * half:
                self._capture(st, xyz, self._shot)
                del self._shot
                self.cur, self.i, self.t0 = dict(to), self.i + 1, None
            pose["gripper"] = jaw
        elif not cap and el >= self.dur:
            self.cur, self.i, self.t0 = dict(to), self.i + 1, None
        return {f"{k}.pos": float(v) for k, v in pose.items()}

    def _capture(self, st, xyz, shot):
        c, o = shot.get("closed"), shot.get("open")
        px = jaw_by_motion(c, o, shot.get("closed2"), shot.get("open2")) if c is not None and o is not None else None
        try:  # keep every wiggle pair: lets the jaw finder be checked and tuned later
            import cv2
            d = FRAMES_DIR / f"calibrate-{self.stamp}"
            d.mkdir(parents=True, exist_ok=True)
            k = len(list(d.glob("*-closed.jpg")))
            cv2.imwrite(str(d / f"{k:02d}-closed.jpg"), c)
            cv2.imwrite(str(d / f"{k:02d}-open.jpg"), o)
            with (d / "stops.jsonl").open("a") as f:
                f.write(json.dumps({"k": k, "grid": list(xyz), "px": px, "joints": shot["joints"]}) + "\n")
        except Exception:  # noqa: BLE001
            pass
        if px is None:
            return
        q = np.array([shot["joints"][m] for m in JOINTS])  # where the arm really was, not where it was told
        tip = np.asarray(self.kin.forward(q), float)
        self.samples.append({"grid": list(xyz), "px": list(px), "tip": tip.round(4).tolist()})

    def _fit(self, st):
        import cv2
        zg = self.cal["grasp_z_m"]
        by = {}
        for smp in self.samples:
            by.setdefault(tuple(smp["grid"][:2]), []).append(smp)
        pix, xy = [], []
        for pair in by.values():
            if len(pair) < 2:
                continue
            a, b = sorted(pair, key=lambda s_: s_["tip"][2])[:2]  # low, high
            dz = b["tip"][2] - a["tip"][2]
            if abs(dz) < 0.01:
                continue
            k = (zg - a["tip"][2]) / dz  # straight-line extrapolation of the tape pixel and tip down to the grasp height
            pix.append([a["px"][i] + (b["px"][i] - a["px"][i]) * k for i in range(2)])
            xy.append([a["tip"][i] + (b["tip"][i] - a["tip"][i]) * k for i in range(2)])
        out = {"t": time.time(), "samples": self.samples, "pairs": len(pix)}
        if len(pix) < 6:
            self.phase, self.detail = "calibrate failed", f"only {len(pix)} usable grid points (need 6): is the tape in view?"
            st.note("autopick calibrate: " + self.detail)
        else:
            Hm, inl = cv2.findHomography(np.array(pix), np.array(xy), cv2.RANSAC, 0.01)
            P = np.c_[np.array(pix), np.ones(len(pix))] @ Hm.T
            err = np.linalg.norm(P[:, :2] / P[:, 2:] - np.array(xy), axis=1)
            good = inl.ravel().astype(bool)
            out.update({"H": Hm.tolist(), "err_cm_median": float(np.median(err[good]) * 100),
                        "err_cm_max": float(err[good].max() * 100), "inliers": int(good.sum())})
            cal = load_calib()
            cal["table_H_prev"] = cal.get("table_H")
            cal["table_H"] = Hm.tolist()
            cal["table_H_from"] = (f"autopick calibrate {time.strftime('%Y-%m-%d %H:%M')}: {int(good.sum())}/{len(pix)} grid "
                                   f"points, median {out['err_cm_median']:.1f} cm, max {out['err_cm_max']:.1f} cm")
            cal["workspace_m"] = {"x": [min(CAL_XS) - 0.02, max(CAL_XS) + 0.02], "y": [min(CAL_YS) - 0.02, max(CAL_YS) + 0.02]}
            (HERE / "autopick_calib.json").write_text(json.dumps(cal, indent=1) + "\n")
            self.ap.cal.update(cal)
            self.phase, self.detail = "calibrated", cal["table_H_from"]
            st.note("autopick calibrate: " + self.detail)
        try:
            FRAMES_DIR.mkdir(parents=True, exist_ok=True)
            (FRAMES_DIR / f"calibrate-{time.strftime('%Y%m%d-%H%M%S')}.json").write_text(json.dumps(out))
        except Exception:  # noqa: BLE001
            pass
