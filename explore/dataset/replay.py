"""Replay recorded LeRobot (v3, or v2.x) SO-101 demos through the MuJoCo sim next to the real videos.

    .venv/bin/python explore/dataset/replay.py --root <ds> --episode 0 [--port 8095]
    .venv/bin/python explore/dataset/replay.py --root <ds> --check

Mapping used for the sim: joints 1-5 degrees -> radians directly (the so101_new_calib MJCF
shares LeRobot's zero), gripper 0..100 -> jaw joint range (0 closed, 100 open).
Tip xyz shown/checked comes from arm/kinematics.py (rig.json signs/offsets) and, for
comparison, from the MuJoCo gripperframe site.
"""
import argparse
import json
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from explore.dataset import lerobot_meta  # noqa: E402
NAMES = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
HTML = Path(__file__).with_name("replay.html")
# fixed sim camera approximating the real side camera (tune with --cam az,el,dist,lx,ly,lz)
CAM = dict(azimuth=90.0, elevation=-12.0, distance=0.65, lookat=(0.10, 0.0, 0.15))


# ---- dataset ----------------------------------------------------------------
class Dataset:
    def __init__(self, root):
        self.root = Path(root)
        self.info = json.loads((self.root / "meta/info.json").read_text())
        self.fps = self.info["fps"]
        if lerobot_meta.is_v2(self.root):  # LeRobot v2.x: episodes.jsonl, one data/video file per episode
            eps = [lerobot_meta.v2_episodes_df(self.root, self.info)]
        else:
            eps = [pd.read_parquet(f) for f in sorted((self.root / "meta/episodes").glob("chunk-*/file-*.parquet"))]
        self.eps = pd.concat(eps).sort_values("episode_index").set_index("episode_index", drop=False)
        self._data = {}

    def episodes(self):
        return [int(i) for i in self.eps.index]

    def _data_path(self, c, f):
        tpl = self.info["data_path"]
        if "{episode_index" in tpl:  # v2: file index is the episode index
            return self.root / tpl.format(episode_chunk=c, episode_index=f)
        return self.root / tpl.format(chunk_index=c, file_index=f)

    def _file(self, c, f):
        key = (c, f)
        if key not in self._data:
            p = self._data_path(c, f)
            self._data[key] = pd.read_parquet(p, columns=["observation.state", "action", "episode_index", "frame_index"])
        return self._data[key]

    def states(self, ep):
        r = self.eps.loc[ep]
        d = self._file(int(r["data/chunk_index"]), int(r["data/file_index"]))
        d = d[d.episode_index == ep].sort_values("frame_index")
        return np.stack(d["observation.state"].values).astype(float), np.stack(d["action"].values).astype(float)

    def task(self, ep):
        t = self.eps.loc[ep]["tasks"]
        return str(t[0]) if len(t) else ""

    def frames(self, ep, cam, size=(480, 360)):
        """Decode this episode's video segment -> list of JPEG bytes."""
        import av
        k = f"observation.images.{cam}"
        r = self.eps.loc[ep]
        p = lerobot_meta.video_file(self.root, self.info, k, r)
        t0 = float(r[f"videos/{k}/from_timestamp"])
        n = int(r["length"])
        out = []
        with av.open(str(p)) as c:
            s = c.streams.video[0]
            for fr in c.decode(s):
                if fr.time is not None and fr.time < t0 - 0.5 / self.fps:
                    continue
                img = fr.to_ndarray(format="bgr24")
                if size:
                    img = cv2.resize(img, size, interpolation=cv2.INTER_AREA)
                out.append(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes())
                if len(out) >= n:
                    break
        return out


# ---- kinematics / sim -------------------------------------------------------
def clamp_deg(kin, s):
    """Joint degrees clamped into the URDF limits (via rig signs/offsets), plus per-joint overshoot in degrees."""
    q = np.rad2deg(kin.to_urdf(s[:5]))
    lo, hi = np.rad2deg(kin.lower), np.rad2deg(kin.upper)
    over = np.where(q < lo, q - lo, np.where(q > hi, q - hi, 0.0))
    return kin.from_urdf(np.deg2rad(np.clip(q, lo, hi))), over


def kin_tip(kin, s):
    """(tip xyz m from arm/kinematics.py forward(), in_limits). Out-of-limit states are clamped to the limits first."""
    ok = kin.valid(s[:5])
    return kin.forward(s[:5] if ok else clamp_deg(kin, s)[0]), ok


class Sim:
    def __init__(self, size=(480, 360), cam=None):
        import mujoco
        from sim import scene
        self.mj = mujoco
        tmp = Path(tempfile.mkdtemp(prefix="replay_scene_"))
        scene.SCENES = tmp  # do not touch sim/scenes
        path = scene.build()
        arm = tmp / "_arm.xml"
        arm.write_text(arm.read_text().replace("../models/so101/assets", str(scene.HERE / "models/so101/assets")))
        self.m = mujoco.MjModel.from_xml_path(str(path))
        self.d = mujoco.MjData(self.m)
        self.site = self.m.site("gripperframe").id
        self.lo, self.hi = self.m.jnt_range[5]
        self.size = size
        self.r = mujoco.Renderer(self.m, height=size[1], width=size[0])
        self.cam = mujoco.MjvCamera()
        c = {**CAM, **(cam or {})}
        self.cam.azimuth, self.cam.elevation, self.cam.distance = c["azimuth"], c["elevation"], c["distance"]
        self.cam.lookat[:] = c["lookat"]
        self.opt = mujoco.MjvOption()

    def qpos(self, s):
        q = np.zeros(6)
        q[:5] = np.deg2rad(s[:5])
        q[5] = self.lo + np.clip(s[5], 0, 100) / 100.0 * (self.hi - self.lo)
        return q

    def tip(self, s):
        self.d.qpos[:6] = self.qpos(s)
        self.mj.mj_kinematics(self.m, self.d)
        return self.d.site_xpos[self.site].copy()

    def render(self, s):
        self.d.qpos[:6] = self.qpos(s)
        self.mj.mj_forward(self.m, self.d)
        self.r.update_scene(self.d, self.cam, self.opt)
        rgb = self.r.render()
        return cv2.imencode(".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 88])[1].tobytes()


# ---- --check ----------------------------------------------------------------
def check(ds):
    from arm.kinematics import Kinematics
    kin = Kinematics()
    sim = Sim(size=(64, 48))
    print(f"signs={kin.signs.tolist()} offsets_deg={kin.offsets.tolist()} fps={ds.fps}")
    print("urdf limits deg lo:", np.round(np.rad2deg(kin.lower), 1).tolist(), "hi:", np.round(np.rad2deg(kin.upper), 1).tolist())
    rows = []
    for ep in ds.episodes():
        S, _ = ds.states(ep)
        bad = np.array([not kin.valid(s[:5]) for s in S])
        per_joint = [int(np.sum((np.deg2rad(S[:, j] * kin.signs[j] + kin.offsets[j]) < kin.lower[j] - 1e-8) |
                                (np.deg2rad(S[:, j] * kin.signs[j] + kin.offsets[j]) > kin.upper[j] + 1e-8))) for j in range(5)]
        ov = np.array([clamp_deg(kin, s)[1] for s in S])
        kt = np.array([kin_tip(kin, s)[0] for s in S])  # clamped into limits where outside
        st = np.array([sim.tip(s) for s in S])
        print(f"\nepisode {ep}  frames={len(S)}  task={ds.task(ep)!r}")
        print(f"  state min {np.round(S.min(0), 1).tolist()}")
        print(f"  state max {np.round(S.max(0), 1).tolist()}")
        print(f"  outside URDF limits: {int(bad.sum())}/{len(S)} frames, per joint {per_joint}; max overshoot deg {np.round(ov[np.abs(ov).argmax(0), range(5)], 1).tolist()}")
        print("  kinematics tip m (clamped) min", np.round(kt.min(0), 3).tolist(), "max", np.round(kt.max(0), 3).tolist(),
              f" z<0: {int((kt[:, 2] < 0).sum())}")
        print("  sim tip m                  min", np.round(st.min(0), 3).tolist(), "max", np.round(st.max(0), 3).tolist(),
              f" z<0: {int((st[:, 2] < 0).sum())}")
        dist = np.linalg.norm(kt - st, axis=1)
        print(f"  kinematics vs sim tip distance: in-limit frames max {dist[~bad].max() if (~bad).any() else float('nan'):.4f} m, all frames max {dist.max():.3f} m")
        rows.append((ep, len(S), int(bad.sum()), int((kt[:, 2] < 0).sum()), int((st[:, 2] < 0).sum())))
    print("\nsummary: episode frames outside_limits kin_z<0 sim_z<0")
    for r in rows:
        print("  ", *r)
    print("sim tip z<0 or kinematics outside_limits>0 means a sign/offset/unit mismatch (the sim uses raw degrees->radians).")


# ---- server -----------------------------------------------------------------
def serve(ds, ep, port, cam):
    import uvicorn
    from fastapi import FastAPI, HTTPException, Response
    from fastapi.responses import HTMLResponse
    from arm.kinematics import Kinematics

    kin = Kinematics()
    S, A = ds.states(ep)
    ex = ThreadPoolExecutor(1)  # all GL work on one thread
    sim = ex.submit(Sim, (480, 360), cam).result()
    vid = {}
    print("decoding videos...", flush=True)
    for c in ("side", "wrist"):
        try:
            vid[c] = ds.frames(ep, c)
        except Exception as e:  # noqa: BLE001
            print(f"video {c} unavailable: {e}")
            vid[c] = []
    print("ready", flush=True)
    n = len(S)
    app = FastAPI()
    cache = {}
    lock = threading.Lock()

    def idx(i):
        if not 0 <= i < n:
            raise HTTPException(404, "frame out of range")
        return i

    @app.get("/", response_class=HTMLResponse)
    def index():
        return HTML.read_text()

    @app.get("/api/meta")
    def meta():
        return {"episode": ep, "episodes": ds.episodes(), "frames": n, "fps": ds.fps, "task": ds.task(ep), "names": NAMES,
                "video_frames": {k: len(v) for k, v in vid.items()}}

    @app.get("/api/state/{i}")
    def state(i: int):
        s = S[idx(i)]
        t, ok = kin_tip(kin, s)
        over = clamp_deg(kin, s)[1]
        st = ex.submit(sim.tip, s).result()
        return {"i": i, "t": i / ds.fps, "state": s.tolist(), "action": A[i].tolist(),
                "in_limits": ok, "overshoot_deg": over.tolist(), "tip": t.tolist(), "sim_tip": st.tolist()}

    @app.get("/sim/{i}.jpg")
    def sim_frame(i: int):
        s = S[idx(i)]
        with lock:
            if i not in cache:
                cache[i] = ex.submit(sim.render, s).result()
        return Response(cache[i], media_type="image/jpeg")

    @app.get("/video/{cam}/{i}.jpg")
    def video(cam: str, i: int):
        f = vid.get(cam)
        if not f or not 0 <= i < len(f):
            raise HTTPException(404, "no frame")
        return Response(f[i], media_type="image/jpeg")

    print(f"http://127.0.0.1:{port}  episode {ep} ({n} frames)", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--episode", type=int, default=0)
    ap.add_argument("--port", type=int, default=8095)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--cam", help="azimuth,elevation,distance,lx,ly,lz for the sim camera")
    a = ap.parse_args()
    ds = Dataset(a.root)
    cam = None
    if a.cam:
        v = [float(x) for x in a.cam.split(",")]
        cam = dict(azimuth=v[0], elevation=v[1], distance=v[2], lookat=tuple(v[3:6]))
    if a.check:
        check(ds)
    else:
        if a.episode not in ds.episodes():
            sys.exit(f"episode {a.episode} not in {ds.episodes()}")
        serve(ds, a.episode, a.port, cam)


if __name__ == "__main__":
    main()
