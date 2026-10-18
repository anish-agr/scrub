# Scrub

A robot arm that passes instruments by voice. Built at DubHacks '26 (Oct 17 to 18, 2026).

A clinician asks for an instrument out loud. The SO-101 arm picks it from the tray, carries it to the handoff point, slows down as it gets there, and lets go when they pull or say "got it." Then it goes straight home on its own. Scrub keeps a running count and reads back what's out.

The tray holds three instruments: scalpel handle, hemostat and Mayo scissors. On the real arm, putting an instrument back is manual. The demo video shows a simulated electromagnet return, labeled as simulation.

## How it fits together

```
phone on speaker
  -> Photon number -> ElevenLabs voice agent -> voice/ (Gemini turns words into a command)
                                                   |
                                                   v
vision/ (camera: tray state) -> controller/ -> arm/ -> SO-101
                                                   |            (taught skill today; Perceptron model once deployed)
                                                   v
                                    ledger/ (MongoDB) + dashboard/ (web page)
```

Only the controller moves the arm. Everything else sends it information.

Status, as of 07:15 Oct 18: the controller, vision, voice, ledger, dashboard, sim arm and fake arm run and are tested. On the real arm, the recording station (`explore/station/`) picks and hands over with skills we taught it: each one replays an averaged path from our recorded demonstrations. No Perceptron model is deployed (0 deployments), so no pick comes from a model, and each event says which source moved the arm. The Photon line (+1 785 867 1047) goes to the ElevenLabs agent and `voice/`; without a call you can drive the same voice server with `cd voice && npm run say -- "grab me the kelly"`. What each tool does today, with proof commands, is in [docs/INTEGRATION.md](docs/INTEGRATION.md).

## Folders and owners

| Folder | What | Owner |
| --- | --- | --- |
| `controller/` | FastAPI server, command flows, safety, fake arm, `run_all` (whole stack), ops page, doctor | Caiden |
| `voice/` | Photon + ElevenLabs + Gemini (TypeScript) | Caiden |
| `explore/` | Recorder, recording station, thermal logging, dataset QA, recognition bench. Also idea prototypes and research that move out before release. See `explore/README.md` | Caiden |
| `sim/` | MuJoCo SO-101 with the same arm interface (tests, backup demo) | Caiden |
| `deploy/` | Vultr public page scripts and `python -m deploy` (checks every key and service) | Caiden |
| `arm/` | LeRobot wrapper, hardware layer, `move_to`, taught skills, recording, training pipeline | Anish |
| `docs/` | contracts, setup, arm and training guides, integration proof | Anish |
| `vision/` | camera, calibration, Perceptron tray perception, OCR reads, event clips | Brandon |
| `dashboard/` | the web page and tablet view | Evan |
| `ledger/` | MongoDB logging, success tables, case replay, public judge page | Evan |
| `settings/` | one JSON file per tray (the demo uses `surgical.json`) | Evan |
| `design/` | the shared stylesheet and its check scripts | Evan |
| `video/` | builds the demo and arm videos from the ledger and dataset | Evan |
| `team/` | the team's working notes (status, tasks, pitch, prompts). Removed before the repo goes public | everyone |

`data/` holds local recordings and is not committed. Only edit your own folder. To change something in someone else's folder, ask them.

## Docs

- [docs/OVERVIEW.md](docs/OVERVIEW.md): **start here.** Every idea, decision and part of the project in one place
- [docs/INTEGRATION.md](docs/INTEGRATION.md): every tool Scrub uses, where it is called, the command that proves it, and whether it passed
- [docs/CONTRACTS.md](docs/CONTRACTS.md): the messages and endpoints every part codes against
- [docs/SETUP.md](docs/SETUP.md): accounts, keys, installs
- [docs/BRINGUP.md](docs/BRINGUP.md): first power-on of the arm and cameras
- [docs/ARM.md](docs/ARM.md): connecting the arm, recording demos, training
- [docs/TRAINING.md](docs/TRAINING.md): what to record and the operator checklist
- [docs/TEACH.md](docs/TEACH.md): taught skills, what moves the real arm today
- [docs/PERCEPTRON-ROBOTICS.md](docs/PERCEPTRON-ROBOTICS.md): Perceptron's training, inference and vision APIs (schema in `docs/perceptron-openapi.json`)
- [docs/RECOGNITION.md](docs/RECOGNITION.md): tray recognition bench results
- [docs/BUSINESS.md](docs/BUSINESS.md): the business case
- [docs/DESIGN-SYSTEM.md](docs/DESIGN-SYSTEM.md), [docs/VIDEO-TOOL.md](docs/VIDEO-TOOL.md): the shared stylesheet and the video tool
- [docs/DATA-LOG.md](docs/DATA-LOG.md): one row per recorded batch
- [AGENTS.md](AGENTS.md): rules for Claude, Codex and Cursor in this repo

Team working notes, removed before the repo goes public: [team/LEFT.md](team/LEFT.md) (what's left, who, steps, deadline), [team/STATE.md](team/STATE.md) (what exists and works), [team/PROMPTS.md](team/PROMPTS.md) (the prompt to paste into your agent), [team/PITCH.md](team/PITCH.md), [team/DEMO.md](team/DEMO.md).

## Running it

Once, from the repo root (Python 3.10, Node 20):

```
python3.10 -m venv .venv
.venv/bin/pip install -r controller/requirements.txt -r vision/requirements.txt -r ledger/requirements.txt
.venv/bin/pip install -r sim/requirements.txt        # only for the sim arm
cd voice && npm install && cd ..
cp .env.example .env                                  # fill in the keys; never commit .env
```

One command starts the whole stack and prints every URL (Ctrl-C stops it all):

```
.venv/bin/python -m controller.run_all                          # fake arm, fake vision, voice
.venv/bin/python -m controller.run_all --arm sim                # MuJoCo arm, viewer at :8002/web/viewer.html
.venv/bin/python -m controller.run_all --real --tunnel          # judging: real arm, real camera, ledger, judge mode, public voice URL
```

`--real` is `--arm real --vision real --ledger --judge --skills auto`; each part can still be overridden. `--skills model|taught|auto` picks what moves the arm (`auto` uses the model for an item once a deployment exists and the item passed its last 3 real tries). Add `--judge` for judge mode (only handover, count and stop), `--no-voice`, or `--ledger` (public page on 8080).

A second stack beside a live one (for testing) needs `--base-port 8100 --offline`. The ports move together: controller 8100, vision 8101, sim 8102, voice 3100, ledger 8103. `--offline` matters: voice reads its keys from `.env`, so without it a second voice server also listens on the live Photon line. It also keeps the ledger off MongoDB (it buffers to `ledger/buffer.jsonl`, or `LEDGER_BUFFER`). On a moved stack, open the dashboard as `http://localhost:8100/?vision=http://localhost:8101&ledger=http://localhost:8103`. Without those, it shows the camera on 8001 and links the ledger page on 8080.

| URL | What |
| --- | --- |
| http://localhost:8000/ | dashboard |
| http://localhost:8000/demo | judge console: 1 surgical, R reset, Space stop, J judge mode |
| http://localhost:8000/ops | operator page: step, skill source, arm temperatures, camera rates, latencies, errors |
| http://localhost:8000/nurse, /tablet.html | nurse console, tablet view |
| http://localhost:8001/ | vision preview (`/stream` is the camera) |
| http://localhost:3000/health | voice server (ElevenLabs uses `<tunnel>/v1`) |

At the demo table (the full run order is in [team/DEMO.md](team/DEMO.md)):

```
.venv/bin/python -m controller.run_all reset     # between judges: clear the count, surgical tray, normal light
.venv/bin/python -m controller.run_all backup    # the arm failed: the sim arm plays a full run
.venv/bin/python -m controller.run_all check --url http://localhost:8000 --vision-url http://localhost:8001 --voice-url http://localhost:3000
                                                 # the running stack: every part answers and connects
```

`check` without `--url` starts its own fake stack on 8100 and checks that instead. With `--url` it never moves a real arm. It does switch to another tray setting and back, which clears the count, and on a fake or sim arm it runs one hemostat handover. So run it before a case, then `run_all reset`.

Each part also runs alone: `.venv/bin/python -m controller --fake-arm` (8000), `.venv/bin/python -m vision --fake` (8001), `cd voice && npm run dev` (3000), `.venv/bin/python -m ledger serve` (8080). The docs write `python -m ...` for short; on the Mac that means `source .venv/bin/activate` first.

A health check of every service, key (names only) and log: `.venv/bin/python -m controller.doctor` (add `--no-ai` to skip the Gemini fix list).

Tests:

```
.venv/bin/python -m controller.test_flows        # every flow and failure on the fake arm
.venv/bin/python -m controller.test_run_all
.venv/bin/python -m vision.test_vision
.venv/bin/python -m unittest discover -s arm -t . -p "test_*.py"
.venv/bin/python -m pytest -q sim/test_sim.py ledger/test_ledger.py
.venv/bin/python -m unittest video.test_video
cd voice && npm test
```

Recording demos for training: `.venv/bin/python -m arm.check_setup --side C920 --wrist icspring`, then `.venv/bin/python -m arm.record --lighting normal` (add `--item` and `--direction`; see `--help`) ([docs/TRAINING.md](docs/TRAINING.md)).

## Team

Anish, Caiden, Brandon, Evan.
