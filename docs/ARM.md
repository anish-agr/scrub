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

The dataset format, training and inference calls are in `docs/PERCEPTRON-ROBOTICS.md`. Short version: 30 FPS, cameras named `side` and `wrist` at 640x480, six joint values with the gripper at 0 to 100, and a public Hugging Face repo or a direct upload.

## Connecting (LeRobot SO-101)

1. `pip install -e ".[feetech]"` inside a LeRobot checkout.
2. `lerobot-find-port` for each arm. Unplug when asked and it prints the port.
3. `lerobot-calibrate` for the follower (robot) and the leader (teleop). Give each a fixed `id` and always reuse it.
4. `lerobot-teleoperate`, with `--robot.cameras` and `--display_data=true` to watch.
5. `hf auth login`, then `lerobot-record`:
    - `--dataset.single_task "pick the hemostat"` (the instruction)
    - `--dataset.num_episodes 15`
    - right arrow ends a demo early, left arrow re-records it, Escape stops and uploads
    - `--dataset.push_to_hub=false` if we're not using the Hub
6. Fine-tune with Perceptron's endpoint (the LeRobot equivalent is `lerobot-train`).
7. Run with `lerobot-rollout` (policy path, robot, `--task`), or Perceptron's inference endpoint.

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
| 2 | Dental | mouth mirror, explorer, cotton pliers | 75 | about 1 h 15 min |
| 3 | Bench | needle-nose pliers, wire cutters, hex key | 75 | about 1 h 15 min |

Per item: 15 hand-out and 10 put-back. Two people: one on the leader arm, one resetting and logging in `docs/DATA-LOG.md`.

If arm time turns out short, cut in this order: bench put-back, dental put-back, then dim light for dental and bench. Never cut the operating room set.

## Fine-tuning runs

1. **Run 1:** right after the operating room set, to see early whether grasps work.
2. **Run 2:** all three settings.
3. Any item under about 70% after a run gets 10 more demos before the next run.

## Item placement

Instruments lie flat, spaced apart, in the same taped slot every time. If a thin instrument is hard to grip flat, a folded strip of towel under the handle lifts it so the gripper can close around it.
