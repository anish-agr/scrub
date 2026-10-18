# explore/ (Caiden)

Start with [ARM-RUNBOOK.md](ARM-RUNBOOK.md) (how to record, safety, heat, data, open items). Tools built on the recording Mac while we brought up the SO-101: the recording station that ran the real arm, telemetry, dataset checks, data analysis and the recognition benches. The product is `controller/`, `arm/`, `vision/`, `voice/`, `dashboard/` and `ledger/`. Links into this folder: `arm/pipeline.py` imports `explore.dataset.qa` and `qa_video`, `arm/record.py` runs `explore/arm_session.py` as its default recorder, `arm/check_setup.py`
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
| `thermal_plot.py` | Heat graphs (PNG) from the telemetry logs into `~/scrub-logs/thermal-plots`. Reads logs only |
| `station/` | Hardware. The recording station on :8090: one process, arms/cameras/dataset open once, start/save/discard, KILL, home, and Run mode for replays. See `ARM-RUNBOOK.md` and `station/README.md` |
| `station/run_station.sh` | Supervisor: restarts the station when it asks (hung camera, Reconnect). `explore/station/run_station.sh --task "pick the hemostat"` |
| `station/autopick.py`, `autopick_calib.json` | The station's pick and handoff driver: averages the recorded demonstrations of an item into one path, holds the instrument out, lets go on a pull or "let go". Also the camera calibration and detection modes |
| `station_voice.py` | Speaks station updates (ElevenLabs, Mac voice offline) from `GET /status`; never sends a command |
| `test_arm_session.py` | Offline tests: busy-port refusal, explicit `use_degrees`, `--help` of the port tools |

## Dataset, bench and recognition

| Path | What |
| --- | --- |
| `dataset/` | Read-only dataset QA, grasp variety, sim replay and camera aim, with offline tests on a synthetic dataset. See `dataset/README.md` |
| `bench/console.py`, `console.html` | Test bench console on :8098 against a controller started with `--sim-arm --setting bench` |
| `bench/identify.py`, `identify.html` | On-device tray identifier on :8097 (Apple Vision OCR and torchvision). Reference crops go in `bench/refs/<item_id>/` (not committed) |
| `analysis/` | `python -m explore.analysis`: read-only MongoDB report (training episodes, real-arm handoffs, heat, reading) into `docs/DATA.md`, `docs/media/data/` and `data/analysis.json`; `--fixture` runs on a JSON dump. Tests: `.venv/bin/python -m pytest -q explore/analysis` |
| `recognition/bench.py`, `test_bench.py` | Perceptron detect and Gemini on saved tray images: `python -m explore.recognition.bench`. Results in `recognition/out/` (generated) |
| `recognition/read_bench.py`, `capture.py`, `props.py`, `props/` | Reading (OCR) bench scored against `props/truth.json`, a labeled photo capture tool, and the printable props with their test images |

## Research

| Path | What |
| --- | --- |
| `research/overheating/README.md` | Why the follower overheats, the telemetry schema, and resting at home between commands |

Tests: `.venv/bin/python -m pytest -q explore`.
