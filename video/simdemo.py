"""Scripted sim demo for the video: smooth, labeled SIMULATION, same scene as simcine.

Unlike `simcine render`, nothing is replayed from the live sim (its items snap between spots). The arm
moves through IK keyframes with eased timing, the jaw closes on each instrument, and a held instrument
rides with the gripper. Sequence: hemostat handoff, scalpel set on the table beside the tray, Mayo
scissors handoff, hemostat return (simulated electromagnet pickup).

  python -m video.simdemo still --t 6 --out data/video/simdemo/still.png
  python -m video.simdemo sheet --out data/video/simdemo/sheet.png      # one frame per second
  python -m video.simdemo render --out data/video/out/sim-demo.mp4
"""
import argparse
import math
from pathlib import Path

import numpy as np

from video.simcine import _font, _overlay, load_model

OPEN, CLOSED, HOLD = 0.55, -0.17, -0.15  # jaw qpos: open, tips touching, closed on a thin instrument
SLOTS = {"hemostat": (0.24, -0.08), "scalpel": (0.24, 0.0), "mayo_scissors": (0.24, 0.08)}
TABLE_Z, TRAY_Z = 0.0, 0.004            # item resting heights (table top, paper liner)
SAFE = (0.17, -0.31)                    # scalpel safe spot: on the table, clear of the tray
RETURN = (0.17, 0.31)                   # return spot: on the table, other side
HANDOFF = np.array([0.27, -0.26, 0.17])  # where the clinician's hand takes it
HOME = np.zeros(6)
READY = np.array([0.0, -0.45, 0.5, 1.13, 1.59, 0.0])  # elbow up, tip down over the tray


# ---- IK -------------------------------------------------------------------------------------------
def _target_rot(approach, across):
    """Site frame with x along `approach` and z (the jaw opening direction) along `across`."""
    x = np.asarray(approach, float); x /= np.linalg.norm(x)
    z = np.asarray(across, float); z -= x * (z @ x); z /= np.linalg.norm(z)
    return np.column_stack([x, np.cross(z, x), z])


def ik(m, d, site, pos, rot, q0, w_rot=0.25, iters=300):
    import mujoco

    q = q0.copy()
    jp, jr = np.zeros((3, m.nv)), np.zeros((3, m.nv))
    for _ in range(iters):
        d.qpos[:] = q
        mujoco.mj_forward(m, d)
        ep = pos - d.site_xpos[site]
        R = d.site_xmat[site].reshape(3, 3)
        er = 0.5 * sum(np.cross(R[:, i], rot[:, i]) for i in range(3))
        if np.linalg.norm(ep) < 5e-4 and np.linalg.norm(er) < 2e-3:
            break
        mujoco.mj_jacSite(m, d, jp, jr, site)
        J = np.vstack([jp[:, :5], w_rot * jr[:, :5]])
        e = np.concatenate([ep, w_rot * er])
        dq = J.T @ np.linalg.solve(J @ J.T + 1e-4 * np.eye(6), e)
        q[:5] = np.clip(q[:5] + 0.5 * dq, m.jnt_range[:5, 0], m.jnt_range[:5, 1])
    return q, float(np.linalg.norm(ep))


# ---- the script -----------------------------------------------------------------------------------
def _ease(u):
    u = min(1.0, max(0.0, u))
    return u * u * u * (10 - 15 * u + 6 * u * u)  # min-jerk


def build(m, d):
    """Keyframes (t, qpos, step, caption, event) and item events. Returns (keys, events, length)."""
    site = m.site("gripperframe").id
    down = (0, 0, -1)
    keys, events = [(0.0, HOME.copy(), None)], []
    t, q = 0.0, HOME.copy()

    def to(pos, approach=down, across=None, dur=1.4, jaw=None, step=None):
        nonlocal t, q
        pos = np.asarray(pos, float)
        if approach is down:  # tip slightly outward, like the real arm reaching over the tray
            ang = math.atan2(pos[1], pos[0])
            approach = (0.4 * math.cos(ang), 0.4 * math.sin(ang), -1)
        if across is None:  # jaws close across the instrument (items lie along y, radial-ish)
            ang = math.atan2(pos[1], pos[0])
            across = (-math.sin(ang), math.cos(ang), 0)
        rot = _target_rot(approach, across)
        best = None
        ready = READY.copy(); ready[0] = math.atan2(pos[1], pos[0])
        for w in (0.25, 0.1, 0.03):
            for q0 in (q, ready):
                qq, err = ik(m, d, site, pos, rot, q0, w_rot=w)
                score = err + 0.02 * np.abs(qq[:5] - q[:5]).sum()  # stay close to the last pose: no flips
                if err < 0.003 and (best is None or score < best[0]):
                    best = (score, qq)
            if best:
                break
        assert best, f"unreachable {pos}"
        q = best[1]
        if jaw is not None:
            q[5] = jaw
        t += dur
        keys.append((t, q.copy(), step))

    def jaw(v, dur=0.5, step=None):
        nonlocal t, q
        q = q.copy(); q[5] = v
        t += dur
        keys.append((t, q.copy(), step))

    def hold(dur, step=None):
        nonlocal t
        t += dur
        keys.append((t, q.copy(), step))

    def ev(kind, **kw):
        events.append(dict(t=t, kind=kind, **kw))

    def pick(item, x, y, z, step="PICK"):
        to((x, y, z + 0.09), across=(-math.sin(math.atan2(y, x)), math.cos(math.atan2(y, x)), 0), dur=1.6, jaw=OPEN, step="FIND")
        to((x, y, z + 0.012), dur=1.0, step=step)
        jaw(HOLD, 0.45, step=step)
        ev("grab", item=item)
        hold(0.25, step="CHECK")
        to((x, y, z + 0.11), dur=0.9, step="CHECK")

    def hand(item, say_ready):
        to(HANDOFF, approach=(0.15, -1, -0.25), across=(0, 0, 1), dur=1.9, step="HAND")
        ev("say", text=say_ready)
        hold(1.3, step="WAIT")
        jaw(OPEN, 0.4, step="RELEASE")
        ev("taken", item=item)
        hold(0.6, step="RELEASE")
        to((0.24, -0.16, 0.16), approach=(0.2, -1, -0.4), across=(0, 0, 1), dur=1.0, step="HOME")

    def home():
        nonlocal t, q
        q = HOME.copy(); q[5] = 0.0
        t += 1.5
        keys.append((t, q.copy(), "HOME"))
        hold(0.6)

    ev("say", text="Hemostat coming.")
    x, y = SLOTS["hemostat"]; pick("hemostat", x, y, TRAY_Z)
    hand("hemostat", "Here's the hemostat. Ready to grab.")
    home()

    ev("say", text="Scalpel to the safe spot.")
    x, y = SLOTS["scalpel"]; pick("scalpel", x, y, TRAY_Z)
    to((SAFE[0], SAFE[1], 0.09), dur=1.7, step="HAND")
    to((SAFE[0], SAFE[1], TABLE_Z + 0.012), dur=0.9, step="HAND")
    jaw(OPEN, 0.4, step="RELEASE")
    ev("place", item="scalpel")
    ev("say", text="Scalpel down, on the safe spot. Careful, it's sharp.")
    to((SAFE[0], SAFE[1], 0.11), dur=0.8, step="RELEASE")
    home()

    ev("say", text="Mayo scissors coming.")
    x, y = SLOTS["mayo_scissors"]; pick("mayo_scissors", x, y, TRAY_Z)
    hand("mayo_scissors", "Here are the Mayo scissors. Ready to grab.")
    home()

    ev("appear", item="hemostat", at=(RETURN[0], RETURN[1], TABLE_Z))
    ev("say", text="Returning the hemostat.")
    ev("tag", text="SIMULATED RETURN  ·  electromagnet pickup")
    pick("hemostat", RETURN[0], RETURN[1], TABLE_Z, step="PICK")
    x, y = SLOTS["hemostat"]
    to((x, y, 0.1), dur=1.7, step="HAND")
    to((x, y, TRAY_Z + 0.012), dur=0.9, step="HAND")
    jaw(OPEN, 0.4, step="RELEASE")
    ev("place", item="hemostat")
    ev("say", text="Hemostat back in its slot.")
    to((x, y, 0.11), dur=0.8, step="RELEASE")
    ev("tag", text="")
    home()
    return keys, events, t


class Player:
    def __init__(self):
        import mujoco

        self.mj = mujoco
        self.m = load_model()
        self.d = mujoco.MjData(self.m)
        self.site = self.m.site("gripperframe").id
        self.mocap = {self.m.body(i).name[5:]: self.m.body_mocapid[i] for i in range(self.m.nbody)
                      if self.m.body_mocapid[i] >= 0 and self.m.body(i).name.startswith("item_")}
        self.keys, self.events, self.length = build(self.m, self.d)

    def q_at(self, t):
        ks = self.keys
        for (t0, q0, _), (t1, q1, s1) in zip(ks, ks[1:]):
            if t <= t1:
                u = _ease((t - t0) / (t1 - t0)) if t1 > t0 else 1.0
                return (1 - u) * q0 + u * q1, s1
        return ks[-1][1], ks[-1][2]

    def _site_pose(self, q):
        self.d.qpos[:] = q
        self.mj.mj_forward(self.m, self.d)
        return self.d.site_xpos[self.site].copy(), self.d.site_xmat[self.site].reshape(3, 3).copy()

    def items_at(self, t):
        """Each item's (pos, rotation matrix) or None (hidden), from the events up to t."""
        state = {k: (np.array([*SLOTS[k], TRAY_Z]), np.eye(3)) for k in SLOTS}
        for k in self.mocap:
            state.setdefault(k, None)
        held = None  # (item, offset pos in site frame, offset rot)
        taken = None
        for e in self.events:
            if e["t"] > t:
                break
            p, R = self._site_pose(self.q_at(e["t"])[0])
            if e["kind"] == "grab":
                ip, iR = state[e["item"]]
                held = (e["item"], R.T @ (ip - p), R.T @ iR)
            elif e["kind"] in ("place", "taken") and held:
                name, op, oR = held
                state[name] = (p + R @ op, R @ oR)
                if e["kind"] == "place":  # settle flat on the surface, keep its heading
                    ipos, iR = state[name]
                    yaw = math.atan2(iR[1, 1], iR[0, 1]) - math.pi / 2
                    c, s = math.cos(yaw), math.sin(yaw)
                    ipos[2] = TABLE_Z if abs(ipos[1]) > 0.235 else TRAY_Z
                    state[name] = (ipos, np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]]))
                else:
                    taken = (name, e["t"], state[name])
                held = None
            elif e["kind"] == "appear":
                state[e["item"]] = (np.array(e["at"], float), np.eye(3))
        if held:
            p, R = self._site_pose(self.q_at(t)[0])
            name, op, oR = held
            state[name] = (p + R @ op, R @ oR)
        if taken:  # the hand draws it away and out of shot
            name, t0, (p0, R0) = taken
            u = _ease((t - t0) / 0.5)
            state[name] = None if u >= 1 else (p0 + u * np.array([0.03, -0.25, 0.06]), R0)
        return state

    def pose(self, t):
        q, step = self.q_at(t)
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
        self.mj.mj_forward(self.m, self.d)
        return step

    def caption(self, t):
        says = [e for e in self.events if e["kind"] == "say" and e["t"] <= t]
        return says[-1]["text"] if says and t - says[-1]["t"] < 3.0 else None

    def tag(self, t):
        tags = [e for e in self.events if e["kind"] == "tag" and e["t"] <= t]
        return tags[-1]["text"] if tags else ""


def _plain(img, cap, tag, fonts):
    from PIL import ImageDraw

    d = ImageDraw.Draw(img, "RGBA")
    W, H = img.size
    _, mono, big = fonts
    d.text((40, 36), tag, font=mono, fill=(40, 38, 32, 255))
    if cap:
        w = d.textlength(cap, font=big)
        d.text(((W - w) / 2 + 2, H - 128), cap, font=big, fill=(0, 0, 0, 160))
        d.text(((W - w) / 2, H - 130), cap, font=big, fill=(255, 255, 255, 255))
    return img


def frames(width=1920, height=1080, fps=30, times=None):
    from PIL import Image

    P = Player()
    mj = P.mj
    r = mj.Renderer(P.m, height=height, width=width)
    cam = mj.MjvCamera()
    cam.type = mj.mjtCamera.mjCAMERA_FREE
    fonts = (_font(["arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"], 44),
             _font(["arial.ttf", "Arial.ttf", "DejaVuSans.ttf"], 28),
             _font(["seguisb.ttf", "arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"], 40))
    steps = ["FIND", "PICK", "CHECK", "HAND", "WAIT", "RELEASE", "HOME"]
    if times is None:
        times = [k / fps for k in range(int(P.length * fps))]
    look = None
    for t in times:
        step = P.pose(t)
        tip = P.d.site_xpos[P.site]
        goal = np.array([0.18, 0.0, 0.06])
        look = goal if look is None or len(times) < 100 else look + 0.04 * (goal - look)
        cam.lookat[:] = look
        cam.distance = 1.45
        cam.azimuth = 135
        cam.elevation = -30
        r.update_scene(P.d, camera=cam)
        img = Image.fromarray(r.render())
        tag = P.tag(t)
        img = _plain(img, P.caption(t), "SIMULATED RETURN (electromagnet)" if tag else "SIMULATION", fonts)
        yield t, img, P.length
    r.close()


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("still"); s.add_argument("--t", type=float, default=5.0); s.add_argument("--out", required=True)
    s = sub.add_parser("sheet"); s.add_argument("--out", required=True); s.add_argument("--every", type=float, default=1.0)
    s = sub.add_parser("render"); s.add_argument("--out", required=True); s.add_argument("--fps", type=int, default=30)
    s.add_argument("--draft", action="store_true", help="960x540, quick look")
    a = ap.parse_args()
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    if a.cmd == "still":
        for _, img, _ in frames(times=[a.t]):
            img.save(a.out)
    elif a.cmd == "sheet":
        from PIL import Image

        n = int(Player().length / a.every) + 1
        imgs = [img.resize((480, 270)) for _, img, _ in frames(times=[i * a.every for i in range(n)])]
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
                print(f"  {t:5.1f} / {L:.1f} s")
        w.close()
        print("wrote", a.out)


if __name__ == "__main__":
    main()
