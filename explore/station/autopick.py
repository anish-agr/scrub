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
hold at the handoff spot -> glide home still holding -> {"done": "off"} (torque off in place, still gripping).
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
MAX_DEG_S = 30.0          # PEAK joint speed of each move (minimum-jerk peaks at 1.875x its average)
MJ_PEAK = 1.875
WARM_C, WARM_SLOW = 52, 1.6   # above this, every move takes 1.6x longer
JAW_OPEN, JAW_CLOSE = 35.0, 2.0   # the gripper guard stops the close at the handle and holds gently
HANDOFF_HOLD_S = 3.0      # pause at the handoff spot so someone can see / take it
MIN_MOVE_S = 0.8


def load_calib(path=HERE / "autopick_calib.json") -> dict:
    return json.loads(Path(path).read_text())


def pixel_to_table(H, u: float, v: float) -> np.ndarray:
    p = np.asarray(H, float) @ np.array([u, v, 1.0])
    return p[:2] / p[2]


def handle_midpoint(bgr, box):
    """Midpoint and angle (deg, image) of the handle inside a detection box. The box can cover two
    neighbouring rods, so the dark pixels are split into connected shapes and the handle is the
    biggest elongated one (weighted by darkness, nearer the box centre wins ties)."""
    import cv2
    x1, y1, x2, y2 = [int(round(t)) for t in box]
    x1, y1 = max(0, x1), max(0, y1)
    roi = cv2.cvtColor(bgr[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    if roi.size == 0:
        return (x1 + x2) / 2, (y1 + y2) / 2, None
    thr = min(np.percentile(roi, 25), float(roi.mean()) - 25)
    mask = (roi < thr).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    n, lab, st_, cen = cv2.connectedComponentsWithStats(mask, connectivity=8)
    best, best_score = None, -1.0
    cx, cy = roi.shape[1] / 2, roi.shape[0] / 2
    for i in range(1, n):
        area = st_[i, cv2.CC_STAT_AREA]
        if area < 12:
            continue
        ys, xs = np.nonzero(lab == i)
        pts = np.c_[xs, ys].astype(float)
        w, _ = np.linalg.eigh(np.cov(pts.T)) if len(pts) > 2 else (np.array([1, 1]), None)
        elong = math.sqrt(max(w[1], 1e-6) / max(w[0], 1e-6))
        if elong < 2.5:
            continue
        dark = 255.0 - float(roi[ys, xs].mean())
        dist = math.hypot(cen[i][0] - cx, cen[i][1] - cy) / max(cx, cy)
        score = area * dark * (1.0 - 0.3 * dist)
        if score > best_score:
            best, best_score = pts, score
    if best is None:
        return (x1 + x2) / 2, (y1 + y2) / 2, None
    c = best.mean(0)
    _w, vec = np.linalg.eigh(np.cov(best.T))
    d = vec[:, 1]
    return x1 + c[0], y1 + c[1], float(math.degrees(math.atan2(d[1], d[0])))


def detect_handle(bgr, detector=None, label="scalpel handle"):
    """(u, v, angle, box) of the handle's midpoint in the side frame, or None."""
    if detector is None:
        from dotenv import dotenv_values
        from vision.tray import PerceptronDetector
        detector = PerceptronDetector(dotenv_values(ROOT / ".env").get("PERCEPTRON_API_KEY"), timeout=15)
    from vision.tray import detection_box
    hits = [d for d in detector.detect(bgr, [label, "tweezers", "scissors", "robot arm"]) if d.get("mention") == label]
    if not hits:
        return None
    box = detection_box(hits[0])
    u, v, ang = handle_midpoint(bgr, box)
    return u, v, ang, box


def min_jerk(s: float) -> float:
    s = min(1.0, max(0.0, s))
    return s * s * s * (10 - 15 * s + 6 * s * s)


class AutoPick:
    name = "autopick"

    def __init__(self, args: dict | None = None, calib: dict | None = None, detector=None, kin=None):
        args = dict(args or {})
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

    # ---- interface
    def start(self, st) -> None:
        self._aborted = False
        self.start_pose = {m: float(st.joints[m]) for m in JOINTS}
        self.start_pose["gripper"] = float(st.gripper if st.gripper is not None else JAW_OPEN)
        self._phase, self._detail, self._progress = "detect", "looking for the " + self.label, 0.0
        frame = self._frame(st)
        self._detect_thread = threading.Thread(target=self._detect, args=(st, frame), daemon=True, name="autopick-detect")
        self._detect_thread.start()

    def tick(self, st, obs):
        if self._aborted:
            return None
        if self._phase == "detect":
            return {}  # hold everything while the detector runs on its own thread
        if self._phase == "failed":
            return {"done": "home"}
        if not self.plan:
            return None
        now = time.perf_counter()
        if self.seg_t0 is None:
            self.seg_t0 = now
        seg = self.plan[self.seg]
        f = min_jerk((now - self.seg_t0) / seg["dur"])
        pose = {k: seg["from"][k] + (seg["to"][k] - seg["from"][k]) * f for k in seg["to"]}
        self._phase, self._detail = seg["name"], seg.get("detail", "")
        self._progress = (self.seg + min(1.0, (now - self.seg_t0) / seg["dur"])) / len(self.plan)
        if now - self.seg_t0 >= seg["dur"] + seg.get("hold", 0.0):
            self.seg += 1
            self.seg_t0 = None
            if self.seg >= len(self.plan):
                self._phase, self._progress = "done", 1.0
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
            hit = detect_handle(frame, self.detector, self.label)
            if self._aborted:
                return
            if hit is None:
                raise RuntimeError(f"no {self.label} in view")
            u, v, ang, box = hit
            xy = pixel_to_table(self.cal["table_H"], u, v)
            ws = self.cal["workspace_m"]
            if not (ws["x"][0] <= xy[0] <= ws["x"][1] and ws["y"][0] <= xy[1] <= ws["y"][1]):
                raise RuntimeError(f"{self.label} at {np.round(xy, 3).tolist()} m is outside the reachable table area")
            self.found = {"pixel": [round(u), round(v)], "angle_deg": ang and round(ang), "xy_m": np.round(xy, 3).tolist(),
                          "box": [round(t) for t in box]}
            self.plan = self._make_plan(st, xy)
            st.note(f"autopick: {self.label} midpoint at x {xy[0]:.3f} m, y {xy[1]:.3f} m; picking it up")
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
            ("handoff", lift, JAW_CLOSE, HANDOFF_HOLD_S, "holding it up for a hand"),
            ("home", home, JAW_CLOSE, 0.5, "back home, still holding"),
        ]
        plan, cur = [], dict(self.start_pose)
        for name, arm, jaw, hold, detail in steps:
            to = {**arm, "gripper": jaw}
            span = max(abs(to[m] - cur[m]) for m in JOINTS)
            dur = max(MIN_MOVE_S, span * MJ_PEAK / MAX_DEG_S, abs(jaw - cur["gripper"]) * MJ_PEAK / 60.0) * slow
            plan.append({"name": name, "from": dict(cur), "to": to, "dur": round(dur, 2), "hold": hold, "detail": detail})
            cur = to
        return plan
