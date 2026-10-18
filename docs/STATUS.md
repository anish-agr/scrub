# Status

Agents: the first unchecked box in your person's section is the next task. Tick it when its "done when" passes and add one line under it: what works and how to run it. Edit only your person's section. Task details are in `docs/TASKS.md`.

## Anish

- [x] A1 workshop notes in `docs/ARM.md`
  - Covered by `explore/research/isaac-workshop-notes.md` and the capabilities block in `docs/ARM.md`.
- [x] A2 `arm/perceptron.py`, `arm/train.py`, `arm/upload_dataset.py`
  - Client/CLI/uploader implemented; `python -m unittest arm.test_perceptron -v` passes 5 offline tests. Live `python -m arm.train capabilities` blocked by missing `PERCEPTRON_TEAM_API_KEY` (no root `.env`). Anish authorized A7/A6 work while this check waits.
- [ ] A3 arm connected, both cameras, poses in `arm/rig.json`
- [ ] A4 operating room demos recorded (75)
- [ ] A5 fine-tuning run 1 started
- [ ] A6 `arm/real_arm.py` with `run_skill`
  - [x] Offline implementation/dry-run: complete interface, LeRobot adapter, 30 Hz playback + RTC predicts, stop/load/session tests. `python -m arm --dry-run --self-test` succeeds; all 26 arm tests pass on Python 3.10.11. Live API/hardware acceptance pending. Caiden integration items are in `arm/README.md`.
- [ ] A7 `move_to` with IK
  - [x] Offline FK/IK, random round trips, handoff-box preflight, speed limits and fake-joint `Arm.move_to` pass. Run `python -m unittest arm.test_kinematics arm.test_real_arm -v`. Real calibration and five-point ~2 cm hardware acceptance still pending; rig is an unmeasured, hardware-disabled template.
- [ ] A8 first real handoff by voice
- [ ] A9 dental and bench demos recorded
- [ ] A10 fine-tuning run 2, all 9 items
- [ ] A11 tests logged
- [ ] A12 Perceptron arm video
- [ ] P1 pitch script final
- [ ] P6 Commit Fellowship form
- [x] R1 training pipeline: local preflight/cadence, resumable HF registration, validation, training/follow, matching ready deployment and `.env` update; `python -m unittest arm.test_pipeline -v` passes 10 offline tests. Commands/evidence format in `arm/README.md`; no real job submitted.
- [x] R2 torque-off hand-guided teaching: `python -m arm.teach --port <port> --supported-and-empty`, h/c/s poses and a/b FK region corners, atomic rig updates with hardware verification cleared. `python -m unittest arm.test_teach -v` passes 8 offline tests; no real torque operation run.
- [x] R3 optional `Arm.prepare(instructions)`: instruction-bound session cache, reuse/cleanup/expiry/context handling, freeze-safe transactional preparation. `python -m unittest arm.test_prepare -v` passes 11 offline tests, including reuse by the real playback loop with fake joints. Base contract and Caiden's files unchanged.
  - Full owned arm suite: 55/55 offline tests pass; `python -m arm --dry-run --self-test` still succeeds. R4 waits for Anish to confirm the arm is plugged in and the Robotics team key is in `.env`.
- [x] Q1 `docs/BRINGUP.md`: PowerShell commands, expected results and recovery gates from ports/calibration through recording, training, overhead calibration and first voice handoff. Checked against current CLIs/routes; physical acceptance and team-key calls remain R4, not claimed as tested.
- [x] Q2 `controller/trials.py`: default 195-trial PLAN matrix, filters/N override, operator confirmation, command-correlated outcomes, local ledger calls and action-separated JSONL evidence; practice never logs measured trials. `python -m controller.trials --self-test` passes 19 offline tests including real fake-controller routes; `--plan-only` verifies counts. No other controller files edited.

## Caiden

- [x] C1 controller on the fake arm, every endpoint
  - `.venv/bin/python -m controller` (fake arm, port 8000). A curl handover runs finding → picking → checking → moving_to_hand → waiting_for_pull → releasing → homing, all on `WS /events`. Details in `controller/README.md`.
- [x] C2 pushed and announced
  - Pushed `ed084b6`. Point vision at `POST :8000/vision/hand` and `/vision/tray`; the dashboard at `WS :8000/events`, `GET /state`, `GET /setting`.
- [ ] C3 Photon call reaches `voice/`
- [ ] C4 Gemini commands, stop path, spoken replies
  - Works without a call: `curl -XPOST localhost:3000/heard -d '{"text":"grab me the kelly"}'` gives `handover hemostat` and "Hemostat coming." with Gemini live; mayo, "knife please", "what's out" and "stop" checked too. `cd voice && npm test` passes offline. Left: the same on a real Photon call (C3).
- [ ] C5 Checkpoint 1 shown
  - Ready on the agent side: voice → controller tested locally (`/heard` "grab me the kelly" → `handover hemostat`, lines spoken from events). Needs the team at 6 PM: phone call, Brandon's Hand posts, Evan's dashboard. Dry run: `.venv/bin/python -m controller.smoke --return`.
- [x] C6 real controller flows and failure cases
  - `.venv/bin/python -m controller.test_flows` forces each failure on the fake arm: 28/28 pass. Real-arm safe: stop latches until `POST /reset` (rearms with `resume()`, sets a held item at the safe spot), missing load falls back to `got_it`, failed set-down holds (Anish's arm/README handoff items 1-4). Sim: 3 clean full runs in a row. Covers grasp check + one retry, wait for pull/`got_it` (30 s), freeze on hand lost or path blocked, slow near the hand, the request-to-hand timer. Force live failures with `POST /fake/force`.
- [ ] C7 end-of-case summary text
  - Gemini writes it from the case events with the count first (from the controller's `out`), item names, no double counting; checked against a live fake-arm case. `POST localhost:3000/summary` sends it via Photon to the caller or `PHOTON_SUMMARY_TO`. Left: one real send to a phone.
- [ ] C8 ten clean full runs
  - Tool ready: `.venv/bin/python -m controller --real-arm` then `.venv/bin/python -m controller.smoke --runs 10 --human --return` counts the clean streak. Needs `arm/real_arm.py` (A6) and the arm.
- [x] P4 demo mode and backup run
  - `http://localhost:8000/demo`: 1/2/3 load the trays, R resets and clears the count (`POST /reset {"clear_count": true}`), Space/Esc stop, 3:00 cue cards and a rehearsal log. Checked live on the fake arm. A plain `POST /reset` now keeps the count after a stop. The backup full run is recorded Sunday morning.
- [ ] P2 backup slide deck

## Brandon

- [x] B1 camera with locked exposure
  - Locked exposure and white balance, default exposure -6 (`CAMERA_EXPOSURE` to override). `python -m vision` (add `--fake` with no camera). Preview at http://localhost:8001/. Checked on the Acer FHD camera: a fixed exposure stays put. With the overhead camera, a lamp should brighten the picture and leave it there.
- [x] B2 hand tracker posting Hand
  - MediaPipe hand landmarker posts a Hand about 10 times a second to `CONTROLLER_URL/vision/hand`. Open palm means all five fingertips are farther from the wrist than their middle joints. `target` stays null until `vision/calibration.json` exists. `python -m vision.test_vision`
- [x] B3 MJPEG stream
  - http://localhost:8001/stream draws slot boxes and the palm dot. The dashboard image is `<img src="http://localhost:8001/stream">`.
- [x] B4 tray perception posting TrayState
  - Perceptron `/v1/detect` about once a second, mapped onto slot boxes, posted to `/vision/tray`. A failed call keeps the last state and sets `stale: true`. The controller's `GET /setting` supplies aliases and boxes. Shapes are in `docs/PERCEPTRON.md`. Live calls need `PERCEPTRON_API_KEY` in `.env`. `python -m vision.test_vision`
- [ ] B5 slot boxes marked for all three trays
- [ ] B6 camera-to-arm calibration
- [x] B7 `path_clear` and saved hand height
  - `path_clear` is false when a second hand or a robot-arm box crosses the gripper-to-target segment. Hand height is saved per clinician with `POST /clinician`. `python -m vision.test_vision`. On the real camera, wave a hand through the path and the preview should say "path blocked".
- [ ] B8 lighting tests

## Evan

- [x] E1 three settings files
  - `settings/surgical.json`, `dental.json`, and `bench.json`. Only the scalpel is sharp. Slot and return boxes are null until Brandon sends them.
- [x] E2 dashboard live on the controller
  - Open http://localhost:8000/ after `python -m controller --fake-arm`. A handover updates the step, the log, what's out, and the handoff time. If the controller is down, the page shows a sample handover.
- [ ] E3 ledger in MongoDB Atlas
- [ ] E4 data log kept during recording
- [ ] E5 Devpost draft submitted by 10:00 PM
- [ ] E6 tables on the dashboard, public page on Vultr and the domain
- [ ] E7 demo video and final Devpost

## Checkpoints

- [ ] Sat 6:00 PM: a spoken request runs every step on the fake arm and shows on the dashboard
- [ ] Sat 10:00 PM: Devpost draft submitted
- [ ] Sat 10:30 PM: first real handoff by voice
- [ ] Sun 2:00 AM: all three settings, put-back and the count working
- [ ] Sun 6:00 AM: feature freeze
- [ ] Sun 9:30 AM: video uploaded, repo public, final Devpost submitted
