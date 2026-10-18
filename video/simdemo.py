"""Scripted sim demo for the video: smooth, labeled SIMULATION, same scene as simcine.

Unlike `simcine render`, nothing is replayed from the live sim (its items snap between spots). The arm
moves through IK keyframes with eased timing, the jaw closes on each instrument, and a held instrument
rides with the gripper. Sequence: hemostat into the gloved hand and home; Mayo scissors into the hand
and home; scalpel carry with a stop mid-move, then continue and home; simulated return of the hemostat
(electromagnet pickup from the table back to its slot). The arm slows on the last approach to the hand.

  python -m video.simdemo still --t 6 --out data/video/simdemo/still.png
  python -m video.simdemo sheet --out data/video/simdemo/sheet.png      # one frame per second
  python -m video.simdemo render --out data/video/out/sim-demo.mp4
  python -m video.simdemo segments                                       # segment start / home times
"""
import argparse
import math
import re
from pathlib import Path

import numpy as np

from video.simcine import _cap, _box, _font, cinematic_xml

OPEN, CLOSED, HOLD = 0.55, -0.17, -0.15  # jaw qpos: open, tips touching, closed on a thin instrument
ROLL = 0.0  # wrist roll for every keyframe: moving jaw on top, jaws open toward/away from the base like the real arm
SLOTS = {"hemostat": (0.24, -0.08), "scalpel": (0.24, 0.0), "mayo_scissors": (0.24, 0.08)}
TABLE_Z, TRAY_Z = 0.0, 0.004            # item resting heights (table top, paper liner)
RETURN = (0.19, -0.29)                  # where the hand sets the used hemostat down: table, beside the tray
HANDOFF = np.array([0.25, -0.25, 0.17])  # where the clinician's hand takes it
HOME = np.zeros(6)
READY = np.array([0.0, -0.45, 0.5, 1.13, ROLL, 0.0])  # elbow up, tip down over the tray
GRIP = np.array([0.0, -0.038, 0.0])     # where the glove holds an instrument (ring end), item frame

# a gloved hand and gown sleeve; origin at the grip point, the forearm runs back along -y
GLOVE = (_box((0, -0.012, 0), (0.016, 0.02, 0.009), "glove")
         + "".join(_cap((x, 0.006, 0.006), (x * 1.1, 0.03, -0.004), 0.0062, "glove") for x in (-0.012, -0.004, 0.004, 0.012))
         + _cap((0.016, -0.012, -0.004), (0.02, 0.01, -0.012), 0.0068, "glove")
         + _cap((0, -0.03, -0.002), (0, -0.06, -0.012), 0.017, "glove")
         + _cap((0, -0.07, -0.016), (0, -0.80, -0.20), 0.032, "gown"))


def load_model():
    import mujoco

    from video.simcine import SCENES  # the scene include path
    src = cinematic_xml()
    src = re.sub(r'(<body name="hand_zone"[^>]*>).*?(</body>)', lambda mm: mm.group(1) + GLOVE + mm.group(2),
                 src, count=1, flags=re.S)
    path = SCENES / "_simdemo.xml"
    path.write_text(src, encoding="utf-8")
    try:
        model = mujoco.MjModel.from_xml_path(str(path))
    finally:
        path.unlink(missing_ok=True)
    for i in range(model.nmat):  # same arm colors as simcine
        r, g_, b, a = model.mat_rgba[i]
        if r > 0.9 and g_ > 0.7 and b < 0.3:
            model.mat_rgba[i] = (0.93, 0.92, 0.89, 1.0)
            model.mat_specular[i], model.mat_shininess[i] = 0.25, 0.3
        elif r < 0.2 and g_ < 0.2 and b < 0.2:
            model.mat_rgba[i] = (0.13, 0.13, 0.12, 1.0)
    return model


# ---- IK -------------------------------------------------------------------------------------------
def ik(m, d, site, pos, approach, q0, w_rot=0.25, iters=300):
    """Position plus tool direction (site x axis) with the first four joints; wrist roll stays at ROLL."""
    import mujoco

    a = np.asarray(approach, float); a /= np.linalg.norm(a)
    q = q0.copy(); q[4] = ROLL
    jp, jr = np.zeros((3, m.nv)), np.zeros((3, m.nv))
    for _ in range(iters):
        d.qpos[:] = q
        mujoco.mj_forward(m, d)
        ep = pos - d.site_xpos[site]
        er = np.cross(d.site_xmat[site].reshape(3, 3)[:, 0], a)
        if np.linalg.norm(ep) < 5e-4 and np.linalg.norm(er) < 2e-3:
            break
        mujoco.mj_jacSite(m, d, jp, jr, site)
        J = np.vstack([jp[:, :4], w_rot * jr[:, :4]])
        e = np.concatenate([ep, w_rot * er])
        dq = J.T @ np.linalg.solve(J @ J.T + 1e-4 * np.eye(6), e)
        q[:4] = np.clip(q[:4] + 0.5 * dq, m.jnt_range[:4, 0], m.jnt_range[:4, 1])
    return q, float(np.linalg.norm(ep))


# ---- the script -----------------------------------------------------------------------------------
def _ease(u, mode="mj"):
    u = min(1.0, max(0.0, u))
    if mode == "in":     # start from rest, arrive still moving
        return u * u * (2 - u)
    if mode == "out":    # arrive moving, settle slowly (the slow last approach to the hand)
        return 1 - (1 - u) ** 3
    if mode == "stop":   # moving, then brake hard
        return 1 - (1 - u) ** 2
    return u * u * u * (10 - 15 * u + 6 * u * u)  # min-jerk


def build(m, d):
    """Keyframes (t, qpos, mode) and events. Returns (keys, events, length)."""
    site = m.site("gripperframe").id
    down = (0, 0, -1)
    keys, events = [(0.0, HOME.copy(), "mj")], []
    t, q = 0.0, HOME.copy()

    def solve(pos, approach=down):
        pos = np.asarray(pos, float)
        ang = math.atan2(pos[1], pos[0])
        if approach is down:  # tip slightly outward, like the real arm reaching over the tray
            approach = (0.4 * math.cos(ang), 0.4 * math.sin(ang), -1)
        best = None
        ready = READY.copy(); ready[0] = ang
        for w in (0.25, 0.1, 0.03):
            for q0 in (q, ready):
                qq, err = ik(m, d, site, pos, approach, q0, w_rot=w)
                score = err + 0.02 * np.abs(qq[:4] - q[:4]).sum()  # stay close to the last pose: no flips
                if err < 0.003 and (best is None or score < best[0]):
                    best = (score, qq)
            if best:
                break
        assert best, f"unreachable {pos}"
        out = best[1].copy()
        out[5] = q[5]  # the jaw only changes when asked
        return out

    def key(qn, dur, mode="mj"):
        nonlocal t, q
        q = qn.copy()
        t += dur
        keys.append((t, q.copy(), mode))

    def to(pos, approach=down, dur=1.4, jaw=None, mode="mj"):
        qn = solve(pos, approach)
        if jaw is not None:
            qn[5] = jaw
        key(qn, dur, mode)

    def jaw(v, dur=0.5):
        qn = q.copy(); qn[5] = v
        key(qn, dur)

    def hold(dur):
        key(q, dur)

    def ev(kind, **kw):
        events.append(dict(t=t, kind=kind, **kw))

    def pick(item, x, y, z, grip=HOLD):
        to((x, y, z + 0.09), dur=1.6, jaw=OPEN if grip == HOLD else CLOSED)
        to((x, y, z + 0.012), dur=1.0)
        if grip == HOLD:
            jaw(HOLD, 0.45)
        else:
            hold(0.3)
        ev("grab", item=item)
        hold(0.25)
        to((x, y, z + 0.11), dur=0.9)

    def outward(p, down_=0.25):
        ang = math.atan2(p[1], p[0])
        return (math.cos(ang), math.sin(ang), -down_)

    def approach_hand(first=1.4):
        """Carry toward the hand, then slow down over the last few centimeters."""
        a = np.array(outward(HANDOFF)); a /= np.linalg.norm(a)
        to(HANDOFF - 0.07 * a, approach=outward(HANDOFF), dur=first, mode="in")
        to(HANDOFF, approach=outward(HANDOFF), dur=1.3, mode="out")

    def give(item, say_ready):
        ev("say", text=say_ready)
        ev("reach", item=item)          # the hand comes in to take it
        hold(1.1)
        jaw(OPEN, 0.4)
        ev("taken", item=item)
        hold(0.5)

    def home(dur=1.8):
        qn = HOME.copy(); qn[5] = 0.0
        key(qn, dur)
        ev("home")
        hold(0.6)

    def segment(name):
        ev("segment", name=name)

    # 1. hemostat into the hand, home
    segment("hemostat")
    ev("say", text="Hemostat coming.")
    x, y = SLOTS["hemostat"]; pick("hemostat", x, y, TRAY_Z)
    approach_hand()
    give("hemostat", "Here's the hemostat.")
    home()

    # 2. Mayo scissors into the hand, home
    segment("scissors")
    ev("say", text="Mayo scissors coming.")
    x, y = SLOTS["mayo_scissors"]; pick("mayo_scissors", x, y, TRAY_Z)
    approach_hand(first=1.7)
    give("mayo_scissors", "Here are the Mayo scissors.")
    home()

    # 3. scalpel: stop mid-move, then continue to the hand, home
    segment("stop")
    ev("say", text="Scalpel coming.")
    x, y = SLOTS["scalpel"]; pick("scalpel", x, y, TRAY_Z)
    a = np.array(outward(HANDOFF)); a /= np.linalg.norm(a)
    q_from, q_to = q.copy(), solve(HANDOFF - 0.07 * a, outward(HANDOFF))
    ev("say", text="Stop.")
    key(q_from + 0.38 * (q_to - q_from), 0.7, "in")
    key(q_from + 0.46 * (q_to - q_from), 0.35, "stop")
    ev("say", text="STOPPED")
    hold(2.2)
    ev("say", text="Continue.")
    to(HANDOFF - 0.07 * a, approach=outward(HANDOFF), dur=1.0, mode="in")
    to(HANDOFF, approach=outward(HANDOFF), dur=1.3, mode="out")
    give("scalpel", "Here's the scalpel.")
    home()

    # 4. simulated return: the hand sets the hemostat on the table, the arm picks it up and puts it back
    segment("return")
    ev("tag", on=True)
    ev("say", text="Returning the hemostat.")
    ev("handback", item="hemostat", at=(RETURN[0], RETURN[1], TABLE_Z), dur=3.6)
    hold(3.6)
    pick("hemostat", RETURN[0], RETURN[1], TABLE_Z, grip=CLOSED)
    x, y = SLOTS["hemostat"]
    to((x, y, 0.1), dur=1.7)
    to((x, y, TRAY_Z + 0.012), dur=0.9)
    hold(0.3)
    ev("place", item="hemostat")
    ev("say", text="Hemostat back in its slot.")
    to((x, y, 0.11), dur=0.8)
    home()
    ev("tag", on=False)
    hold(0.6)
    return keys, events, t


FOREARM = np.array([0.25, -1.0, 0.0]) / math.hypot(0.25, 1.0)  # the clinician stands on the arm's right
_PSI = math.atan2(FOREARM[0], -FOREARM[1])
GLOVE_R = np.array([[math.cos(_PSI), -math.sin(_PSI), 0], [math.sin(_PSI), math.cos(_PSI), 0], [0, 0, 1]])
AWAY = 1.35 * FOREARM + np.array([0, 0, 0.06])  # out of shot, past the table's edge


BLEND, OUT_T = 0.9, 1.3  # s: settling into a resting pose; the hand drawing away


def _blend_rot(Ra, Rb, u):
    """Rotation part way from Ra to Rb (quaternion nlerp)."""
    import mujoco

    qa, qb = np.zeros(4), np.zeros(4)
    mujoco.mju_mat2Quat(qa, np.ascontiguousarray(Ra).ravel())
    mujoco.mju_mat2Quat(qb, np.ascontiguousarray(Rb).ravel())
    if qa @ qb < 0:
        qb = -qb
    q = (1 - u) * qa + u * qb
    q /= np.linalg.norm(q)
    M = np.zeros(9)
    mujoco.mju_quat2Mat(M, q)
    return M.reshape(3, 3)


def _flat(R):
    """Keep only the heading of an item's long (y) axis: lying flat."""
    yaw = math.atan2(R[1, 1], R[0, 1]) - math.pi / 2
    c, s = math.cos(yaw), math.sin(yaw)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


class Player:
    def __init__(self):
        import mujoco

        self.mj = mujoco
        self.m = load_model()
        self.d = mujoco.MjData(self.m)
        self.site = self.m.site("gripperframe").id
        self.mocap = {self.m.body(i).name[5:]: self.m.body_mocapid[i] for i in range(self.m.nbody)
                      if self.m.body_mocapid[i] >= 0 and self.m.body(i).name.startswith("item_")}
        self.glove = self.m.body_mocapid[self.m.body("hand_zone").id]
        self.keys, self.events, self.length = build(self.m, self.d)
        self._timeline()

    def q_at(self, t):
        ks = self.keys
        for (t0, q0, _), (t1, q1, mode) in zip(ks, ks[1:]):
            if t <= t1:
                u = _ease((t - t0) / (t1 - t0), mode) if t1 > t0 else 1.0
                return (1 - u) * q0 + u * q1
        return ks[-1][1]

    def _site_pose(self, q):
        self.d.qpos[:] = q
        self.mj.mj_forward(self.m, self.d)
        return self.d.site_xpos[self.site].copy(), self.d.site_xmat[self.site].reshape(3, 3).copy()

    def _timeline(self):
        """Walk the events once: for each item, a list of (t_from, kind, data) phases."""
        self.phases = {k: [(0.0, "rest", (np.array([*SLOTS[k], TRAY_Z]), np.eye(3)))] for k in SLOTS}
        self.hand = []  # (t0, t1, kind, anchor, item)
        held = None
        for e in self.events:
            p, R = self._site_pose(self.q_at(e["t"]))
            k = e.get("item")
            if e["kind"] == "grab":
                ip, iR = self._rest(k, e["t"])
                held = (k, R.T @ (ip - p), R.T @ iR)
                self.phases[k].append((e["t"], "held", held[1:]))
            elif e["kind"] == "place" and held:
                _, op, oR = held
                ip, iR = p + R @ op, _flat(R @ oR)
                ip[2] = TABLE_Z if abs(ip[1]) > 0.235 else TRAY_Z
                if k in SLOTS and np.linalg.norm(ip[:2] - SLOTS[k]) < 0.02:  # back in its slot: exactly where it started
                    ip, iR = np.array([*SLOTS[k], TRAY_Z]), np.eye(3)
                t_held, _, data = self.phases[k][-1]  # ease into the resting pose on the way down, no snap
                self.phases[k][-1] = (t_held, "held", (*data, e["t"], ip, iR))
                self.phases[k].append((e["t"], "rest", (ip, iR)))
                held = None
            elif e["kind"] == "reach":
                _, op, oR = held
                ip, iR = p + R @ op, R @ oR
                self.hand.append((e["t"] - 2.0, e["t"] - 0.2, "in", ip + iR @ GRIP, None))
                self._reach_t = e["t"] - 0.2
            elif e["kind"] == "taken" and held:
                _, op, oR = held
                ip, iR = p + R @ op, R @ oR
                anchor = ip + iR @ GRIP
                self.hand.append((self._reach_t, e["t"] + 0.15, "hold", anchor, None))
                self.hand.append((e["t"] + 0.15, e["t"] + 0.15 + OUT_T, "out", anchor, (k, ip - anchor, iR)))
                self.phases[k].append((e["t"], "hand", (anchor, ip - anchor, iR, e["t"] + 0.15)))
                held = None
            elif e["kind"] == "handback":
                at, D = np.array(e["at"], float), e["dur"]
                iR = np.eye(3)
                ang = math.atan2(at[1], at[0])  # lies tangential, like it sat in the tray
                iR = np.array([[math.cos(ang), -math.sin(ang), 0], [math.sin(ang), math.cos(ang), 0], [0, 0, 1]])
                anchor = at + iR @ GRIP
                t0 = e["t"]
                self.hand.append((t0, t0 + 0.5 * D, "bring", anchor, (k, at - anchor, iR)))
                self.hand.append((t0 + 0.5 * D, t0 + 0.7 * D, "lower", anchor, (k, at - anchor, iR)))
                self.hand.append((t0 + 0.7 * D, t0 + D, "out", anchor, None))
                self.phases[k].append((t0, "hb", (anchor, at - anchor, iR, t0, D)))
                self.phases[k].append((t0 + 0.7 * D, "rest", (at, iR)))

    def _rest(self, k, t):
        for t0, kind, data in reversed(self.phases[k]):
            if t0 <= t:
                return data if kind == "rest" else (np.array([*SLOTS[k], TRAY_Z]), np.eye(3))
        return np.array([*SLOTS[k], TRAY_Z]), np.eye(3)

    def glove_at(self, t):
        """Glove grip-point position, or None when out of shot."""
        for t0, t1, kind, anchor, _ in self.hand:
            if t0 <= t < t1:
                u = _ease((t - t0) / (t1 - t0))
                if kind == "in":
                    return anchor + (1 - u) * AWAY
                if kind == "hold":
                    return anchor
                if kind == "out":
                    return anchor + u * AWAY
                if kind == "bring":
                    return anchor + np.array([0, 0, 0.05]) + (1 - u) * AWAY
                if kind == "lower":
                    return anchor + np.array([0, 0, 0.05 * (1 - u)])
        return None

    def items_at(self, t):
        """Each item's (pos, rotation matrix) or None (hidden)."""
        state = {k: None for k in self.mocap}
        for k, phases in self.phases.items():
            cur = [ph for ph in phases if ph[0] <= t][-1]
            t0, kind, data = cur
            if kind == "rest":
                state[k] = data
            elif kind == "held":
                p, R = self._site_pose(self.q_at(t))
                op, oR = data[:2]
                pos, rot = p + R @ op, R @ oR
                if len(data) > 2:
                    t_p, rp, rR = data[2:]
                    u = _ease((t - (t_p - BLEND)) / BLEND)
                    if u > 0:
                        pos = (1 - u) * pos + u * rp
                        rot = _blend_rot(rot, rR, u)
                state[k] = (pos, rot)
            elif kind == "hand":  # rides out with the glove, then gone
                anchor, off, iR, t_out = data
                g = self.glove_at(t)
                if t < t_out:
                    state[k] = (anchor + off, iR)
                elif g is not None and t < t_out + OUT_T:
                    state[k] = (g + off, iR)
            elif kind == "hb":
                anchor, off, iR, t0, D = data
                g = self.glove_at(t)
                if g is not None and t < t0 + D:
                    state[k] = (g + off, iR)
        return state

    def pose(self, t):
        q = self.q_at(t)
        items = self.items_at(t)
        self.d.qpos[:] = q
        for k, mid in self.mocap.items():
            v = items.get(k)
            if v is None:
                self.d.mocap_pos[mid] = (0, 0, -1)
                continue
            quat = np.zeros(4)
            self.mj.mju_mat2Quat(quat, np.ascontiguousarray(v[1]).ravel())
            self.d.mocap_pos[mid], self.d.mocap_quat[mid] = v[0], quat
        g = self.glove_at(t)
        quat = np.zeros(4)
        self.mj.mju_mat2Quat(quat, np.ascontiguousarray(GLOVE_R).ravel())
        self.d.mocap_pos[self.glove] = (0, 0, -2) if g is None else g
        self.d.mocap_quat[self.glove] = quat
        self.mj.mj_forward(self.m, self.d)

    def caption(self, t):
        says = [e for e in self.events if e["kind"] == "say" and e["t"] <= t]
        if not says:
            return None
        last = says[-1]
        return last["text"] if t - last["t"] < (3.0 if last["text"] != "STOPPED" else 2.3) else None

    def tag(self, t):
        tags = [e for e in self.events if e["kind"] == "tag" and e["t"] <= t]
        return bool(tags and tags[-1]["on"])

    def segments(self):
        """(name, start, home) for each segment: start of the segment to the arm settling at home."""
        out, cur = [], None
        for e in self.events:
            if e["kind"] == "segment":
                cur = (e["name"], e["t"])
            elif e["kind"] == "home" and cur:
                out.append((cur[0], cur[1], e["t"])); cur = None
        return out


def _plain(img, cap, tag, fonts):
    from PIL import ImageDraw

    d = ImageDraw.Draw(img, "RGBA")
    W, H = img.size
    small, cap_font = fonts
    s = H / 1080
    d.text((40 * s, 32 * s), tag, font=small, fill=(40, 38, 32, 255))
    if cap:
        w = d.textlength(cap, font=cap_font)
        d.text(((W - w) / 2 + 2 * s, H - 118 * s), cap, font=cap_font, fill=(0, 0, 0, 150))
        d.text(((W - w) / 2, H - 120 * s), cap, font=cap_font, fill=(255, 255, 255, 255))
    return img


CAM = dict(lookat=(0.22, -0.1, 0.1), distance=1.45, azimuth=172, elevation=-29)


def frames(width=1920, height=1080, fps=30, times=None):
    from PIL import Image

    P = Player()
    mj = P.mj
    r = mj.Renderer(P.m, height=height, width=width)
    cam = mj.MjvCamera()
    cam.type = mj.mjtCamera.mjCAMERA_FREE
    cam.lookat[:] = CAM["lookat"]
    cam.distance, cam.azimuth, cam.elevation = CAM["distance"], CAM["azimuth"], CAM["elevation"]
    s = height / 1080
    fonts = (_font(["arial.ttf", "Arial.ttf", "DejaVuSans.ttf"], int(26 * s)),
             _font(["arial.ttf", "Arial.ttf", "DejaVuSans.ttf"], int(42 * s)))
    if times is None:
        times = [k / fps for k in range(int(P.length * fps))]
    for t in times:
        P.pose(t)
        r.update_scene(P.d, camera=cam)
        img = Image.fromarray(r.render())
        img = _plain(img, P.caption(t), "SIMULATED RETURN (electromagnet)" if P.tag(t) else "SIMULATION", fonts)
        yield t, img, P.length
    r.close()


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("still"); s.add_argument("--t", type=float, default=5.0); s.add_argument("--out", required=True)
    s = sub.add_parser("sheet"); s.add_argument("--out", required=True); s.add_argument("--every", type=float, default=1.0)
    s.add_argument("--start", type=float, default=0.0); s.add_argument("--end", type=float, default=None)
    s = sub.add_parser("render"); s.add_argument("--out", required=True); s.add_argument("--fps", type=int, default=30)
    s.add_argument("--draft", action="store_true", help="960x540, quick look")
    sub.add_parser("segments")
    a = ap.parse_args()
    if a.cmd == "segments":
        for name, t0, t1 in Player().segments():
            print(f"{name:10s} {t0:6.2f} {t1:6.2f}")
        return
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    if a.cmd == "still":
        for _, img, _ in frames(times=[a.t]):
            img.save(a.out)
    elif a.cmd == "sheet":
        from PIL import Image, ImageDraw

        end = a.end if a.end is not None else Player().length
        ts = list(np.arange(a.start, end + 1e-6, a.every))
        imgs = []
        for t, img, _ in frames(width=960, height=540, times=ts):
            im = img.resize((480, 270)); ImageDraw.Draw(im).text((400, 8), f"{t:.2f}", fill=(0, 0, 0))
            imgs.append(im)
        cols = 6
        sheet = Image.new("RGB", (480 * cols, 270 * math.ceil(len(imgs) / cols)))
        for i, im in enumerate(imgs):
            sheet.paste(im, (480 * (i % cols), 270 * (i // cols)))
        sheet.save(a.out)
        print(a.out, len(imgs), "frames")
    else:
        import imageio_ffmpeg

        size = (960, 540) if a.draft else (1920, 1080)
        w = imageio_ffmpeg.write_frames(a.out, size, fps=a.fps, codec="libx264", quality=8,
                                        pix_fmt_out="yuv420p", macro_block_size=8)
        w.send(None)
        for k, (t, img, L) in enumerate(frames(width=size[0], height=size[1], fps=a.fps)):
            w.send(np.ascontiguousarray(np.asarray(img.convert("RGB"))))
            if k % (a.fps * 5) == 0:
                print(f"  {t:5.1f} / {L:.1f} s", flush=True)
        w.close()
        print("wrote", a.out)


if __name__ == "__main__":
    main()
