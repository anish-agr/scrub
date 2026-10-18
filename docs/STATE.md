# State of Scrub (Sun Oct 18, 1:45 AM)

What exists and what works now, from the code, the test runs and the live checks on the arm Mac. What is left to do, with who and when, is in `docs/LEFT.md`. Every tool with its proof command is in `docs/INTEGRATION.md`. The project in one document is `docs/OVERVIEW.md`; every message and endpoint is in `docs/CONTRACTS.md`.

Scrub is an SO-101 arm that passes surgical instruments by voice. Surgical tray first (scalpel handle, hemostat, Mayo scissors). Robotics bench tray second (needle-nose pliers, wire cutters, hex key), to show a new setting needs demos and no new code. `settings/dental.json` stays on disk but is hidden. Only the controller moves the arm.

## Summary

The software runs end to end on the fake arm and the MuJoCo sim arm, and its tests pass. The real arm path (`arm/real_arm.py` on the shared `arm/hardware.py` layer, with rest and wake, the thermal guard and taught skills) is tested on fake buses only. No fine-tuning run has finished: the Robotics API answers with the team key (HTTP 200) and lists 0 deployments. `arm/rig.json` has a measured `home`, but `hardware_verified` is false and `carry` and `safe_spot` are null. No taught skill is recorded (`arm/skills/surgical/` is empty; `arm/skills/example/` holds one sample). `vision/calibration.json` does not exist and no slot box is marked in `settings/surgical.json` or `settings/bench.json`. `docs/DATA-LOG.md` has no batch row; `~/scrub-dataset` holds 6 unlogged episodes that do not count. The phone line, the domain and the end-of-case text to a real phone still need a person.

## Data flow

```
phone -> Photon number -> ElevenLabs agent --(Custom LLM, via tunnel)--> voice :3000 -> Gemini (words -> Command)
                                                                              | POST /command, /stop
overhead camera -> vision :8001 --POST /vision/hand, /vision/tray--> controller :8000 --move/pick/release--> arm
                                                                              |  (fake | sim :8002 | real SO-101: Perceptron model or taught skill)
                                                                              +--events (WS /events)--> dashboard, tablet, nurse, demo console, /ops
                                                                              +--log--> ledger --> MongoDB Atlas --> public page :8080 (Vultr 144.202.95.111)
voice <-- WS /events (spoken lines)          Photon text in: restock, what's out, check the tray, summary
voice --end of case--> Photon text out: count, items, times, case replay link
```

## Parts

`PY` is `.venv/bin/python`. All commands run from the repo root. Status words: works; offline only (tested on fakes or sim, needs hardware or an account to be real); partial.

| Folder (owner) | What it holds | Start | Port | Status |
| --- | --- | --- | --- | --- |
| `controller/` (Caiden) | Step machine, safety, events, `--skills model\|taught\|auto` with `skill_source` on pick and return events, release on pull, judge mode, trials and smoke tools; serves the dashboard, `/demo`, `/nurse`, `/ops` | `PY -m controller` (`--sim-arm`, `--real-arm`, `--judge`, `--setting bench`, `--skills`) | 8000 | offline only: fake and sim arm pass; never run on the real arm |
| `controller/run_all.py` | Starts controller, vision, voice, tunnel and ledger; prints URLs; `reset`, `backup`, `check`; `--real` is the judging preset (`--arm real --vision real --ledger --judge --skills auto`) | `PY -m controller.run_all` (judging: `PY -m controller.run_all --real --tunnel`) | 8000, 8001, 8002, 3000, 8080 | works |
| `controller/doctor.py` | Checks every service, key presence (never values) and logs; Gemini writes the fix list | `PY -m controller.doctor` | none | works |
| `voice/` (Caiden) | ElevenLabs Custom LLM endpoint, Gemini to Command, spoken lines, Photon texts in and out, end-of-case summary | `cd voice && npm run dev` (tunnel: `npm run tunnel`; no call: `npm run say -- "grab me the kelly"`) | 3000 | works with Gemini; the live call and a real text are not done (setup in `voice/README.md` Call setup) |
| `vision/` (Brandon) | Locked-exposure camera, MediaPipe hand, Perceptron tray detect, `path_clear`, MJPEG preview, tray check, event clips with Perceptron captions, OCR reading of count sheets, tray tags and pack labels | `PY -m vision` (`--fake` with no camera; binds 127.0.0.1, `VISION_HOST=0.0.0.0` opens it) | 8001 | partial: no `calibration.json`, no slot boxes, lighting tests not run |
| `arm/` (Anish) | Arm interface, shared hardware layer, LeRobot real arm, 30 Hz streaming, kinematics, sessions, taught skills, pose teaching, recorder wrapper, dataset check, training CLI and pipeline | no server. `PY -m arm.check_setup`, `PY -m arm.record`, `PY -m arm.teach`, `PY -m arm.teach skill <item> pick\|return`, `PY -m arm.taught --check`, `PY -m arm.dataset_check <root>`, `PY -m arm.train ...` | none | offline only: no logged episodes, no finished run, rig not verified |
| `sim/` (Caiden) | MuJoCo SO-101 and table on the same Arm interface; 3D viewer; backup-demo arm | `PY -m sim` (or `controller --sim-arm`) | 8002 | works |
| `ledger/` (Evan) | Event log, success tables (fake-arm and sim rows left out), case replay, public judge page, series and memory pages, QR card, DATA-LOG rows | `PY -m ledger serve`; `PY -m ledger log ...` | 8080 | works; Atlas and the Vultr page pass, no domain |
| `dashboard/` (Evan) | Static dashboard and tablet pages; "No real-arm tries yet." empty state; stale-vision warning | served by the controller | 8000 | works |
| `settings/` (Evan) | One JSON per tray, plus `<id>.local.json` clinic-word overlay | loaded by the controller | none | partial: items final, slot boxes null |
| `deploy/` (Brandon) | `python -m deploy` checks every key against its service; public page server scripts (`setup_public.sh`, nginx, `enable_https.ps1`) | `PY -m deploy` | none | works |
| `video/` | Demo cut from ledger events and joints: ingest, EDL render, cards, overlays, sim backup capture | `PY -m video ...` (`video/README.md`, `docs/VIDEO-TOOL.md`) | none | works on synthetic assets; no real footage yet |
| `explore/` (Caiden) | Real tools: `station/` (persistent recording station), `arm_session.py` and `arm_ui.*` (recorder), `dataset/` (QA, video QA, variety, replay, aim), `recognition/` (bench), `thermal_log.py`, `thermal_analyze.py`, `thermal_web.py`, `home_pose.py`, `calibrate_follower.py`. The rest is research | station or recorder page 8090 (`PY explore/station/station.py --task "..."`); thermal 8093; dataset tools 8095, 8096 | 8090, 8093, 8095, 8096 | works offline; the wrist camera ran 22.6 fps and dark on Oct 17 |

## URLs

| URL | What |
| --- | --- |
| http://localhost:8000/ | dashboard: step, what is out, log, tables, stop |
| http://localhost:8000/ops | operator page: steps, skill source, arm temperatures, vision, voice, latencies, errors |
| http://localhost:8000/demo | judge console: 1 surgical, 2 bench, R reset, Space stop, J judge mode |
| http://localhost:8000/nurse | nurse console: pose, side and wrist cameras, count against the camera |
| http://localhost:8000/tablet.html | big-type tablet view |
| http://localhost:8001/ | vision preview (`/stream` MJPEG, `/health` with `fps.overhead` and `detect_p50_ms`) |
| http://localhost:3000/health | voice server (key booleans, never values) |
| http://localhost:8080/ (`/cases.html`, `/card.html`, `/series.html`, `/memory.html`) | public judge page, case replay, table card, series, memory |
| http://144.202.95.111/ | the public page on Vultr (HTTP only) |
| http://localhost:8002/web/viewer.html | sim 3D viewer |
| http://localhost:8090/ | recording station or recorder page |
| http://localhost:8093/ | live arm temperatures |

## Tests

Run on this worktree Sun Oct 18, 1:35 to 1:45 AM.

| Suite | Command | Result |
| --- | --- | --- |
| controller flows | `PY -m controller.test_flows` | 85/85 passed |
| run_all | `PY -m controller.test_run_all` | 32 OK |
| trials | `PY -m controller.trials --self-test` | 20 OK |
| doctor | `PY -m controller.test_doctor` | prints "doctor ok" (STATUS run, 1:00 to 1:30 AM) |
| arm | `PY -m unittest discover -s arm -t . -p "test_*.py"` | 134 OK |
| vision | `PY -m vision.test_vision`; `PY -m pytest -q vision/test_clips.py vision/test_reading.py` | 47 OK; 35 passed |
| ledger | `PY -m ledger.test_ledger` | 22 OK |
| deploy | `PY -m deploy.test_check_env` | 8 OK |
| sim | `PY -m pytest -q sim/test_sim.py` | 17 passed |
| station | `PY -m pytest -q explore/station/test_station.py` | 3 passed |
| recognition bench | `PY -m pytest -q explore/recognition` | 30 passed |
| thermal analyzer | `PY -m unittest discover -s explore -p test_thermal_analyze.py` | 13 OK |
| video | `PY -m pytest -q video` | 25 passed, 1 failed here: the Playwright browser is not installed under this worktree's `data/video/browser` (environment, not code) |
| voice | `cd voice && npm test` | voice tests passed |

Run suites one at a time. Several at once can collide on shared test ports.

## Live checks

`PY -m deploy` on the arm Mac at 1:40 AM:

| Service | Result |
| --- | --- |
| Perceptron robotics | PASS, HTTP 200 |
| Perceptron detect | PASS (key ok, HTTP 400 on the 1x1 test image) |
| Perceptron deployment | FAIL: the id in `PERCEPTRON_DEPLOYMENT_ID` is not among 0 deployments |
| Gemini, ElevenLabs, MongoDB Atlas, Hugging Face | PASS |
| Vultr public page | PASS, HTTP 200 |
| Photon | FAIL, HTTP 403 (the probe sends the Spectrum secret to a REST path; `docs/INTEGRATION.md` treats it as unreliable) |
| Tiger Data, Backboard | FAIL, keys missing |
| controller :8000, vision :8001, voice :3000 | PASS (running) |

Key names set in `.env` (values never read): PERCEPTRON_TEAM_API_KEY, PERCEPTRON_DEPLOYMENT_ID, PERCEPTRON_API_KEY, HF_TOKEN, HF_USER, GEMINI_API_KEY, ELEVENLABS_API_KEY, VOICE_LLM_SECRET, MONGODB_URI, SCRUB_SERVER_IP, SPECTRUM_PROJECT_ID and SPECTRUM_PROJECT_SECRET (read as the Photon keys), CAMERA_INDEX. Missing: SO101_PORT, SCRUB_PUBLIC_URL, TIGER_DATABASE_URL, BACKBOARD_API_KEY, BACKBOARD_ASSISTANT_ID. `deploy` reports ELEVENLABS_AGENT_ID as set although no `ELEVENLABS_AGENT_ID=` line with a value is in `.env` (it may come from the shell).

Running at 1:45 AM: vision on :8001 is an older `--fake` build (its `/health` has no `fps` or `detect_p50_ms`), and the controller on :8000 is a fake-arm build whose `/state` has no `skills` or `arm_telemetry`. No recorder holds the arm ports.

## Proven live (from `docs/INTEGRATION.md`, 1:00 AM)

| Proven | Not proven |
| --- | --- |
| Perceptron robotics key (`arm.train capabilities`, `ready_for_training: true`) | Live inference: 0 deployments, no job recorded in any doc |
| Perceptron detect in `vision/` (HTTP 200 in 1.8 s; bench found rate 0.4 on 5 synthetic cases, median 2.7 s) | Detect accuracy on real trays |
| Gemini: voice parse, doctor, recognition bench | Gemini tray check in the live path (only in the bench) |
| ElevenLabs speech in the room (22 KB mp3 returned) | The phone agent on a call |
| MongoDB Atlas: 33,814 event docs in `scrub.events`, 2,148 in `scrub.thermal` | Photon: no real text or call sent |
| Vultr page `http://144.202.95.111/api/stats` with live Atlas numbers | GoDaddy domain and HTTPS |
| MediaPipe landmarker ran on a blank frame | MediaPipe model cached on this Mac (`vision/models/` is empty) |
| MuJoCo sim stack and scripted backup run | Tiger Data, Backboard (no keys; pages run from the local ledger) |
| `run_all --base-port 8100 --ledger --judge --skills auto --offline`: every URL answered | Any real-arm try |

## Fake or not real yet

- The arm in every passing run is the fake arm or the sim arm. No real handoff has happened.
- Success tables show "No real-arm tries yet." Fake-arm and sim rows are left out (`GET /api/stats?sim=1` includes them).
- Recorded data: 6 unlogged episodes in `~/scrub-dataset`, plus two 4-episode test sets from Oct 17 (`~/scrub-dataset-backup-1820`, `~/scrub-dataset-blackwrist-1820`). None count toward training.
- Hardware seen on Oct 17: follower `/dev/tty.usbmodem5C821089781`, leader `/dev/tty.usbmodem5C821067211`, calibration ids `scrub_follower` and `scrub_leader` (follower recalibrated 21:49). The side camera (C920) was not seen; the wrist camera (icspring) ran 640x480 at 22.6 fps and needs 28 or more.
- Thermal (Oct 17 230 s torque-on hold): gripper fastest at 1.13 C/min, peak 55 C; other motors 0.84 to 1.07 C/min. Recorder runs were 2 to 48 s, too short for a phase or load conclusion (`explore/research/overheating/HANDOFF.md`). The guard cools the arm at 60 C.
- Perceptron allows 2 successful training jobs per team.
- Tiger Data and Backboard pages answer from the local ledger, not those services.
- `video/` demo assets are synthetic until real footage is ingested.

## Safety rules held in code

Stop works from every state and thread. Freeze resends the last command (no sag, no slack grip). A chunk older than capture plus 400 ms never runs. Handoff only inside the region and only to an open hand with a clear path. Sharps go to the safe spot, never hand to hand. Only `POST /reset` rearms after a stop. The claw guard and range clamp keep the gripper from stalling. Serial ports held by another process are refused. Details and tests: `docs/AUDIT.md`.

## Related docs

`README.md` (run steps), `docs/SETUP.md`, `docs/BRINGUP.md` (first contact with the arm), `docs/TRAINING.md` (recording and the two runs), `docs/TEACH.md` (taught skills), `docs/ARM.md`, `docs/PERCEPTRON-ROBOTICS.md`, `docs/RECOGNITION.md`, `docs/VIDEO-TOOL.md`, `docs/DESIGN-SYSTEM.md`, `docs/DATA-LOG.md`, `docs/AUDIT.md`, `docs/DEMO.md`.

## After DubHacks

The business case and roadmap are in `docs/BUSINESS.md`: break-even is 22 operating room minutes saved per room per month ($792 a month at $36 an OR minute, JAMA Surgery 2018).
