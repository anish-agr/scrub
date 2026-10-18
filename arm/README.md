# arm

Owner: Anish. Tasks A3, A6, A7 in `docs/TASKS.md`. Steps in `docs/ARM.md`.

`real_arm.py` implements the arm interface in `docs/CONTRACTS.md` with LeRobot and the fine-tuned Isaac 0.5 policy. `rig.json` holds the home, carry and safe-spot poses and the handoff region. Only the controller imports this folder.

Done when: the controller runs a real "pick the hemostat" with `--real-arm`, and `move_to` reaches test points within about 2 cm.

## Robotics API (A2)

Install: `python -m pip install -r arm/requirements.txt`. Run from the repo root:

```text
python -m arm.train capabilities
python -m arm.train register-hf <user>/scrub --name scrub --idempotency-key scrub-hf-v1
python -m arm.train upload <dataset-root> --name scrub --idempotency-key scrub-upload-v1
python -m arm.train status dataset <dataset-id>
python -m arm.train validation <dataset-id>
python -m arm.train train <dataset-id> --idempotency-key scrub-run-1 --confirmed-replay-and-cadence
python -m arm.train follow <job-id>
python -m arm.train deployments
python -m arm.train contract <deployment-id>
python -m unittest arm.test_perceptron -v
```

Put `PERCEPTRON_TEAM_API_KEY` in the root `.env`, never in a command or git.
Use the same idempotency key AND body when retrying a logical registration or
job submission. No automatic retries: stale predicts must not be resent.
Training requires a ready dataset and explicit confirmation that replay/cadence
were checked. Read validation evidence before submitting; only two successful
jobs are budgeted. `follow` reads logs/metrics with their returned cursors,
prints checkpoint/deployment information on job completion; export can still be
pending, so use `deployments` until the desired deployment is ready.

Control and inference have separate HTTP clients. Inference uses a grant's
`endpoint_url`, falling back to `/v1/inference` on the control host per workshop
notes. This routing is offline-tested, not yet confirmed with a live grant.
Signed uploads use a third, unauthenticated client; a 303 is followed by GET
without replaying upload bytes or headers. Local datasets are read only when
the operator explicitly invokes `upload`; no dataset was inspected in setup.

## Training pipeline (R1)

```text
python -m arm.train pipeline <local-export> --cadence-report <cadence.json> --check-only
python -m arm.train pipeline <local-export> --cadence-report <cadence.json> --repo-id <user>/scrub --revision <HF-commit> --idempotency-key scrub-run-1 --confirmed-replay --confirmed-hf-matches-local
```

The first command is entirely offline. The second spends one training submission
only after local checks, a ready dataset and completed service validation. Use
an immutable HF commit when possible; publishing to HF is a separate step, and
the operator must confirm that repo/revision contains this local export.
No actual dataset was read or job submitted while implementing this command.

Local preflight checks LeRobot v2.0/v2.1/v3.0, fps=30, exactly side/wrist RGB
640x480 metadata, six float32 joint names in contract order, >=2 episodes,
episode lengths/counts, finite state/actions and gripper bounds, continuous
frame indices/timestamps in parquet, and measured recording cadence for **every**
episode. Media dimensions come from metadata; decode/replay and the service
validator remain mandatory. `pyarrow` is used for parquet, without loading LeRobot.

Supply cadence evidence transcribed from recording's wall-clock cadence reports,
not computed from frame-index timestamps. Format:

```json
{"episodes": [{"episode_index": 0, "measured_fps": 29.88}, {"episode_index": 1, "measured_fps": 30.0}]}
```

Each episode must measure 29..31 Hz. A dataset declaring 30 fps but recorded at
25 Hz fails if its measured report is honest; metadata alone cannot detect that.

The pipeline polls ingestion/validation, follows logs and metrics with cursors,
then waits for a ready deployment matching **this job's checkpoint**, never an
unrelated ready model. It writes only `PERCEPTRON_DEPLOYMENT_ID` to the local
`.env`, preserving other entries, and does not auto-pin a motion contract.
Unknown API response shapes fail safely rather than selecting an arbitrary model.

Retry the **same** command/key to resume. IDs and the local snapshot hash are
saved in root `.env.pipeline-<key>.json` (already git-ignored); this state has no
credentials. Changed inputs are rejected, registration/job retries use stable
keys, and failed jobs are not automatically replaced. Optional `--state-file`,
`--env-file`, `--interval` and `--timeout` support testing/recovery. Timeouts do
not cancel remote jobs. Keep this state until deployment succeeds. Only two
successful jobs are budgeted; never change the run key just to retry a lost reply.

## Offline arm / IK (A7, A6)

```text
python -m unittest discover -s arm -t . -p "test_*.py" -v
python -m arm --dry-run --self-test
python -m arm --dry-run --side-image <side.png> --wrist-image <wrist.png>
python -m arm --dry-run --self-test --latency-ms 450 --max-s 1.2
```

The last command should exit 1 with `success: false`, `reason: max_s`, and no
accepted chunks. All commands above use **fake** joints and fake predictions,
no API key, no camera, no LeRobot import, and no motor connection. `--self-test`
creates temporary synthetic saved PNGs; it is a protocol test, not a grasp test.
Saved input images must be 640x480; PNGs are sent to the policy interface.

`Arm` in `real_arm.py` implements the public interface; `move_to` delegates to
URDF IK and the same 30 Hz sender. The sender owns all bus I/O; the caller of
`run_skill` is the inference thread. Predict runs synchronously every 15 rows
on the playback clock. A chunk's rows remain anchored at capture time, not
arrival time. RTC commits 12 rows, uses a 400 ms acceptance deadline, and
switches only at `execute_from_index`. Late replies are discarded. Playback
holds measured position when no chunk covers the current tick. Joint rate
limiting is reflected in `rtc.committed_actions`; the server must echo those
rows or the reply is rejected. Gaps after an exhausted chunk reset the session
before sending a fresh first observation. Missed ticks are not replayed in bursts.

`run_skill` returns true only after a closed-and-still gripper; max_s, freeze,
and errors return false. This heuristic is not proof of a grasp. In particular,
an open-gripper return ending at max_s is **not** automatically a successful
return; that flow needs an independently verified completion condition later.

`freeze()` is nonblocking and latched. The playback thread holds on its next
available tick; an in-flight HTTP response cannot restart motion. `resume()` is
an explicit operator rearm outside the base contract. A serial/driver stall can
delay a hold; this software is not a physical emergency stop. Bus errors latch
a failure and require reconnecting after inspection. No blind hold write is
issued after feedback becomes invalid. Disconnect preserves torque to avoid
dropping a held tool; support the arm, set tools down and power off manually.

The LeRobot adapter uses `use_degrees=True`, named `side`/`wrist` RGB cameras
at 640x480/30 FPS, no automatic calibration, and `Present_Load` from the Feetech
bus with `normalize=False` (signed raw motor load, not torque). Missing load
raises instead of manufacturing a reading. Measured pose moves preserve the
current gripper value; `set_down_safe_spot()` opens only after arrival.

Source APIs were inspected against LeRobot `v0.4.4`:
`robots/so_follower/{so_follower,config_so_follower}.py`,
`cameras/opencv/{camera_opencv,configuration_opencv}.py`, and
`motors/{motors_bus.py,feetech/tables.py}`. LeRobot is not installed or hardware
tested here. Install its workshop-approved source checkout with Feetech/camera
extras in the arm environment, then verify these imports there. The dependency
file here covers offline tests/client code, not LeRobot's heavy hardware stack.

## Pre-open instruction sessions (R3)

`Arm.prepare(instructions)` is optional; the base arm contract is unchanged.
Call it in the controller's worker (for example, `await asyncio.to_thread(arm.prepare,
instructions)`), **not** on the FastAPI event loop. Supply exact recorded task
strings for the active setting. It returns the unique prepared strings, never
tokens. No motor connection, camera capture or motion is performed by this hook.

Each instruction gets its own contract-pinned session/grant. Repeating the same
set reuses sessions; changing settings closes obsolete ones. `run_skill` selects
the prepared session instead of opening a grant on first use, and still resets
sequence/RTC history between runs. `prepare([])` releases the prepared set, and
disconnect deletes all cached sessions. Ordinary unprepared instructions retain
the previous one-on-demand-session behavior.

Deployment/contract changes invalidate all old grants. A locally known TTL expiry
requests a fresh grant; idle expiry on the server can happen sooner and remains
a runtime failure/reset/regrant case, not something local pre-opening can prevent.
If preparing a new set partially fails, newly opened sessions are closed and the
previous good set is retained. Freeze cancels preparation without rearming or
allowing a late grant to restart motion. The method shares the operation lock
with skills/motion, so it may wait for a running skill; `freeze()` stays nonblocking.

Test: `python -m unittest arm.test_prepare -v` (11 tests, fake sessions, no key).
Caiden can call the optional hook when settings change via `getattr`; no
`controller/` or `docs/CONTRACTS.md` edits were made here.

## Recording (L6): check_setup and record

```text
python -m arm.check_setup --side C920 --wrist icspring          # Mac; Windows: --side 0 --wrist 1
python -m arm.check_setup --json --out ~/scrub-setup-check/now  # machine output, frames to a folder
python -m arm.record --task "pick the hemostat" --lighting bright --episodes 5 --print-only
python -m arm.record --setting surgical --item hemostat --direction put-back --lighting dim --episodes 5
python -m arm.record --lerobot --follower COM5 --leader COM6 --side 0 --wrist 1 --task "pick the hex key" --lighting normal
python -m unittest arm.test_record -v
```

`check_setup` lists serial ports without opening them (motors untouched), opens
every camera at 640x480 at 30 fps, measures the real fps over 2 s (PASS needs
640x480 and at least 28 fps), saves one frame each outside the repo, and exits 1
on any failure. Cameras are matched by name on macOS (AVFoundation, OpenCV's
order) and on Windows when `pygrabber` is installed; otherwise pass indexes.
Missing `opencv-python` or `pyserial` is reported in the table, not a crash.

`record` fixes use_degrees=true, 30 fps, 25 s episodes, 10 s reset, repo
`<HF_USER>/scrub` (`--hf-user`, `HF_USER`, or `huggingface_hub.whoami` on
`HF_TOKEN`) and root `~/scrub-dataset` (resumed when `meta/info.json` exists; a
folder without it is refused). Task text must be an exact instruction from
`settings/surgical.json` or `settings/bench.json`; dental is not recorded. After
the batch it appends one `docs/DATA-LOG.md` row through `ledger.logbook.log_batch`
(same line as `python -m ledger log`), with the episodes actually saved and the
batch's loop rate from `<root>-cadence.json`. The default backend runs
`explore/arm_session.py` as a subprocess (the recorder that works on the Mac);
`--lerobot` runs the plain BRINGUP section 6 `lerobot-record` (local unless
`--push`). arm_session has no use_degrees flag: it relies on LeRobot's SO-101
default (true in the installed LeRobot), and `record` refuses to start if that
default is ever false. `SCRUB_FOLLOWER_PORT`, `SCRUB_LEADER_PORT`,
`SCRUB_SIDE_CAMERA` and `SCRUB_WRIST_CAMERA` set the defaults.

## Before hardware

### Hand-guided teaching (R2)

```text
python -m arm.teach --port <follower-port> --robot-id scrub_follower --supported-and-empty
python -m unittest arm.test_teach -v
```

Run only with the empty arm physically supported: disabling torque can make
it fall. Close the controller, teleop and recording first so teach alone owns
the serial bus. Reuse the dataset's saved follower calibration; this tool never
recalibrates, configures motors, enables torque, or sends position targets.
It uses degrees, no cameras and no API key. Torque remains **off on exit**.

Move by hand, then type a key and Enter: `h` saves home, `c` carry, `s` safe_spot,
`p` prints joints/FK, `a` and `b` mark opposite handoff-region corners, `q` quits.
Both corners are required before the region is saved; every axis must span at
least 1 cm. Corner coordinates are FK estimates, not a new measurement of the
base transform: verify signs, offsets and base frame against real positions
first. Teaching does not calibrate the kinematic model.

Saves preserve unrelated rig fields, refuse concurrent edits, and always set
`hardware_verified: false`; only a later physical acceptance check enables
motion. `--dry-run --rig <separate-test-copy.json> --joints <six-values>` runs
the same keyboard/save flow with fake joints. The copy's `urdf` must resolve
to the SO-101 chain file (use an absolute path if the copy is elsewhere).
Dry-run refuses the shipped `arm/rig.json` so fake poses cannot silently
replace measured ones. Eight offline teaching tests cover saves, invalid
readings/regions, concurrent edits and the no-torque-enable/no-target rule.

`rig.json` is an unmeasured template with `hardware_verified: false`, null
poses and a null `verified_contract_id`. Do not flip these just to bypass a
failure. Measure/verify:

- Base transform (our x forward, y left, z up), five joint signs/degree offsets,
  URDF limits and the new/mid-range zero convention. Old calibration is different.
- Gripper raw open/closed endpoints; interface returns 0 open / 1 closed while
  inference receives unconverted raw 0..100, exactly like recording.
- Home/carry/safe_spot poses (six raw values), handoff box, speeds. Carry and
  every interpolated handoff position must already lie in the handoff box.
- Contract from `python -m arm.train contract <deployment-id>`: review joint
  order/units, absolute targets, cameras, horizon 30, 30 Hz and RTC delay 12;
  pin the reviewed `contract_id`. A changed contract fails before a grant.

Set these local `.env` variables (never commit it): `PERCEPTRON_TEAM_API_KEY`,
`PERCEPTRON_DEPLOYMENT_ID`, `SO101_PORT`, `SO101_ROBOT_ID` (default
`scrub_follower`), `SO101_SIDE_CAMERA` (default 0), `SO101_WRIST_CAMERA` (default 1).
Camera ids and calibration id must match recording. Then the controller, not
another script, connects with `python -m controller --real-arm`.

### Handoff to Caiden (no controller/contract edits made here)

1. In `controller/core.py::_reset`, explicitly call optional `arm.resume()`
   **before** `open_gripper`/`go_home`, only on an operator-authorized reset.
   A tracking-loss retry must not implicitly clear a latched freeze; request
   rearm rather than just retrying `move_to`.
2. In `_wait_for_pull`, catch missing-load `RuntimeError` from both the initial
   and subsequent `gripper_load()` calls; continue waiting for `got_it` with
   the existing timeout and generation checks. Do not synthesize a load jump.
   Check the measured sign and magnitude of load changes before enabling pull.
3. In `_set_down`, inspect the bool from `set_down_safe_spot()`. If false, do
   not add the item to `out` or emit successful `set_down`; stop/report failure.
4. Decide a return-completion condition from tray perception; max_s is a
   timeout, not proof of successful put-back. Current generic closed-and-still
   termination can occur before the end of a return trajectory.
