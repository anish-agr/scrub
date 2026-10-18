# Hardware to-do (ordered)

## Tonight's plan (Sun Oct 18, 00:45 to 09:30)

Goal: a fine-tuned model that passes real tries, and a Perceptron arm video. Training is the only thing on a clock, so the data steps come first and everything else runs while it trains. Times are targets; if a step slips, cut the later steps in the order given at the end.

Rule for every step: one process owns the arm ports and the cameras. Before each step stop the one before it (teleop, `explore/arm_session.py`, `arm.record`, the controller, `python -m vision`). Right now the recorder `explore/arm_session.py` (pid 73879) owns both. Roles come from `docs/TASKS.md`: Anish arm and training, Caiden controller and tools, Brandon vision and the clinician hand, Evan tray, lamp, `docs/DATA-LOG.md` and the video edit.

Facts checked at 00:50 (read-only): `arm.train deployments` returns an empty list (no ready deployment), `status deployment` on the id in `.env` returns HTTP 404, and no job or dataset id is written in any doc. The "2 successful jobs" quota is Perceptron's default. Nothing in the repo shows a job submitted. Treat run 1 as the first real job and do not assume a model exists. Check: `.venv/bin/python -m arm.train status job <id>` once Anish has the id.

| Clock | Step | Who | Process that owns the arm and cameras |
| --- | --- | --- | --- |
| 00:45 to 01:00 | 1. Cameras. Stop the recorder (Ctrl+C in its terminal). Both cameras to 30 fps at 640x480 in `.venv/bin/python -m arm.check_setup --side C920 --wrist icspring --seconds 3` (steps 1 and 2 below). Lamp on, direct USB ports. If the wrist camera will not reach 28 fps, write which port, light or setting fixed it in `docs/DATA-LOG.md` notes | Anish at the cameras, Caiden reads the output | `arm.check_setup` only |
| 01:00 to 01:15 | 2a. Tape the base, tray outline, slots, return spot and both camera mounts (step 3 below). Cameras never move after this | Anish, Evan | none |
| 01:15 to 01:20 | 2b. One slow teleop test (step 4): `.venv/bin/python explore/arm_session.py --side C920 --wrist icspring`, look at http://localhost:8090, then Ctrl+C | Anish | `explore/arm_session.py` |
| 01:20 to 01:40 | 2c. Teach `home`, `carry`, `safe_spot` and the handoff box into `arm/rig.json`, plus the shoulder_lift offset (step 5). Torque stays off after exit | Anish; Caiden reviews `arm/rig.json` | `arm.teach` only |
| 01:40 to 02:30 | 3. Run 1 data: hemostat only, 30 to 40 episodes, "pick the hemostat" and "return the hemostat", in normal and bright light (about 20 pick and 10 to 20 return, half and half per light). `--print-only` first, then the same command without it (step 6). Cadence line must say about 30 Hz after each episode. Log every batch in `docs/DATA-LOG.md` | Anish drives the leader, Evan resets the item, moves the lamp, writes the log | `arm.record` only. Brandon does vision slot boxes (step 8, B5) on his own laptop view with no arm or camera ports from this Mac while recording |
| 02:30 to 02:50 | 4. Gates, read-only on the dataset: `.venv/bin/python -m explore.dataset.qa --root ~/scrub-dataset --out ~/qa.html`, then `.venv/bin/python -m arm.train pipeline ~/scrub-dataset --cadence-report ~/scrub-dataset-cadence.json --check-only` (this runs the `arm/dataset_check.py` checks; the module has no CLI of its own). Replay episode 0 on the arm (step 7.3). Fix every FAIL, re-record those episodes | Caiden runs QA, Anish replays | `lerobot-replay` for the replay, then nothing |
| 02:50 to 03:05 | 5. Upload and start run 1 (step 7.6, key `scrub-run-1`). Anish says "approve" out loud; Caiden checks the printed job id and the command before it runs. Write the job id in the chat and here | Anish, Caiden | none (training is in the cloud) |
| 03:05 to 04:15 | 6. While run 1 trains (about 1 h plus export): record the Mayo scissors and the scalpel (pick goes to the safe spot) into the same dataset, normal and bright, about 25 pick and 10 return each; then teach taught skills for hemostat, scissors, scalpel: `.venv/bin/python -m arm.teach skill <item> pick` and `return` (`docs/TEACH.md`, being written; confirm with `python -m arm.teach --help`). Follow the job: `.venv/bin/python -m arm.train follow <job-id>` in a separate terminal | Anish and Evan record, then Anish teaches. Caiden watches the job and runs QA on the new batches | `arm.record`, then `arm.teach`, one at a time |
| 04:15 | 7. Check run 1: `.venv/bin/python -m arm.train deployments` shows a ready deployment and `PERCEPTRON_DEPLOYMENT_ID` is set. If it is not ready by 04:45, keep recording and teaching and ask the Perceptron staff | Anish, Caiden | none |
| 04:20 to 05:10 | 8. 10 real tries for the hemostat through the controller with `--skills model`: `.venv/bin/python -m controller --real-arm --skills model` plus vision, then ask by `curl` or voice. Brandon is the hand, Evan resets, Caiden holds Space. Log each try (`controller/trials.py` or the ledger). The hemostat is `model` only if it passes | Anish, Brandon, Evan, Caiden | the controller only. Stop it before anything else touches the arm |
| 05:10 to 05:20 | 9. Run 2 on the full surgical dataset if QA is clean (key `scrub-run-2`). It is the last run. Start no later than 05:30 so it finishes before 07:00 | Anish, Caiden | none |
| 05:20 to 06:30 | 10. While run 2 trains: 10 tries per item with the taught skills (`--skills taught`) for the scissors and the scalpel, ledger rows labeled `taught`. Brandon finishes slot boxes and `vision/calibration.json` (steps 8, B6) if not done. Evan starts `python -m video ingest` on the clips filmed so far. Short sleep in shifts: at most two people asleep at once | all | the controller only |
| 06:30 to 07:15 | 11. Run 2 deployment ready: 10 tries per item with `--skills model` (hemostat, scissors, scalpel). Each item goes to `model` only if it passes its last 3 tries; `--skills auto` then picks per item. Success table comes from the ledger. If run 2 is not ready by 07:15, run level 1 on run 1 only | Anish, Brandon, Evan, Caiden | the controller only |
| 07:15 to 08:15 | 12. Film with `video/`: real tries only, cleaned only, the success table from the ledger as the end card, `video/edl/perceptron-arm.yaml` (exists). Render: `.venv/bin/python -m video render --edl video/edl/perceptron-arm.yaml --bindings edit.json --output renders/perceptron-arm.mp4` (see `video/README.md`). The arm is free once filming ends | Anish operates, Evan films and edits, Caiden runs `video/` | the controller for filming, then nothing |
| 08:15 to 09:15 | 13. Devpost: upload the video, paste the measured numbers from the ledger, mark anything unproven as unproven. Fill `docs/PITCH.md` and `docs/SLIDES.md` blanks marked "to fill from the ledger". Choose the demo level (`docs/DEMO.md`) | Evan (Devpost), Caiden (docs), Anish (review) | none |
| 09:15 to 09:30 | 14. Submit on Devpost. Pack the arm, power strip, spare cable, laptop and tape for the Ballroom (judging 10:30, HUB Ballroom) | everyone | none |

What to cut if time runs short, first to last: sleep stays; drop the dim and extra-light batches; drop run 2 and use run 1 plus taught skills (level 1 still says which source each item used); drop the bench tray entirely (it is not part of this plan); 10 tries per item becomes 5 and the table says 5. Never cut QA before an upload and never film with a failed try removed without saying "cleaned" in the video.

The step sections below still apply. The numbers in "What the evidence says" were written on Oct 17.


Written Oct 17 from evidence on the arm Mac (files, logs, the camera check), not from STATUS.md. Do the steps in order. Commands are bash on this Mac, from the repo root. Only one process may own the arm ports and the cameras at a time: stop teleop, recording, vision and the controller before each step.

## What the evidence says right now

| Thing | Found | Where |
| --- | --- | --- |
| Arm ports | Both present: follower `/dev/tty.usbmodem5C821089781`, leader `/dev/tty.usbmodem5C821067211` (listed, not opened) | `python -m arm.check_setup --no-cameras` |
| Side camera (C920) | NOT plugged in or not seen. The Mac sees only `icspring camera` (index 0) and `MacBook Pro Camera` (index 1). Logs: 76 lines "running without the side camera (C920)" | check_setup, `~/scrub-logs` |
| Wrist camera (icspring) | 640x480 but 22.6 fps, needs 28 or more. A test frame today was lit (mean brightness 118 of 255) but earlier episodes were dark, and one saved test set is named `blackwrist` | check_setup run on Oct 17, `explore/dataset/README.md` |
| Overhead camera | Not a LeRobot camera. Vision on :8001 is running with `--fake`; no real overhead camera is in use | `ps` |
| Calibration ids | Follower `scrub_follower`, leader `scrub_leader`, in `~/.cache/huggingface/lerobot/calibration/`. Follower was recalibrated at 21:49 (backup at 21:37); leader at 17:51. No recording or teleop has run since the follower recalibration | file times, last log 21:29 |
| Earlier fault | Log: "wrist_flex reads 421, outside its calibrated range: torque off, recalibrate". The 21:49 recalibration was the fix; it is not yet proven by a run | `~/scrub-logs` |
| `arm/rig.json` | UNMEASURED template: `hardware_verified: false`, zero offsets, signs all 1, `home`, `carry`, `safe_spot` all null, handoff region is the default box | `arm/rig.json` |
| Rest pose | shoulder_lift rests at about -103.7 deg, past the URDF limit of -100. Suggested +4 deg offset in `arm/rig.json`, to be measured | `explore/dataset/README.md` |
| Recorded dataset | `~/scrub-dataset` does not exist. Only two 4-episode test sets: `~/scrub-dataset-backup-1820` and `~/scrub-dataset-blackwrist-1820` (4 episodes, 3000 frames each, one task). Neither counts toward training | `meta/info.json` |
| `docs/DATA-LOG.md` | No rows (header only). 0 episodes logged | file |
| Cadence report | None (`~/scrub-dataset-cadence.json` missing) | `ls ~` |
| Slot boxes | `slot: null` for all 3 items in surgical, bench and dental; `return_spot: null` in all three. B5 not done | `settings/*.json` |
| `vision/calibration.json` | Does not exist. B6 not done | file |
| `vision/hand_heights.json` | Default only: 0.18 m, no clinician entries | file |
| Training | No job. `python -m arm.train deployments` prints `Perceptron HTTP 401`: the robotics team key (`PERCEPTRON_TEAM_API_KEY`) is rejected. `PERCEPTRON_DEPLOYMENT_ID` is set in `.env` but cannot be checked until the key works | arm.train, deploy |

One mismatch to fix first: `docs/DATA-LOG.md` says targets 15 hand-out and 10 put-back per item. `docs/TRAINING.md` says 20 pick and 10 return for surgical, 15 and 10 for bench. This file uses TRAINING.md.

## Steps

### 1. Fix the wrist camera (Anish or Caiden, 15 min)

Problem: icspring runs at 22.6 fps; LeRobot needs 30. Low light makes this camera stretch its exposure and drop frames, so fix light and USB first.
1. Plug the icspring directly into a Mac port (no hub). Turn the lamp on so the grasp area is bright.
2. Close everything that uses a camera (Zoom, Discord calls, browser tabs on camera pages, `explore/arm_session.py`).
3. Run: `.venv/bin/python -m arm.check_setup --wrist icspring --seconds 3`
4. You should see `wrist ... 640x480 ... 30.x ... PASS`, and the frame at the printed path should be bright and show the gripper jaws and the table.
5. If fps is still under 28: try another USB port on the other side of the Mac, then a different cable, then run it again with the lamp brighter. If it only passes in bright light, record bright and normal only and drop dim for the wrist camera, and say so in `docs/DATA-LOG.md` notes.
6. If still stuck: the camera is the problem, swap it for another UVC webcam, or ask the Perceptron staff. Do not record at under 29 Hz: the metadata would still claim 30 fps.

### 2. Get the side camera seen (Anish or Caiden, 5 min)

1. Plug in the C920 directly (not through a hub). Run: `.venv/bin/python -m arm.check_setup --no-cameras`
2. You should see three cameras: `HD Pro Webcam C920`, `icspring camera`, `MacBook Pro Camera`.
3. If the C920 is missing: another cable and port; unplug and replug. Last resort: any other 640x480 webcam, and pass its name part with `--side`.
4. Then run: `.venv/bin/python -m arm.check_setup --side C920 --wrist icspring --seconds 3`
5. You should see both roles PASS at about 30 fps and a final `PASS` line. Look at both saved frames. Known issue: the side camera repeated about half its frames (15 fps doubled to 30). If the C920 reports 30 but looks choppy, the room is too dim for it; brighten the room.

### 3. Tape the setup (Anish and one person, 10 min)

Tape the arm base, tray outline, slots, return spot, both camera mounts. After this, cameras never move for the whole dataset. Keep the safe spot clear and apart from the handoff region.

### 4. One slow teleop test after the recalibration (Anish, 5 min)

1. Run: `.venv/bin/python explore/arm_session.py --side C920 --wrist icspring`
2. Open http://localhost:8090. Move the leader slowly through the full range, including the wrist and the gripper.
3. You should see the follower copy it, both camera feeds live, the loop line at about 30 Hz, and no "joint guard" lines. Press Ctrl+C to stop.
4. If you see `joint guard: wrist_flex ... outside its calibrated range`: run `.venv/bin/python explore/calibrate_follower.py` (it backs up the old calibration; cycle the 12 V power first if a motor reads past one turn). Do not record around a sign or range fault.
5. `--check` with no hardware: `.venv/bin/python explore/arm_session.py --check` says whether `~/scrub-dataset` is ready to train (it will say no until step 7).

### 5. Teach poses and measure the arm (Anish, 20 min)

1. Support the empty arm by hand, close teleop and the controller. Run: `.venv/bin/python -m arm.teach --port /dev/tty.usbmodem5C821089781 --robot-id scrub_follower --supported-and-empty`
2. Move by hand, then key plus Enter: `h` home, `c` carry, `s` safe spot, `a` and `b` opposite corners of the handoff box (at least 1 cm apart on every axis), `p` to print, `q` to quit. Torque stays off after it exits.
3. You should see `home`, `carry`, `safe_spot` and the handoff region filled in `arm/rig.json`, and `hardware_verified` still false.
4. Also measure the shoulder_lift offset (suggested +4 deg) and the joint signs against real positions, and put them in `arm/rig.json`. Test that `.venv/bin/python -m arm --dry-run --self-test` still passes.
5. If it rejects a corner or a pose: restart teaching, read the message. Do not set `hardware_verified` yet.

### 6. Recording, surgical set (Anish drives, one person resets; about 1.5 hours)

Targets from `docs/TRAINING.md`, split bright, normal and dim in thirds, item moved slightly in its slot each time:

| Item | pick | return | per lighting (pick / return) |
| --- | --- | --- | --- |
| scalpel (pick goes to the safe spot) | 20 | 10 | about 7 / 3 each |
| hemostat | 20 | 10 | about 7 / 3 each |
| Mayo scissors | 20 | 10 | about 7 / 3 each |

Recorded so far: 0 of 90 (the two 4-episode test sets are not part of the dataset).
1. Always look first: `.venv/bin/python -m arm.record --task "pick the hemostat" --lighting bright --episodes 5 --side C920 --wrist icspring --print-only`
2. Then run it without `--print-only`. Keys: `n` or right arrow ends an episode, `r` or left arrow re-records, `q` or Esc saves and quits. Recorder page: http://localhost:8090.
3. Check the cadence line after each episode: about 30 Hz. If it is under 29, close apps and re-record those episodes.
4. Next batches: same command with `--task "pick the scalpel"`, `"pick the mayo scissors"`, `"return the hemostat"` and so on, and `--lighting normal` or `dim`.
5. After each batch you should see one new row in `docs/DATA-LOG.md`. If not, add it: `.venv/bin/python -m ledger log --setting surgical --item hemostat --direction hand-out --lighting bright --demos 5 --dataset local --notes "cadence ok"`
6. Bad or blocked-camera episodes are thrown away, not kept.

### 7. Check the dataset, replay, then run 1 (Anish)

1. QA: `.venv/bin/python -m explore.dataset.qa --root ~/scrub-dataset --out ~/qa.html`, open `~/qa.html`. Fix every FAIL.
2. Variety: `PYTHONPATH=. .venv/bin/python explore/dataset/variety.py --root ~/scrub-dataset --out ~/variety.html`
3. Replay episode 0 on the arm (clear the workspace, blunt object, nobody in the path): `lerobot-replay --robot.type=so101_follower --robot.port=/dev/tty.usbmodem5C821089781 --robot.id=scrub_follower --robot.use_degrees=true --dataset.repo_id=<HF_USER>/scrub --dataset.root=$HOME/scrub-dataset --dataset.episode=0`. It should repeat the recorded move.
4. Local check: `.venv/bin/python explore/arm_session.py --check` then `.venv/bin/python -m arm.train pipeline ~/scrub-dataset --cadence-report ~/scrub-dataset-cadence.json --check-only`. It should list no problems and every episode at 29 to 31 Hz.
5. Fix the robotics key first (see `docs/ACCOUNTS-TODO.md`, Perceptron). Check: `.venv/bin/python -m arm.train deployments` must not print `Perceptron HTTP 401`.
6. Run 1 (only 2 successful runs allowed in total, never start one before the check passes): `.venv/bin/python -m arm.train pipeline ~/scrub-dataset --cadence-report ~/scrub-dataset-cadence.json --repo-id <HF_USER>/scrub --revision <HF_COMMIT> --idempotency-key scrub-run-1 --confirmed-replay --confirmed-hf-matches-local`
7. You should see the dataset ready, validation passed, a job id, then a ready deployment, and `PERCEPTRON_DEPLOYMENT_ID` written to `.env`. If the reply is lost, rerun the same command with the same key; never use a new key to retry. State is in `.env.pipeline-scrub-run-1.json`. Validation failed: `.venv/bin/python -m arm.train validation <dataset id>`, fix, make a new dataset.

### 8. While run 1 trains (about 1 hour): record the bench set, B5 and B6

Bench targets (same dataset, same cameras, `--resume` is automatic):

| Item | pick | return |
| --- | --- | --- |
| needle-nose pliers | 15 | 10 |
| wire cutters | 15 | 10 |
| hex key | 15 | 10 |

Recorded so far: 0 of 75. Example: `.venv/bin/python -m arm.record --task "pick the hex key" --lighting normal --episodes 5 --side C920 --wrist icspring`. Use the exact words from `settings/bench.json`.

B5, slot boxes (Brandon, with the tray in place, one real overhead camera): set `CAMERA_INDEX` in `.env` to the overhead camera, then
`.venv/bin/python -m vision` (own terminal), then
`curl -s http://localhost:8001/snapshot -o ~/scrub-tray.jpg` and
`.venv/bin/python -m vision.mark_slots --setting surgical --image ~/scrub-tray.jpg`, then the same for `--setting bench`.
You should see `slot` and `return_spot` filled in `settings/surgical.json` and `settings/bench.json` (they are null now). Check with `curl -s localhost:8001/tray_check`. If boxes land in the wrong place, the camera moved: re-snapshot and redo.

B6, camera-to-arm calibration (Brandon with Anish): vision must run with the real camera (not `--fake`), controller stopped, arm still. Run `.venv/bin/python -m vision.calibrate`, enter one line per point as `pixel_x pixel_y arm_x arm_y arm_z` in meters, 6 to 8 spread points, then a blank line. Add held-out points. You should see an error under about 2 cm on the held-out points and a new `vision/calibration.json`. Restart vision. The command can write a file even if the error is over 2 cm: do not accept it then. Then open http://localhost:8001/ and check `target` is non-null for a hand, and `path_clear` changes when you put an obstacle in view. Also record one real `vision/hand_heights.json` entry for the person who will take the tool (default is 0.18 m).

### 9. Test run 1, then fill gaps (Anish, Caiden)

1. Controller with the real arm: `.venv/bin/python -m controller --real-arm --setting surgical`. It must not move on connect.
2. Ask for one item: `curl -s -XPOST localhost:8000/command -H 'content-type: application/json' -d '{"action":"handover","item":"hemostat","source":"keyboard"}'`. Spotter ready, blunt object, stop key in reach (`curl -XPOST localhost:8000/stop`).
3. You should see pick, carry, slow approach to the hand, release only after a pull or `got_it`, then home. If an item fails often, record 10 more episodes of it for run 2.
4. Reset after a stop needs a person: `curl -XPOST localhost:8000/reset -H 'content-type: application/json' -d '{"clear_count":false}'`.

### 10. Five-point reach check and gripper load check (R4, Anish; before `hardware_verified`)

1. Reach: command the arm to 5 spread points inside the handoff box (corners and center) with `move_to`, read the tip with a ruler. Each must land within about 2 cm. Also check the tool attitude (handle toward the person; position IK does not set pitch). If a point misses: fix signs, offsets or the base transform in `arm/rig.json`, repeat all five.
2. Gripper load: close on a real item and on air, read the signed `Present_Load` from the bus both times (`arm/real_arm.py` `gripper_load()`). You should see a clear signed change when the item is held, and another when a person pulls. If there is no usable change, the controller falls back to `got_it`: leave pull release off and say so in the demo.
3. When both pass: put the measured poses, region and limits in `arm/rig.json`, run `.venv/bin/python -m arm.train contract <DEPLOYMENT_ID>`, pin its `contract_id` in `verified_contract_id` after checking six joints in order, absolute targets, two cameras, horizon and rate 30, RTC delay 12, then set `hardware_verified: true`. Check `.venv/bin/python -m unittest arm.test_kinematics arm.test_real_arm -v` still passes.

### 11. Run 2 (Anish; the last run)

Only after step 8 recording is done and run 1 has been tested. Same pipeline command with `--idempotency-key scrub-run-2`, on the whole dataset (surgical 90 plus bench 75 plus corrections). Confirm with `.venv/bin/python -m arm.train deployments` that a new ready deployment exists, and update `PERCEPTRON_DEPLOYMENT_ID` (the pipeline does it). Do not start a third run unless staff allow it.

### 12. Live handoff by voice (Caiden, Anish)

1. Real arm up (step 9), voice on :3000 already live. Text test: `curl -s -XPOST localhost:3000/heard -H 'content-type: application/json' -d '{"text":"grab me the kelly"}'` (this moves the real arm).
2. Then a call or text. You should hear "Hemostat coming.", see the arm hand over, "got it" release, and home. "stop" must hold the arm at any point. If voice is silent, see the Custom LLM URL item in `docs/ACCOUNTS-TODO.md`.

### 13. Ten clean runs, then the success tests (Anish, Evan, with a spotter)

1. Ten clean live runs in a row on the surgical tray, then the bench tray (a clean run is a correct handoff, no stop, no touch-ups). Restart the count after any failure.
2. Success tests (human confirms physical success after each try, failures count): `.venv/bin/python -m controller.trials --plan-only` first (195 trials: 90 surgical, 60 bench, 45 returns), then `.venv/bin/python -m controller.trials --settings surgical --items hemostat --lighting normal --actions handover --tries 2` and widen. `MONGODB_URI` should be set on this Mac first (see accounts) or results sit in the local buffer.
3. You should see each try logged in the ledger and the tables on the dashboard.

### 14. Perceptron arm video (Anish, 15 min)

Record one clean real handoff with the side view and the wrist view, plus the arm in frame, from request to home. Keep a clearly labeled backup (sim). Do not call it clinically validated. Save it outside the repo and upload it for Devpost.
