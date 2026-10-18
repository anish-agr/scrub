# How to train Scrub (one page to share)

> **Demo scope (Oct 18 morning):** the demo uses three instruments (scalpel handle, hemostat, Mayo scissors), and the arm goes home after each handoff. Return on the real arm is manual. This page is the plan. What happened: 29 episodes recorded (24 usable; scalpel handle, scalpel, hemostat, tweezers, spatula), none of the bench items below, lighting not logged per episode, and 0 Perceptron training jobs, so no model was trained or deployed. Real picks replay our recorded demonstrations (`explore/station/README.md`). Record the scalpel like the other picks, ending at the handoff point.

This is the plain version. Every command with every flag is in `docs/BRINGUP.md` sections 6 to 8. Run all of this on **the laptop the arm is plugged into** (the Mac), from the repo root, after `source .venv/bin/activate` (plain `python` is not on the Mac's PATH without it).

The checklist for the operator (the person or agent helping at the arm) is the section "Operator checklist" at the end of this page.

## The idea in four lines

1. A person moves the **leader** arm by hand. The **follower** arm copies it. That's teleoperation.
2. While that happens, LeRobot saves both cameras (`side`, `wrist`) and the six joint angles, 30 times a second. One try is one **episode**.
3. We upload the episodes to Hugging Face, and Perceptron fine-tunes its Isaac 0.5 model on them. One training run takes about an hour.
4. The trained model gets a **deployment id**. `arm/real_arm.py` sends it camera images and joint angles, and it sends back moves.

## Rules that matter

- **5 successful training jobs per team** (the live API reported this at 2:05 AM Oct 18; 0 used). Run 1 is the hemostat, pick and return, 30 to 40 episodes. Run 2 is all surgical items, started as soon as its data passes `python -m arm.train preflight`. A run 3 only to fix something runs 1 or 2 showed. Record with `explore/station/station.py` into `~/scrub-surgical` (not `~/scrub-dataset`, which holds spatula episodes), episodes under 20 s. Don't start a run until the dataset check passes.
- **One dataset for everything.** Same repo, same calibration, cameras never moved. Later batches add to it with `--resume=true`.
- **Use the exact instruction text** from `settings/surgical.json` and `settings/bench.json`: `pick the hemostat`, `return the hemostat`, and so on. The model is told the same words later.
- **Each episode is about 10 to 20 seconds.** "Pick" ends with the arm holding the item still at the carry pose. "Return" ends with the item in its slot and the arm back home.
- **Check the cadence line after each episode.** It must say about 30 Hz. If the laptop is slow, close other apps and re-record.
- Keys stay in `.env`. Never paste them anywhere.

## What to record

| Tray | Item | "pick the X" | "return the X" |
| --- | --- | --- | --- |
| Operating room | scalpel | 20 | 10 |
| Operating room | hemostat | 20 | 10 |
| Operating room | Mayo scissors | 20 | 10 |
| Bench | needle-nose pliers | 15 | 10 |
| Bench | wire cutters | 15 | 10 |
| Bench | hex key | 15 | 10 |

Split each row across bright (lamp on, close), normal (room lights) and dim (some lights off). Move the item a little in its slot between episodes. Every batch gets a row in `docs/DATA-LOG.md` (`python -m arm.record` writes it).

## Two people per session

- **Driver:** moves the leader arm. Smooth and slow, the same way every time.
- **Resetter:** puts the item back, changes the lighting, presses the keys: `n` ends an episode cleanly, `r` re-records a bad one, `q` finishes and saves.

## Steps

0. **Check the setup:** `python -m arm.check_setup --side C920 --wrist icspring` (Windows: `--side 0 --wrist 1`). Both arm ports, both cameras at 640x480 and about 30 fps, then a PASS line. Look at the saved test frames.
1. **Record** the operating room rows, one batch per instruction and lighting (`docs/BRINGUP.md` section 6). About 90 episodes, about 1.5 hours:
   `python -m arm.record --setting surgical --item hemostat --direction hand-out --lighting bright --episodes 5`
   (or `--task "return the hemostat"`; add `--print-only` to see the exact command first, and `--lerobot --follower <port> --leader <port> --side 0 --wrist 1` on the Windows laptop). It keeps one dataset (`<HF_USER>/scrub`, `~/scrub-dataset`, resumed automatically) and writes the batch's row in `docs/DATA-LOG.md`.
2. **Check** (section 7): replay episode 0 on the arm, then `python -m arm.train pipeline <dataset folder> --cadence-report <file> --check-only`. Fix anything it flags.
3. **Run 1** (section 8): `python -m arm.train pipeline ... --idempotency-key scrub-run-1 ...`. It uploads, waits for Perceptron's check, trains, and writes `PERCEPTRON_DEPLOYMENT_ID` into `.env` when the model is ready.
4. **While run 1 trains:** record the bench rows into the same dataset (`python -m arm.record --setting bench --item hex_key --direction hand-out --lighting normal --episodes 5`, and so on), and practice the pitch.
5. **Test run 1:** `python -m controller --real-arm`, then ask for the hemostat. Any item that fails a lot gets 10 more episodes.
6. **Run 2:** same pipeline command with `--idempotency-key scrub-run-2`, on the whole dataset.
7. **Success tests:** `python -m controller.trials` logs every try to the tables.

## If something goes wrong

| You see | Do |
| --- | --- |
| `401` | The Robotics team key is missing or wrong in `.env` |
| Cadence under 29 Hz | Close apps, re-record those episodes |
| Validation failed | Read `python -m arm.train validation <id>`, fix, make a new dataset |
| No deployment after training | Wait (export takes a while), check `python -m arm.train status job <job-id>` and `python -m arm.train deployments`, then ask Perceptron staff |
| The arm jerks or stutters | Network is slow: get closer to the router or use a wired connection |

## Operator checklist

For whoever sits at the arm and runs the batches and the two training runs. Work one step at a time. Before each step know whether it is read-only, opens cameras, moves the arm, publishes a dataset or can spend a training run. Report cadence lines and pass or fail only. Never paste keys, `.env` or signed URLs. Commands below use `$Var` for values you confirm first (PowerShell on Windows; use shell variables on the Mac). On Windows the arm ports are `COM...`, on the Mac `/dev/tty.usbmodem...`.

### Set up the session

Confirm and write down these before the first batch. Do not guess a value; find it.

| Field | How |
| --- | --- |
| Checkout | the real project folder and `git log -1`; run `git pull --rebase` if clean, never stash or discard other people's work |
| Follower and leader ports | `lerobot-find-port`, one cable at a time |
| Side and wrist cameras | `lerobot-find-cameras opencv` or `python -m arm.check_setup --no-cameras`; a person confirms which is which. Both are 640x480 at 30 fps. The overhead camera belongs to `vision/`, so do not open it |
| Calibration ids | the ones already saved (`arm.record` defaults to `scrub_follower` and `scrub_leader`). Never recalibrate or rename in the middle of a dataset |
| Hugging Face repo | one repo, `<hf user>/scrub`, with write access (`arm.record --hf-user` or `HF_USER`). Not separate repos per tray or per run |
| Dataset root | `~/scrub-dataset` (`--root`). New or resumed, and the current episode count |
| Cadence file | a JSON file outside Git, for example `~/scrub-cadence.json` |
| People | a driver and a resetter; workspace clear |

Keys: robotics uses `PERCEPTRON_TEAM_API_KEY`, vision uses `PERCEPTRON_API_KEY`, Hugging Face uses `HF_TOKEN` or an HF login. Check they exist without printing them (`python -m deploy`).

### Before the first accepted batch

- The driver moves the leader. The resetter restores the tray, changes the light, presses the keys and can cut power. The software stop is not an emergency stop.
- Use blunt practice tools and a scalpel handle with no blade. Keep people out of the arm's path. No handoff to a person while recording.
- One process owns the follower port and each camera. Stop teleop before recording or replay.
- State and action are six values in this order: `shoulder_pan.pos`, `shoulder_lift.pos`, `elbow_flex.pos`, `wrist_flex.pos`, `wrist_roll.pos`, `gripper.pos`. Five joints in degrees, gripper 0 closed to 100 open.
- Cameras are exactly `observation.images.side` and `observation.images.wrist`. The side camera sees the whole task, the wrist camera sees the grasp. Check with images, not metadata. Fix glare and occlusion before collecting more.
- Tape the base, tray, slots and camera mounts. Keep them fixed for every batch and both runs. Move the item a little inside its slot; do not move the layout or a camera.
- Do one slow teleop move first if the setup is new. Stop on unexpected direction, jerk or collision risk.

### Per-light targets

Pick / return episodes per cell. This is the split of the table above across the three lights. Count only accepted episodes.

| Tray | Item | Bright | Normal | Dim | Total |
| --- | --- | --- | --- | --- | --- |
| surgical | scalpel, hemostat, mayo_scissors (each) | 7 / 4 | 7 / 3 | 6 / 3 | 20 / 10 |
| bench | needle_nose_pliers, wire_cutters, hex_key (each) | 5 / 4 | 5 / 3 | 5 / 3 | 15 / 10 |

Totals: surgical 90, bench 75, together 165 before any extra corrective episodes. After every batch, write down accepted against target for each tray, item, direction and light, plus the episode indices, the lowest and highest measured Hz, and what is rejected or pending. A re-record (`r`) does not count twice.

Exact instruction text (from `settings/*.json`; aliases like "kelly" are for voice only, not for recording):

| Item id | Pick | Return |
| --- | --- | --- |
| scalpel | `pick the scalpel` | `return the scalpel` |
| hemostat | `pick the hemostat` | `return the hemostat` |
| mayo_scissors | `pick the mayo scissors` | `return the mayo scissors` |
| needle_nose_pliers | `pick the needle-nose pliers` | `return the needle-nose pliers` |
| wire_cutters | `pick the wire cutters` | `return the wire cutters` |
| hex_key | `pick the hex key` | `return the hex key` |

A non-sharp pick ends held, still, at the carry pose. A return starts from the return spot, places the item in its slot and ends at home. The scalpel pick ends at the handoff point like the other picks.

### One batch

One batch is one tray, item, direction, instruction and light. Start with a small normal-light hemostat pick batch of 5. Before it, say the task, light, how many episodes, how many already exist and that `--resume=true` applies (arm.record adds it for you after the first batch).

1. Record: `python -m arm.record ...` (step 1 above). `--episodes` is the number to add, not the total. Keys in the recorder: `n` or right arrow ends an episode, `r` or left arrow discards and re-records, `q` or Esc finishes and saves. Do not unplug while it encodes. Most episodes last 10 to 20 s; 25 s is the cap.
2. Cadence: read each episode's measured wall-clock rate. Accept 29 to 31 Hz. The nominal 30 fps in the metadata is not evidence. If the build reports no cadence, stop and ask for the instrumentation; do not fill in 30.0 or resample slow clips.
3. Reject anything slow, hidden, incomplete or on the wrong task, and re-record it with `r`. If it is already saved, stop and agree a repair; do not delete files by hand or renumber.
4. Update the cadence file, one entry per saved episode, with the real episode index and measured rate: `{"episodes": [{"episode_index": <int>, "measured_fps": <number>}, ...]}`. Cover every episode in the snapshot, no duplicates, no gaps.
5. Check: `python -m arm.train pipeline "$DatasetRoot" --cadence-report "$Cadence" --check-only` (needs at least two complete episodes). Exit 0 and fps 30 means the local check passed. It spends nothing and says nothing about video quality or physical success.
6. Log: `python -m arm.record` already appended a row to `docs/DATA-LOG.md`. For a batch recorded another way: `python -m ledger log --setting surgical --item hemostat --direction hand-out --lighting normal --demos 5 --dataset local --notes "<episode range, Hz min/max, rejects>"`. Direction is `hand-out` for pick and `put-back` for return. Dataset is `local` until the push has succeeded. Do not log planned batches or unmeasured values. Stage only `docs/DATA-LOG.md`, commit, `git pull --rebase`, push.

### Gates before each training run

Do not start a run until all of these have evidence and the team agrees. Two runs, `scrub-run-1` (operating room) and `scrub-run-2` (all 165 episodes plus corrections). Perceptron allows two successful jobs per team; do not submit speculative or replacement jobs. Check existing jobs first (`python -m arm.train deployments`).

1. Counts: run 1 meets the 90 surgical episodes; run 2 contains all of run 1 plus bench. Every episode has a measured 29 to 31 Hz.
2. A stable snapshot: encoding finished and nothing writing. Do not use a folder copied while recording.
3. Replay episode 0 on the real follower with a clear workspace and a spotter (this moves the arm). For run 2, also replay one episode of a newly added item:
   `lerobot-replay --robot.type=so101_follower --robot.port="$Follower" --robot.id="$FollowerId" --robot.use_degrees=true --dataset.repo_id="$Repo" --dataset.root="$DatasetRoot" --dataset.episode=0`
4. The offline check from step 5 above on that exact folder.
5. Publish to Hugging Face first (`arm.record --lerobot --push`, or `lerobot-record --dataset.push_to_hub=true`). `arm.train pipeline` registers the existing repo; it does not upload local files. Resolve the commit SHA of the pushed revision, not just `main`, and use it as `--revision`.
6. `python -m arm.train capabilities`: confirm `standard`, `expert_only`, horizon 30, RTC and 1000 steps are allowed, and write the result in `docs/ARM.md`.
7. Validation: the pipeline waits for the service to ingest the dataset and for a successful `/validation` before it submits a job. To look first: `python -m arm.train register-hf ...`, `status dataset <id>`, `validation <id>`. Do not use raw `train` to skip a gate.

### Submit once, monitor, resume

```
python -m arm.train pipeline "$DatasetRoot" --cadence-report "$Cadence" --repo-id "$Repo" --revision "$HfCommit" --idempotency-key scrub-run-1 --backend standard --mode expert_only --steps 1000 --confirmed-replay --confirmed-hf-matches-local
```

The pipeline sets horizon 30 and RTC on itself. Training takes about 45 minutes plus queue and export. It keeps its resume state in `.env.pipeline-scrub-run-1.json` in the repo root (the file name follows the key). A dropped connection or timeout does not cancel the remote job. To resume, run the same command again with the same key, revision, folder, cadence file and state file. Do not delete the state file, change the key or call raw `train`. An HTTP 409 or fingerprint mismatch is a stop. A failed job needs a person and Perceptron staff.

Read-only monitoring (use the ids it prints): `python -m arm.train status dataset|job|checkpoint|deployment <id>`, `validation <dataset-id>`, `follow <job-id>`, `deployments`, `contract <deployment-id>`.

When the deployment is ready, the pipeline writes `PERCEPTRON_DEPLOYMENT_ID` into the ignored `.env` and the public ids into `arm/run_info.json` (dataset URL, job, checkpoint, deployment, status). That file is not the private resume state. Copy the run's non-secret record (SHA, counts, ids, outcome) into this page or `docs/ARM.md` before run 2 replaces it.

Recording bench episodes while run 1 trains changes the folder and the cadence file the pipeline fingerprints, which can stop run 1 from resuming. Either leave the run-1 folder and cadence file untouched until the deployment is ready, or make a complete snapshot and a copied cadence file before submitting and pass those paths. Append bench only to the original cumulative folder in the same repo.

Run 2 uses `--idempotency-key scrub-run-2`, its own state file, a newly pinned revision of the whole dataset and the same gates. It starts from the base model, not from run 1. Do not train on bench alone. If run 1 shows weak items, record about 10 more episodes for each, log them and include them before run 2. A ready deployment does not make the rig safe; the gates in `docs/BRINGUP.md` section 10 still apply.

### Stop and ask

Missing keys, ports or cameras you cannot identify, two processes on one device, a moved camera, unsafe motion, missing or slow cadence, a count that disagrees with the log, an unfinished encode or upload, a failed replay, check or validation, unknown quota, the wrong revision, or changed resume inputs. Name the gate that failed and run one safe diagnostic. Never fix a blocked gate by spending a job.
