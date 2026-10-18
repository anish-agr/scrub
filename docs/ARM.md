# Arm, recording and fine-tuning

Owner: Anish. The workshop is the source of truth. Where it differs from below, the workshop wins and this file gets updated.

## Workshop notes (fill in at 12:30)

| Question | Answer |
| --- | --- |
| How long is each arm slot? When are ours? | |
| Overnight arm time? | we have the arm the whole competition |
| Where does the arm live? Can we bring our tray, lamp and towel? | |
| Cameras on the arm setup (wrist, front, overhead)? Can we add a USB webcam? | |
| Does the gripper report load (for release on pull)? | |
| How long does a 1,000-step run take? Steps for 75 to 225 episodes? | |
| Can one dataset hold several instructions? | |
| Demos per item they suggest? | |
| Image augmentation (brightness, contrast) in their pipeline? | |
| One model with a different text instruction per item? | |
| Predict latency per action chunk? | |
| Vision API: endpoint, keys, rate limits | |
| Does LeRobot's end-effector control work on the SO-101 (for `move_to`)? | |
| Does the arm come to judging, or do we demo at their station? | |

## Perceptron's format

### A2 capabilities check (Oct 17)

Ran `python -m arm.train capabilities` from `dubhacks-2026`.
Result: exit 1, `Missing PERCEPTRON_TEAM_API_KEY in the repository .env`.
There is no root `.env` and the variable is not present in the process
environment. No request was sent and no live capabilities or quotas have been
verified. Anish must supply the key locally, then rerun the command; record its
JSON here before marking A2 complete. Do not paste credentials into chat.

The client/CLI/uploader are implemented; five offline tests pass with
`python -m unittest arm.test_perceptron -v` (control routes checked against the
saved OpenAPI, auth isolation, multipart inference, upload hashing/batches,
303 polling, sanitized errors). No dataset was uploaded or training started.
Anish subsequently authorized continuing A7/A6 without the key; A2's live check
remains pending.

### A7 offline kinematics

`arm/so101_chain.urdf` is a kinematic-only extract of the SO-101 **new**
calibration URDF (upstream blob recorded in the file). `arm/kinematics.py`
computes FK and bounded numerical position IK at `gripper_frame_link`;
`arm/motion.py` exposes `move_to` through an injected trajectory executor.
Wrist roll is preserved, but pitch/handle orientation is not constrained by
position-only IK. No collision checking is claimed.

`speed` is a fraction (0, 1] of rig limits. Preflight checks every interpolated
point against the handoff box, so the carry pose must already be inside it.
Paths obey both joint and Cartesian speed limits at 30 Hz. Coordinates are
meters in the configured base frame. `base_to_urdf` maps these coordinates to
URDF coordinates; `q_urdf_deg = q_lerobot_deg * joint_signs + joint_offsets_deg`.
Verify this mapping at the real arm before enabling hardware.

`arm/rig.json` is an **unmeasured template**, not a saved calibration. Hardware
is disabled (`hardware_verified: false`); poses are null. The gripper mapping
is deliberately separate from URDF: upstream documents LeRobot 0 closed,
100 open, whereas our public interface is 0 open, 1 closed. Measure actual
endpoints on this arm and preserve the raw 0..100 convention for inference.

Run `python -m unittest arm.test_kinematics -v` without an arm. Physical A7
acceptance (five test points within ~2 cm) is still pending.

### A6 offline implementation and hardware acceptance

Implemented the complete `Arm` interface with a LeRobot backend, persistent
30 Hz bus-owner/playback thread, and a single synchronous inference caller
every 15 rows. RTC uses delay 12, a strict capture+400 ms acceptance deadline,
committed rows (including rate limits), and boundary-based chunk switching.
Expired coverage holds and resets histories; late replies cannot execute.
Stop conditions: max_s (false), closed-and-still (true; controller checks grasp),
or a latched nonblocking freeze (false). Session reset between same-instruction
runs; changed instruction deletes the old session and requests a new grant.
Signed Feetech load is read directly, never taken from the policy.

On Python 3.10.11, all 26 offline tests pass:
`python -m unittest discover -s arm -t . -p "test_*.py" -v`.
`python -m arm --dry-run --self-test` also succeeds with synthetic saved PNGs
and fake joints, reporting `closed_and_still`. This does not validate the remote
API, learned behavior, calibration, orientation, or physical safety.

Remaining checks at the arm, with a clear workspace and an operator ready to
stop power (no sharp tool or person in the work envelope initially):

1. Complete the measured rig/contract/environment checklist in `arm/README.md`.
   No real connection is allowed by the shipped template.
2. Resolve Caiden's four integration items in `arm/README.md` before calling
   the whole controller flow reliable. His files were not edited.
3. `python -m controller --real-arm`: confirm calibrated joints/camera feeds,
   then request `pick the hemostat`. Confirm the arm holds on an empty/late
   response and on stop, does not replay an old reply, and never releases during
   carry. Use a blunt practice object for first motion tests.
4. Verify five measured in-region targets through the controller with the
   smallest suitable speed; measure tip error (goal ~2 cm), check tool attitude
   and handle-first presentation separately. FK/IK round trips are not a
   substitute for this physical check.
5. Measure load changes and test explicit `got_it`, safe-spot arrival/release,
   stopped-state rearm, and unavailable-policy handling. No claim of clinical
   validation or hardware success has been made.

The dataset format, training and inference calls are in `docs/PERCEPTRON-ROBOTICS.md`. Short version: 30 FPS, cameras named `side` and `wrist` at 640x480, six joint values with the gripper at 0 to 100, and a public Hugging Face repo or a direct upload.

## Connecting (LeRobot SO-101)

1. `pip install -e ".[feetech]"` inside a LeRobot checkout.
2. `lerobot-find-port` for each arm. Unplug when asked and it prints the port.
3. `lerobot-calibrate` for the follower (robot) and the leader (teleop). Give each a fixed `id` and always reuse it.
4. `lerobot-teleoperate`, with `--robot.cameras` and `--display_data=true` to watch.
5. `hf auth login`, then `lerobot-record`:
    - `--dataset.single_task "pick the hemostat"` (the instruction)
    - `--dataset.num_episodes 15`
    - `--robot.use_degrees=true --dataset.fps=30`
    - `--dataset.episode_time_s=25 --dataset.reset_time_s=10`
    - one dataset `<user>/scrub`, one calibration and fixed camera mounts
    - append later batches with `--resume=true --dataset.root=<same local root>`
    - right arrow or n ends an episode, left arrow or r re-records it, Escape or q stops and encodes; Hub push only if configured
    - `--dataset.push_to_hub=false` if we're not using the Hub
6. Replay episode 0, check the ~30 Hz cadence report and API validation before spending a training run.
7. Fine-tune with `python -m arm.train`; remote inference runs through `Arm`, not a local LeRobot policy rollout.

Perceptron's arms come assembled, so skip `lerobot-setup-motors` unless they say otherwise.

## One demonstration

- **Hand out:** the arm starts at home, the item in its slot. Pick it by the handle, lift to the carry pose, hold still. The move to the hand isn't recorded, since `move_to` plans it from the hand tracker. For the scalpel, place it in the safe spot instead.
- **Put back:** the item lies in the return spot. Pick it, place it in its slot.
- Instructions: `pick the <name>` and `return the <name>`, matching `settings/*.json`.

## What varies between demos

- the item's position and angle in its slot and in the return spot (small shifts)
- the lighting: a third each in bright, normal and dim
- which other items are on the tray

## Recording order

| Order | Setting | Items | Demos | Arm time |
| --- | --- | --- | --- | --- |
| 1 | Operating room | scalpel handle, hemostat, Mayo scissors | 75 | about 1 h 15 min |
| 2 | ~~Dental~~ dropped: more operating room demos instead (another 10 per item, mostly bright light and new slot positions) | | 30 | about 30 min |
| 3 | Bench | needle-nose pliers, wire cutters, hex key | 75 | about 1 h 15 min |

Per item: 15 hand-out and 10 put-back. Two people: one on the leader arm, one resetting and logging in `docs/DATA-LOG.md`.

If arm time turns out short, cut in this order: bench put-back, then dim light for bench (dental is dropped). Was: dental put-back, then dim light for dental and bench. Never cut the operating room set.

## Fine-tuning runs

1. **Run 1:** right after the operating room set, to see early whether grasps work.
2. **Run 2:** all three settings.
3. Add corrective demos to the same dataset before run 2. The workshop budget is only two successful jobs; no third fix-up run unless live capabilities explicitly allow it. Each run starts from the base model, so run 2 includes every earlier episode too.

## Item placement

Instruments lie flat, spaced apart, in the same taped slot every time. If a thin instrument is hard to grip flat, a folded strip of towel under the handle lifts it so the gripper can close around it.

## Capabilities with our team key (Sat 5:45 PM)

`python -m arm.train capabilities` works. Limits:
- backends: `standard` (`expert_only`, `backbone_lora`, `full`), `shared` (`expert_only`)
- horizon 30, 30 fps, stride 15, max prefix 12, deadline 400 ms, RTC on or off
- steps: 1000 only
- **2 successful jobs per team**
- max dataset 20 GiB, job timeout 6 h
- ready for training: yes
