# Scrub

A robot arm that passes surgical instruments when you ask out loud. Built at DubHacks '26 (Oct 17 to 18, 2026) by Anish, Caiden, Brandon and Evan.

A surgeon asks for an instrument. The SO-101 arm picks it from the tray, brings it to their open hand handle first, and lets go when they pull or say "got it." A scalpel goes to a fixed safe spot instead of hand to hand. An instrument set in the return spot goes back to its slot. Scrub keeps a count, checks it with the camera, and reads back what is still out.

Surgical first. The robotics bench tray is the second setting, to show that a new tray needs new demonstrations and a settings file, not new code.

| Setting | Items |
| --- | --- |
| Operating room | scalpel handle, hemostat, Mayo scissors |
| Robotics bench | needle-nose pliers, wire cutters, hex key |

Scrub is a research prototype, not a medical device. It makes no clinical claims.

## Why

Hospitals can't hire enough scrub techs. A surgical tech job takes about 120 days to fill ([Periop Leader, 2024](https://www.periopleader.com/survey-staffing-woes-ease-slightly-but-challenges-remain/)). Without one, the surgeon looks away from the patient to search the tray. Counts and sharps matter: one Mayo Clinic study found an item left inside a patient about once in 5,500 operations ([Cima et al., 2008](https://pubmed.ncbi.nlm.nih.gov/18589366/)), and US hospital staff have about 385,000 needle and sharps injuries a year ([CDC](https://www.cdc.gov/sharpssafety/)).

## How it works

![System diagram](docs/media/system.svg)

- A phone on speaker calls a Photon number. An ElevenLabs voice agent hears the words. Gemini turns them into one command from the current tray.
- One overhead camera finds the open hand (MediaPipe) and reads the tray (Perceptron's vision API).
- Perceptron's Isaac 0.5, fine-tuned on our own demonstrations, does the pick and the return on the SO-101.
- Only the controller moves the arm. Everything else sends it information.
- Every event goes to MongoDB Atlas. The dashboard and the public page show the count and the success tables.

Stop is its own path. The word "stop", the spacebar or the button on the page freezes the arm without waiting on a model. The arm stays frozen until someone resets it.

## Pictures

From a fake-arm case.

![Dashboard](docs/media/dashboard.png)

![Tablet view, for someone across the room](docs/media/tablet.png)

![One case, played back](docs/media/case.png)

![Public page](docs/media/public.png)

The same page at phone width: [docs/media/public-phone.png](docs/media/public-phone.png).

## How to run

Once, from the repo root (Python 3.10, Node 20):

```
python3.10 -m venv .venv
.venv/bin/pip install -r controller/requirements.txt -r vision/requirements.txt -r ledger/requirements.txt
.venv/bin/pip install -r sim/requirements.txt        # only for the sim arm
cd voice && npm install && cd ..
cp .env.example .env                                  # fill in your own keys; never commit .env
```

One command starts the whole stack and prints every URL (Ctrl-C stops it all):

```
.venv/bin/python -m controller.run_all                 # fake arm, fake camera, voice
.venv/bin/python -m controller.run_all --arm fake      # same as the line above
.venv/bin/python -m controller.run_all --arm sim       # MuJoCo arm, viewer at :8002/web/viewer.html
.venv/bin/python -m controller.run_all --ledger        # also the public page on :8080
```

Then open http://localhost:8000/ for the dashboard and http://localhost:8000/tablet.html for the large view. With `--ledger`, the public page is http://127.0.0.1:8080/. Series is `/series.html`. Memory is `/memory.html`. Cases are `/cases.html`. The table card is `/card.html`.

Drive one spoken line without a phone:

```
cd voice && npm run say -- "grab me the kelly"
```

The real arm is `--arm real --vision real`. It needs the arm plugged in, a camera, `PERCEPTRON_TEAM_API_KEY` and a deployment id from training. The phone call needs Photon and ElevenLabs set up as in `voice/README.md`.

Tests:

```
.venv/bin/python -m controller.test_flows
.venv/bin/python -m vision.test_vision
.venv/bin/python -m pytest -q sim/test_sim.py ledger/test_ledger.py
cd voice && npm test
```

## Tracks

| Track | Where it shows up |
| --- | --- |
| Community Kitchen | A working assistant for a real staffing gap in health care |
| Perceptron Robotics | Isaac 0.5 fine-tuned on our own demonstrations, on the SO-101 |
| Perceptron Perception | Their vision API: tray state, grasp check, automatic return, count check, tray check |
| Photon (and best voice agent) | The whole case over a phone call, texts in, and the summary text on the same thread |
| DubHacks NEXT | Business case: surgery centers first, a monthly fee per operating room (`docs/NEXT-PASS-PROMPT.md` (section "Earlier next-steps notes")) |
| MLH Gemini API | Speech becomes one command from the current tray. Also the summary and texts |
| MLH MongoDB Atlas | The event log, case replays and success tables |
| MLH Tiger Data | Handoff times by minute on the series page |
| MLH Backboard | What was asked, and what usually comes next, on the memory page |
| MLH Vultr | The public page's server |
| MLH GoDaddy Registry | The domain on the QR code |

## Team

Anish (arm and training), Caiden (controller and voice), Brandon (camera and hand tracking), Evan (dashboard, ledger and data).
