# Arm, recording and fine-tuning

Owner: Anish. The workshop is the source of truth. Where it differs from below, the workshop wins and this file gets updated.

## Workshop notes

The full notes from the workshop deck are in `explore/research/isaac-workshop-notes.md` (sections 2 and 5). Where they differ from this file, the notes win, except limits that the live API reports (see "Capabilities with our team key"). Answers we have:

- Arm time: we have the arm the whole competition.
- One dataset can hold several instructions, and the model follows the instruction text. We use one dataset, `<hf user>/scrub`.
- The model gives positions only, no gripper load. We read load from the Feetech bus.
- Predict latency per chunk is about 283 ms at p95. A 1,000-step run takes about 45 minutes plus export.
- Open: image augmentation in their pipeline, whether the arm comes to judging (see the message for Perceptron staff in `team/DEMO.md`), and whether LeRobot's end-effector control works on the SO-101 (we use our own IK in `arm/kinematics.py`).

## Perceptron's format

### A2 capabilities check (Oct 18)

`python -m arm.train capabilities` answers with the team key from this Mac's `.env` (see the limits at the end of this file). `python -m arm.train deployments` returns an empty list, so no model is trained yet.

The client, CLI and uploader are implemented; five offline tests pass with
`python -m unittest arm.test_perceptron -v` (control routes checked against the
saved OpenAPI, auth isolation, multipart inference, upload hashing/batches,
303 polling, sanitized errors). No dataset was uploaded or training started.

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

`arm/rig.json` is not a verified calibration. Hardware is disabled
(`hardware_verified: false`); `home` is a measured folded pose, and `carry`,
`safe_spot` and the axis signs and offsets are still unmeasured. The gripper mapping
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

On Python 3.10, all 134 offline arm tests pass:
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
| 1 | Operating room | scalpel handle, hemostat, Mayo scissors | 90 (20 pick + 10 return per item) | about 1 h 30 min |
| 2 | Bench | needle-nose pliers, wire cutters, hex key | 75 (15 pick + 10 return per item) | about 1 h 15 min |

Per item: 20 pick and 10 return for the operating room, 15 pick and 10 return for the bench. Two people: one on the leader arm, one resetting and logging in `docs/DATA-LOG.md`.

If arm time turns out short, cut in this order: bench put-back, then dim light for bench (dental is dropped). Never cut the operating room set.

## Fine-tuning runs

1. **Run 1:** right after the operating room set, to see early whether grasps work.
2. **Run 2:** the operating room and bench settings.
3. Add corrective demos to the same dataset before run 2. The workshop budget is only two successful jobs; no third fix-up run unless live capabilities explicitly allow it. Each run starts from the base model, so run 2 includes every earlier episode too.

## Item placement

Instruments lie flat, spaced apart, in the same taped slot every time. If a thin instrument is hard to grip flat, a folded strip of towel under the handle lifts it so the gripper can close around it.

## Capabilities with our team key (live, Oct 18)

`python -m arm.train capabilities` works. Limits:
- backends: `standard` (`expert_only`, `backbone_lora`, `full`), `shared` (`expert_only`)
- horizon 30, 30 fps, stride 15, max prefix 12, deadline 400 ms, RTC on or off
- steps: 1000 only
- **Successful jobs per team: the API now reports 5.** The workshop said 2, and we still plan only two runs until staff confirm the higher number.
- GPU budget: 1200 GPU hours for the account, 64.8 used; a `standard` job reserves 48
- max dataset 20 GiB, job timeout 6 h (production), 2 h (qualification)
- ready for training: yes
