# sim

Owner: Caiden. A MuJoCo simulation of the SO-101 and the Scrub table, so the controller, vision and dashboard can be built and tested without the arm. `sim/web/` (3D viewer / layout designer) belongs to another agent.

What is here:

| File | What |
| --- | --- |
| `sim_arm.py` | `SimArm`: the exact Arm interface from `docs/CONTRACTS.md`, physics in a background thread at real time |
| `ik.py` | standalone damped-least-squares IK and reachability (reference for Anish's A7 `move_to`; **Anish owns the real one**) |
| `scene.py` | builds `scenes/scrub_scene.xml` (and `scenes/_arm.xml`, the camera model with a wrist `<camera>`) from `layout.json` |
| `layout.json` | all positions, arm base frame, meters, x forward, y left, z up, table top at z=0 |
| `server.py`, `__main__.py` | FastAPI on port 8002 |
| `reach_check.py` | reachability report for the layout |
| `fetch_model.py` | downloads the SO-101 MuJoCo model into `models/so101/` (already run) |

## Run

From the repo root:

```bash
python3.10 -m venv .venv && .venv/bin/pip install -r sim/requirements.txt   # once
.venv/bin/python -m sim.fetch_model        # once, only if sim/models/so101 is missing
.venv/bin/python -m sim                    # server on http://127.0.0.1:8002
.venv/bin/mjpython -m sim --view           # native MuJoCo viewer (macOS needs mjpython) plus the server
.venv/bin/python -m sim.reach_check        # is every tape position reachable?
.venv/bin/python -m pytest sim/test_sim.py # tests
```

`--view` needs `mjpython`, which calls `otool`; if it fails with exit status 69, accept the Xcode license (`sudo xcodebuild -license`) or install the command line tools. In `--view` mode `/stream` returns 503 (one GL thread per process). Camera streams render on the main thread of `python -m sim` because OpenGL on macOS hangs on other threads.

## HTTP (port 8002, CORS open for localhost)

| Endpoint | Returns |
| --- | --- |
| `GET /stream` | MJPEG of the `overhead` camera, 640x480 (`/stream?cam=wrist` for the wrist camera). Point vision or the dashboard at it as a fake camera |
| `GET /state` | `{"q":[6 rad],"names":[...],"gripper":0..1,"holding":item_id or null}` |
| `GET /reach?x=&y=&z=` | `{"reachable":bool,"error_m":float,"q":[6]}` |
| `POST /reach/batch` `{"points":[[x,y,z],...]}` | `{"results":[{"reachable","error_m","q"},...]}` |
| `GET /layout`, `PUT /layout` | read or write `layout.json` (PUT rebuilds the scene and reloads the arm) |
| `POST /scene/reset` | put every item back in its slot and the arm at home (between smoke runs) |
| `/web/*`, `/models/*` | static files from `sim/web/` and `sim/models/` |

## Using it from the controller (C1 hook)

Caiden's controller can add a flag next to `--fake-arm`:

```python
if args.sim_arm:
    from sim.sim_arm import SimArm
    arm = SimArm()
```

`SimArm` has the same methods as `controller/fake_arm.py`, so nothing else changes. Extras: `arm.pull()` simulates a tug on the item (gripper load rises for 0.5 s), `arm.state()`, `arm.tip()`. `freeze()` can be called from any thread and aborts a running call.

## Behavior notes

- Poses and the handoff region come from `arm/rig.json` if it exists (`home`, `carry`, `safe_spot` as 6 joint radians; `handoff_region` as `{"min":[x,y,z],"max":[x,y,z]}` or `{"x":[a,b],"y":..,"z":..}`), otherwise from `layout.json`. Anish: if your rig.json uses other keys, tell Caiden or change `_pose` / `_region` in `sim_arm.py`.
- `move_to` returns False outside the handoff region or if IK can't get within 5 mm. Speed is m/s along a straight line, joint steps are capped.
- `run_skill("pick the hemostat")` (also "return the X": picks X from `return_spot` and places it in its tray slot; falls back to placing a held X; False if X is neither there nor held) is a scripted stand-in: IK above the slot, descend, close, attach, lift. Items are kinematic mocap bodies (no contact physics); the jaw stops at an item-width angle so `gripper_position()` is about 0.75 and `gripper_load()` is the saturated servo force.
- Tool pitch: IK prefers the gripper pointing down (soft constraint) and falls back to position only.
- Axes: this MJCF's positive `shoulder_pan` swings the gripper toward -y (right). `ik.py` handles that; Anish should check his real-arm sign.

## Limits

The scripted pick stands in for the fine-tuned Isaac 0.5 policy; nothing here says anything about how the real policy or the real arm will behave. No sim-to-real claims. Servo gains and gravity are approximate (gravity is compensated in the sim).

## Attribution

Robot model: TheRobotStudio SO-ARM100 / SO-101, https://github.com/TheRobotStudio/SO-ARM100 (Simulation folder), Apache-2.0, pinned to commit `a758567c3978dfeefe282ede0500085a48fe8f78` by `fetch_model.py`. Files are not modified; the wrist camera is added in a generated copy (`scenes/_arm.xml`).
