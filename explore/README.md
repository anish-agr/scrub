# explore/ (Caiden)

Tools built on the recording Mac while we brought up the SO-101, plus the prototypes and research from
Saturday. The product is `controller/`, `arm/`, `vision/`, `voice/`, `dashboard/` and `ledger/`; nothing there
imports this folder. `arm/record.py` runs `explore/arm_session.py` as its default recorder, `arm/check_setup.py`
reads that file's port names, and `controller/doctor.py` looks for its process.

Every command runs from the repo root with `.venv/bin/python`. Scripts that open the arm ports or the cameras
are marked "hardware".

## Recording and the arm on the Mac

| Path | What |
| --- | --- |
| `arm_session.py` | Hardware. The recorder: teleop or `lerobot-record` with the leader/follower pair, ease-in, claw and joint guards, cool-down, park, camera reconnects, a supervisor that restarts sessions. Refuses to start while another process has an arm port open. `--check` (no hardware) says if `~/scrub-dataset` is ready to train. `--help` lists the flags |
| `arm_ui.py`, `arm_ui.html` | The recorder page on http://localhost:8090, run inside `arm_session.py` |
| `arm_voice.py` | The arm speaks its lines (ElevenLabs, macOS `say` offline). `arm_voice.py "Ready."` |
| `home_pose.py`, `home_pose.json` | Hardware. Save, show and test the folded home pose: `home_pose.py {save,show,test,home,on,off}` |
| `calibrate_follower.py` | Hardware. Recalibrate the follower without the Oct 17 traps. Refuses while another process has the port |
| `thermal_log.py` | Telemetry rows to `~/scrub-logs/thermal` and MongoDB. `thermal_log.py {watch,upload,snapshot,idle}`; `snapshot` and `idle` need free ports |
| `thermal_analyze.py`, `test_thermal_analyze.py` | Report on what made the arm hot, from those rows |
| `thermal_web.py` | Live temperature page on :8093 |
| `station/` | A single-process recording station (in progress in another session) |
| `test_arm_session.py` | Offline tests: busy-port refusal, explicit `use_degrees`, `--help` of the port tools |

## Dataset, bench and recognition

| Path | What |
| --- | --- |
| `dataset/` | Read-only dataset QA, grasp variety, sim replay and camera aim, with offline tests on a synthetic dataset. See `dataset/README.md` |
| `bench/console.py`, `console.html` | Test bench console on :8098 against a controller started with `--sim-arm --setting bench` |
| `bench/identify.py`, `identify.html` | On-device tray identifier (Apple Vision OCR and torchvision) |
| `bench/refs/` | Saved crops per item, used by `recognition/` |
| `analysis/` | `python -m explore.analysis`: read-only MongoDB report (training episodes, real-arm handoffs, heat, reading) into `docs/DATA.md`, `team/NOTES-DATA.md`, `docs/media/data/` and `data/analysis.json`; `--fixture` runs on a JSON dump. Tests: `.venv/bin/python -m pytest -q explore/analysis` |
| `recognition/bench.py`, `test_bench.py` | Perceptron detect and Gemini on saved tray images: `python -m explore.recognition.bench`. Results in `recognition/out/` and `docs/RECOGNITION.md` |

## Notes, pages and prototypes (moving to `team/`)

| Path | What |
| --- | --- |
| `pages/` | Single-file pages: track playbook, startup case, setup and test, overheating |
| `prototypes/` | The idea gallery (`prototypes/index.html`, mock data, no server). Rebuild: `python3 team/prototypes/build_gallery.py` |
| `research/` | Surgeon research, tracks, workshop notes. Check each stat against its source before it goes on a slide |
| `status-board/` | Status board mockups |
| `IDEAS-BACKLOG.md` | Feature ideas written before the repo plan; ideas only |

Tests: `.venv/bin/python -m pytest -q explore/test_arm_session.py explore/test_thermal_analyze.py explore/dataset/test_dataset_tools.py` and
`.venv/bin/python -m unittest explore.recognition.test_bench`.
