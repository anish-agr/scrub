# State of Scrub

Read `README.md` first, then this page. Written Oct 17, 2026 from the code, the tests and the running services, not from `docs/STATUS.md`.

Scrub is an SO-101 arm that passes surgical instruments by voice. Surgical tray first (scalpel handle, hemostat, Mayo scissors). Robotics bench tray second (needle-nose pliers, wire cutters, hex key), to show a new setting needs demos and no new code. Dental is hidden; `settings/dental.json` stays on disk. Only the controller moves the arm.

## In one paragraph

Software is finished and tested on the fake arm and the MuJoCo sim arm. The real arm path exists in code but has never run on hardware: no demos are recorded, no model is trained, `arm/rig.json` is an unmeasured template (`hardware_verified: false`), and `vision/calibration.json` does not exist. The wrist camera runs at about 23 fps and is dark. The phone line and the end-of-case text need accounts and clicks that only a person can do.

## Data flow

```
phone -> Photon number -> ElevenLabs agent --(Custom LLM, via tunnel)--> voice :3000 -> Gemini (word -> Command)
                                                                              | POST /command, /stop
overhead camera -> vision :8001 --POST /vision/hand, /vision/tray--> controller :8000 --move/pick/release--> arm
                                                                              |  (fake | sim :8002 | real SO-101 + Perceptron Isaac)
                                                                              +--events (WS /events)--> dashboard, tablet, nurse, demo console
                                                                              +--log--> ledger --> MongoDB Atlas --> public page :8080
voice <-- WS /events (spoken lines)          Photon text in: restock, what's out, check the tray, summary
voice --end of case--> Photon text out: count, items, times, case replay link
```

## Parts

Status words: works, works offline only (tested on fakes or sim, needs hardware or an account to be real), partial, missing. All commands run from the repo root; `PY` is `.venv/bin/python`.

| Part (owner) | What it does | Start | Port | Depends on | Tests | Status |
| --- | --- | --- | --- | --- | --- | --- |
| `controller/` (Caiden) | Command flows, safety, step machine, events, serves dashboard, demo, nurse | `PY -m controller` (`--sim-arm`, `--real-arm`, `--judge`, `--setting bench`) | 8000 | arm (fake, sim or real), vision posts, ledger; keys: none | `PY -m controller.test_flows` (53/53) | works offline only: fake and sim arm pass; real arm never run |
| `controller/run_all.py` | One command starts controller, vision, voice, tunnel, optional ledger; prints URLs; `reset`, `backup`, `check` | `PY -m controller.run_all` (`--arm sim`, `--arm real --vision real --tunnel`, `--base-port 8100`) | moves 8000/8001/8002/3000/8080 | all parts below; tunnel needs `ssh` (Pinggy) | `PY -m controller.test_run_all` (27 OK) | works |
| `voice/` (Caiden) | Call and text path: ElevenLabs Custom LLM endpoint, Gemini to Command, spoken lines, Photon texts, end-of-case summary | `cd voice && npm run dev` (tunnel: `npm run tunnel`) | 3000 | controller; keys GEMINI_API_KEY, ELEVENLABS_*, PHOTON_PROJECT_ID + PHOTON_API_KEY (or SPECTRUM_PROJECT_ID + SPECTRUM_PROJECT_SECRET), VOICE_LLM_SECRET (optional), PHOTON_SUMMARY_TO | `cd voice && npm test` (passes, offline) | works with Gemini; the live call and texts need Photon and ElevenLabs set up by a person (C3 open) |
| `vision/` (Brandon) | Locked-exposure camera, MediaPipe hand, Perceptron tray detect, `path_clear`, MJPEG preview, tray check | `PY -m vision` (`--fake` with no camera) | 8001 | overhead camera; PERCEPTRON_API_KEY, CAMERA_INDEX | `PY -m vision.test_vision` (passes) | partial: runs on the real camera; no `calibration.json`, slot boxes not marked (B5, B6), lighting tests open (B8) |
| `arm/` (Anish) | Arm interface, LeRobot real arm, 30 Hz streaming, kinematics, sessions, recorder, training CLI | no server. Check: `PY -m arm.check_setup`; record: `PY -m arm.record`; train: `PY -m arm.train status` | none | SO-101, side and wrist cameras, Perceptron Robotics API; keys PERCEPTRON_TEAM_API_KEY, PERCEPTRON_DEPLOYMENT_ID, HF_TOKEN, SO101_PORT | `PY -m unittest discover -s arm -t . -p "test_*.py"` (78 OK, 9 suites) | works offline only: no episodes recorded, no training run, rig unmeasured |
| `sim/` (Caiden) | MuJoCo SO-101 and table; same Arm interface; 3D viewer; backup-demo arm | `PY -m sim` (or `controller --sim-arm`) | 8002 | MuJoCo, `sim/models` | `PY -m pytest -q sim/test_sim.py` (16 passed; `python -m sim.test_sim` also runs) | works |
| `ledger/` (Evan) | Logs events and test results, success tables, case replay, public judge page, QR | `PY -m ledger serve` (page); `PY -m ledger log ...` (DATA-LOG row) | 8080 | MongoDB Atlas (MONGODB_URI); falls back to `ledger/buffer.jsonl` | `PY -m ledger.test_ledger` (11 OK) | works offline only: Atlas write was proved once (E3); MONGODB_URI is empty on this Mac; Vultr page not deployed |
| `dashboard/` (Evan) | Static pages: dashboard, tablet; tables, stale-vision warning | served by the controller | 8000 | controller | none of its own (covered by QA in `docs/QA.md`) | works |
| `settings/` (Evan) | One JSON per tray, plus `<id>.local.json` clinic-word overlay | loaded by the controller | none | slot boxes need Brandon's `mark_slots` | `controller.test_flows` loads them | partial: item lists final; slot boxes are defaults, not measured |
| `deploy/` (Brandon) | `python -m deploy` checks every key against its service; scripts for the public page server | `PY -m deploy` | none | all keys (prints PASS or FAIL, never values) | `PY -m deploy.test_check_env` (3 OK) | works; Vultr and domain not done |
| `explore/` (Caiden) | Not the build, except: `arm_session.py` (the official recorder), `arm_ui.*` (recorder page), `dataset/` (QA, variety, replay, aim), `bench/` (tray identifier), prototypes | recorder: `PY explore/arm_session.py` (or `PY -m arm.record`); page 8090 | 8090; dataset tools 8095, 8096 | arm, two cameras; ElevenLabs key for the arm's voice (optional) | none | partial: tested only against the test recording; wrist camera 23 fps and dark |

## URLs a person opens

| URL | What |
| --- | --- |
| http://localhost:8000/ | dashboard: step, what is out, log, tables, stop |
| http://localhost:8000/demo | judge console: 1 surgical, 2 bench, R reset, Space stop, J judge mode |
| http://localhost:8000/nurse | nurse console: pose, side and wrist cameras, count vs camera |
| http://localhost:8000/tablet.html | big-type tablet view |
| http://localhost:8001/ | vision preview (`/stream` is the MJPEG, `/health` is the check) |
| http://localhost:3000/health | voice server (booleans for keys, never values) |
| http://localhost:8080/ (`/cases.html`, `/card.html`) | public judge page, case replay, printable table card |
| http://localhost:8002/web/viewer.html | sim 3D viewer (sim arm only) |

## What was checked today

- Tests (this worktree): controller.test_flows 53/53; controller.test_run_all 27 OK; vision.test_vision OK; deploy.test_check_env 3 OK; ledger.test_ledger 11 OK; arm 78 OK across 9 suites; sim 16 passed; voice `npm test` passed.
- Running now on this Mac: controller :8000 answers (an old fake-arm build); vision :8001 `/health` ok with the camera open and exposure locked; voice :3000 `/health` ok with gemini and photon true and llm_secret false, controller reachable. Nothing on :8080 or :8002.
- Keys set in the main `.env`, by name only: GEMINI_API_KEY, ELEVENLABS_API_KEY, PERCEPTRON_API_KEY, PERCEPTRON_TEAM_API_KEY, PERCEPTRON_DEPLOYMENT_ID. Photon is set as SPECTRUM_PROJECT_ID and SPECTRUM_PROJECT_SECRET (voice reads them when the PHOTON_* names are empty; /health shows photon true). Empty: ELEVENLABS_AGENT_ID, MONGODB_URI, HF_TOKEN, SO101_PORT. `python -m deploy` checks each one live.
- Hardware: `arm/rig.json` unmeasured and disabled; no `vision/calibration.json`; `docs/DATA-LOG.md` has no real batch; arm_session logs exist in `~/scrub-logs`; no training job submitted (two successful runs are all Perceptron allows).

## External services and keys

| Service | Used for | Key names |
| --- | --- | --- |
| Perceptron Robotics API | datasets, training, the Isaac 0.5 arm model | PERCEPTRON_TEAM_API_KEY, PERCEPTRON_DEPLOYMENT_ID |
| Perceptron vision API | tray detect | PERCEPTRON_API_KEY |
| Hugging Face | LeRobot dataset hosting | HF_TOKEN |
| Gemini | words to Command | GEMINI_API_KEY |
| ElevenLabs | call agent (Custom LLM), the arm's spoken voice | ELEVENLABS_API_KEY, ELEVENLABS_AGENT_ID, VOICE_LLM_SECRET (optional), ELEVENLABS_VOICE_ID (optional) |
| Photon | phone number and iMessage texts | PHOTON_PROJECT_ID + PHOTON_API_KEY (or SPECTRUM_PROJECT_ID + SPECTRUM_PROJECT_SECRET), PHOTON_SUMMARY_TO (optional) |
| MongoDB Atlas | ledger | MONGODB_URI |
| Pinggy, cloudflared or ngrok | public tunnel to voice | none (ngrok needs an authtoken) |
| Vultr and GoDaddy | public judge page and domain | none in `.env`; SCRUB_PUBLIC_URL is not secret |

Local wiring (no secrets): CONTROLLER_URL, VISION_URL, VOICE_PORT, CAMERA_INDEX, SO101_PORT, SO101_SIDE_CAMERA, SO101_WRIST_CAMERA.

## Where to look next

- `docs/HARDWARE-TODO.md`: every hardware step left, in order, with the command and what you should see.
- `docs/ACCOUNTS-TODO.md`: every account and key, where to get it, and whether it works now.
- `docs/AUDIT.md`: the comb findings by severity and what was fixed.
- Also: `docs/CONTRACTS.md` (every message and endpoint), `docs/DEMO.md` (the live run), `docs/BRINGUP.md` and `docs/TRAINING.md` (first contact with the arm).
