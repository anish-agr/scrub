# Batch 55-57 brief: cameras wired to the real SO-101 (follows ARM_BRIEF.md and BRIEF_47.md)

Read ARM_BRIEF.md, BRIEF.md, BRIEF_47.md and DESIGN-DE-AI.md (strictly) first. Same file rules, smoke test and no edits in dubhacks-2026/.

## The camera situation (ground truth, Sat Oct 17 evening)

Three cameras on the rig:
- **overhead**: owned by `vision/` (Brandon), port 8001. `GET /stream` (MJPEG, already annotated with slot boxes and the palm dot),
  `GET /snapshot` (one annotated JPEG), `GET /health`, `GET /vision/tray`, `GET /vision/hand`, `GET /lighting`. NO CORS on :8001,
  so pages can show its images with `<img>` / drawImage, but must read JSON through the controller instead.
- **side** and **wrist**: owned by the arm process (LeRobot inside `python -m controller --real-arm`). They feed the Isaac policy
  at 30 Hz while a skill runs. They cannot be opened by a second process. Until now nothing let a person see them live.
- Calibration: `vision/calibration.json` holds `homography` (3x3, overhead pixel -> arm table x,y in meters), `image_points`,
  `arm_points`, `hand_height_m`, `standoff_m` (0.04), `max_error_m`, `rms_error_m`. B6 is still open: the file may not exist.
  Arm -> pixel is the inverse homography (only valid on the table plane; at hand height it is approximate, say so).

## Controller endpoints (port 8000, CORS *), including the new ones for this batch

Existing: `GET /state` (now also `out_camera`: what the camera says is out, or null; `case_id`), `GET /setting` (items with `slot`
pixel boxes `[x1,y1,x2,y2]` or null until B5, `return_spot`), `WS /events`, `GET /events/recent?n=`, `POST /command`, `POST /stop`,
`POST /reset`, `GET /vision` (`{tray, tray_age_s, hand, hand_age_s}`, the last TrayState and Hand posted by vision), `POST /fake/pull`,
`POST /fake/force`, `GET /nurse` (the nurse console).

New in this batch (being added to controller/armview.py right now; build against these shapes, fall back to a labeled mock on 404/network error):
- `GET /arm/pose` -> `{"available": bool, "joints_deg": [5 numbers] | null, "gripper": 0..1 closed | null, "tip_m": [x,y,z] | null,
  "tip_px": [x,y] | null, "calibrated": bool, "reason": str | null, "t": seconds}`. tip_m is forward kinematics from arm/rig.json
  (meters, arm base frame, x forward, y left, z up). tip_px is tip_m projected into the overhead image with the calibration (null
  without calibration). On the fake arm: available false, reason "fake arm has no joints".
- `GET /arm/camera/side` and `GET /arm/camera/wrist` -> one JPEG. `GET /arm/stream/side|wrist` -> MJPEG. 404 with
  `{"detail": "..."}` when the arm does not expose frames (the fake arm, and real_arm until Anish adds `camera_jpeg(name)`).
- `GET /camera/overhead` -> the vision snapshot proxied through the controller (same origin as /nurse, CORS *), 502 if vision is down.
- `GET /calibration` -> vision/calibration.json, 404 if missing.

Rules for every page: a `?api=http://host:8000` override (default `http://localhost:8000`) and `?vision=http://host:8001`;
a visible LIVE / MOCK badge per data source, never mixing silently; STOP (Space/Esc -> POST /stop) wherever the arm can move;
the arm, tray and camera frames drawn as they are, in mm or px with units. Image sizes: the overhead is 640x480 unless the
frame says otherwise (use naturalWidth/naturalHeight).

Item ids: surgical `scalpel` (sharp), `hemostat`, `mayo_scissors`; dental `mouth_mirror`, `explorer`, `cotton_pliers`;
bench `needle_nose_pliers`, `wire_cutters`, `hex_key`. Steps: idle, finding, picking, checking, moving_to_hand,
waiting_for_pull, releasing, setting_down, homing, returning, stopped, error. Event types: command, step, picked, handed,
set_down, released, returned, missed, count, stopped, error (fields in dubhacks-2026/docs/CONTRACTS.md).
