"""Deterministic fixtures, not demonstration or performance evidence."""
from __future__ import annotations

import json
import cv2
import numpy as np

from .common import encode, save_provenance, stamp, write_json


def demo_assets(ws, seconds=6):
    for folder in ("raw", "photos"):
        (ws.root / folder).mkdir(exist_ok=True)
    if (ws.root / "raw/demo.mp4").exists():
        raise ValueError("Demo fixture exists; use a fresh --root under data/video/")
    rng = np.random.default_rng(2026)
    plate = np.full((360, 600, 3), (216, 222, 225), np.uint8)
    # Natural-looking fine tray texture, no fiducials or corner markers.
    noise = rng.normal(0, 16, plate.shape[:2]).astype(np.int16)
    plate = np.clip(plate.astype(np.int16) + noise[..., None], 0, 255).astype(np.uint8)
    for _ in range(400):
        x, y = rng.integers([4, 4], [596, 356])
        cv2.circle(plate, (int(x), int(y)), 1, (170, 175, 180), -1)
    for _ in range(140):
        x,y = rng.integers([12,12], [588,348])
        dx,dy = rng.integers(-9,10,2)
        shade = int(rng.integers(130,210))
        cv2.line(plate, (int(x),int(y)), (int(x+dx),int(y+dy)), (shade,shade,shade), 2)
    for x in (150, 300, 450):
        cv2.line(plate, (x, 115), (x, 245), (85, 90, 95), 9)
        cv2.circle(plate, (x-12, 245), 11, (95, 100, 105), 3)
        cv2.circle(plate, (x+12, 245), 11, (95, 100, 105), 3)
    source = np.float32([[0, 0], [599, 0], [599, 359], [0, 359]])
    quad = np.float32([[90, 95], [552, 110], [580, 390], [55, 375]])
    transform = cv2.getPerspectiveTransform(source, quad)
    background = np.full((480, 640, 3), (155, 70, 15), np.uint8)
    mask = cv2.warpPerspective(np.full(plate.shape[:2], 255, np.uint8), transform, (640, 480))
    view = cv2.warpPerspective(plate, transform, (640, 480))
    background[mask > 0] = view[mask > 0]
    for i in range(8):
        shift = np.float32([[1, 0, (i-3)*1.2], [0, 1, (i%3-1)*1.0]])
        photo = cv2.warpAffine(background, shift, (640, 480), borderMode=cv2.BORDER_REFLECT)
        name = ws.root / "photos" / f"demo-{i:02d}.png"
        cv2.imwrite(str(name), stamp(photo, {"kind":"simulation", "synthetic":True}))
        save_provenance(name, kind="simulation", synthetic=True)
    meta = {"kind": "simulation", "synthetic": True}
    def sequence():
        for n in range(round(seconds * 30)):
            image = background.copy()
            # Fixture motion only; distinct from the actual SO-101 sim roll below.
            cv2.line(image, (320, 470), (int(300 + 70*np.sin(n/35)), 290), (55, 65, 80), 22)
            yield stamp(image, meta)
    path = ws.root / "raw/demo.mp4"
    details = encode(ws, path, sequence())
    save_provenance(path, kind="simulation", synthetic=True, start_time=1792285200.0, **details)
    n = round(seconds * 30)
    states = np.zeros((n, 6))
    states[:, 0] = 12 * np.sin(np.arange(n)/60)
    states[:, 1] = -65
    states[:, 2] = 60 + 6*np.sin(np.arange(n)/50)
    states[:, 3] = 45
    states[:, 5] = 50
    dataset = ws.out("demo/joints.json")
    write_json(dataset, {"kind": "simulation", "synthetic": True, "fps": 30,
        "start_time": 1792285200.0, "units": "degrees_gripper_0_100",
        "states": states.tolist(), "instruction": "pick the hemostat"})
    rows = [
        {"type": "command", "action": "handover", "heard": "grab me the kelly", "step": "finding", "out": []},
        {"type": "picked", "step": "picking", "out": []},
        {"type": "handed", "step": "waiting_for_pull", "request_to_hand_s": seconds/2, "retries": 0, "out": ["hemostat"]},
        {"type": "released", "step": "homing", "out": ["hemostat"]},
    ]
    log = ws.out("demo/events.jsonl")
    with log.open("w", encoding="utf-8") as stream:
        for offset, row in zip((0, seconds/4, seconds/2, seconds*.75), rows):
            stream.write(json.dumps({**row, "t": 1792285200.0 + offset, "command_id": "demo-command",
                "case_id": "demo-case", "item": "hemostat", "setting": "surgical", "lighting": "normal",
                "synthetic": True, "fake_arm": True}) + "\n")
        for success in (True,False):
            stream.write(json.dumps({'kind':'test','doc':{'t':1792285200.0+seconds,
                'item':'hemostat','setting':'surgical','lighting':'normal','success':success,
                'seconds':seconds/2 if success else None,'retries':0,'synthetic':True}})+'\n')
    write_json(ws.out("demo/truth.json"), {"corners": quad.tolist(), "width_mm": 300, "height_mm": 180})
    write_json(ws.out("demo/plate-alignment.json"), {"synthetic": True,
        "world_corners_m": [[.19,-.13,0], [.29,-.13,0], [.29,.13,0], [.19,.13,0]]})
    write_json(ws.out("sync.json"), {"demo.mp4": {"start_time": 1792285200.0,
        "method": "synthetic fixture clock", "kind": "simulation"}})
    bindings={key:{'source':'raw/demo.mp4'} for key in ['N7','A1','A2','A3','A4','A5','A6','A7','A8','ARM_ROLL']}
    write_json(ws.out('demo/edit.json'),bindings)
    # Real SO-101 MuJoCo renderer, not a fabricated success trajectory.
    from .reconstruction import render_joints
    render_joints(ws, dataset, ws.out("raw-sim/so101.mp4"), width=640, height=480)
    return {"clip": str(path), "events": str(log), "joints": str(dataset),
            "note": "All fixture media and numbers are synthetic, labeled, and unusable as real-arm evidence."}
