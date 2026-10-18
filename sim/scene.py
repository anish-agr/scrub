"""Build the MuJoCo scene from layout.json: sim/scenes/scrub_scene.xml (+ a patched arm file)."""
import json
import re
from pathlib import Path

import mujoco
import numpy as np

HERE = Path(__file__).parent
LAYOUT = HERE / "layout.json"
SCENES = HERE / "scenes"
ARM_SRC = HERE / "models" / "so101" / "so101_new_calib_camera.xml"

# item id -> (list of geom xml, rgba). Long axis along y, lying on the table (yaw 0).
ITEMS = {
    "hemostat": (['type="capsule" fromto="0 -0.035 0 0 0.035 0" size="0.006"'], "0.75 0.75 0.8 1"),
    "scalpel": (['type="box" size="0.004 0.035 0.003"'], "0.9 0.2 0.2 1"),
    "mayo_scissors": (['type="capsule" fromto="0 -0.045 0 0 0.045 0" size="0.007"'], "0.6 0.65 0.7 1"),
    "mouth_mirror": (['type="capsule" fromto="0 -0.04 0 0 0.04 0" size="0.004"'], "0.5 0.8 0.9 1"),
    "explorer": (['type="capsule" fromto="0 -0.04 0 0 0.04 0" size="0.003"'], "0.8 0.7 0.3 1"),
    "cotton_pliers": (['type="capsule" fromto="0 -0.04 0 0 0.04 0" size="0.005"'], "0.7 0.5 0.8 1"),
    # bench tools: two handles that splay apart, a narrow nose or a head
    "needle_nose_pliers": ([
        'type="capsule" fromto="-0.012 -0.055 0 -0.004 -0.005 0" size="0.005"',
        'type="capsule" fromto="0.012 -0.055 0 0.004 -0.005 0" size="0.005"',
        'type="capsule" fromto="0 -0.005 0 0 0.055 0" size="0.0035"'], "0.9 0.5 0.1 1"),
    "wire_cutters": ([
        'type="capsule" fromto="-0.014 -0.05 0 -0.005 -0.005 0" size="0.0055"',
        'type="capsule" fromto="0.014 -0.05 0 0.005 -0.005 0" size="0.0055"',
        'type="box" pos="0 0.012 0" size="0.009 0.014 0.005"'], "0.2 0.6 0.3 1"),
    "hex_key": ([
        'type="capsule" fromto="0 -0.03 0 0 0.03 0" size="0.0025"',
        'type="capsule" fromto="0 -0.03 0 0.02 -0.03 0" size="0.0025"'], "0.3 0.3 0.35 1"),
    "screwdriver": ([
        'type="capsule" fromto="0 -0.06 0 0 -0.015 0" size="0.009"',
        'type="capsule" fromto="0 -0.015 0 0 0.055 0" size="0.0025"'], "0.85 0.15 0.15 1"),
}
PARK = (0.0, 0.0, -1.0)  # items of other settings wait out of sight


def load_layout():
    return json.loads(LAYOUT.read_text())


def _wrist_cam_quat():
    """Local quat that makes the wrist camera look along the finger direction."""
    m = mujoco.MjModel.from_xml_path(str(ARM_SRC))
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    rb = d.xmat[m.body("wrist_camera").id].reshape(3, 3)
    g = d.site_xmat[m.site("gripperframe").id].reshape(3, 3)
    zc, yc = -g[:, 0], g[:, 2]
    rc = np.column_stack([np.cross(yc, zc), yc, zc])
    quat = np.zeros(4)
    mujoco.mju_mat2Quat(quat, (rb.T @ rc).ravel())
    # sit just behind and beside the jaws so the camera sees past them
    p = d.site_xpos[m.site("gripperframe").id] - 0.06 * g[:, 0] + 0.03 * g[:, 2]
    return quat, rb.T @ (p - d.xpos[m.body("wrist_camera").id])


def _patched_arm():
    """Copy of the camera model with an absolute meshdir and a <camera> on the wrist."""
    s = ARM_SRC.read_text().replace('meshdir="assets"', 'meshdir="../models/so101/assets"')
    quat, pos = _wrist_cam_quat()
    q, p = (" ".join(f"{v:.6f}" for v in a) for a in (quat, pos))
    cam = f'<camera name="wrist" pos="{p}" quat="{q}" fovy="75"/>'
    return re.sub(r'(<body name="wrist_camera"[^>]*>)', r"\1" + cam, s, count=1)


def tray_slot(layout, item):
    """The (x, y) tray slot of an item in the active setting, or None."""
    items = layout.get("setting_items", {}).get(layout.get("setting", "surgical"), [])
    if item in items:
        return layout["slots"][items.index(item)]
    for s_name, s_items in layout.get("setting_items", {}).items():
        if item in s_items:
            return layout["slots"][s_items.index(item)]
    return None


def slot_position(layout, item):
    """Where the item is meant to be picked from: its tray slot, unless a test bench moved it
    (layout["_item_xy"], set by SimArm.set_item_pose, never written to layout.json)."""
    moved = layout.get("_item_xy", {}).get(item)
    return list(moved) if moved else tray_slot(layout, item)


def item_start(layout, item):
    xy = tray_slot(layout, item)
    return (xy[0], xy[1], 0.01) if xy else PARK


def build(layout=None):
    """Write the scene files and return the path of scrub_scene.xml."""
    L = layout or load_layout()
    SCENES.mkdir(exist_ok=True)
    (SCENES / "_arm.xml").write_text(_patched_arm())
    tx, ty = L["table"]["center"]
    sx, sy = L["table"]["size"]
    cx, cy = L["tray"]["center"]
    tw, th = L["tray"]["size"]
    oc = L["overhead_cam"]
    bodies = []
    for item, (geoms, rgba) in ITEMS.items():
        x, y, z = item_start(L, item)
        g = "".join(f'<geom {geom} rgba="{rgba}" contype="0" conaffinity="0"/>' for geom in geoms)
        bodies.append(f'    <body name="item_{item}" mocap="true" pos="{x} {y} {z}">{g}</body>')
    marks = [("return_spot", L["return_spot"], "0.2 0.5 0.9 0.6"), ("safe_spot", L["safe_spot"], "0.9 0.2 0.2 0.6")]
    marks_xml = "\n".join(
        f'    <geom name="{n}" type="cylinder" size="0.04 0.0005" pos="{p[0]} {p[1]} 0.0006" rgba="{c}" contype="0" conaffinity="0"/>'
        for n, p, c in marks)
    slots_xml = "\n".join(
        f'    <geom name="slot{i}" type="box" size="0.035 0.035 0.0005" pos="{p[0]} {p[1]} 0.0066" rgba="0.15 0.15 0.15 1" contype="0" conaffinity="0"/>'
        for i, p in enumerate(L["slots"]))
    hx, hy, hz = L["hand_zone"]
    xml = f"""<mujoco model="scrub_scene">
  <include file="_arm.xml"/>
  <visual>
    <headlight diffuse="0.4 0.4 0.4" ambient="0.3 0.3 0.3" specular="0 0 0"/>
    <global offwidth="1280" offheight="960"/>
  </visual>
  <asset>
    <texture type="skybox" builtin="gradient" rgb1="0.6 0.7 0.8" rgb2="0.1 0.1 0.15" width="256" height="256"/>
    <material name="table_mat" rgba="0.55 0.57 0.55 1"/>
    <material name="tray_mat" rgba="0.55 0.58 0.62 1"/>
  </asset>
  <worldbody>
    <light pos="0.2 0 2" dir="0 0 -1" directional="true" diffuse="0.35 0.35 0.35"/>
    <geom name="floor" type="plane" size="2 2 0.05" pos="0 0 -0.75" rgba="0.25 0.28 0.3 1"/>
    <geom name="table" type="box" size="{sx / 2} {sy / 2} 0.01" pos="{tx} {ty} -0.0105" material="table_mat"/>
    <geom name="tray" type="box" size="{tw / 2} {th / 2} 0.003" pos="{cx} {cy} 0.003" material="tray_mat"/>
{slots_xml}
{marks_xml}
    <body name="hand_zone" mocap="true" pos="{hx} {hy} {hz}">
      <geom type="box" size="0.04 0.05 0.015" rgba="0.95 0.75 0.6 0.55" contype="0" conaffinity="0"/>
    </body>
{chr(10).join(bodies)}
    <camera name="overhead" pos="{oc['pos'][0]} {oc['pos'][1]} {oc['pos'][2]}" xyaxes="0 -1 0 1 0 0" fovy="{oc['fovy']}"/>
  </worldbody>
</mujoco>
"""
    path = SCENES / "scrub_scene.xml"
    path.write_text(xml)
    return path


if __name__ == "__main__":
    print(build())
