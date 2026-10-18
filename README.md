# Scrub

A robot arm that passes instruments by voice. Built at DubHacks '26 (Oct 17 to 18, 2026).

A clinician asks for an instrument out loud. The SO-101 arm picks it from the tray and brings it to the clinician's open hand, handle first, and lets go when they pull or say "got it." Scalpels go to a fixed safe spot instead of hand to hand. Instruments set in the return spot go back to their slots. Scrub keeps a running count and reads back what's out.

Scrub is surgical first: the operating room tray is the main setting. The robotics bench tray is the second setting, to show that a new setting needs only demonstrations and no new code. A dental tray file exists in `settings/` but isn't demoed.

| Setting | Items |
| --- | --- |
| Operating room | scalpel handle, hemostat, Mayo scissors |
| Robotics bench | needle-nose pliers, wire cutters, hex key |

## How it fits together

```
phone on speaker
  -> Photon number -> ElevenLabs voice agent -> voice/ (Gemini turns words into a command)
                                                   |
                                                   v
vision/ (camera: tray state + hand position) -> controller/ -> arm/ -> Isaac 0.5 (Perceptron) -> SO-101
                                                   |
                                                   v
                                    ledger/ (MongoDB) + dashboard/ (web page)
```

Only the controller moves the arm. Everything else sends it information.

## Folders and owners

| Folder | What | Owner |
| --- | --- | --- |
| `controller/` | FastAPI server, command flows, safety, fake arm | Caiden |
| `voice/` | Photon + ElevenLabs + Gemini (TypeScript) | Caiden |
| `arm/` | LeRobot wrapper, policy runner, `move_to`, recording scripts | Anish |
| `vision/` | camera, MediaPipe hand tracker, calibration, Perceptron tray perception | Brandon |
| `dashboard/` | the web page | Evan |
| `ledger/` | MongoDB logging and the success tables | Evan |
| `settings/` | one JSON file per tray | Evan |
| `docs/` | plan, tasks, contracts, setup | Anish |

Only edit your own folder. To change something in someone else's folder, ask them.

## Docs

- [docs/PROMPTS.md](docs/PROMPTS.md): **start here.** The prompt to paste into your agent, and which model to use
- [docs/TASKS.md](docs/TASKS.md): what each person does, in order
- [docs/STATUS.md](docs/STATUS.md): checkboxes; the first unchecked one is your next task
- [docs/PLAN.md](docs/PLAN.md): the timeline, checkpoints, demo and submission
- [docs/CONTRACTS.md](docs/CONTRACTS.md): the messages and endpoints every part codes against
- [docs/SETUP.md](docs/SETUP.md): accounts, keys, installs
- [docs/ARM.md](docs/ARM.md): connecting the arm, recording demos, fine-tuning
- [docs/PERCEPTRON-ROBOTICS.md](docs/PERCEPTRON-ROBOTICS.md): Perceptron's training and inference API (schema in `docs/perceptron-openapi.json`)
- [docs/PITCH.md](docs/PITCH.md): the pitch, demo run, video shot list, judge Q&A
- [AGENTS.md](AGENTS.md): rules for Claude, Codex and Cursor in this repo

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
.venv/bin/python -m controller.run_all --arm real --vision real --tunnel   # the demo: real arm, camera, public voice URL
```

Add `--judge` for judge mode (only handover, count and stop), `--no-voice`, `--ledger` (public page on 8080), or `--base-port 8100` to run a second stack beside a live one.

| URL | What |
| --- | --- |
| http://localhost:8000/ | dashboard |
| http://localhost:8000/demo | judge console: 1 surgical, 2 bench, R reset, Space stop, J judge mode |
| http://localhost:8000/nurse, /tablet.html | nurse console, tablet view |
| http://localhost:8001/ | vision preview (`/stream` is the camera) |
| http://localhost:3000/health | voice server (ElevenLabs uses `<tunnel>/v1`) |

At the demo table (the full run order is in [docs/DEMO.md](docs/DEMO.md)):

```
.venv/bin/python -m controller.run_all reset     # between judges: clear the count, surgical tray, normal light
.venv/bin/python -m controller.run_all backup    # the arm failed: the sim arm plays a full run
.venv/bin/python -m controller.run_all check     # every part answers and connects
```

Each part also runs alone: `python -m controller --fake-arm` (8000), `python -m vision --fake` (8001), `cd voice && npm run dev` (3000), `python -m ledger serve` (8080).

Tests:

```
.venv/bin/python -m controller.test_flows        # every flow and failure on the fake arm
.venv/bin/python -m controller.test_run_all
.venv/bin/python -m vision.test_vision
.venv/bin/python -m unittest discover -s arm -t . -p "test_*.py"
.venv/bin/python -m pytest -q sim/test_sim.py ledger/test_ledger.py
cd voice && npm test
```

Recording demos for training: `python -m arm.check_setup`, then `python -m arm.record` ([docs/TRAINING.md](docs/TRAINING.md)).

## Team

Anish, Caiden, Brandon, Evan.
