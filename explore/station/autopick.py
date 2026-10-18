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
MAX_DEG_S = 30.0          # PEAK joint speed of each move (minimum-jerk peaks at 1.875x its average)
MJ_PEAK = 1.875
WARM_C, WARM_SLOW = 52, 1.6   # above this, every move takes 1.6x longer
JAW_OPEN, JAW_CLOSE = 35.0, 2.0   # the gripper guard stops the close at the handle and holds gently
HANDOFF_HOLD_S = 3.0      # pause at the handoff spot so someone can see / take it
OFFER_XYZ = (0.20, 0.10, 0.22)  # where it holds the handle up for a hand (m, arm frame: +y = camera left)
OFFER_TIMEOUT_S = 45.0    # nobody took it: go home holding it, motors off (holding still heats the servos)
GRAB_LOAD = 35            # gripper |load| change (or 4x the baseline noise) that means a hand took hold
GRAB_JAW = 1.2            # ... or the jaw moving this much while we hold it still
GRAB_SUSTAIN_S = 0.15
AFTER_GRAB_S = 3.0        # keep holding this long after the grab, then let go
RELEASE_S = 1.5           # jaw open this long for the hand to take it
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


def gemini_box(bgr, label="scalpel handle", timeout=15.0):
    """Box [x1, y1, x2, y2] (pixels) of the label from Gemini, or None. Perceptron's labels flip with the
    lighting (the handle comes back as tweezers/forceps); Gemini with a description of the handle got it
    right on every saved frame (Flash-Lite ~4 s)."""
    import base64
    import cv2
    import requests
    from dotenv import dotenv_values
    key = dotenv_values(ROOT / ".env").get("GEMINI_API_KEY")
    if not key:
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


def detect_handle(bgr, detector=None, label="scalpel handle", in_reach=None, use_gemini=True):
    """(u, v, angle, box) of the handle's midpoint in the side frame, or None.
    The detector's labels flip with lighting (the handle comes back as "tweezers", "forceps" or "thin rod"),
    so every instrument box is a candidate and the handle is the one holding the darkest long thin shape.
    A box the detector itself calls the label gets a small bonus; in_reach(u, v) drops out-of-reach ones."""
    if use_gemini and detector is None:
        box = gemini_box(bgr, label)
        r = _dark_rod(bgr, box) if box is not None else None
        # Gemini once boxed the steel scissors: only trust a box holding a dark rod
        if r is not None and r[4] >= HANDLE_DARK and (in_reach is None or in_reach(r[1], r[2])):
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
        if self.mode not in ("handoff", "hold", "offer"):
            raise ValueError("mode must be 'handoff' (wait for a hand, release, go home) or 'hold' (bring it home)")
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
        if self._phase == "detect":
            return {}  # hold everything while the detector runs on its own thread
        if self._phase == "failed":
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
            if seg["name"] == "grip" and self.grip_hold is None and not self.missed:
                self._missed(st, pose)  # closed on nothing: don't carry an empty jaw to the handoff
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
            moved = jaw is not None and jb is not None and abs(jaw - jb) >= GRAB_JAW
            tugged = load is not None and l0 is not None and abs(load - l0) >= max(GRAB_LOAD, 4 * ln)
            if moved or tugged:
                self.h_since = self.h_since or now
                if now - self.h_since >= GRAB_SUSTAIN_S:
                    self.found = {**(self.found or {}), "grab": {"jaw": jaw, "jaw_base": jb, "load": load, "load_base": l0}}
                    self._set(st, "grabbed", now, f"hand detected (jaw {jb:.1f}->{jaw:.1f}, load {l0}->{load}); "
                                                  f"letting go in {AFTER_GRAB_S:.0f} s")
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
            pose["gripper"] = g0 + (JAW_OPEN - g0) * min_jerk(el / 0.8)
            if el >= 0.8 + RELEASE_S:
                self._jaw_hist.clear()
                self._set(st, "check", now, "checking the jaw is empty")
            return self._hold_action(pose)
        if self.hand == "check":
            cmd = JAW_OPEN + (JAW_CLOSE - JAW_OPEN) * min_jerk(el / 1.2)
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
                st.note("autopick: it's gone from the jaw; going home to wait")
                return self._hold_action(pose)
            if jaw is not None:
                self._jaw_hist.append((now, jaw))
            recent = [g for t, g in self._jaw_hist if now - t <= 0.4]
            stalled = len(recent) >= 6 and max(recent) - min(recent) < 0.6
            if el > 1.4 and stalled and jaw > EMPTY_JAW + 1.0:  # something stopped the jaw: still there
                self.grip_hold = max(0.0, jaw - SQUEEZE)
                self._offer_start(st, now, {**self.offer_pose, "gripper": self.grip_hold})
            return self._hold_action(pose)
        return self._hold_action(pose)

    def _missed(self, st, pose) -> None:
        """Replace the rest of the plan with: open, lift clear, home."""
        self.missed = True
        self.found = {**(self.found or {}), "result": "missed"}
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
            self.plan = self._make_plan(st, xy)
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
