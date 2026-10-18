# Status

Read `README.md` first, then this page. The "Current state" section is the map of the system as of Sun Oct 18, about 1:30 AM, written from the code, the tests I ran and the services' own checks. The task boxes below it are the checklist. Every box ticked has a test, a command or a commit behind it; the note under it says which. Unticked boxes say what is missing.

Agents: the first unchecked box in your person's section is the next task. Tick it when its "done when" passes and add one line under it: what works and how to run it. Edit only your person's section. Task details are in `docs/TASKS.md`. What is left for people is ordered in `docs/LEFT.md`, `docs/HARDWARE-TODO.md` and `docs/ACCOUNTS-TODO.md`; every comb finding is in `docs/AUDIT.md`.

## Current state

Scrub is an SO-101 arm that passes surgical instruments by voice. Surgical tray first (scalpel handle, hemostat, Mayo scissors). Robotics bench tray second (needle-nose pliers, wire cutters, hex key), to show a new setting needs demos and no new code. Dental is hidden; `settings/dental.json` stays on disk. Only the controller moves the arm.

**In one paragraph.** The software runs end to end on the fake arm and the MuJoCo sim arm, and its tests pass. The real arm path (`arm/real_arm.py` on the shared `arm/hardware.py` layer, with rest and wake, the thermal guard and taught skills) is tested on fake buses only. No fine-tuning run has finished: the Robotics API answers with the team key (HTTP 200) and lists 0 deployments. `arm/rig.json` has a measured `home` but `hardware_verified` is false and `carry` and `safe_spot` are null. No taught skill is recorded (`arm/skills/surgical/` is empty). `vision/calibration.json` does not exist and no slot box is marked in `settings/surgical.json` or `settings/bench.json`. `docs/DATA-LOG.md` has no batch row; a local dataset in `~/scrub-dataset` holds 6 episodes that are not logged. The phone line, the Vultr page and the end-of-case text need accounts and clicks that only a person can do.

### Data flow

```
phone -> Photon number -> ElevenLabs agent --(Custom LLM, via tunnel)--> voice :3000 -> Gemini (word -> Command)
                                                                              | POST /command, /stop
overhead camera -> vision :8001 --POST /vision/hand, /vision/tray--> controller :8000 --move/pick/release--> arm
                                                                              |  (fake | sim :8002 | real SO-101 + Perceptron Isaac, or taught skills)
                                                                              +--events (WS /events)--> dashboard, tablet, nurse, demo console, ops page
                                                                              +--log--> ledger --> MongoDB Atlas --> public page :8080
voice <-- WS /events (spoken lines)          Photon text in: restock, what's out, check the tray, summary
voice --end of case--> Photon text out: count, items, times, case replay link
```

### Parts

Status words: works, works offline only (tested on fakes or sim, needs hardware or an account to be real), partial, missing. All commands run from the repo root; `PY` is `.venv/bin/python`. Test counts are from runs on Oct 18 between 1:00 and 1:30 AM.

| Part (owner) | What it does | Start | Port | Tests | Status |
| --- | --- | --- | --- | --- | --- |
| `controller/` (Caiden) | Command flows, safety, step machine, events, `--skills model`, `taught` or `auto`, `skill_source` on pick and return events, release on pull, serves dashboard, demo, nurse, `/ops` | `PY -m controller` (`--sim-arm`, `--real-arm`, `--judge`, `--setting bench`) | 8000 | `PY -m controller.test_flows` (84/84) | works offline only: fake and sim arm pass; real arm never run |
| `controller/run_all.py` | One command starts controller, vision, voice, tunnel, optional ledger; prints URLs; `reset`, `backup`, `check`; `--real` is the judging preset | `PY -m controller.run_all` (`--arm sim`, `--arm real --vision real --tunnel`, `--base-port 8100`) | 8000, 8001, 8002, 3000, 8080 | `PY -m controller.test_run_all` (32 OK) | works |
| `controller/doctor.py` | Checks every service, key presence (never values) and logs; Gemini turns findings into a fix list | `PY -m controller.doctor` | none | `PY -m controller.test_doctor` (prints "doctor ok") | works |
| `voice/` (Caiden) | Call and text path: ElevenLabs Custom LLM endpoint, Gemini to Command, spoken lines, Photon texts, end-of-case summary | `cd voice && npm run dev` (tunnel: `npm run tunnel`) | 3000 | `cd voice && npm test` (passes, offline) | works with Gemini; the live call and texts need Photon and ElevenLabs set up by a person (C3 open) |
| `vision/` (Brandon) | Locked-exposure camera, MediaPipe hand, Perceptron tray detect, `path_clear`, MJPEG preview, tray check, event clips | `PY -m vision` (`--fake` with no camera) | 8001 | `PY -m vision.test_vision` (47 OK) | partial: no `calibration.json`, slot boxes not marked (B5, B6), lighting tests open (B8) |
| `arm/` (Anish) | Arm interface, shared hardware layer, LeRobot real arm, 30 Hz streaming, kinematics, sessions, taught skills, recorder, training CLI | no server. Check: `PY -m arm.check_setup`; record: `PY -m arm.record`; train: `PY -m arm.train pipeline ...` | none | `PY -m unittest discover -s arm -t . -p "test_*.py"` (134 OK) | works offline only: no logged episodes, no finished training run, rig unmeasured |
| `sim/` (Caiden) | MuJoCo SO-101 and table; same Arm interface; 3D viewer; backup-demo arm | `PY -m sim` (or `controller --sim-arm`) | 8002 | `PY -m pytest -q sim/test_sim.py` (17 passed) | works |
| `ledger/` (Evan) | Logs events and test results, success tables (fake-arm and sim rows left out), case replay, public judge page, QR | `PY -m ledger serve` (page); `PY -m ledger log ...` (DATA-LOG row) | 8080 | `PY -m ledger.test_ledger` (22 OK) | works offline only: Atlas ping passes (`python -m deploy`); the Vultr page is not deployed |
| `dashboard/` (Evan) | Static pages: dashboard, tablet; tables with "No real-arm tries yet." empty state, stale-vision warning | served by the controller | 8000 | none of its own (covered by `docs/QA.md`) | works |
| `settings/` (Evan) | One JSON per tray, plus `<id>.local.json` clinic-word overlay | loaded by the controller | none | `controller.test_flows` loads them | partial: item lists final; slot boxes are null, not measured |
| `deploy/` (Brandon) | `python -m deploy` checks every key against its service; scripts for the public page server | `PY -m deploy` | none | `PY -m deploy.test_check_env` (8 OK) | works; Vultr and domain not done |
| `explore/` (Caiden) | Not the build, except: `arm_session.py` (the recorder), `arm_ui.*` (recorder page), `dataset/` (QA, variety, replay, aim), `bench/`, `recognition/`, `thermal_web.py` | recorder: `PY explore/arm_session.py` (or `PY -m arm.record`); page 8090 | 8090; thermal 8093; dataset tools 8095, 8096 | `PY -m unittest discover -s explore -p test_thermal_analyze.py` (13 OK) | partial: wrist camera about 23 fps and dark as of Oct 17 |

### URLs a person opens

| URL | What |
| --- | --- |
| http://localhost:8000/ | dashboard: step, what is out, log, tables, stop |
| http://localhost:8000/ops | operator page: steps, skill source, arm temperatures, vision, voice, latencies, errors |
| http://localhost:8000/demo | judge console: 1 surgical, 2 bench, R reset, Space stop, J judge mode |
| http://localhost:8000/nurse | nurse console: pose, side and wrist cameras, count vs camera |
| http://localhost:8000/tablet.html | big-type tablet view |
| http://localhost:8001/ | vision preview (`/stream` is the MJPEG, `/health` is the check) |
| http://localhost:3000/health | voice server (booleans for keys, never values) |
| http://localhost:8080/ (`/cases.html`, `/card.html`) | public judge page, case replay, printable table card |
| http://localhost:8002/web/viewer.html | sim 3D viewer (sim arm only) |

### What was checked at 1:00 to 1:30 AM Oct 18

- Tests: controller.test_flows 84/84; controller.test_run_all 32 OK; vision.test_vision 47 OK; deploy.test_check_env 8 OK; ledger.test_ledger 22 OK; arm 134 OK; sim 17 passed (an earlier run with several suites going at once failed 6 of them on shared ports; the rerun alone passed); controller.trials self-test 20 OK; voice `npm test` passed.
- `python -m deploy` (live): Perceptron robotics PASS (HTTP 200), Perceptron detect PASS, Perceptron deployment FAIL (`PERCEPTRON_DEPLOYMENT_ID` is set but the account lists 0 deployments), Gemini PASS, ElevenLabs PASS, MongoDB Atlas PASS, controller and vision PASS. FAIL: Photon (HTTP 403), Tiger Data, Backboard, Hugging Face (`HF_TOKEN`), Vultr public page (`SCRUB_PUBLIC_URL`), voice :3000 (not running then).
- Keys set in `.env`, by name only: GEMINI_API_KEY, ELEVENLABS_API_KEY, PERCEPTRON_API_KEY, PERCEPTRON_TEAM_API_KEY, PERCEPTRON_DEPLOYMENT_ID, MONGODB_URI, SPECTRUM_PROJECT_ID and SPECTRUM_PROJECT_SECRET (voice reads them as the Photon keys). Empty: ELEVENLABS_AGENT_ID, HF_TOKEN, SO101_PORT, TIGER_DATABASE_URL, BACKBOARD_API_KEY.
- Not checked: the arm ports and cameras (the recorder owns them), the follower is unpowered, so nothing on the real arm was run.

### External services and keys

| Service | Used for | Key names |
| --- | --- | --- |
| Perceptron Robotics API | datasets, training, the Isaac 0.5 arm model | PERCEPTRON_TEAM_API_KEY, PERCEPTRON_DEPLOYMENT_ID |
| Perceptron vision API | tray detect, clip captions | PERCEPTRON_API_KEY |
| Hugging Face | LeRobot dataset hosting | HF_TOKEN |
| Gemini | words to Command | GEMINI_API_KEY |
| ElevenLabs | call agent (Custom LLM), the arm's spoken voice | ELEVENLABS_API_KEY, ELEVENLABS_AGENT_ID, VOICE_LLM_SECRET (optional), ELEVENLABS_VOICE_ID (optional) |
| Photon | phone number and iMessage texts | PHOTON_PROJECT_ID + PHOTON_API_KEY (or SPECTRUM_PROJECT_ID + SPECTRUM_PROJECT_SECRET), PHOTON_SUMMARY_TO (optional) |
| MongoDB Atlas | ledger | MONGODB_URI |
| Tiger Data, Backboard | handoff time series, request memory (optional) | TIGER_DATABASE_URL, BACKBOARD_API_KEY + BACKBOARD_ASSISTANT_ID |
| Pinggy, cloudflared or ngrok | public tunnel to voice | none (ngrok needs an authtoken) |
| Vultr and GoDaddy | public judge page and domain | none in `.env`; SCRUB_PUBLIC_URL is not secret |

Local wiring (no secrets): CONTROLLER_URL, VISION_URL, VOICE_PORT, CAMERA_INDEX, SO101_PORT, SO101_SIDE_CAMERA, SO101_WRIST_CAMERA.

### Where to look next

- `docs/LEFT.md`: the one list of what is left, with who and when.
- `docs/HARDWARE-TODO.md`: every hardware step left, in order, with the command and what you should see.
- `docs/ACCOUNTS-TODO.md`: every account and key, where to get it, and whether it works now.
- `docs/AUDIT.md`: the comb findings by severity and what was fixed.
- `docs/CONTRACTS.md` (every message and endpoint), `docs/DEMO.md` (the live run), `docs/BRINGUP.md` and `docs/TRAINING.md` (first contact with the arm).

### Who edits what

The comb pass is finished and committed. Boxes below are edited by their own person only (see `AGENTS.md`). Fake-arm and sim rows do not count in the ledger's rates (`GET /api/stats?sim=1` includes them), so the success tables stay empty until the first real-arm tries.

## Anish

- [x] A1 workshop notes in `docs/ARM.md`
  - Covered by `explore/research/isaac-workshop-notes.md` and the capabilities block in `docs/ARM.md`.
- [x] A2 `arm/perceptron.py`, `arm/train.py`, `arm/upload_dataset.py`
  - Client/CLI/uploader implemented; `python -m unittest arm.test_perceptron -v` passes 5 offline tests (Oct 18). Oct 18: `python -m arm.train deployments` answers (`{"items": []}`) and `python -m deploy` shows Perceptron robotics PASS, so the team key works live. `python -m arm.train capabilities` is in `docs/ARM.md`.
- [ ] A3 arm connected, both cameras, poses in `arm/rig.json`
  - Evidence Oct 17 night: follower recalibrated 21:49; the side camera (C920) is not seen by the Mac; the wrist camera (icspring) runs 22.6 fps (needs 30). Oct 18 1:30 AM: `arm/rig.json` has a measured `home`, but `hardware_verified` is false and `carry` and `safe_spot` are null. A recorder owns the ports and cameras now, so cameras were not rechecked. Steps 1 to 5 in `docs/HARDWARE-TODO.md`.
- [ ] A4 operating room demos recorded (90: 20 pick + 10 put-back per item, `docs/TRAINING.md`)
  - 0 logged. `docs/DATA-LOG.md` has no rows. `~/scrub-dataset` holds 6 episodes (`python -m arm.record --print-only` reports it) that are not in the log and have no cadence report, so none count.
- [ ] A5 fine-tuning run 1 started
  - Not started. The robotics key works now (`python -m deploy`: HTTP 200, no longer 401) and `python -m arm.train deployments` lists 0 deployments. Waits on A4 and the dataset checks in `docs/TRAINING.md`.
- [ ] A6 `arm/real_arm.py` with `run_skill`
  - [x] Offline implementation/dry-run: complete interface, LeRobot adapter, 30 Hz playback + RTC predicts, stop/load/session tests. `python -m arm --dry-run --self-test` succeeds; `python -m unittest discover -s arm -t . -p "test_*.py"` passes 134 tests. Live API/hardware acceptance pending. Caiden integration items are in `arm/README.md`.
  - [x] Comb fixes: holds the last command (no sag, no slack grip), claw guard, API retries then `APIError`, busy-port refusal, returns end on release. `arm/test_safety.py` (16 tests) and `arm/test_hardware.py` (11) are in that 134.
- [ ] A7 `move_to` with IK
  - [x] Offline FK/IK, random round trips, handoff-box preflight, speed limits and fake-joint `Arm.move_to` pass. Run `python -m unittest arm.test_kinematics arm.test_real_arm -v` (25 tests pass). Real calibration and five-point ~2 cm hardware acceptance still pending; rig is an unmeasured, hardware-disabled template.
- [ ] A8 first real handoff by voice
- [ ] A9 dental and bench demos recorded
- [ ] A10 fine-tuning run 2, all 9 items
- [ ] A11 tests logged
- [ ] A12 Perceptron arm video
- [ ] P1 pitch script final
- [ ] P6 Commit Fellowship form
- [x] R1 training pipeline: local preflight/cadence, resumable HF registration, validation, training/follow, matching ready deployment and `.env` update; `python -m unittest arm.test_pipeline -v` passes 10 offline tests. Commands/evidence format in `arm/README.md`; no real job submitted.
- [x] R2 torque-off hand-guided teaching: `python -m arm.teach --port <port> --supported-and-empty`, h/c/s poses and a/b FK region corners, atomic rig updates with hardware verification cleared. `python -m unittest arm.test_teach -v` passes 12 offline tests; no real torque operation run.
- [x] R3 optional `Arm.prepare(instructions)`: instruction-bound session cache, reuse/cleanup/expiry/context handling, freeze-safe transactional preparation. `python -m unittest arm.test_prepare -v` passes 11 offline tests, including reuse by the real playback loop with fake joints. Base contract and Caiden's files unchanged.
  - Full arm suite: 134 offline tests pass; `python -m arm --dry-run --self-test` succeeds. R4 waits for Anish to confirm the arm is plugged in and the Robotics team key is in `.env`.
- [x] Q1 `docs/BRINGUP.md`: PowerShell commands, expected results and recovery gates from ports/calibration through recording, training, overhead calibration and first voice handoff. Checked against current CLIs/routes; physical acceptance and team-key calls remain R4, not claimed as tested.
- [x] Q2 `controller/trials.py`: default 195-trial PLAN matrix, filters/N override, operator confirmation, command-correlated outcomes, local ledger calls and action-separated JSONL evidence; practice never logs measured trials. `python -m controller.trials --self-test` passes 20 offline tests including real fake-controller routes; `--plan-only` verifies counts. No other controller files edited.

## Caiden

- [x] TH1 overheating telemetry audit and analyzer correction (Oct 17; handed off Oct 18)
  - Read [thermal findings and operator handoff](../explore/research/overheating/HANDOFF.md#results) and the [per-session report](../explore/research/overheating/telemetry-review-20261017.md). Existing 230 s torque-on hold: gripper fastest at 1.13 C/min, peak 55 C; other motors 0.84-1.07 C/min. Some heat with reported zero current; this does not prove the dominant heat source.
  - Fixed the analyzer joining different sessions into heating windows; added phase/outage boundaries, minimum coverage, missing-value handling and heat/current correlation. Recorder runs were only 2-48 s: **no valid phase, holding-vs-moving or load/current-correlation conclusion yet**. Offline: `python -m unittest discover -s explore -p test_thermal_analyze.py -v` (13 tests pass). No arm/camera ports opened or servo settings changed.
- [ ] TH2 Caiden at the arm: baseline experiment #1, then fan-only experiment #2
  - Follow the [exact baseline procedure](../explore/research/overheating/HANDOFF.md#caiden-next-action-is-experiment-1-not-new-motor-settings): verify servo voltage ratings, start with every follower motor <=47 C, repeat the fixed routine for up to 10 min, watch heat/strain/sag/guard events, and never bypass 60 C cooldown. Never open ports/cameras while a recorder is running; use its `/status` or MongoDB `thermal_log.py watch` instead.
  - Return the session id and observations; analyze with `.venv/bin/python explore/thermal_analyze.py --session <id>` and append per-motor C/min/verdict to HANDOFF Results. This audit implemented no motor-setting experiments. **Upstream update Oct 18:** `319161a` separately added situational gripper torque (150/350/500) and gripper dead zone 3; the older telemetry does not validate those changes. Label the new baseline with its code/settings and keep them unchanged for the fan comparison. Reset torque-off and body-joint register experiments remain pending; long-session operation below 60 C is not yet demonstrated.

- [x] C1 controller on the fake arm, every endpoint
  - `.venv/bin/python -m controller` (fake arm, port 8000). A curl handover runs finding → picking → checking → moving_to_hand → waiting_for_pull → releasing → homing, all on `WS /events`. Details in `controller/README.md`.
- [x] C2 pushed and announced
  - Pushed `ed084b6`. Point vision at `POST :8000/vision/hand` and `/vision/tray`; the dashboard at `WS :8000/events`, `GET /state`, `GET /setting`.
- [ ] C3 Photon call reaches `voice/`
  - Oct 17 night: Photon project id and secret are in `.env` (as `SPECTRUM_PROJECT_ID`/`SPECTRUM_PROJECT_SECRET`); live voice `/health` shows photon true and `[texts] listening on the Photon line`. Oct 18: the `python -m deploy` Photon check answers HTTP 403, so the Photon credentials need a look. Left: find the iMessage line number, `ELEVENLABS_AGENT_ID`, SIP inbound, and whether a shared-pool line takes calls (`docs/ACCOUNTS-TODO.md`).
  - Ready for the call: ElevenLabs Custom LLM → `voice/` `/v1/chat/completions`, verified through a public tunnel (`npm run tunnel`, Pinggy on 443; cloudflared is blocked on venue Wi-Fi). `curl localhost:3000/health` shows keys (booleans) and the controller. Left: Caiden's clicks in Photon and ElevenLabs, steps in `voice/README.md` "Call setup".
- [ ] C4 Gemini commands, stop path, spoken replies
  - Works without a call: `curl -XPOST localhost:3000/heard -d '{"text":"grab me the kelly"}'` gives `handover hemostat` and "Hemostat coming." with Gemini live; mayo, "knife please", "what's out" and "stop" checked too. `cd voice && npm test` passes offline. Merged code checked Oct 17 against the fake arm through `npm run say`: kelly, got it, knife, what's out, stop. Left: the same on a real Photon call (C3).
- [ ] C5 Checkpoint 1 shown
  - Ready on the agent side: voice → controller tested locally (`/heard` "grab me the kelly" → `handover hemostat`, lines spoken from events). Needs the team at 6 PM: phone call, Brandon's Hand posts, Evan's dashboard. Dry run: `.venv/bin/python -m controller.smoke --return`.
- [x] C6 real controller flows and failure cases
  - `.venv/bin/python -m controller.test_flows` forces each failure on the fake arm; the whole suite is 84/84 today. Real-arm safe: stop latches until `POST /reset` (rearms with `resume()`, sets a held item at the safe spot), missing load falls back to `got_it`, failed set-down holds (Anish's arm/README handoff items 1-4). Sim: 3 clean full runs in a row. Covers grasp check + one retry, wait for pull/`got_it` (30 s), freeze on hand lost or path blocked, slow near the hand, the request-to-hand timer. Force live failures with `POST /fake/force`.
- [ ] C7 end-of-case summary text
  - Gemini writes it from the case events with the count first (from the controller's `out`), item names, no double counting; checked against a live fake-arm case. `POST localhost:3000/summary` sends it via Photon to the caller or `PHOTON_SUMMARY_TO`; it names the case (setting, start time, items used) by `case_id` (F4). Left: one real send to a phone.
- [x] F1 auto return from the return spot
  - An item in the return spot for 2 s with the arm idle goes back on its own ("Returning the X.", `command` event with `source: "auto"`); once per visit, never while busy or stopped. Tests in `controller.test_flows`.
- [x] F2 count from the camera
  - `GET /state` has `out_camera`; "count" adds "Camera also sees the X gone." / "Camera sees the X back." when they disagree. Tests in `controller.test_flows`.
- [x] F3 Photon texts in
  - `voice/src/texts.ts`: restock ("add a second hemostat to the surgical tray" → ledger via `POST :8000/restock`, file fallback), "what's out?", "summary", help. Starts with the Photon keys in `.env`. Offline tests in `cd voice && npm test`; not yet tried on the real number.
- [x] F4 call-to-text memory
  - The end-of-case text goes to the caller's thread and names the case, grouped by `case_id` (now on State and every event). Offline tests in `npm test`; the real send is C7.
- [x] QA-12 sharp acknowledgement
  - A scalpel handover now says "Scalpel to the safe spot." (test in `controller.test_flows`).
- [x] X3 tray check, command side
  - "check the tray" / "is the tray ready" by voice or text → controller `GET /tray_check` → vision's `/tray_check` (3 s timeout, in a thread) → "Tray's ready: …", "Missing the scalpel.", "The hemostat is in the Mayo scissors' slot."; a passing check on a call also texts "Tray ready". Until vision adds the endpoint: "I can't check the tray right now." Tests in `controller.test_flows` and `cd voice && npm test`.
- [x] X5 Photon extras
  - Text or say "start a bench case" / "switch to the surgical tray" → `POST /setting`, reply lists the tray's instruments (busy: "The arm is busy…"). After the summary text, "Case replay: <SCRUB_PUBLIC_URL>/case.html?id=<case_id>" (Evan's replay page) when `SCRUB_PUBLIC_URL` is set. The "tray ready" text is in X3. Offline tests in `npm test`.
- [x] X6 clinic words
  - "call the hemostat a clamp", "when I say clamp I mean the hemostat" or "clamp means the hemostat" (call or text) → controller `POST /alias` → saved in `settings/<id>.local.json`, merged over Evan's file (never written) and live at once. Unknown requests now hint: "Which instrument? You can say: call the hemostat a kelly." Tests in `controller.test_flows` and `npm test`.
- [ ] C8 ten clean full runs
  - Tool ready: `.venv/bin/python -m controller --real-arm` then `.venv/bin/python -m controller.smoke --runs 10 --human --return` counts the clean streak. Needs `arm/real_arm.py` (A6) and the arm.
- [x] P4 demo mode and backup run
  - `http://localhost:8000/demo`: 1/2/3 load the trays, R resets and clears the count (`POST /reset {"clear_count": true}`), Space/Esc stop, 3:00 cue cards and a rehearsal log. Checked live on the fake arm. A plain `POST /reset` now keeps the count after a stop. The backup full run is recorded Sunday morning.
- [ ] P2 backup slide deck
  - Slide text final in `docs/SLIDES.md` (surgical first, bench second), diagram `docs/media/system.svg` / `.png`, judge Q&A `docs/QNA.md`, run order `docs/DEMO.md`. Left: a person builds the Google Slides deck and pastes the link.
- [x] L2 robot sessions pre-opened per tray; Perceptron 401/409/503 spoken as `error` events with `code` (`controller.test_flows`)
- [x] L3 judge mode: `POST /judge`, `--judge`, J on `/demo`; only handover, count, stop, got it. Voice refuses tray switches, clinic words and restocks in judge mode (`cd voice && npm test`)
- [x] L6 `python -m arm.check_setup` and `python -m arm.record` (official recorder over `explore/arm_session.py`, or `--lerobot`; appends `docs/DATA-LOG.md`); `unittest arm.test_record` 24 tests
- [x] Q3 `docs/AUDIT.md`: the comb pass (contracts, line by line, safety checklist, full stack on the sim arm, public-repo scan). Criticals and highs fixed with tests; `controller.test_flows` is 85/85 today
- [x] L7/L10 `python -m controller.run_all` (start, `reset`, `backup`, `check`): sim backup run clean, full-stack check 18/18 on a fake stack (`controller.test_run_all` 32 tests)

## Brandon

- [x] B1 camera with locked exposure
  - Locked exposure and white balance, default exposure -6 (`CAMERA_EXPOSURE` to override). `python -m vision` (add `--fake` with no camera). Preview at http://localhost:8001/. Checked on the Acer FHD camera: a fixed exposure stays put. With the overhead camera, a lamp should brighten the picture and leave it there.
- [x] B2 hand tracker posting Hand
  - MediaPipe hand landmarker posts a Hand about 10 times a second to `CONTROLLER_URL/vision/hand`. Open palm means all five fingertips are farther from the wrist than their middle joints. `target` stays null until `vision/calibration.json` exists. `python -m vision.test_vision`
- [x] B3 MJPEG stream
  - http://localhost:8001/stream draws slot boxes and the palm dot. The dashboard image is `<img src="http://localhost:8001/stream">`.
- [x] B4 tray perception posting TrayState
  - Perceptron `/v1/detect` about once a second, mapped onto slot boxes, posted to `/vision/tray`. A failed call keeps the last state and sets `stale: true`. The controller's `GET /setting` supplies aliases and boxes. Shapes are in `docs/PERCEPTRON-ROBOTICS.md` (Part 2). Live calls need `PERCEPTRON_API_KEY` in `.env`. `python -m vision.test_vision`
- [ ] B5 slot boxes marked for all three trays
  - Oct 17 night: `slot` and `return_spot` are null in every `settings/*.json`. Only surgical and bench are needed now (dental dropped).
- [ ] B6 camera-to-arm calibration
  - `vision/calibration.json` does not exist yet. Vision on :8001 is running `--fake`.
- [x] B7 `path_clear` and saved hand height
  - `path_clear` is false when a second hand or a robot-arm box crosses the gripper-to-target segment. Hand height is saved per clinician with `POST /clinician`. `python -m vision.test_vision`. On the real camera, wave a hand through the path and the preview should say "path blocked".
- [ ] B8 lighting tests

## Evan

- [x] E1 three settings files
  - `settings/surgical.json`, `dental.json`, and `bench.json`. Only the scalpel is sharp. The dashboard picker shows the operating room and the robotics bench. `dental.json` stays on disk and is not in the picker.
- [x] E2 dashboard live on the controller
  - Open http://localhost:8000/ after `python -m controller --fake-arm`. A handover updates the step, the log, what's out, and the handoff time. If the controller is down, the page shows a sample handover.
- [x] E3 ledger in MongoDB Atlas
  - `python -m controller --fake-arm`, then `POST /command` `{"action":"handover","item":"hemostat"}`. Eleven events landed in Atlas database `scrub`, collection `events`. `GET /stats` shows hemostat out. No open hand was posted, so the fake arm set it down and there is no handoff time yet. `ledger/buffer.jsonl` flushed. Oct 18: `python -m deploy` MongoDB Atlas PASS (ping ok) from this Mac with `MONGODB_URI` set.
- [x] E4 data log kept during recording
  - `python -m ledger log --setting surgical --item hemostat --direction hand-out --lighting bright --demos 5 --dataset local --notes "cadence ok"` appends one row to `docs/DATA-LOG.md` in the same shape `arm/record.py` should append. The table is empty until the first real batch.
- [ ] E5 Devpost draft submitted by 10:00 PM
  - Paste-ready text is in `docs/DEVPOST.md` (surgical first, bench as the second tray, tracks listed, no measured rates invented). Evan pastes it by 9:30 PM.
- [ ] E6 tables on the dashboard, public page on Vultr and the domain
  - The dashboard shows the success tables, handoff times, the current lighting, and a "Vision stale" warning. Public page: `python -m ledger serve` then http://127.0.0.1:8080/. QA-01, QA-02, QA-03, QA-07, QA-08, QA-09, QA-10, and QA-11 are fixed (see `docs/QA.md`). Oct 18: `python -m deploy` Vultr public page FAIL (`SCRUB_PUBLIC_URL` not set), so it is not deployed. Fake-arm and sim rows are left out of the tables, which show "No real-arm tries yet." until the first real tries. Brandon has the Vultr and domain deploy (`deploy/README.md`).
- [ ] E7 demo video and final Devpost
  - Shot-list checklist is at the bottom of `docs/DEVPOST.md`. The edit and the upload are Sunday. The backup clip is `python -m controller.run_all backup --offline --loop --pause 2` screen-recorded with the dashboard open (`docs/DEMO.md`).
- [x] X1 case replay
  - `python -m ledger serve`, then http://127.0.0.1:8080/cases.html. Each case lists the events, handoff times, the count at each moment, and a short summary. The dashboard links to the current case.
- [x] X2 likely next
  - `GET /stats` includes `next_likely`. The dashboard shows "Likely next: hemostat (70%)" when past requests support it. The arm does not move on that line.
- [x] X7 tablet view
  - http://localhost:8000/tablet.html after `python -m controller`. Large type, the step, what is out, Stop, and Reset.
- [x] X8 honest tables
  - Each success cell shows the rate, the tries, and a 95% Wilson range, on the dashboard and the public page.

## Checkpoints

- [ ] Sat 6:00 PM: a spoken request runs every step on the fake arm and shows on the dashboard
- [ ] Sat 10:00 PM: Devpost draft submitted
- [ ] Sat 10:30 PM: first real handoff by voice
- [ ] Sun 2:00 AM: all three settings, put-back and the count working
- [ ] Sun 6:00 AM: feature freeze
- [ ] Sun 9:30 AM: video uploaded, repo public, final Devpost submitted
