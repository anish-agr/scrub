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

Filled in as parts land. Target:

```
python -m controller --fake-arm     # port 8000, also serves the dashboard
python -m vision                    # port 8001
cd voice && npm run dev             # port 3000
```

## Team

Anish, Caiden, Brandon, Evan.
