"""Scripted sim demo for the video: smooth, labeled SIMULATION, our arm on a wood table with the real sheet pan.

Nothing is replayed from the live sim. The arm moves through IK keyframes with eased timing, the jaw closes on each
instrument, and a held instrument rides rigidly with the gripper. No hand prop: at the handoff point the arm holds,
opens, and the instrument is lifted away out of shot as if taken. Sequence: hemostat to the handoff point and home;
Mayo scissors the same; scalpel carry with a stop mid-move (STOPPED, then continue) and home; simulated return
(the hemostat lies on the table beside the pan, the closed jaw picks it up as an electromagnet would and sets it
flat back in its slot, home). The arm slows over the last few centimeters to the handoff point.

  python -m video.simdemo still --t 6 --out still.png
  python -m video.simdemo sheet --every 1 --out sheet.png        # one frame per second (--start/--end to zoom)
  python -m video.simdemo render --out simdemo-final.mp4          # 1080p 30 fps, 2x supersampled
  python -m video.simdemo segments                                # segment start / home times
"""
import argparse
import math
import re
import tempfile
from pathlib import Path

import numpy as np

from video.simcine import _box, _font, cinematic_xml

OPEN, CLOSED, HOLD = 0.55, -0.17, -0.15  # jaw qpos: open, tips touching, closed on a thin instrument
ROLL = 0.0  # wrist roll for every keyframe: jaws open toward/away from the base like the real arm
SLOTS = {"hemostat": (0.21, 0.0), "scalpel": (0.28, 0.0), "mayo_scissors": (0.35, 0.0)}  # parallel, along y
TABLE_Z, TRAY_Z = 0.0022, 0.0047        # item resting heights (table top, paper liner)
RETURN = (0.10, -0.15)                  # the used hemostat lies on the table beside the pan
HANDOFF = np.array([0.30, -0.24, 0.17])  # where the clinician takes it
TAKE = np.array([0.15, -0.55, 0.40])    # the instrument leaves along this, out of shot
TAKE_T = 0.8
HOME = np.array([0.0, -1.7, 1.55, 0.45, ROLL, 0.0])  # the real arm's folded rest pose (layout.json)
READY = np.array([0.0, -0.45, 0.5, 1.13, ROLL, 0.0])  # elbow up, tip down over the tray
GRIP_DZ = 0.006  # gripper site above the item centre when grasping: the item sits between the tips, tips clear the liner
FADE = 0.4  # s: fade out / in around the cut into the simulated return

WHITE, SERVO, TIP = (0.93, 0.92, 0.89, 1.0), (0.11, 0.11, 0.11, 1.0), (0.07, 0.07, 0.07, 1.0)
CAM = dict(lookat=(0.20, -0.06, 0.12), distance=0.76, azimuth=150, elevation=-30)


# ---- scene ----------------------------------------------------------------------------------------
def _stl(path):
    b = Path(path).read_bytes()
    n = int(np.frombuffer(b[80:84], np.uint32)[0])
    return np.frombuffer(b[84:84 + n * 50], dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))


def _write_stl(path, tris):
    out = np.zeros(len(tris), dtype=tris.dtype)
    out[:] = tris
    Path(path).write_bytes(b"\0" * 80 + np.uint32(len(out)).tobytes() + out.tobytes())


def _split_tips(assets, tmp):
    """Split each jaw mesh into the printed part and its black tip (the last ~3 cm), like the real jaw pads."""
    out = {}
    for name, axis, sign, cut in (("moving_jaw_so101_v1", 1, -1, 0.052), ("wrist_roll_follower_so101_v1", 2, 1, 0.074)):
        t = _stl(assets / f"{name}.stl")
        c = t["v"].mean(axis=1)[:, axis] * sign
        tip = c > cut
        for part, mask in (("body", ~tip), ("tip", tip)):
            p = Path(tmp) / f"{name}_{part}.stl"
            _write_stl(p, t[mask])
            out[(name, part)] = p
    return out


def _wood(path, w=1024, h=1024):
    """A light maple tabletop texture: soft grain along x."""
    from PIL import Image

    rng = np.random.default_rng(3)
    y = np.linspace(0, 1, h)[:, None]
    x = np.linspace(0, 1, w)[None, :]
    wob = sum(rng.uniform(0.002, 0.01) * np.sin(2 * np.pi * (rng.integers(1, 5) * x + rng.uniform())) for _ in range(4))
    g = 0.5 + 0.5 * np.sin(2 * np.pi * (y + wob) * 48 + 2.5 * np.sin(2 * np.pi * (y * 3 + x * 0.7)))
    g = g ** 4
    noise = np.repeat(rng.normal(0, 1, (h, w // 128)), 128, axis=1)
    noise = 0.5 * noise + 0.5 * np.roll(noise, 64, axis=1)
    v = 0.86 - 0.03 * g + 0.012 * noise
    base = np.array([0.84, 0.72, 0.57])
    img = np.clip(v[..., None] / 0.86 * base[None, None, :], 0, 1)
    Image.fromarray((img * 255).astype(np.uint8)).save(path)


VISUAL = """<visual>
  <headlight diffuse="0.12 0.12 0.12" ambient="0.30 0.29 0.27" specular="0.03 0.03 0.03"/>
  <global offwidth="3840" offheight="2160" fovy="34"/>
  <quality shadowsize="8192" offsamples="4"/>
  <map znear="0.01" zfar="20" shadowclip="0.9" haze="0"/>
</visual>"""

LIGHTS = """<light name="key" pos="0.85 -0.75 1.35" dir="-0.55 0.45 -1" castshadow="true" bulbradius="0.18" cutoff="45" exponent="2" diffuse="0.62 0.58 0.52" specular="0.25 0.24 0.22"/>
    <light name="fill" pos="-0.4 0.7 1.1" dir="0.4 -0.6 -1" castshadow="false" diffuse="0.20 0.20 0.21" specular="0 0 0"/>
    <light name="top" pos="0.2 0 1.6" dir="0 0 -1" castshadow="false" cutoff="60" exponent="1" diffuse="0.22 0.21 0.20" specular="0.05 0.05 0.05"/>"""


def scene_xml(tmp):
    src = cinematic_xml()
    src = re.sub(r"<visual>.*?</visual>", VISUAL, src, count=1, flags=re.S)
    src = re.sub(r'<light name="key".*?<light name="top"[^>]*/>', LIGHTS, src, count=1, flags=re.S)
    src = re.sub(r'<body pos="[-\d. ]+">.*?</body>', "", src, flags=re.S)  # only the three demo instruments
    # warm grey room like the logo, a light wood table
    src = re.sub(r'<texture name="cine_sky"[^>]*/>',
                 '<texture name="cine_sky" type="skybox" builtin="gradient" rgb1="0.80 0.77 0.72" rgb2="0.66 0.63 0.59" width="512" height="512"/>', src)
    wood = Path(tmp) / "wood.png"
    _wood(wood)
    src = re.sub(r'<material name="cine_floor_mat"[^>]*/>',
                 '<material name="cine_floor_mat" rgba="0.70 0.67 0.62 1" specular="0" shininess="0"/>'
                 f'<texture name="wood" type="2d" file="{wood}"/>', src)
    src = re.sub(r'<material name="table_mat"[^>]*/>',
                 '<material name="table_mat" texture="wood" texrepeat="1 1" texuniform="false" rgba="1 1 1 1" specular="0.15" shininess="0.25" reflectance="0"/>', src)
    src = re.sub(r'<material name="alum"[^>]*/>',
                 '<material name="alum" rgba="0.74 0.75 0.77 1" specular="0.7" shininess="0.6" reflectance="0.05"/>', src)
    src = re.sub(r'<material name="paper"[^>]*/>', '<material name="paper" rgba="0.93 0.93 0.92 1" specular="0.05" shininess="0.05"/>', src)
    src = re.sub(r'<material name="tape"[^>]*/>', '<material name="tape" rgba="0.16 0.42 0.82 1" specular="0.15" shininess="0.2"/>', src)
    src = re.sub(r'<material name="steel"[^>]*/>',
                 '<material name="steel" rgba="0.78 0.80 0.83 1" specular="0.9" shininess="0.85" reflectance="0.1"/>', src)
    src = re.sub(r'<material name="steel_dark"[^>]*/>',
                 '<material name="steel_dark" rgba="0.55 0.57 0.60 1" specular="0.8" shininess="0.8" reflectance="0.08"/>', src)
    # black jaw tips: split the two jaw meshes, in a patched copy of the arm file
    from video.simcine import SCENES
    arm = (SCENES / "_arm.xml").read_text(encoding="utf-8")
    assets = Path(__file__).resolve().parents[1] / "sim" / "models" / "so101" / "assets"
    parts = _split_tips(assets, tmp)
    meshes = "".join(f'<mesh name="{name}_{part}" file="{p}"/>' for (name, part), p in parts.items())
    mats = ('<material name="jaw_white" rgba="0.93 0.92 0.89 1" specular="0.25" shininess="0.3"/>'
            '<material name="jaw_tip" rgba="0.07 0.07 0.07 1" specular="0.35" shininess="0.4"/>')
    arm = arm.replace("</asset>", meshes + mats + "</asset>", 1)
    for name in ("moving_jaw_so101_v1", "wrist_roll_follower_so101_v1"):
        m = re.search(rf'<geom type="mesh" class="visual"([^>]*?)mesh="{name}" material="[^"]*"/>', arm)
        attrs = m.group(1)
        new = (f'<geom type="mesh" class="visual"{attrs}mesh="{name}_body" material="jaw_white"/>'
               f'<geom type="mesh" class="visual"{attrs}mesh="{name}_tip" material="jaw_tip"/>')
        arm = arm[:m.start()] + new + arm[m.end():]
    src = src.replace('<include file="_arm.xml"/>', '<include file="_simdemo_arm.xml"/>', 1)
    return src, arm


def load_model():
    import mujoco

    from video.simcine import SCENES  # the scene include path
    with tempfile.TemporaryDirectory() as tmp:
        path, arm_path = SCENES / "_simdemo.xml", SCENES / "_simdemo_arm.xml"
        src, arm = scene_xml(tmp)
        path.write_text(src, encoding="utf-8")
        arm_path.write_text(arm, encoding="utf-8")
        try:
            model = mujoco.MjModel.from_xml_path(str(path))
        finally:
            path.unlink(missing_ok=True)
            arm_path.unlink(missing_ok=True)
    for i in range(model.nmat):  # white printed parts, black servos
        r, g_, b, a = model.mat_rgba[i]
        if r > 0.9 and g_ > 0.7 and b < 0.3:
            model.mat_rgba[i] = WHITE
            model.mat_specular[i], model.mat_shininess[i] = 0.25, 0.3
        elif r < 0.2 and g_ < 0.2 and b < 0.2 and model.mat(i).name.startswith("sts"):
            model.mat_rgba[i] = SERVO
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
    if mode == "out":    # arrive moving, settle slowly (the slow last approach to the handoff point)
        return 1 - (1 - u) ** 3
    if mode == "stop":   # moving, then brake hard
        return 1 - (1 - u) ** 2
    if mode == "lin":
        return u
    return u * u * u * (10 - 15 * u + 6 * u * u)  # min-jerk


def _yaw(ang):
    c, s = math.cos(ang), math.sin(ang)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


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
            approach = (0.3 * math.cos(ang), 0.3 * math.sin(ang), -1)
        best = None
        ready = READY.copy(); ready[0] = -ang  # positive pan swings toward -y
        for w in (0.25, 0.1, 0.03, 0.01):
            for q0 in (q, ready, keys[-2][1] if len(keys) > 1 else q):
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
        to((x, y, z + 0.08), dur=1.6, jaw=OPEN if grip == HOLD else CLOSED)
        to((x, y, z + GRIP_DZ), dur=0.9)
        if grip == HOLD:
            jaw(HOLD, 0.45)
        else:
            hold(0.35)
        ev("grab", item=item)
        hold(0.2)
        to((x, y, z + 0.10), dur=0.9)

    def outward(p, down_=0.25):
        ang = math.atan2(p[1], p[0])
        return (math.cos(ang), math.sin(ang), -down_)

    def approach_hand(first=1.4):
        """Carry toward the handoff point, then slow down over the last few centimeters."""
        a = np.array(outward(HANDOFF)); a /= np.linalg.norm(a)
        to(HANDOFF - 0.07 * a, approach=outward(HANDOFF), dur=first, mode="in")
        to(HANDOFF, approach=outward(HANDOFF), dur=1.3, mode="out")

    def give(item):
        hold(0.9)
        jaw(OPEN, 0.4)
        ev("taken", item=item)
        hold(TAKE_T + 0.3)

    def home(dur=1.8):
        qn = HOME.copy(); qn[5] = 0.0
        key(qn, dur)
        ev("home")
        hold(0.6)

    def segment(name):
        ev("segment", name=name)

    hold(0.5)
    # 1. hemostat to the handoff point, home
    segment("hemostat")
    ev("say", text="Hemostat coming.")
    x, y = SLOTS["hemostat"]; pick("hemostat", x, y, TRAY_Z)
    approach_hand()
    ev("say", text="Here's the hemostat.")
    give("hemostat")
    home()

    # 2. Mayo scissors, home
    segment("scissors")
    ev("say", text="Mayo scissors coming.")
    x, y = SLOTS["mayo_scissors"]; pick("mayo_scissors", x, y, TRAY_Z)
    approach_hand(first=1.7)
    ev("say", text="Here are the Mayo scissors.")
    give("mayo_scissors")
    home()

    # 3. scalpel: stop mid-move, then continue to the handoff point, home
    segment("stop")
    ev("say", text="Scalpel coming.")
    x, y = SLOTS["scalpel"]; pick("scalpel", x, y, TRAY_Z)
    a = np.array(outward(HANDOFF)); a /= np.linalg.norm(a)
    q_from, q_to = q.copy(), solve(HANDOFF - 0.07 * a, outward(HANDOFF))
    ev("say", text="Stop.")
    key(q_from + 0.38 * (q_to - q_from), 0.7, "in")
    key(q_from + 0.46 * (q_to - q_from), 0.3, "stop")
    ev("status", text="STOPPED")
    hold(2.2)
    ev("say", text="Continue.")
    ev("status", text="continue")
    to(HANDOFF - 0.07 * a, approach=outward(HANDOFF), dur=1.0, mode="in")
    ev("status", text=None)
    to(HANDOFF, approach=outward(HANDOFF), dur=1.3, mode="out")
    ev("say", text="Here's the scalpel.")
    give("scalpel")
    home()

    # 4. simulated return: the hemostat lies on the table beside the pan; pick it up, set it back in its slot
    hold(FADE)
    ev("cut")          # fade through black: the hemostat is on the table when the picture comes back
    hold(FADE)
    segment("return")
    ev("tag", on=True)
    ev("lying", item="hemostat", at=(RETURN[0], RETURN[1], TABLE_Z))
    ev("say", text="Returning the hemostat.")
    hold(1.2)
    pick("hemostat", RETURN[0], RETURN[1], TABLE_Z, grip=CLOSED)
    x, y = SLOTS["hemostat"]
    to((x, y, 0.09), dur=1.7)
    to((x, y, TRAY_Z + GRIP_DZ), dur=1.0)
    hold(0.3)
    ev("place", item="hemostat")
    ev("say", text="Hemostat back in its slot.")
    hold(0.2)
    to((x, y, 0.10), dur=0.8)
    home()
    ev("tag", on=False)
    hold(0.6)
    return keys, events, t


BLEND = 0.9  # s: settling into a resting pose on the way down


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
    return _yaw(yaw)


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
                ip[2] = TRAY_Z
                if np.linalg.norm(ip[:2] - SLOTS[k]) < 0.03:  # back in its slot: exactly where it started
                    ip, iR = np.array([*SLOTS[k], TRAY_Z]), np.eye(3)
                t_held, _, data = self.phases[k][-1]  # ease into the resting pose on the way down, no snap
                self.phases[k][-1] = (t_held, "held", (*data, e["t"], ip, iR))
                self.phases[k].append((e["t"], "rest", (ip, iR)))
                held = None
            elif e["kind"] == "taken" and held:
                _, op, oR = held
                self.phases[k].append((e["t"], "taken", (p + R @ op, R @ oR, e["t"])))
                self.phases[k].append((e["t"] + TAKE_T, "gone", None))
                held = None
            elif e["kind"] == "lying":
                at = np.array(e["at"], float)
                ang = math.atan2(at[1], at[0])  # lies tangential, like it sat in the tray
                self.phases[k].append((e["t"], "rest", (at, _yaw(ang))))

    def _rest(self, k, t):
        for t0, kind, data in reversed(self.phases[k]):
            if t0 <= t:
                return data if kind == "rest" else (np.array([*SLOTS[k], TRAY_Z]), np.eye(3))
        return np.array([*SLOTS[k], TRAY_Z]), np.eye(3)

    def items_at(self, t):
        """Each item's (pos, rotation matrix) or None (hidden)."""
        state = {k: None for k in self.mocap}
        for k, phases in self.phases.items():
            t0, kind, data = [ph for ph in phases if ph[0] <= t][-1]
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
            elif kind == "taken":  # lifted up and away out of shot, as if a hand took it
                pos, rot, ts = data
                u = (t - ts) / TAKE_T
                state[k] = (pos + _ease(u, "in") * TAKE, rot)
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
        self.mj.mj_forward(self.m, self.d)

    def caption(self, t):
        says = [e for e in self.events if e["kind"] == "say" and e["t"] <= t]
        if not says:
            return None
        last = says[-1]
        return last["text"] if t - last["t"] < 3.0 else None

    def status(self, t):
        st = [e for e in self.events if e["kind"] == "status" and e["t"] <= t]
        return st[-1]["text"] if st else None

    def tag(self, t):
        tags = [e for e in self.events if e["kind"] == "tag" and e["t"] <= t]
        return bool(tags and tags[-1]["on"])

    def fade(self, t):
        """Picture brightness 0..1 around the cut into the simulated return."""
        for e in self.events:
            if e["kind"] == "cut" and abs(t - e["t"]) < FADE:
                return abs(t - e["t"]) / FADE
        return 1.0

    def segments(self):
        """(name, start, home) for each segment: start of the segment to the arm settling at home."""
        out, cur = [], None
        for e in self.events:
            if e["kind"] == "segment":
                cur = (e["name"], e["t"])
            elif e["kind"] == "home" and cur:
                out.append((cur[0], cur[1], e["t"])); cur = None
        return out


def _plain(img, cap, tag, status, fonts):
    from PIL import ImageDraw

    d = ImageDraw.Draw(img, "RGBA")
    W, H = img.size
    small, cap_font = fonts
    s = H / 1080

    def text(xy, txt, font):
        d.text((xy[0] + 2 * s, xy[1] + 2 * s), txt, font=font, fill=(0, 0, 0, 110))
        d.text(xy, txt, font=font, fill=(255, 255, 255, 255))

    text((40 * s, 32 * s), tag, small)
    if status:
        text((40 * s, 68 * s), status, small)
    if cap:
        w = d.textlength(cap, font=cap_font)
        text(((W - w) / 2, H - 120 * s), cap, cap_font)
    return img


def frames(width=1920, height=1080, fps=30, times=None, captions=True, ss=2):
    from PIL import Image

    P = Player()
    mj = P.mj
    r = mj.Renderer(P.m, height=height * ss, width=width * ss)
    cam = mj.MjvCamera()
    cam.type = mj.mjtCamera.mjCAMERA_FREE
    cam.lookat[:] = CAM["lookat"]
    cam.distance, cam.azimuth, cam.elevation = CAM["distance"], CAM["azimuth"], CAM["elevation"]
    s = height / 1080
    fonts = (_font(["arial.ttf", "Arial.ttf", "DejaVuSans.ttf"], int(28 * s)),
             _font(["arial.ttf", "Arial.ttf", "DejaVuSans.ttf"], int(42 * s)))
    if times is None:
        times = [k / fps for k in range(int(P.length * fps))]
    for t in times:
        P.pose(t)
        r.update_scene(P.d, camera=cam)
        img = Image.fromarray(r.render())
        if ss > 1:
            img = img.reduce(ss)
        f = P.fade(t)
        if f < 1:
            img = Image.fromarray((np.asarray(img).astype(np.float32) * f).astype(np.uint8))
        else:
            tag = "SIMULATED RETURN (electromagnet)" if P.tag(t) else "SIMULATION"
            img = _plain(img, P.caption(t) if captions else "", tag, P.status(t), fonts)
        yield t, img, P.length
    r.close()


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("still"); s.add_argument("--t", type=float, default=5.0); s.add_argument("--out", required=True)
    s.add_argument("--no-captions", action="store_true")
    s = sub.add_parser("sheet"); s.add_argument("--out", required=True); s.add_argument("--every", type=float, default=1.0)
    s.add_argument("--start", type=float, default=0.0); s.add_argument("--end", type=float, default=None)
    s.add_argument("--big", action="store_true", help="960x540 tiles instead of 480x270")
    s = sub.add_parser("render"); s.add_argument("--out", required=True); s.add_argument("--fps", type=int, default=30)
    s.add_argument("--draft", action="store_true", help="960x540, no supersampling, quick look")
    s.add_argument("--no-captions", action="store_true", help="tag only; the edit burns its own captions")
    sub.add_parser("segments")
    a = ap.parse_args()
    if a.cmd == "segments":
        for name, t0, t1 in Player().segments():
            print(f"{name:10s} {t0:6.2f} {t1:6.2f}")
        return
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    if a.cmd == "still":
        for _, img, _ in frames(times=[a.t], captions=not a.no_captions):
            img.save(a.out)
    elif a.cmd == "sheet":
        from PIL import Image, ImageDraw

        end = a.end if a.end is not None else Player().length
        ts = list(np.arange(a.start, end + 1e-6, a.every))
        tw, th = (960, 540) if a.big else (480, 270)
        imgs = []
        for t, img, _ in frames(width=960, height=540, times=ts, ss=2):
            im = img.resize((tw, th)); ImageDraw.Draw(im).text((tw - 80, 8), f"{t:.2f}", fill=(0, 0, 0))
            imgs.append(im)
        cols = 6 if not a.big else 3
        sheet = Image.new("RGB", (tw * cols, th * math.ceil(len(imgs) / cols)))
        for i, im in enumerate(imgs):
            sheet.paste(im, (tw * (i % cols), th * (i // cols)))
        sheet.save(a.out)
        print(a.out, len(imgs), "frames")
    else:
        import imageio_ffmpeg

        size = (960, 540) if a.draft else (1920, 1080)
        w = imageio_ffmpeg.write_frames(a.out, size, fps=a.fps, codec="libx264", quality=None,
                                        output_params=["-crf", "14", "-preset", "medium"],
                                        pix_fmt_out="yuv420p", macro_block_size=8)
        w.send(None)
        it = frames(width=size[0], height=size[1], fps=a.fps, captions=not a.no_captions, ss=1 if a.draft else 2)
        for k, (t, img, L) in enumerate(it):
            w.send(np.ascontiguousarray(np.asarray(img.convert("RGB"))))
            if k % (a.fps * 5) == 0:
                print(f"  {t:5.1f} / {L:.1f} s", flush=True)
        w.close()
        print("wrote", a.out)


if __name__ == "__main__":
    main()
