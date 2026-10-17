# Status

Agents: the first unchecked box in your person's section is the next task. Tick it when its "done when" passes and add one line under it: what works and how to run it. Edit only your person's section. Task details are in `docs/TASKS.md`.

## Anish

- [ ] A1 workshop notes in `docs/ARM.md`
- [ ] A2 `arm/perceptron.py`, `arm/train.py`, `arm/upload_dataset.py`
  - Client/CLI/uploader implemented; `python -m unittest arm.test_perceptron -v` passes 5 offline tests. Live `python -m arm.train capabilities` blocked by missing `PERCEPTRON_TEAM_API_KEY` (no root `.env`). Not complete; A7/A6 wait in requested order.
- [ ] A3 arm connected, both cameras, poses in `arm/rig.json`
- [ ] A4 operating room demos recorded (75)
- [ ] A5 fine-tuning run 1 started
- [ ] A6 `arm/real_arm.py` with `run_skill`
- [ ] A7 `move_to` with IK
- [ ] A8 first real handoff by voice
- [ ] A9 dental and bench demos recorded
- [ ] A10 fine-tuning run 2, all 9 items
- [ ] A11 tests logged
- [ ] A12 Perceptron arm video
- [ ] P1 pitch script final
- [ ] P6 Commit Fellowship form

## Caiden

- [x] C1 controller on the fake arm, every endpoint
  - `.venv/bin/python -m controller` (fake arm, port 8000). A curl handover runs finding → picking → checking → moving_to_hand → waiting_for_pull → releasing → homing, all on `WS /events`. Details in `controller/README.md`.
- [x] C2 pushed and announced
  - Pushed `ed084b6`. Point vision at `POST :8000/vision/hand` and `/vision/tray`; the dashboard at `WS :8000/events`, `GET /state`, `GET /setting`.
- [ ] C3 Photon call reaches `voice/`
- [ ] C4 Gemini commands, stop path, spoken replies
- [ ] C5 Checkpoint 1 shown
  - Ready on the agent side: voice → controller tested locally (`/heard` "grab me the kelly" → `handover hemostat`, lines spoken from events). Needs the team at 6 PM: phone call, Brandon's Hand posts, Evan's dashboard. Dry run: `.venv/bin/python -m controller.smoke --return`.
- [x] C6 real controller flows and failure cases
  - `.venv/bin/python -m controller.test_flows` forces each failure on the fake arm: 17/17 pass. Covers grasp check + one retry, wait for pull/`got_it` (30 s), freeze on hand lost or path blocked, slow near the hand, the request-to-hand timer. Force live failures with `POST /fake/force`.
- [ ] C7 end-of-case summary text
- [ ] C8 ten clean full runs
  - Tool ready: `.venv/bin/python -m controller --real-arm` then `.venv/bin/python -m controller.smoke --runs 10 --human --return` counts the clean streak. Needs `arm/real_arm.py` (A6) and the arm.
- [ ] P4 demo mode and backup run
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

- [ ] E1 three settings files
- [ ] E2 dashboard live on the controller
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
