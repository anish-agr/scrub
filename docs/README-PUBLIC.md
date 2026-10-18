# Scrub

A robot arm that passes surgical instruments when you ask out loud. Built at DubHacks '26 (Oct 17 to 18, 2026) by Anish, Caiden, Brandon and Evan.

You ask for the scalpel, the hemostat or the Mayo scissors. The SO-101 arm picks it from the tray and holds it out at the handoff point. It lets go when you pull it or say "let go", then goes straight home. "Stop" freezes the arm where it is.

On the real arm, the picks are taught skills: replays of demonstrations we recorded ourselves (29 episodes, 24 usable). We did not run a fine-tuning job, so no model drives the arm. In the simulation, the controller slows the arm for the last stretch to the handoff point.

Scrub is a research prototype, not a medical device. It never touches the patient and makes no clinical claims.

## Why

Hospitals can't hire enough scrub techs. A surgical tech job takes about 120 days to fill ([Periop Leader, 2024](https://www.periopleader.com/survey-staffing-woes-ease-slightly-but-challenges-remain/)). Without one, the surgeon looks away from the patient to search the tray. Counts and sharps matter: one Mayo Clinic study found an item left inside a patient about once in 5,500 operations ([Cima et al., 2008](https://pubmed.ncbi.nlm.nih.gov/18589366/)), and US hospital staff have about 385,000 needle and sharps injuries a year ([CDC](https://www.cdc.gov/sharpssafety/)).

## How it works

- **Voice.** A call to the Photon number reaches an ElevenLabs voice agent, whose language model is our voice server (`voice/`). Gemini turns the words into one command from the tray's fixed list. Known names and "stop" skip Gemini. Without a phone: `cd voice && npm run say -- "grab me the kelly"`.
- **Arm.** The real arm runs through the recording station (`explore/station/`), which replays each instrument's recorded demonstration. The controller (`controller/`) runs the same flow on a fake arm or a MuJoCo sim arm.
- **Vision.** Perceptron's vision API reads the tray and, with OCR, the printed count sheet (`vision/`).
- **Sim.** A MuJoCo SO-101 (`sim/`) runs the controller's flow when the real arm is busy.
- **Ledger.** Every event goes to MongoDB Atlas (`ledger/`). The public page runs on Vultr.

## Safety

- "Stop" freezes the arm where it is. In the controller it stays frozen until a reset (`controller/core.py`).
- Motor temperatures are checked every couple of seconds. At 60 C the arm goes home and turns the motors off until they cool (`arm/thermal.py`, `explore/station/station.py`).
- Every move is speed-capped: 45 degrees a second peak on the real arm, slower once a motor passes 52 C (`explore/station/autopick.py`).
- In the controller, joint commands are clamped to the arm's limits and the grasp is checked before carrying (`arm/real_arm.py`, `controller/core.py`).
- It lets go when you pull the instrument or tell it to.

## How to run

Once, from the repo root (Python 3.10, Node 20):

```
python3.10 -m venv .venv
.venv/bin/pip install -r controller/requirements.txt -r vision/requirements.txt -r ledger/requirements.txt
.venv/bin/pip install -r sim/requirements.txt        # only for the sim arm
cd voice && npm install && cd ..
cp .env.example .env                                  # fill in your own keys; never commit .env
```

One command starts the stack and prints every URL (Ctrl-C stops it all):

```
.venv/bin/python -m controller.run_all                 # fake arm, fake camera, voice
.venv/bin/python -m controller.run_all --arm sim       # MuJoCo arm, viewer at :8002/web/viewer.html
.venv/bin/python -m controller.run_all --ledger        # also the public page on :8080
```

Then open http://localhost:8000/ for the dashboard. With `--ledger`, the public page is http://127.0.0.1:8080/.

The real arm needs the SO-101 plugged in and `explore/station/run_station.sh`; voice finds the station on `localhost:8090` by itself. The phone call needs Photon and ElevenLabs set up as in `voice/README.md`.

Tests:

```
.venv/bin/python -m controller.test_flows
.venv/bin/python -m vision.test_vision
.venv/bin/python -m pytest -q sim/test_sim.py ledger/test_ledger.py
cd voice && npm test
```

## Tracks

| Track | Proof |
| --- | --- |
| Community Kitchen | The project |
| Perceptron Robotics | The arm on video, picks labeled as taught skills. No fine-tuning job (0 jobs, 0 deployments) |
| Perceptron Perception | Tray check and OCR read on video, with latency |
| Photon | A call to +1 785 867 1047 on video (not yet confirmed) |
| DubHacks NEXT | `docs/BUSINESS.md` |
| MLH Gemini API | Words to one command from the tray's fixed list |
| MLH MongoDB Atlas | Event log and arm temperature log |
| MLH Vultr | The public judge page |

## Team

Anish (arm and training), Caiden (controller and voice), Brandon (camera), Evan (dashboard, ledger and data).
