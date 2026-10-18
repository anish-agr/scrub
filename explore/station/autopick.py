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

try:
    from . import instances
except ImportError:  # station loads its drivers by filename
    import instances

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


def gemini_box(bgr, label="scalpel handle", timeout=15.0, all_boxes=False):
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
    prompt = GEMINI_PROMPT.format(label=label)
    if all_boxes:
        prompt += (' Find ALL matching handles, each separately. Return {"boxes_2d": '
                   '[[ymin, xmin, ymax, xmax], ...]}, or {"boxes_2d": []} if none.')
    body = {"contents": [{"parts": [
        {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(cv2.imencode(".jpg", bgr)[1]).decode()}},
        {"text": prompt}]}], "generationConfig": {"response_mime_type": "application/json"}}
    for model in GEMINI_MODELS:
        try:
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                              headers={"x-goog-api-key": key}, json=body, timeout=timeout)
            r.raise_for_status()
            _record_spend(model, r.json().get("usageMetadata") or {})
            out = json.loads(r.json()["candidates"][0]["content"]["parts"][-1]["text"])
            out = out[0] if isinstance(out, list) and out else out
            if all_boxes and isinstance(out, dict):
                boxes = out.get("boxes_2d", [out["box_2d"]] if out.get("box_2d") else [])
                return [[float(b[1]) * w / 1000, float(b[0]) * h / 1000,
                         float(b[3]) * w / 1000, float(b[2]) * h / 1000] for b in boxes]
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


# ---- wrist camera: line the handle up between the jaw tips before going down
WRIST_GAP_X, WRIST_GAP_Y = 330.0, 300.0   # jaw-gap centre in the 640x480 wrist image (camera rides on the gripper)
ALIGN_NUDGE_M = 0.012                     # test nudge that measures px per metre at this height, in this room
ALIGN_MAX_M = 0.03


def wrist_line(bgr):
    """(x where the instrument line crosses the jaw-gap row, angle deg from vertical, length px) of the crisp
    straight edge nearest the jaw gap, or None. Edges, not darkness: in the wrist view the handle's steel end
    shines; soft hand shadows give no crisp edges."""
    import cv2
    h, w = bgr.shape[:2]
    sx, sy = w / 640.0, h / 480.0
    g = cv2.GaussianBlur(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    e = cv2.Canny(g, 60, 160)
    e[int(WRIST_GAP_Y * sy):] = 0          # the jaws themselves
    e[:, : int(130 * sx)] = 0              # the tray rim at the left edge
    e[:, int(560 * sx):] = 0
    lines = cv2.HoughLinesP(e, 1, np.pi / 180, 40, minLineLength=int(60 * sy), maxLineGap=10)
    if lines is None:
        return None
    cand = []
    for x1, y1, x2, y2 in np.asarray(lines).reshape(-1, 4):
        x1, x2, y1, y2 = x1 / sx, x2 / sx, y1 / sy, y2 / sy
        if abs(y2 - y1) < 1e-3:
            continue  # horizontal: can't cross the gap row
        ang = math.degrees(math.atan2(x2 - x1, y2 - y1))
        ang = (ang + 90) % 180 - 90  # -90..90, 0 = straight up the image
        if abs(ang) > 60:
            continue
        cand.append((x1 + (x2 - x1) * (WRIST_GAP_Y - y1) / (y2 - y1), ang, math.hypot(x2 - x1, y2 - y1)))
    best = None
    for xg, ang, length in cand:
        # an instrument has two parallel edges: use the line halfway between them when the partner is there
        mates = [c for c in cand if abs(c[1] - ang) < 8 and 6 <= abs(c[0] - xg) <= 70]
        mid = (xg + max(mates, key=lambda c: c[2])[0]) / 2 if mates else xg
        score = length + (40 if mates else 0) - 0.8 * abs(mid - WRIST_GAP_X)
        if best is None or score > best[0]:
            best = (score, float(mid), float(ang), float(length))
    return None if best is None else best[1:]


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


def local_detect(bgr, H, workspace, all_candidates=False):
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
    best, hits = None, []
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
        box = [float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())]
        mid = c + d * (proj.min() + proj.max()) / 2  # preserve the measured whole-object midpoint
        hit = (float(mid[0]), float(mid[1]), float(math.degrees(math.atan2(d[1], d[0]))), box)
        hits.append(hit)
        if best is None or score > best[0]:
            best = (score, *hit)
    if all_candidates:
        return hits  # separate local components are separate handles, even if they are close together
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


def gemini_vote(bgr, label="scalpel handle", agree_px=20.0, tries=3, all_boxes=False):
    """Ask Gemini until two answers agree (centres within agree_px); a one-off wrong box (it once boxed
    the scissors) is outvoted. None if no two agree."""
    from concurrent.futures import ThreadPoolExecutor
    if all_boxes:
        # Same two-of-up-to-three voting rule and spend cap, independently for every physical handle.
        with ThreadPoolExecutor(2) as ex:
            votes = list(ex.map(lambda _: gemini_box(bgr, label, all_boxes=True) or [], range(2)))

        def agreed():
            hits = []
            for i, first in enumerate(votes):
                for second in votes[i + 1:]:
                    remaining = list(second)
                    for a in first:
                        if not remaining:
                            break
                        b = min(remaining, key=lambda b: math.dist(_centre(a), _centre(b)))
                        if math.dist(_centre(a), _centre(b)) <= agree_px:
                            remaining.remove(b)
                            box = [(a[k] + b[k]) / 2 for k in range(4)]
                            hits.append((*_centre(box), None, box))
            return [h[3] for h in instances.unique_hits(hits)]

        boxes = agreed()
        if boxes and len(boxes) == len(votes[0]) == len(votes[1]):
            return boxes
        for _ in range(tries - 2):
            votes.append(gemini_box(bgr, label, all_boxes=True) or [])
        return agreed()
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


def detect_handle(bgr, detector=None, label="scalpel handle", in_reach=None, use_gemini=True, all_candidates=False):
    """(u, v, angle, box) of the handle's midpoint in the side frame, or None.
    The detector's labels flip with lighting (the handle comes back as "tweezers", "forceps" or "thin rod"),
    so every instrument box is a candidate and the handle is the one holding the darkest long thin shape.
    A box the detector itself calls the label gets a small bonus; in_reach(u, v) drops out-of-reach ones."""
    if use_gemini and detector is None:
        boxes = gemini_vote(bgr, label, all_boxes=True) if all_candidates else [gemini_vote(bgr, label)]
        hits = []
        for box in boxes:
            r = _dark_rod(bgr, box) if box is not None else None
            # Gemini once boxed the steel scissors: only trust a box holding a dark rod
            if r is not None and r[4] >= HANDLE_DARK and (in_reach is None or in_reach(r[1], r[2])):
                save_example(bgr, box, label, "gemini")
                hits.append((r[1], r[2], r[3], box))
        if hits:
            return instances.unique_hits(hits) if all_candidates else hits[0]
    if detector is None:
        from dotenv import dotenv_values
        from vision.tray import PerceptronDetector
        detector = PerceptronDetector(dotenv_values(ROOT / ".env").get("PERCEPTRON_API_KEY"), timeout=15)
    from vision.tray import detection_box
    cats = [label] + [c for c in CANDIDATES if c != label]
    best, hits = None, []
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
        hits.append((r[1], r[2], r[3], box))
        if best is None or score > best[0]:
            best = (score, r[1], r[2], r[3], box)
    if all_candidates:
        return instances.unique_hits(hits)
    return None if best is None else best[1:]


EPISODES_DIR = Path.home() / "scrub-logs" / "episodes"  # local copy of every saved demo (to_mongo.upload_episode)
ALL_JOINTS = JOINTS + ["gripper"]


def demo_keyposes(state, fps=30):
    """Key poses of one demo from its joint trajectory (degrees, 6 columns incl gripper): approach (above the
    item, jaw open), grasp (the moment the jaw closes on it), lift (highest point after the grasp, by shoulder
    lift), handoff (where the jaw opens again, the release). None if no clear grasp."""
    a = np.asarray(state, float)
    if a.ndim != 2 or a.shape[1] < 6 or len(a) < fps:
        return None
    g = a[:, 5]
    i_open = int(np.argmax(g[: max(2, int(len(g) * 0.8))]))
    after = g[i_open:]
    g_open, g_min = float(g[i_open]), float(after.min())
    if g_open - g_min < 8:  # the jaw never really closed
        return None
    thr = g_open - 0.7 * (g_open - g_min)
    i_grasp = i_open + int(np.argmax(after < thr))  # the arm's pose as the jaw closes (lifting starts right after)
    i_closed = min(len(a) - 1, i_grasp + int(0.3 * fps))  # the jaw's own value once it has finished closing
    i_app = max(0, i_grasp - int(1.2 * fps))
    seg = a[i_grasp: i_grasp + int(4 * fps)]
    i_lift = i_grasp + int(np.argmin(seg[:, 1])) if len(seg) else i_grasp  # shoulder_lift most negative = highest
    rel = np.nonzero(g[i_closed:] > g[i_closed] + 0.6 * (g_open - g[i_closed]))[0]
    i_hand = i_closed + int(rel[0]) - int(0.3 * fps) if len(rel) else None
    pose = lambda i: {m: float(a[i, k]) for k, m in enumerate(ALL_JOINTS)}  # noqa: E731
    out = {"approach": pose(i_app), "grasp": pose(i_grasp), "lift": pose(i_lift), "grip_closed": float(a[i_closed, 5]),
           "open": g_open, "frames": {"approach": i_app, "grasp": i_grasp, "lift": i_lift, "handoff": i_hand}}
    if i_hand is not None and i_hand > i_lift:
        out["handoff"] = pose(i_hand)
    return out


def learn_demos(task, min_episode=0, folder=None):
    """Median key poses over the saved demos of a task. {} if none usable."""
    rows = []
    for f in sorted(Path(folder or EPISODES_DIR).glob("ep-*.json")):
        if "-start" in f.name:
            continue
        try:
            d = json.loads(f.read_text())
        except Exception:  # noqa: BLE001
            continue
        if d.get("task") != task or int(d.get("episode_index", -1)) < min_episode:
            continue
        k = demo_keyposes(d["state"], int(d.get("fps") or 30))
        if k:
            rows.append((d["episode_index"], k))
    if not rows:
        return {}
    out = {"episodes": [r[0] for r in rows]}
    for key in ("approach", "grasp", "lift", "handoff"):
        got = [r[1][key] for r in rows if key in r[1]]
        if got:
            out[key] = {m: float(np.median([p[m] for p in got])) for m in ALL_JOINTS}
    out["grip_closed"] = float(np.median([r[1]["grip_closed"] for r in rows]))
    out["open"] = float(np.median([r[1]["open"] for r in rows]))
    return out


def min_jerk(s: float) -> float:
    s = min(1.0, max(0.0, s))
    return s * s * s * (10 - 15 * s + 6 * s * s)


class AutoPick:
    name = "autopick"

    def __init__(self, args: dict | None = None, calib: dict | None = None, detector=None, kin=None):
        args = dict(args or {})
        self.mode = args.get("mode", "handoff")
        self.task = args.get("task", "pick the scalpel")
        self.min_episode = int(args.get("min_episode", 18))  # demos from the current setup (camera moved after 17)
        if self.mode not in ("handoff", "hold", "offer", "calibrate", "look", "learned"):
            raise ValueError("mode must be 'handoff' (wait for a hand, release, go home) or 'hold' (bring it home)")
        self.align = bool(args.get("align", True))  # wrist-camera line-up before going down
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
        self.instance = instances.parse_instance(args.get("instance"))
        self._choice_lock = threading.Lock()
        self._choice_event = threading.Event()
        self._question = None
        self._answer = None
        self._choice_rows = []
        self._choice_st = None
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
        self.xy_target = None
        self.al = None

    # ---- interface
    def start(self, st) -> None:
        self._aborted = False
        self._choice_st = st
        self.start_pose = {m: float(st.joints[m]) for m in JOINTS}
        self.start_pose["gripper"] = float(st.gripper if st.gripper is not None else JAW_OPEN)
        if self.mode == "learned":  # replay what the demos taught: smooth, then offer and let go on command
            demo = learn_demos(self.task, self.min_episode)
            if "grasp" not in demo:
                self._phase, self._detail = "failed", f"no usable demos for {self.task!r} (episode >= {self.min_episode})"
                st.note("autopick: " + self._detail)
                return
            self.found = {"demos": demo["episodes"]}
            self.plan = self._learned_plan(st, demo)
            self.mode = "handoff"  # after the plan: offer, wait for "let go" or a hand, release, home
            self._phase = self.plan[0]["name"]
            st.note(f"autopick: learned from demos {demo['episodes']}; picking it up")
            return
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
        if self._phase in ("detect", "clarify", "clarify_timeout", "clarify_failed"):
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
        if seg["name"] == "align":
            out = self._align_tick(st, now, seg)
            if out is not None:
                return out
            seg = self.plan[self.seg]  # alignment finished and re-planned from here
            self.seg_t0 = now
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
        with self._choice_lock:
            question = self._question
            answer_ms = round((time.perf_counter() - self._choice_t0) * 1000) if question else None
            self._aborted = True
            self._phase = "aborted"
            self._question = None
            self._choice_event.set()  # wake the worker without waiting for the 15 s timeout
        if question:
            self._choice_log(self._choice_st, "clarify_answer", question_id=question["id"], item=self.label,
                             answer="timeout", status="cancelled", reason="cancelled", answer_ms=answer_ms)

    def status(self) -> dict:
        out = {"phase": self._phase, "detail": self._detail, "progress": round(self._progress, 2)}
        if self.found:
            out["target"] = self.found
        with self._choice_lock:
            out["question"] = dict(self._question) if self._question else None
        return out

    @staticmethod
    def _choice_log(st, kind, **fields):
        try:
            if callable(getattr(st, "event", None)):
                st.event(kind, driver="autopick", **fields)
        except Exception:  # logging must never unlock motion or block an abort with a held lock
            pass

    def answer(self, st, question_id, side):
        """Called only through the station's queued control; stale/double/late answers cannot move it."""
        with self._choice_lock:
            q = self._question
            if self._aborted or q is None or question_id != q["id"]:
                return False, "which one: question is no longer active"
            if time.perf_counter() >= self._choice_deadline:
                return False, "which one: question timed out"
            if side not in ("left", "right", "closest"):
                return False, "which one: answer left, right or closest"
            self._answer = instances.select(self._choice_rows, {"side": side})
            self._question = None
            self._phase = "detect"  # still hold while the worker builds the plan
            slot = self._answer["slot"]
            answer_ms = round((time.perf_counter() - self._choice_t0) * 1000)
            self._choice_event.set()
        self._choice_log(st, "clarify_answer", question_id=q["id"], item=self.label, side=side,
                         answer=side, status="answered", reason=None, slot=slot, answer_ms=answer_ms)
        return True, f"autopick: your {side} one"

    def _which_one(self, st, rows):
        import uuid
        plural = self.label if self.label.endswith("s") else self.label + "s"
        question = {"id": uuid.uuid4().hex, "item": self.label, "count": len(rows),
                    "say": f"I see two {plural}: the left one or the right one?",
                    "orientation": instances.ORIENTATION, "timeout_s": instances.CLARIFY_TIMEOUT_S,
                    "choices": ["left", "right"]}
        if len(rows) > 2:
            question["say"] = (f"I see {len(rows)} {self.label} candidates: your leftmost, your rightmost, "
                               "or the one closest to you? Press C for closest.")
        self._choice_log(st, "clarify", question_id=question["id"], item=self.label, say=question["say"],
                         candidates=[{k: v for k, v in r.items() if k != "hit"} for r in rows],
                         orientation=instances.ORIENTATION, timeout_s=instances.CLARIFY_TIMEOUT_S)
        with self._choice_lock:
            if self._aborted:
                return None
            self._choice_event.clear()
            self._choice_st = st
            self._answer, self._choice_rows = None, rows
            self._choice_t0 = time.perf_counter()
            self._choice_deadline = self._choice_t0 + instances.CLARIFY_TIMEOUT_S
            self._question = question
            self._phase, self._detail = "clarify", question["say"]
        st.note("autopick: " + question["say"])
        self._choice_event.wait(instances.CLARIFY_TIMEOUT_S)
        with self._choice_lock:
            question = self._question
            self._question = None
            if self._aborted:
                return None
            if self._answer is None:
                self._phase, self._detail = "clarify_timeout", "I'll wait for you to ask again."
            answer_ms = round((time.perf_counter() - self._choice_t0) * 1000)
            answer = self._answer
        if answer is None:
            if question:
                self._choice_log(st, "clarify_answer", question_id=question["id"], item=self.label,
                                 answer="timeout", status="timeout", reason="timeout", answer_ms=answer_ms,
                                 say="I'll wait for you to ask again.")
            st.note("autopick: " + self._detail)
        return answer

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
            if getattr(self, "_release_req", False):
                self._release_req = False
                self._log(st, event="hand", source="let go command", frames=("side@hand", "wrist@hand"))
                self._set(st, "release", now, "let go (command)")
                return self._hold_action(pose)
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

    def _wrist(self, st):
        import cv2
        jpg = st.jpeg("wrist") if hasattr(st, "jpeg") else None
        return None if not jpg else cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)

    def _align_tick(self, st, now, seg):
        """Hold above the handle, measure the wrist-camera line, test-nudge sideways to learn px/m, correct, then
        re-plan descend/grip/lift/present from the corrected spot. Returns an action while busy, None when done."""
        a = self.al
        base = seg["to"]
        if a is None:
            a = self.al = {"state": "settle", "t0": now}
            self._phase, self._detail = "align", "lining up with the wrist camera"
        el = now - a["t0"]
        if a["state"] == "settle":
            if el < 0.5:
                return self._hold_action(base)
            a["m0"] = wrist_line(self._wrist(st)) if self._wrist(st) is not None else None
            if a["m0"] is None:
                return self._align_done(st, 0.0, "no clear line in the wrist camera; picking without it")
            try:
                xy = self.xy_target
                nud = self._ik([xy[0], xy[1] + ALIGN_NUDGE_M, self.cal["grasp_z_m"] + self.cal["approach_dz_m"]],
                               [base[m] for m in JOINTS])
            except RuntimeError:
                return self._align_done(st, 0.0, "test nudge out of reach; picking without it")
            a.update(state="nudge", t0=now, nud={**nud, "gripper": base["gripper"]})
            return self._hold_action(base)
        if a["state"] == "nudge":
            f = min_jerk(el / 0.6)
            pose = {k: base[k] + (a["nud"][k] - base[k]) * f for k in base}
            if el < 1.0:
                return self._hold_action(pose)
            img = self._wrist(st)
            m1 = wrist_line(img) if img is not None else None
            if m1 is None:
                return self._align_done(st, 0.0, "lost the line after the test nudge; picking without it", pose)
            gain = (m1[0] - a["m0"][0]) / ALIGN_NUDGE_M  # wrist px per metre of +y, here and now
            if abs(gain) < 300:
                return self._align_done(st, 0.0, f"test nudge barely moved the line ({gain:.0f} px/m); picking without it", pose)
            dy = max(-ALIGN_MAX_M, min(ALIGN_MAX_M, -(a["m0"][0] - WRIST_GAP_X) / gain))
            return self._align_done(st, dy, f"line {a['m0'][0] - WRIST_GAP_X:+.0f} px off the jaw gap, "
                                            f"{gain:.0f} px/m: moving {dy * 100:+.1f} cm sideways", pose)
        return None

    def _align_done(self, st, dy, msg, pose=None):
        """Re-plan everything after the align step from the corrected target (dy metres along y)."""
        st.note("autopick align: " + msg)
        self._log(st, event="align", dy_m=dy, msg=msg, m0=(self.al or {}).get("m0"), frames=("wrist@align",))
        xy = [self.xy_target[0], self.xy_target[1] + dy]
        self.xy_target = xy
        cur = pose or self.plan[self.seg]["to"]
        rest = self._make_plan(st, np.array(xy), start=cur, skip=("raise", "align"))
        self.plan = self.plan[: self.seg + 1] + rest
        self.seg += 1
        return None

    def _learned_plan(self, st, demo) -> list[dict]:
        temps = st.temps() if callable(getattr(st, "temps", None)) else (getattr(st, "temps", None) or {})
        slow = WARM_SLOW if max([t for t in temps.values() if isinstance(t, (int, float))], default=0) >= WARM_C else 1.0
        jaw_open = max(demo.get("open", JAW_OPEN), 20.0)
        g, a = demo["grasp"], demo["approach"]
        lift = demo.get("lift", a)
        steps = [("approach", {**a, "gripper": jaw_open}, 0.3, "above it, jaw open (as in the demos)"),
                 ("descend", {**g, "gripper": jaw_open}, 0.3, "jaw around it"),
                 ("grip", {**g, "gripper": JAW_CLOSE}, 0.5, "squeezing"),
                 ("lift", {**lift, "gripper": JAW_CLOSE}, 0.0, "lifting it")]
        if "handoff" in demo:
            steps.append(("present", {**demo["handoff"], "gripper": JAW_CLOSE}, 0.3, "to the hand-off spot (from the demos)"))
        plan, cur = [], dict(self.start_pose)
        for name, to, hold, detail in steps:
            span = max(abs(to[m] - cur[m]) for m in JOINTS)
            dur = max(MIN_MOVE_S, span * MJ_PEAK / MAX_DEG_S, abs(to["gripper"] - cur["gripper"]) * MJ_PEAK / 60.0) * slow
            plan.append({"name": name, "from": dict(cur), "to": to, "dur": round(dur, 2), "hold": hold, "detail": detail})
            cur = to
        return plan

    def release(self) -> None:
        """'let go' (voice or the page): open at the offer right away."""
        self._release_req = True

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
            if self.detector is None:
                hits = local_detect(frame, self.cal["table_H"], ws, all_candidates=True)
                for hit in hits:
                    save_example(frame, hit[3], self.label, "local")
                # Even when cloud fallback is requested, valid local candidates cost no network call.
                if not hits and self.detector_kind == "gemini":
                    hits = detect_handle(frame, self.detector, self.label, in_reach, all_candidates=True)
            else:
                hits = detect_handle(frame, self.detector, self.label, in_reach, all_candidates=True)
            if self._aborted:
                return
            if not hits:
                raise RuntimeError(f"no {self.label} in view within reach (outside the table area the arm can reach?)")
            rows = instances.candidates(hits)
            try:
                selected = instances.select(rows, self.instance)
            except ValueError as e:
                with self._choice_lock:
                    if self._aborted:
                        return
                    self._phase, self._detail = "clarify_failed", str(e) + "; holding still. Stop to end the run."
                st.note("autopick: " + self._detail)
                return
            if selected is None:
                pool = [r for r in rows if "variant" not in self.instance or r["variant"] == self.instance["variant"]]
                selected = self._which_one(st, pool)
            if selected is None or self._aborted:
                return
            u, v, ang, box = selected["hit"][:4]
            xy = pixel_to_table(self.cal["table_H"], u, v)
            ws = self.cal["workspace_m"]
            if not (ws["x"][0] <= xy[0] <= ws["x"][1] and ws["y"][0] <= xy[1] <= ws["y"][1]):
                raise RuntimeError(f"{self.label} at {np.round(xy, 3).tolist()} m is outside the reachable table area")
            with self._choice_lock:
                if self._aborted:
                    return
                self.found = {"pixel": [round(u), round(v)], "angle_deg": ang and round(ang),
                              "xy_m": np.round(xy, 3).tolist(), "box": [round(t) for t in box],
                              "slot": selected["slot"], "instance": self.instance}
            if self.mode == "look":  # check detection only: say what and where, never move
                self._phase, self._detail = "seen", (f"{self.label} midpoint at x {xy[0]:.3f} m, y {xy[1]:.3f} m "
                                                     f"(pixel {u:.0f}, {v:.0f}); no pick")
                st.note("autopick look: " + self._detail)
                save_example(frame, box, self.label, "local-look")
                return
            plan = self._make_plan(st, xy)
            with self._choice_lock:
                if self._aborted:
                    return
                self.xy_target = [float(xy[0]), float(xy[1])]
                self.plan = plan
                self._phase = plan[0]["name"]
            self._log(st, event="detected", pixel=[u, v], angle_img=ang, box=[float(t) for t in box],
                      xy_m=[float(xy[0]), float(xy[1])], grasp=next((p["to"] for p in plan if p["name"] == "grip"), None),
                      frames=("side@detect",))
            st.note(f"autopick: {self.label} box {[round(t) for t in box]} midpoint px ({u:.0f}, {v:.0f}) -> "
                    f"x {xy[0]:.3f} m, y {xy[1]:.3f} m; picking it up")
        except Exception as e:  # noqa: BLE001
            with self._choice_lock:
                if self._aborted:
                    return
                self._question = None
                self._phase, self._detail = "failed", str(e)
            st.note(f"autopick: stopped ({e})")

    def _ik(self, xyz, seed):
        q = self.kin.inverse(np.asarray(xyz, float), np.asarray(seed, float), require_region=False)
        if q is None or not self.kin.valid(q):
            raise RuntimeError(f"no reachable joint pose for {np.round(xyz, 3).tolist()}")
        return {m: float(v) for m, v in zip(JOINTS, q)}

    def _make_plan(self, st, xy, start=None, skip=()) -> list[dict]:
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
            *([("align", approach, JAW_OPEN, 0.0, "lining up with the wrist camera")] if self.align else []),
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
        plan, cur = [], dict(start if start is not None else self.start_pose)
        for name, arm, jaw, hold, detail in steps:
            if name in skip:
                continue
            to = {**arm, "gripper": jaw}
            span = max(abs(to[m] - cur[m]) for m in JOINTS)
            dur = max(MIN_MOVE_S, span * MJ_PEAK / MAX_DEG_S, abs(jaw - cur["gripper"]) * MJ_PEAK / 60.0) * slow
            plan.append({"name": name, "from": dict(cur), "to": to, "dur": round(dur, 2), "hold": hold, "detail": detail})
            cur = to
        return plan


# ---- calibrate: the arm maps the side camera to the table by itself (no network, no person)
CAL_XS = (0.22, 0.31, 0.40)        # 3 x 4 grid over where the instruments lie (the arm reaches past 0.44):
CAL_YS = (-0.12, -0.04, 0.04, 0.12)  # ~1.5 min and ~45% of the old 4 x 5 grid's jaw work
CAL_Z = (0.08, 0.045)      # jaw tip heights (m), extrapolated down to the grasp height. The jaw tape hides magnets:
                           # at 0.0 (2.5 cm over the table) it pulled an instrument up, so stay ~6+ cm above
CAL_SETTLE_S = 0.6


def tape_pair(high_bgr, low_bgr):
    """Best candidate of tape_pairs, or None."""
    c = tape_pairs(high_bgr, low_bgr)
    return c[0] if c else None


def tape_pairs(high_bgr, low_bgr, keep=6):
    """Jaw tip pixels (high, low) from two still frames of the same spot, jaw lowered between them; no claw
    movement needed. The black fingertip tape is a dark spot that appears in the low frame where the high
    frame was bright, and one that disappears from the high frame. A straight-down move puts the low spot
    in the same column and further down, which a person walking past doesn't do. None if not found."""
    import cv2
    gh = cv2.GaussianBlur(cv2.cvtColor(high_bgr, cv2.COLOR_BGR2GRAY), (3, 3), 0).astype(np.int16)
    gl = cv2.GaussianBlur(cv2.cvtColor(low_bgr, cv2.COLOR_BGR2GRAY), (3, 3), 0).astype(np.int16)

    def blobs(dark, other):
        m = ((dark < 70) & (other - dark > 40)).astype(np.uint8)
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        n, lab, st_, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
        out = []
        for i in range(1, n):
            if 25 <= st_[i, cv2.CC_STAT_AREA] <= 0.01 * m.size:
                ys, xs = np.nonzero(lab == i)
                tip = ys >= np.percentile(ys, 70)  # bottom of the tape = the fingertip
                out.append((float(xs[tip].mean()), float(ys[tip].mean()), len(xs)))
        return out
    cand = []
    for uh, vh, ah in blobs(gh, gl):
        for ul, vl, al in blobs(gl, gh):
            dv, du = vl - vh, abs(ul - uh)
            if not (4 <= dv <= 120 and du <= 0.6 * dv + 12 and 0.33 <= al / ah <= 3):
                continue
            # the arm's black servos move straight down too: keep several; the fit picks the consistent one
            cand.append((4 * vl + 0.05 * (ah + al) - 2 * du, (uh, vh), (ul, vl)))
    cand.sort(key=lambda c: -c[0])
    return [c[1:] for c in cand[:keep]]


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


def fit_spots(spots, zg, tol=0.02, iters=3000, seed=0):
    """Pixel -> table map at the grasp height from calibration spots, each with several tape candidates
    (the arm's black servos look like tape too). RANSAC over spots *and* candidates: the map that the most
    spots agree with (each through its best candidate) wins. None if fewer than 4 spots."""
    import cv2
    rows = []
    for sp in spots:
        th, tl = np.array(sp["tip_high"]), np.array(sp["tip_low"])
        if abs(th[2] - tl[2]) < 0.01 or not sp["cands"]:
            continue
        k = (zg - tl[2]) / (th[2] - tl[2])  # straight-line extrapolation down to the grasp height
        xy = tl[:2] + (th[:2] - tl[:2]) * k
        px = [np.array(pl) + (np.array(ph) - np.array(pl)) * k for ph, pl in sp["cands"]]
        rows.append((xy, px))
    if len(rows) < 4:
        return None

    def apply(H, p):
        q = H @ np.array([p[0], p[1], 1.0])
        return q[:2] / q[2]
    rng = np.random.default_rng(seed)
    best = []
    for _ in range(iters):
        pick = rng.choice(len(rows), 4, replace=False)
        src = np.array([rows[i][1][rng.integers(len(rows[i][1]))] for i in pick], float)
        H, _ = cv2.findHomography(src, np.array([rows[i][0] for i in pick], float), 0)
        if H is None:
            continue
        chosen = []
        for xy, cands in rows:
            e = [np.linalg.norm(apply(H, c) - xy) for c in cands]
            j = int(np.argmin(e))
            if e[j] < tol:
                chosen.append((cands[j], xy))
        if len(chosen) > len(best):
            best = chosen
    if len(best) < 4:
        return {"agree": len(best)}
    src, dst = np.array([c[0] for c in best]), np.array([c[1] for c in best])
    H, _ = cv2.findHomography(src, dst, 0)
    err = np.array([np.linalg.norm(apply(H, s_) - d_) for s_, d_ in zip(src, dst)])
    return {"H": H.tolist(), "agree": len(best), "err_cm_median": float(np.median(err) * 100),
            "err_cm_max": float(err.max() * 100)}


class Calibrate:
    """Visit a grid over the tray at two heights with the jaw closed, find the tape at each stop, fit the
    pixel -> table homography at the grasp height, save it to autopick_calib.json (old one kept), go home."""

    def __init__(self, ap: AutoPick, st):
        self.ap, self.kin, self.cal = ap, ap.kin, ap.cal
        self.samples: list[dict] = []
        self.spots: list[dict] = []
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
        if cap and el >= self.dur and not self._settled(st, now, el):
            pass  # the station's gentle speed limit makes real moves slower than planned: wait for the arm to stop
        elif cap and el >= self.dur:
            self._capture(st, xyz, {"frame": self.ap._frame(st), "joints": {m: float(st.joints[m]) for m in JOINTS}})
            self.cur, self.i, self.t0 = dict(to), self.i + 1, None
        elif not cap and el >= self.dur:
            self.cur, self.i, self.t0 = dict(to), self.i + 1, None
        return {f"{k}.pos": float(v) for k, v in pose.items()}

    def _settled(self, st, now, el) -> bool:
        """True once the joints have stopped moving (< 0.4 deg over 0.4 s), or after 3 s more."""
        here = np.array([float(st.joints[m]) for m in JOINTS])
        hist = self.__dict__.setdefault("_settle_hist", [])
        hist.append((now, here))
        while hist and now - hist[0][0] > 0.4:
            hist.pop(0)
        still = len(hist) >= 6 and float(np.abs(hist[-1][1] - hist[0][1]).max()) < 0.4 and now - hist[0][0] >= 0.3
        if still or el >= self.dur + 3.0:
            hist.clear()
            self.dur = el  # the wiggle timeline starts from now
            return True
        return False

    def _capture(self, st, xyz, shot):
        """Keep the still frame; once a grid spot has its high and low frames, find the tape in both."""
        key = (xyz[0], xyz[1])
        got = self.__dict__.setdefault("_pending", {}).setdefault(key, [])
        got.append({"z": xyz[2], **shot})
        if len(got) < 2 or any(g["frame"] is None for g in got):
            return
        hi, lo = sorted(got, key=lambda g: -g["z"])[:2]
        cands = tape_pairs(hi["frame"], lo["frame"])
        pair = cands[0] if cands else None
        try:  # keep every pair: lets the jaw finder be checked and tuned later
            import cv2
            d = FRAMES_DIR / f"calibrate-{self.stamp}"
            d.mkdir(parents=True, exist_ok=True)
            k = len(list(d.glob("*-high.jpg")))
            cv2.imwrite(str(d / f"{k:02d}-high.jpg"), hi["frame"])
            cv2.imwrite(str(d / f"{k:02d}-low.jpg"), lo["frame"])
            with (d / "stops.jsonl").open("a") as f:
                f.write(json.dumps({"k": k, "grid": list(key), "pair": pair, "joints_high": hi["joints"],
                                    "joints_low": lo["joints"]}) + "\n")
        except Exception:  # noqa: BLE001
            pass
        if not cands:
            return
        th, tl = (np.asarray(self.kin.forward(np.array([g["joints"][m] for m in JOINTS])), float) for g in (hi, lo))
        self.spots.append({"grid": list(key), "tip_high": th.round(4).tolist(), "tip_low": tl.round(4).tolist(),
                           "cands": [[list(ph), list(pl)] for ph, pl in cands]})

    def _fit(self, st):
        res = fit_spots(self.spots, self.cal["grasp_z_m"])
        out = {"t": time.time(), "spots": self.spots, **({k: v for k, v in res.items() if k != "H"} if res else {})}
        if res is None or res["agree"] < 6:
            n = 0 if res is None else res["agree"]
            self.phase, self.detail = "calibrate failed", (f"only {n} of {len(self.spots)} grid spots agree (need 6): "
                                                           "is the jaw in view at every spot? old map kept")
            st.note("autopick calibrate: " + self.detail)
        else:
            out["H"] = res["H"]
            cal = load_calib()
            cal["table_H_prev"] = cal.get("table_H")
            cal["table_H"] = res["H"]
            cal["table_H_from"] = (f"autopick calibrate {time.strftime('%Y-%m-%d %H:%M')}: {res['agree']}/{len(self.spots)} "
                                   f"grid spots agree, median {res['err_cm_median']:.1f} cm, max {res['err_cm_max']:.1f} cm")
            cal["workspace_m"] = {"x": [min(CAL_XS) - 0.03, max(CAL_XS) + 0.06], "y": [min(CAL_YS) - 0.04, max(CAL_YS) + 0.04]}
            (HERE / "autopick_calib.json").write_text(json.dumps(cal, indent=1) + "\n")
            self.ap.cal.update(cal)
            self.phase, self.detail = "calibrated", cal["table_H_from"]
            st.note("autopick calibrate: " + self.detail)
        try:
            FRAMES_DIR.mkdir(parents=True, exist_ok=True)
            (FRAMES_DIR / f"calibrate-{time.strftime('%Y%m%d-%H%M%S')}.json").write_text(json.dumps(out))
        except Exception:  # noqa: BLE001
            pass
