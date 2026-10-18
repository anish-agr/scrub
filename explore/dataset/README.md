# Dataset and camera tools (Caiden, explore/)

Checks for the LeRobot demos before they use one of the two Isaac training jobs. All read a dataset with `--root` and never write to it.

| Tool | Command (from the repo root) | What it tells you |
| --- | --- | --- |
| QA | `.venv/bin/python -m explore.dataset.qa --root <ds> --out qa.html` | Per demo PASS/WARN/FAIL: length, frozen arm, gripper never closes or reopens, joint jumps, dropped frames, blurry/dark/frozen cameras, state lag. Thresholds at the top of `qa.py`. |
| Variety | `PYTHONPATH=. .venv/bin/python explore/dataset/variety.py --root <ds> --out variety.html` | Where each grasp happened (top-down and side), 5 cm coverage grid, where to record next. |
| Replay | `.venv/bin/python explore/dataset/replay.py --root <ds> --episode 0 --port 8095` | The MuJoCo arm set to the recorded joints next to the real side and wrist video. `--check` prints joint-limit and tip-height problems with no server. |
| Aim | `.venv/bin/python explore/dataset/aim.py --live` (port 8096) | Camera level, sharpness, brightness, and a ghost of a reference frame with shift/rotation/scale. While `explore/arm_session.py` runs it reads that session's streams on :8090 and never opens a camera. File mode: `--side-image`, `--wrist-image`, `--dataset`. |

Found on the first test recording (Oct 17):
- shoulder_lift rests at about -103.7 deg, past the URDF limit of -100 deg, so `arm/kinematics.py` rejects the rest pose. Suggest a shoulder_lift offset of about +4 deg in `arm/rig.json`, measured on the arm (Anish's file).
- The wrist camera runs at about 23 fps (LeRobot needs 30) and was dark in every test episode.
- The side camera repeats about half its frames (15 fps doubled to 30).
- Kinematics and the sim agree to 0.0 mm wherever joints are inside the limits.
