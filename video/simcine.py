"""Cinematic re-render of a sim run for the demo video.

record: while a run plays (for example `python -m controller.run_all backup --offline --loop`), poll the
sim's /pose and the controller's /state at 30 Hz, then save the controller's recent events (the
spoken lines and handoff times).
render: replay the recording through MuJoCo with a detailed scene (steel instruments, a blue drape, a
gloved hand, three lights with shadows), a camera that follows the action, and the SIMULATION label,
the spoken line and the step strip burned in. 1920x1080, 30 fps, H.264.

  python -m video.simcine record --seconds 45 --out data/video/simcine/run
  python -m video.simcine render --input data/video/simcine/run --out data/video/out/sim-cinematic.mp4

Only the look changes: every arm pose, item position and spoken line comes from the recorded run.
"""
import argparse
import json
import math
import re
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCENES = ROOT / "sim" / "scenes"
STEPS = ["FIND", "PICK", "CHECK", "HAND", "WAIT", "RELEASE", "HOME"]
FONT_DIRS = [Path("C:/Windows/Fonts"), Path("/System/Library/Fonts/Supplemental"), Path("/Library/Fonts"),
             Path("/usr/share/fonts/truetype/dejavu")]


# ---- record -------------------------------------------------------------------------------------
def record(sim, ctl, seconds, out, fps=30, wait_reset=True):
    import httpx

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    frames, dt = [], 1.0 / fps
    with httpx.Client(timeout=2.0) as c:
        if wait_reset:  # start at the top of a run: the backup loop empties the tray count on reset
            print("waiting for the next tray reset ...")
            prev = None
            while True:
                out_items = c.get(f"{ctl}/state").json().get("out")
                if prev and not out_items:
                    break
                prev = out_items
                time.sleep(0.2)
        print(f"recording {seconds} s")
        end = time.time() + seconds
        while time.time() < end:
            t0 = time.time()
            try:
                p, s = c.get(f"{sim}/pose").json(), c.get(f"{ctl}/state").json()
            except Exception:
                time.sleep(dt)
                continue
            frames.append({"t": t0, "qpos": p["qpos"], "mocap": p["mocap"], "holding": p["holding"],
                           "step": s.get("step"), "item": s.get("item")})
            time.sleep(max(0.0, dt - (time.time() - t0)))
        events = c.get(f"{ctl}/events/recent", params={"n": 400}).json()
    (out / "frames.jsonl").write_text("\n".join(json.dumps(f) for f in frames), encoding="utf-8")
    (out / "events.json").write_text(json.dumps(events), encoding="utf-8")
    print(f"{len(frames)} frames, {len(events)} events -> {out}")


# ---- scene ----------------------------------------------------------------------------------------
def _ring(cx, cy, r, thick, mat, n=12):
    pts = [(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)) for k in range(n + 1)]
    return "".join(f'<geom type="capsule" fromto="{a[0]:.4f} {a[1]:.4f} 0 {b[0]:.4f} {b[1]:.4f} 0" size="{thick}" '
                   f'material="{mat}" contype="0" conaffinity="0"/>' for a, b in zip(pts, pts[1:]))


def _cap(a, b, size, mat):
    return (f'<geom type="capsule" fromto="{a[0]} {a[1]} {a[2]} {b[0]} {b[1]} {b[2]}" size="{size}" '
            f'material="{mat}" contype="0" conaffinity="0"/>')


def _box(pos, size, mat):
    return (f'<geom type="box" pos="{pos[0]} {pos[1]} {pos[2]}" size="{size[0]} {size[1]} {size[2]}" '
            f'material="{mat}" contype="0" conaffinity="0"/>')


ITEM_GEOMS = {
    # long axis along y, grasp point at the body origin (where the sim puts the gripper)
    "hemostat": (_ring(-0.009, -0.036, 0.0065, 0.0013, "steel") + _ring(0.009, -0.036, 0.0065, 0.0013, "steel")
                 + _cap((-0.007, -0.03, 0), (-0.0015, 0.008, 0), 0.0016, "steel")
                 + _cap((0.007, -0.03, 0), (0.0015, 0.008, 0), 0.0016, "steel")
                 + _box((0, 0.009, 0), (0.003, 0.003, 0.0018), "steel_dark")
                 + _cap((-0.0009, 0.011, 0), (-0.0005, 0.047, 0), 0.0013, "steel")
                 + _cap((0.0009, 0.011, 0), (0.0005, 0.047, 0), 0.0013, "steel")),
    "scalpel": (_box((0, -0.012, 0), (0.0045, 0.03, 0.0016), "steel_dark")
                + _box((0, -0.036, 0.0017), (0.0046, 0.004, 0.0002), "sharp_band")
                + _box((0, 0.026, 0), (0.0035, 0.009, 0.0003), "steel")
                + _box((0.0012, 0.036, 0), (0.0021, 0.003, 0.0003), "steel")),
    "mayo_scissors": (_ring(-0.011, -0.042, 0.0075, 0.0015, "steel") + _ring(0.011, -0.042, 0.0075, 0.0015, "steel")
                      + _cap((-0.009, -0.035, 0), (-0.0012, 0.0, 0), 0.0019, "steel")
                      + _cap((0.009, -0.035, 0), (0.0012, 0.0, 0), 0.0019, "steel")
                      + '<geom type="cylinder" size="0.0028 0.0022" material="steel_dark" contype="0" conaffinity="0"/>'
                      + _cap((-0.0012, 0.0, 0), (-0.0006, 0.052, 0), 0.0022, "steel")
                      + _cap((0.0012, 0.0, 0), (0.0006, 0.052, 0), 0.0022, "steel")),
}

HAND = ('<geom type="ellipsoid" size="0.034 0.04 0.011" material="glove" contype="0" conaffinity="0"/>'
        + "".join(_cap((-0.03, y, 0.002), (-0.068 + abs(y) * 0.5, y * 1.15, 0.008), 0.0075, "glove")
                  for y in (-0.024, -0.008, 0.008, 0.024))
        + _cap((-0.004, 0.034, 0), (-0.03, 0.056, 0.008), 0.0085, "glove")
        + _cap((0.032, 0, -0.004), (0.15, 0.0, -0.05), 0.017, "gown"))

VISUAL = """<visual>
  <headlight diffuse="0.12 0.12 0.12" ambient="0.16 0.16 0.17" specular="0.05 0.05 0.05"/>
  <global offwidth="1920" offheight="1080" fovy="36"/>
  <quality shadowsize="8192" offsamples="8"/>
  <map znear="0.01" zfar="20" shadowclip="1.2"/>
</visual>"""

ASSETS = """<asset>
  <texture name="cine_sky" type="skybox" builtin="gradient" rgb1="0.14 0.16 0.18" rgb2="0.02 0.02 0.03" width="512" height="512"/>
  <texture name="cine_floor" type="2d" builtin="checker" rgb1="0.17 0.18 0.19" rgb2="0.14 0.15 0.16" width="512" height="512"/>
  <material name="cine_floor_mat" texture="cine_floor" texrepeat="10 10" reflectance="0.12"/>
  <material name="table_mat" rgba="0.62 0.64 0.66 1" specular="0.4" shininess="0.5" reflectance="0.04"/>
  <material name="tray_mat" rgba="0.70 0.72 0.75 1" specular="0.9" shininess="0.85" reflectance="0.22"/>
  <material name="drape" rgba="0.22 0.42 0.64 1" specular="0.03" shininess="0.05"/>
  <material name="steel" rgba="0.82 0.84 0.88 1" specular="1" shininess="0.95" reflectance="0.35"/>
  <material name="steel_dark" rgba="0.56 0.58 0.62 1" specular="0.9" shininess="0.9" reflectance="0.25"/>
  <material name="sharp_band" rgba="0.80 0.12 0.09 1" specular="0.3"/>
  <material name="glove" rgba="0.38 0.58 0.93 1" specular="0.35" shininess="0.4"/>
  <material name="gown" rgba="0.30 0.47 0.52 1" specular="0.05"/>
</asset>"""

LIGHTS = """<light name="key" pos="0.75 -0.55 1.25" dir="-0.5 0.38 -1" castshadow="true" cutoff="50" exponent="6" diffuse="0.78 0.76 0.72" specular="0.35 0.35 0.35"/>
    <light name="fill" pos="-0.45 0.65 1.0" dir="0.45 -0.55 -1" castshadow="false" diffuse="0.24 0.26 0.30" specular="0 0 0"/>
    <light name="top" pos="0.25 0 1.6" dir="0 0 -1" directional="true" castshadow="true" diffuse="0.32 0.32 0.32" specular="0.1 0.1 0.1"/>"""


def cinematic_xml():
    from sim import scene

    src = Path(scene.build(scene.load_layout())).read_text(encoding="utf-8")
    src = re.sub(r"<visual>.*?</visual>", VISUAL, src, count=1, flags=re.S)
    src = re.sub(r"<asset>.*?</asset>", ASSETS, src, count=1, flags=re.S)
    src = re.sub(r"<light [^>]*/>", LIGHTS, src, count=1)
    src = re.sub(r'(<geom name="floor"[^>]*?)rgba="[^"]*"', r'\1material="cine_floor_mat"', src)
    m = re.search(r'<geom name="tray" type="box" size="([\d.]+) ([\d.]+) ([\d.]+)" pos="([\d.-]+) ([\d.-]+) ([\d.-]+)"', src)
    if m:
        hx, hy, hz, x, y, z = map(float, m.groups())
        rim = "".join(f'<geom type="box" pos="{px} {py} {z + hz + 0.004}" size="{sx} {sy} 0.004" material="tray_mat" '
                      f'contype="0" conaffinity="0"/>'
                      for px, py, sx, sy in ((x - hx, y, 0.0015, hy), (x + hx, y, 0.0015, hy),
                                             (x, y - hy, hx, 0.0015), (x, y + hy, hx, 0.0015)))
        drape = ('<geom name="drape" type="box" pos="0.25 0 -0.0002" size="0.19 0.29 0.0003" material="drape" '
                 'contype="0" conaffinity="0"/>')
        src = src.replace(m.group(0), drape + rim + m.group(0), 1)
    src = re.sub(r'(<geom name="slot\d"[^>]*?)rgba="[^"]*"', r'\1rgba="0.62 0.64 0.67 0.12"', src)
    for item, geoms in ITEM_GEOMS.items():
        src = re.sub(rf'(<body name="item_{item}"[^>]*>).*?(</body>)', lambda mm: mm.group(1) + geoms + mm.group(2),
                     src, count=1, flags=re.S)
    src = re.sub(r'(<body name="hand_zone"[^>]*>).*?(</body>)', lambda mm: mm.group(1) + HAND + mm.group(2),
                 src, count=1, flags=re.S)
    return src


def load_model():
    import mujoco

    path = SCENES / "_cinematic.xml"  # next to _arm.xml so the include resolves
    path.write_text(cinematic_xml(), encoding="utf-8")
    try:
        return mujoco.MjModel.from_xml_path(str(path))
    finally:
        path.unlink(missing_ok=True)


# ---- render ---------------------------------------------------------------------------------------
def _font(names, size):
    from PIL import ImageFont

    for d in FONT_DIRS:
        for n in names:
            if (d / n).exists():
                return ImageFont.truetype(str(d / n), size)
    return ImageFont.load_default()


def _step_index(step):
    s = (step or "").lower()
    for i, key in enumerate(("find", "pick", "check", "hand", "wait", "release", "home")):
        if key in s:
            return i
    if "carry" in s or "move" in s:
        return 3
    if "set" in s or "return" in s:
        return 1
    return None


def _shot(step, holding):
    s = (step or "").lower()
    if holding == "scalpel" and ("set" in s or "safe" in s or "hand" in s):
        return "top"
    if "pick" in s or "check" in s or "find" in s or "return" in s:
        return "close"
    if "hand" in s or "wait" in s or "release" in s:
        return "hand"
    return "wide"


def _overlay(img, cap, step_i, label, fonts):
    from PIL import ImageDraw

    d = ImageDraw.Draw(img, "RGBA")
    W, H = img.size
    bold, mono, big = fonts
    # top-left honesty tag, top-right brand
    tag = "SIMULATION  ·  MuJoCo replay of a recorded Scrub run"
    tw = d.textlength(tag, font=mono)
    d.rectangle([40, 36, 40 + tw + 28, 36 + 40], fill=(20, 19, 15, 215))
    d.text((54, 44), tag, font=mono, fill=(236, 232, 221, 255))
    d.text((W - 40 - d.textlength("SCRUB", font=bold), 30), "SCRUB", font=bold, fill=(236, 232, 221, 255))
    # step strip
    x, y, w, h, gap = 40, H - 70, 132, 34, 6
    for i, name in enumerate(STEPS):
        on = i == step_i
        d.rectangle([x, y, x + w, y + h], fill=(236, 232, 221, 235) if on else (20, 19, 15, 170),
                    outline=(236, 232, 221, 200))
        d.text((x + (w - d.textlength(name, font=mono)) / 2, y + 7), name, font=mono,
               fill=(20, 19, 15, 255) if on else (236, 232, 221, 220))
        x += w + gap
    if label:
        d.text((W - 40 - d.textlength(label, font=mono), H - 64), label, font=mono, fill=(236, 232, 221, 235))
    if cap:
        cw = d.textlength(cap, font=big)
        cx = (W - cw) / 2
        d.rectangle([cx - 24, H - 170, cx + cw + 24, H - 108], fill=(20, 19, 15, 200))
        d.text((cx, H - 162), cap, font=big, fill=(255, 255, 255, 255))
    return img


def render(inp, out, fps=30, width=1920, height=1080, max_s=None, cut_idle=True):
    import imageio_ffmpeg
    import mujoco
    from PIL import Image

    inp = Path(inp)
    frames = [json.loads(line) for line in (inp / "frames.jsonl").read_text(encoding="utf-8").splitlines() if line]
    events = json.loads((inp / "events.json").read_text(encoding="utf-8"))
    t0, t1 = frames[0]["t"], frames[-1]["t"]
    if max_s:
        t1 = min(t1, t0 + max_s)
    says = [(e["t"], e["say"]) for e in events if e.get("say") and t0 - 1 <= e["t"] <= t1]
    hands = [(e["t"], e.get("item"), e.get("request_to_hand_s")) for e in events
             if e.get("type") == "handed" and e.get("request_to_hand_s")]

    model = load_model()
    data = mujoco.MjData(model)
    renderer = mujoco.Renderer(model, height=height, width=width)
    opt = mujoco.MjvOption()
    cam = mujoco.MjvCamera()
    cam.type = mujoco.mjtCamera.mjCAMERA_FREE
    site = model.site("gripperframe").id
    mocap_ids = {model.body(i).name: model.body_mocapid[i] for i in range(model.nbody) if model.body_mocapid[i] >= 0}
    fonts = (_font(["arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"], 44),
             _font(["consola.ttf", "Menlo.ttc", "DejaVuSansMono.ttf"], 20),
             _font(["seguisb.ttf", "arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"], 40))

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    writer = imageio_ffmpeg.write_frames(str(out), (width, height), fps=fps, codec="libx264", quality=8,
                                         pix_fmt_out="yuv420p", macro_block_size=8)
    writer.send(None)
    look = np.array([0.22, 0.0, 0.06])
    dist, az, el = 0.82, 60.0, -26.0
    times, idle_since, t = [], None, t0
    fi = 0
    while t < t1:
        while fi + 1 < len(frames) and frames[fi + 1]["t"] <= t:
            fi += 1
        if frames[fi]["step"] == "idle" and not frames[fi]["holding"]:
            idle_since = t if idle_since is None else idle_since
            if cut_idle and t - idle_since > 1.0:
                t += 1 / fps
                continue
        else:
            idle_since = None
        times.append(t)
        t += 1 / fps
    j, n = 0, len(times)
    for k, t in enumerate(times):
        while j + 1 < len(frames) and frames[j + 1]["t"] <= t:
            j += 1
        a = frames[j]
        b = frames[min(j + 1, len(frames) - 1)]
        u = 0.0 if b["t"] == a["t"] else min(1.0, max(0.0, (t - a["t"]) / (b["t"] - a["t"])))
        data.qpos[:6] = (1 - u) * np.array(a["qpos"]) + u * np.array(b["qpos"])
        for name, pose in a["mocap"].items():
            mid = mocap_ids.get(name)
            if mid is None:
                continue
            pb = b["mocap"].get(name, pose)
            data.mocap_pos[mid] = (1 - u) * np.array(pose[:3]) + u * np.array(pb[:3])
            data.mocap_quat[mid] = pose[3:7]
        mujoco.mj_forward(model, data)
        tip = data.site_xpos[site].copy()

        shot = _shot(a["step"], a["holding"])
        hand = np.array(a["mocap"].get("hand_zone", [0.28, -0.14, 0.14])[:3])
        drift = math.sin(2 * math.pi * k / fps / 30.0)
        if shot == "close":
            goal, gd, ga, ge = 0.6 * tip + 0.4 * np.array([0.24, 0.0, 0.0]), 0.52, 50 + 12 * drift, -40
        elif shot == "hand":
            goal, gd, ga, ge = 0.5 * tip + 0.5 * hand, 0.58, 72 + 10 * drift, -20
        elif shot == "top":
            goal, gd, ga, ge = 0.5 * tip + 0.5 * np.array([0.2, -0.1, 0.0]), 0.72, 90, -70
        else:
            goal, gd, ga, ge = 0.4 * tip + 0.6 * np.array([0.22, 0.0, 0.08]), 0.82, 60 + 15 * drift, -26
        s = 0.06  # dolly smoothing per frame
        look += s * (goal - look)
        dist += s * (gd - dist)
        az += s * (ga - az)
        el += s * (ge - el)
        cam.lookat[:], cam.distance, cam.azimuth, cam.elevation = look, dist, az, el
        renderer.update_scene(data, camera=cam, scene_option=opt)
        img = Image.fromarray(renderer.render())

        cap = next((line for ts, line in reversed(says) if ts <= t < ts + 3.2), None)
        last = next(((it, s_) for ts, it, s_ in reversed(hands) if ts <= t < ts + 4.0), None)
        label = f"{last[0].replace('_', ' ').upper()}  ·  request to hand {last[1]:.1f} s (sim)" if last else ""
        img = _overlay(img, cap, _step_index(a["step"]), label, fonts)
        writer.send(np.ascontiguousarray(np.asarray(img.convert("RGB"))))
        if k % (fps * 5) == 0:
            print(f"  {k / fps:5.1f} / {n / fps:.1f} s")
    writer.close()
    renderer.close()
    print(f"wrote {out} ({n / fps:.1f} s)")


def still(out, az=150.0, el=-26.0, dist=0.8):
    """One frame of the detailed scene at home, to check the look quickly."""
    import mujoco
    from PIL import Image

    model = load_model()
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    r = mujoco.Renderer(model, height=1080, width=1920)
    cam = mujoco.MjvCamera()
    cam.type = mujoco.mjtCamera.mjCAMERA_FREE
    cam.lookat[:], cam.distance, cam.azimuth, cam.elevation = [0.22, 0.0, 0.05], dist, az, el
    r.update_scene(data, camera=cam)
    Image.fromarray(r.render()).save(out)
    print(out)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record", help="record a live sim run (sim /pose + controller /state + events)")
    rec.add_argument("--sim", default="http://localhost:8002")
    rec.add_argument("--controller", default="http://localhost:8000")
    rec.add_argument("--seconds", type=float, default=45)
    rec.add_argument("--out", default="data/video/simcine/run")
    rec.add_argument("--now", action="store_true", help="start now instead of at the next tray reset")
    ren = sub.add_parser("render", help="re-render a recording at 1080p with the detailed scene")
    ren.add_argument("--input", default="data/video/simcine/run")
    ren.add_argument("--out", default="data/video/out/sim-cinematic.mp4")
    ren.add_argument("--max-s", type=float)
    ren.add_argument("--keep-idle", action="store_true", help="keep idle stretches (default cuts each to 1 s)")
    st = sub.add_parser("still", help="one frame of the detailed scene")
    st.add_argument("--out", default="data/video/simcine/still.png")
    st.add_argument("--az", type=float, default=150.0)
    st.add_argument("--el", type=float, default=-26.0)
    st.add_argument("--dist", type=float, default=0.8)
    a = p.parse_args()
    if a.cmd == "record":
        record(a.sim, a.controller, a.seconds, a.out, wait_reset=not a.now)
    elif a.cmd == "render":
        render(a.input, a.out, max_s=a.max_s, cut_idle=not a.keep_idle)
    else:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        still(a.out, a.az, a.el, a.dist)


if __name__ == "__main__":
    main()
