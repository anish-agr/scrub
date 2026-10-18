"""Read-only SO-101 replay. Never infer object attachment or successful grasps."""
from __future__ import annotations

import copy
import json
import threading
import uuid
from pathlib import Path

import cv2
import numpy as np

from .common import REPO, encode, finite, read_json, save_provenance, stamp

_SCENE_LOCK = threading.Lock()


def load_joints(path, episode=0):
    path = Path(path)
    if path.is_file():
        doc = read_json(path)
        if doc.get("units") != "degrees_gripper_0_100":
            raise ValueError("Joint logs require explicit degrees_gripper_0_100 units")
        states = np.asarray(doc["states"], dtype=float)
        fps = finite(doc["fps"], "joint FPS", True)
    else:
        # Reuse the v3 reader's feature ordering. It never opens a motor bus.
        from explore.dataset.replay import Dataset
        ds = Dataset(path)
        states, _actions = ds.states(episode)
        fps = finite(ds.fps, "dataset FPS", True)
        doc = {"kind": "reconstructed", "synthetic": False, "instruction": ds.task(episode)}
    if states.ndim != 2 or states.shape[1] != 6 or not len(states) or not np.isfinite(states).all():
        raise ValueError("Need finite recorded six-joint states; no interpolation or IK substitution")
    if np.any((states[:, 5] < 0) | (states[:, 5] > 100)):
        raise ValueError("Gripper is not raw 0..100")
    return states, fps, doc


class JointRenderer:
    def __init__(self, ws, width, height):
        import mujoco
        from sim import scene
        self.mj = mujoco
        self.folder = ws.out("work/scene-" + uuid.uuid4().hex + "/placeholder").parent
        if not scene.ARM_SRC.is_file():
            raise RuntimeError("SO-101 model missing; run python -m sim.fetch_model before reconstruction")
        # Reuse scene builder without modifying a single sim/ file or global after return.
        with _SCENE_LOCK:
            previous = scene.SCENES
            try:
                scene.SCENES = self.folder
                path = scene.build(copy.deepcopy(scene.load_layout()))
            finally:
                scene.SCENES = previous
        arm = self.folder / "_arm.xml"
        arm.write_text(arm.read_text().replace("../models/so101/assets", (scene.HERE / "models/so101/assets").resolve().as_posix()))
        self.model = mujoco.MjModel.from_xml_path(str(path))
        self.model.vis.global_.offwidth = max(width, self.model.vis.global_.offwidth)
        self.model.vis.global_.offheight = max(height, self.model.vis.global_.offheight)
        self.data = mujoco.MjData(self.model)
        self.renderer = mujoco.Renderer(self.model, height=height, width=width)
        self.camera = mujoco.MjvCamera()
        self.camera.lookat[:] = [.20, 0, 0]
        self.camera.azimuth, self.camera.elevation, self.camera.distance = 90, -90, .85
        self.camera.orthographic = 1
        # Map by names, never assume a different MJCF's first six qpos entries.
        names = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
        joints = [self.model.joint(name) for name in names]
        self.addresses = [int(j.qposadr[0]) for j in joints]
        self.lo, self.hi = joints[-1].range
        self.layout = scene.load_layout()

    def image(self, state, arm_only=False):
        values = np.r_[np.deg2rad(state[:5]), self.lo + state[5]/100*(self.hi-self.lo)]
        for address, value in zip(self.addresses, values):
            self.data.qpos[address] = value
        self.mj.mj_forward(self.model, self.data)
        self.renderer.update_scene(self.data, self.camera)
        if arm_only:
            # Segmentation identifies robot bodies, not invented tool attachment.
            self.renderer.enable_segmentation_rendering()
            segment = self.renderer.render().copy()
            self.renderer.disable_segmentation_rendering()
            body_names = [self.mj.mj_id2name(self.model, self.mj.mjtObj.mjOBJ_BODY, i) or "" for i in range(self.model.nbody)]
            robot_ids = {i for i, name in enumerate(body_names) if name and not name.startswith("item_") and name != "hand_zone" and i != 0}
            geom_ids = [i for i, body in enumerate(self.model.geom_bodyid) if int(body) in robot_ids]
            mask = np.isin(segment[:, :, 0], geom_ids) & (segment[:, :, 1] == int(self.mj.mjtObj.mjOBJ_GEOM))
        rgb = self.renderer.render().copy()
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), mask if arm_only else None

    def close(self):
        self.renderer.close()


def render_joints(ws, source, output, width=960, height=720, episode=0, plate=None, start_time=None):
    states, fps, doc = load_joints(source, episode)
    renderer = JointRenderer(ws, width, height)
    meta = {"kind": "reconstructed", "synthetic": bool(doc.get("synthetic")),
            "note": "Joint positions replayed exactly; instrument poses static/illustrative, no contact/outcome inferred."}
    background = cv2.imread(str(plate)) if plate else None
    if plate and background is None:
        raise ValueError("Cannot read photo plate")
    # A plane warp of the tray alone is not a calibrated arm-base/world plate.
    # Require a documented matching full-scene projection before compositing.
    if background is not None and background.shape[:2] != (height, width):
        raise ValueError("Plate must match the orthographic world projection; supply calibrated width/height")
    def images():
        try:
            for state in states:
                image, mask = renderer.image(state, arm_only=background is not None)
                if background is not None:
                    image = np.where(mask[..., None], image, background)
                image = stamp(image, meta)
                yield image
        finally:
            renderer.close()
    details = encode(ws, output, images(), fps)
    return save_provenance(output, kind="reconstructed", synthetic=meta["synthetic"], **details,
        joint_source=str(Path(source).resolve()), episode=episode,
        start_time=start_time if start_time is not None else doc.get("start_time"),
        objects="Static slot illustration only; joint data cannot establish grasps, releases or tool motion.",
        operations=[{"command": "topdown reconstruction", "joint_units": "degrees_gripper_0_100", "orthographic": True}])
