# Scrub: tonight's bring-up

Run commands from the repository root in PowerShell, in the existing environment
with LeRobot and Feetech installed. Use the workshop-approved hardware Python;
the lightweight repo tests also run on Python 3.10. Do not repeat account setup.
Anish drives the arm; a second person resets the tray, watches clearance and can
cut power. Software stop is not an emergency-stop circuit. Start with an empty
gripper and blunt practice objects, never an attached blade.

**Current gate:** R4 is not done. No live checks have been claimed. Wait until
Anish confirms the arm is plugged in and `PERCEPTRON_TEAM_API_KEY` is in `.env`.
The shipped rig disables real operation. Do not mark it verified to bypass errors.

## 1. Check the software without hardware

```powershell
git pull --rebase
python -m unittest arm.test_perceptron arm.test_kinematics arm.test_streaming arm.test_real_arm arm.test_sessions arm.test_pipeline arm.test_teach arm.test_prepare -v
python -m arm --dry-run --self-test
python -m controller --fake-arm --motion-s 0.2
```

In a second terminal, run the state check first. **Require `fake_arm: true`
before the smoke command**; if port 8000 belongs to an existing real controller,
do not run this smoke invocation. Without `--human`, smoke can send simulated
release commands.

```powershell
Invoke-RestMethod http://localhost:8000/state
python -m controller.smoke --items hemostat
```

**Expect:** offline tests pass; dry-run says `closed_and_still`; controller state
says `fake_arm: true`; the fake request releases and homes. Open
`http://localhost:8000/` for the dashboard and `/demo` for judging controls.
**If not:** fix the offline/controller failure first. These tests are not evidence
of learned grasping or physical safety. Stop the fake controller before real setup.

## 2. Identify ports and all three cameras

```powershell
lerobot-find-port
lerobot-find-cameras opencv
```

`lerobot-find-port` asks you to unplug/replug one arm at a time. Label follower
and leader USB cables. Record the actual values below, not these placeholders:

```powershell
$Follower = "REPLACE_FOLLOWER_PORT"
$Leader = "REPLACE_LEADER_PORT"
$Side = 0    # replace with the fixed side camera id
$Wrist = 1   # replace with the wrist camera id
$HfUser = "REPLACE_HF_USER"
$Repo = "$HfUser/scrub"
$DatasetRoot = Join-Path $env:USERPROFILE "scrub-dataset"
$Cadence = Join-Path $env:USERPROFILE "scrub-cadence.json"
$Cameras = "{side: {type: opencv, index_or_path: $Side, width: 640, height: 480, fps: 30}, wrist: {type: opencv, index_or_path: $Wrist, width: 640, height: 480, fps: 30}}"
```

**Expect:** distinct follower/leader ports and side/wrist feeds. A third overhead
camera belongs to `vision/`; it must not reopen a LeRobot-owned device.
**If not:** check power/data cables and camera ids after every replug. Close any
preview/vision/teleop process already owning the device. Never run motor-id setup
on the assembled workshop arms unless staff specifically requires it.

## 3. Reuse one calibration and verify units

For the first setup only, with room to sweep the empty arm and an operator
supporting it, follow the calibration prompts:

```powershell
lerobot-calibrate --robot.type=so101_follower --robot.port=$Follower --robot.id=scrub_follower
lerobot-calibrate --teleop.type=so101_leader --teleop.port=$Leader --teleop.id=scrub_leader
```

**Expect:** saved calibration for exactly `scrub_follower` and `scrub_leader`.
New/mid-range zero is the URDF convention used by this repo. Verify joint signs,
degree offsets and x-forward/y-left/z-up against the physical arm. LeRobot's
gripper is normally 0 closed, 100 open; our public interface reverses that to
0 open, 1 closed. Do not apply the URDF jaw angle to model actions.
**If not:** stop and resolve units/calibration with staff. Recalibration changes
what recorded numbers mean; do not mix it into an existing dataset. All slots,
teleop, recording and inference must reuse the same ids and calibration.

## 4. Teleoperate once, then tape the setup

```powershell
lerobot-teleoperate --robot.type=so101_follower --robot.port=$Follower --robot.id=scrub_follower --robot.use_degrees=true --robot.cameras="$Cameras" --teleop.type=so101_leader --teleop.port=$Leader --teleop.id=scrub_leader --display_data=true
```

**Expect:** follower follows a small, slow leader movement; both RGB views are
640x480 at 30 FPS. Side sees the whole task, wrist sees the grasp. Stop teleop
before teaching or starting the controller; only one process owns the bus.
**If not:** stop motion, check camera ids/visibility and degree conventions. Do
not compensate for a sign error by recording demonstrations around it.

Tape the base, tray outline, slots, return spot and camera mounts. Keep the safe
set-down zone clear and separate from the handoff region. Keep both policy
cameras fixed for the whole dataset, including later dental/bench recording.
Changing trays does not mean moving cameras or recalibrating.

## 5. Teach poses and measure the handoff region

Support the empty arm before disabling torque. With teleop/controller closed:

```powershell
python -m arm.teach --port $Follower --robot-id scrub_follower --supported-and-empty
```

Move by hand, then key + Enter: `h` home, `c` carry, `s` safe-spot, `p` current
joints/FK, `a` and `b` opposite corners, `q` quit. All axes of the corner box
need at least 1 cm separation. **Torque stays off on exit.**

**Expect:** poses and a min/max box saved in `arm/rig.json`; unrelated settings
preserved; `hardware_verified` remains false. FK corner coordinates depend on
the already-verified joint/base mapping, not independent ground truth. Measure
actual tip positions too. Carry and the entire interpolated handoff path must
be inside the region. Pose moves preserve the held gripper value.
**If not:** a degenerate corner, invalid joint or concurrent rig edit is rejected;
restart teaching after resolving it. Do not enable hardware yet. R4 with Anish
must check five targets (~2 cm goal), tool attitude and the signed gripper-load
change. There is no shipped one-command live-joint `--dry-run`: `python -m arm
--dry-run` uses fake joints only. Do not mistake it for hardware verification.

## 6. Record the operating-room set into ONE dataset

Keep one repo `$Repo`, one root `$DatasetRoot`, fixed calibration/cameras and
exact task strings from settings. Example first batch (five picks):

```powershell
lerobot-record --robot.type=so101_follower --robot.port=$Follower --robot.id=scrub_follower --robot.use_degrees=true --robot.cameras="$Cameras" --teleop.type=so101_leader --teleop.port=$Leader --teleop.id=scrub_leader --dataset.repo_id=$Repo --dataset.root=$DatasetRoot --dataset.single_task="pick the hemostat" --dataset.num_episodes=5 --dataset.fps=30 --dataset.episode_time_s=25 --dataset.reset_time_s=10 --dataset.push_to_hub=true
```

For **every later batch**, use the same command with `--resume=true`, the same
root/repo and the next exact instruction/episode count. `num_episodes` counts
additional episodes. Example changes: `return the hemostat`, `pick the mayo
scissors` only if that is the exact `pick_instruction` in the current settings.
Read the actual setting strings; do not invent aliases for recording.

**Expect:** 15 pick + 10 return demos per surgical item (75 total), spread across
bright/normal/dim after one setup is reliable. `n`/right arrow ends cleanly;
`r`/left arrow re-records; `q`/Esc finishes and encodes. Pick demos end still at
carry, not moving toward a person's hand. Evan logs instruction, lighting and
episode counts in `docs/DATA-LOG.md`.
**If not:** discard failed/camera-obscured demos. A cadence report must be about
30 Hz; 25 Hz recordings can still claim 30 fps in metadata. Do not train on that.
Fix laptop/camera load and re-record affected episodes. HF push publishes data:
verify the correct public repo/revision contains the complete export, with no
credentials or unnecessary people in view. Never commit recordings or weights.

## 7. Replay, record cadence evidence, then run the local check

Replay causes real motion: clear the workspace, use a blunt test object and keep
everyone out of the trajectory. Preserve the same calibration:

```powershell
lerobot-replay --robot.type=so101_follower --robot.port=$Follower --robot.id=scrub_follower --robot.use_degrees=true --dataset.repo_id=$Repo --dataset.root=$DatasetRoot --dataset.episode=0
python -m arm.train pipeline $DatasetRoot --cadence-report $Cadence --check-only
```

Before the second command, create `$Cadence` from the actual **wall-clock**
recording reports, one entry for every episode. Schema example, not measured data:

```json
{"episodes": [{"episode_index": 0, "measured_fps": 29.88}, {"episode_index": 1, "measured_fps": 30.0}]}
```

**Expect:** replay reproduces the intended movement; offline check confirms fps,
camera/joint metadata, episode/frame coverage and 29..31 Hz measured cadence for
every episode. At least two complete episodes are needed to split train/validation.
**If not:** fix the export/evidence before any job submission. Frame timestamps
cannot prove cadence. Local checks do not decode media or validate calibration;
replay plus the service validator are still required.

## 8. Check the Robotics key and start run 1

Keep keys only in ignored local `.env`. `PERCEPTRON_TEAM_API_KEY` is the Robotics
team key; `PERCEPTRON_API_KEY` is the different vision key. Once Anish confirms
the Robotics key is present:

```powershell
python -m arm.train capabilities
python -m arm.train pipeline $DatasetRoot --cadence-report $Cadence --repo-id $Repo --revision <HF_COMMIT> --idempotency-key scrub-run-1 --confirmed-replay --confirmed-hf-matches-local
```

Replace `<HF_COMMIT>` with the actual published revision before running.
**Expect:** allowed settings/quotas printed, dataset ready/validation passed, job
id, logs/metrics, then a ready deployment for this checkpoint. The pipeline writes
`PERCEPTRON_DEPLOYMENT_ID` into `.env`, preserving other entries. Record capability
results in `docs/ARM.md`. Standard/expert_only/1000 steps/horizon 30/RTC is the
workshop preset, roughly 45 min plus queue/export, not a timing guarantee.
**If not:** 401 means wrong/missing Robotics credentials; do not paste keys into
chat. Inspect validation for dataset failures. For export delays inspect the job,
checkpoint and deployments. Rerun the **same** pipeline command/key to resume;
do not use a fresh key to retry a lost response. The state is in ignored
`.env.pipeline-scrub-run-1.json`. Failed/unknown validation never submits training.

Only **two successful jobs** are budgeted. Run 2 starts from the base model and
must include all earlier episodes plus later settings/corrections in the same
dataset. The old “run 3 if time allows” sentence in PLAN.md is superseded by the
workshop quota. Do not spend a third job unless live capabilities/staff allow it.

## 9. Calibrate overhead vision with Brandon/Evan

Set `CAMERA_INDEX` in `.env` to the **third** camera. Keep LeRobot's side/wrist
closed while they are not needed. Start vision in its own terminal:

```powershell
python -m vision
python -m vision.calibrate
```

The calibration CLI takes `pixel_x pixel_y arm_x arm_y arm_z`, one line per point;
use 6..8 distributed points in meters, then blank line. The alternative
`python -m vision.calibrate --pairs <pairs.json>` reads `image_points`, `arm_points`
and optional `hand_height_m`. Use additional held-out points, not only fit points.
Restart vision after changing calibration. Preview is `http://localhost:8001/`.

For tray boxes, save a snapshot then pass the actual image:

```powershell
Invoke-WebRequest http://localhost:8001/snapshot -OutFile "$env:TEMP\scrub-tray.jpg"
python -m vision.mark_slots --setting surgical --image "$env:TEMP\scrub-tray.jpg"
```

**Expect:** calibration error under about 2 cm on held-out checks, `target` becomes
non-null, `path_clear` reacts to an obstruction and the lamp stays at its chosen
exposure. Mark slot/return boxes for each real tray; Evan owns committed settings.
**If not:** a homography is not depth sensing. Keep to the calibrated plane/hand
height; fix glare/exposure, wrong camera or point pairing before handoff. The
current calibration CLI can write a file even if reported error is over 2 cm:
do not accept that file as safe just because the command exited successfully.

## 10. Gate real motion, then the first live request

After R4's physical checks, fill measured poses, transforms, limits and the
handoff box in `arm/rig.json`. Fetch and review the deployment contract:

```powershell
python -m arm.train contract <DEPLOYMENT_ID>
```

Pin its `contract_id` in `verified_contract_id` only after verifying six-value
joint order/units, absolute targets, two cameras, horizon/rate 30 and RTC delay
12. Complete physical acceptance before setting `hardware_verified: true`.
Private `.env` values: `SO101_PORT`, `SO101_ROBOT_ID=scrub_follower`,
`SO101_SIDE_CAMERA`, `SO101_WRIST_CAMERA`, Robotics key and deployment id.

```powershell
python -m controller --real-arm --setting surgical
```

**Expect:** real calibrated feedback and no movement merely from connecting.
Verify the configured fallback `handoff_spot` (or the controller's default
`[0.22,-0.10,0.18]`) is actually measured/reachable, or use fresh calibrated Hand
posts. The shipped default is not a measurement of your table. Use a clear,
blunt-object handoff with the spotter ready. This endpoint starts a **whole**
handover, not just an isolated policy skill:

```powershell
Invoke-RestMethod http://localhost:8000/command -Method Post -ContentType application/json -Body '{"action":"handover","item":"hemostat","source":"keyboard"}'
Invoke-RestMethod http://localhost:8000/state
```

**Expect:** pick, verified carry, slow hand approach, release only after pull or
explicit “got it,” then home. Validate handle-first attitude separately: position
IK does not constrain pitch. Sharps go to the measured neutral zone, not a hand.
**If not:** stop immediately and inspect state/events. No chunk coverage or a
late reply must hold; repeated network failures are not permission to move blind.
Closed-and-still is a heuristic, not proof of a grasp or a completed put-back.

## 11. Stop, release and reset deliberately

These are manual operator commands, not a script to run in sequence:

```powershell
Invoke-RestMethod http://localhost:8000/stop -Method Post
Invoke-RestMethod http://localhost:8000/command -Method Post -ContentType application/json -Body '{"action":"got_it","source":"keyboard"}'
Invoke-RestMethod http://localhost:8000/reset -Method Post -ContentType application/json -Body '{"clear_count":false}'
```

**Expect:** stop latches and holds. Send `got_it` only when a recipient really has
the tool and the controller is waiting for release. Reset may move a held item
to the safe spot and home: inspect clearance and authorize that motion first.
**If not:** use physical power stop/support, not repeated commands. A missing load
reading should fall back to `got_it`, not a fabricated load jump. Only clear the
case count after the physical tray has actually been reconciled.

## 12. Voice handoff, test tables and submission

In the existing voice environment:

```powershell
cd voice
npm run dev
```

From another root terminal, test text without a phone:

```powershell
Invoke-RestMethod http://localhost:3000/heard -Method Post -ContentType application/json -Body '{"text":"grab me the kelly"}'
```

**Expect:** one controller request and one spoken reply per event. Then test the
already-configured Photon/ElevenLabs call, a real handoff, stop and explicit
release. Sending a request here can move a real connected arm: use only after
the preceding checks. **If not:** keep the keyboard path demoable, let Caiden
debug voice; do not redo account onboarding or send external texts as a test.

Use PLAN.md's trial matrix: surgical 10/item/light (bright/normal/dim), dental
and bench 5/item/light (normal/bright), and put-back 5/item. A human confirms
physical success and restores the tray between attempts; failed attempts count.
Simulation/fake results stay separate from measured hardware success tables.

### Trial runner (Q2)

These commands perform no hardware work:

```powershell
python -m controller.trials --plan-only
python -m controller.trials --self-test
```

**Expect:** default plan is 195 instrument trials: 90 surgical handovers, 60
dental/bench handovers, 45 returns. Embedded offline tests include the actual
fake-controller FastAPI routes, with ledger writes mocked/disabled.
**If not:** fix that before running a measured batch. Tests and plan-only do
not require the Robotics key, LeRobot, cameras or MongoDB.

After physical bring-up, start small against the real controller:

```powershell
python -m controller.trials --settings surgical --items hemostat --lighting normal --actions handover --tries 2
```

Omit filters/`--tries` to run the full PLAN matrix. Return trials use normal
lighting by default; if filtered to other lights, they use the first selected
label once, not an extra return matrix. Before every attempt, Enter confirms
the correct physical item placement, lamp setting and safe clearance; `q` quits
without inventing an attempt. Switching settings clears the controller count,
so first reconcile the physical inventory. The runner never resets/rearms or
clears the same-setting count automatically. Do not use it during a live case.

**Expect:** release occurs via the recipient's pull/voice/dashboard `got_it`,
not an automatic real-arm release. The runner correlates events to its own
command id and waits for idle/completion. After a software-successful run,
operator `s` confirms correct physical delivery, sharp set-down or put-back;
`f` records failure. A fallback safe set-down of a non-sharp item is not a
successful handoff. Successful retries count as successes with retries recorded.
**If not:** error/stop, timeout or uncertain network submission aborts the batch;
timeouts/network uncertainty request `/stop` but cannot prove it reached the arm.
Inspect the arm and use the existing manual reset workflow before restarting.
There is no automatic retry after an uncertain submission.

Every attempted measured trial calls **local** `ledger.log_test` with item,
setting, lighting, success, handoff/zone time and retries. Ensure this checkout's
MongoDB environment matches the intended ledger when `--url` targets another
host. The ledger buffers when offline; the runner cannot certify Mongo delivery.
The full result, action, physical confirmation and duration are also saved in a
new ignored `.env.trials-<id>.jsonl` journal (`--journal` selects another new
file; existing files are never overwritten). No camera images or keys are logged.

The ledger interface has no action field, so its aggregate item/lighting tables
combine handover and return trials. Use the journal's `action` field for separate
rates, or capture handover-only dashboard tables before running returns. Returns
have ledger `seconds: null`; their duration is only `elapsed_s` in the journal,
not falsely labeled request-to-hand time. Sharp timing is request-to-neutral-zone.

For PLAN.md's bench-adoption row, add
`--bench-start <FIRST_BENCH_DEMO_ISO_WITH_TIMEZONE>` using the actual recorded
first-demo time. The first physically confirmed bench handover writes a separate
`bench_adoption` journal entry in minutes; it is not another instrument trial
or ledger success. Without that timestamp, adoption minutes are unmeasured.
This is the first success observed in this batch, not proof of the first-ever
working bench handoff. Run it at initial bench bring-up, or label a later batch's
timing as a later observation rather than the original adoption time.

Practice against an explicitly fake/sim controller only:

```powershell
python -m controller.trials --practice --yes --settings surgical --items hemostat --lighting normal --actions handover --tries 2
```

`--practice` never calls `ledger.log_test`, labels every journal row as practice,
and permits simulated `got_it`. It refuses a real controller. Conversely,
measured mode refuses a fake/sim controller. `--yes` is prohibited for real trials.

Protect the submission: Devpost draft by Sat 10:30 PM (internal 10:00 PM),
feature freeze Sun 6 AM, public repo + required video and final Devpost by Sun
10:00 AM (internal 9:30 AM). Check organizer updates before claiming a track.
Record a clean real demonstration and a clearly labeled backup; never describe
the prototype as clinically validated.
