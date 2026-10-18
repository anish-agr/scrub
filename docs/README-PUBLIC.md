# Scrub

Anish swaps this file in as `README.md` on Sunday, when the repo is made public. Image paths below assume the file lives at the repo root.

A robot arm that passes instruments when you ask out loud. Built at DubHacks '26 (Oct 17 to 18, 2026) by Anish, Caiden, Brandon, and Evan.

A clinician asks for an instrument. The SO-101 arm picks it from the tray and brings it to an open hand, handle first, and lets go when they pull or say "got it." A scalpel goes to a fixed safe spot instead of hand to hand. An instrument set in the return spot goes back to its slot. Scrub keeps a count and reads back what is still out.

The demo is two trays. The operating room comes first. The robotics bench is the second tray, to show that a new tray is a settings file, not new code.

| Setting | Items |
| --- | --- |
| Operating room | scalpel handle, hemostat, Mayo scissors |
| Robotics bench | needle-nose pliers, wire cutters, hex key |

## Pictures

Replace these with photos from the real arm on Sunday morning if we have them. These are from a fake-arm case.

![Dashboard](docs/media/dashboard.png)

![Tablet view, for someone across the room](docs/media/tablet.png)

![One case, played back](docs/media/case.png)

![Public page](docs/media/public.png)

The same page at phone width: [docs/media/public-phone.png](docs/media/public-phone.png).

A short GIF of a real handoff goes here: `docs/media/handoff.gif` (not recorded yet).

## How it works

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

Stop is its own path. The word "stop", the spacebar, or the button on the page freezes the arm without waiting on a model. The arm stays frozen until someone presses reset.

## How to run

Python 3.10. From the repo root, with the keys from `.env` (copy `.env.example`):

```
python -m venv .venv
source .venv/bin/activate
pip install -r controller/requirements.txt -r ledger/requirements.txt -r vision/requirements.txt

python -m controller --fake-arm    # port 8000, also serves the dashboard
python -m vision --fake            # port 8001, no camera
python -m ledger serve             # port 8080, the public page
```

Open http://localhost:8000/ for the dashboard, http://localhost:8000/tablet.html for the large view, and http://127.0.0.1:8080/ for the judge page.

Voice (Node 20), when the Photon number is live:

```
cd voice && npm install && npm run dev    # port 3000
```

The real arm is `python -m controller --real-arm`. It needs the arm plugged in, `PERCEPTRON_TEAM_API_KEY`, and a deployment id from training. Without those, use `--fake-arm`.

## Tracks

| Track | Where it shows up |
| --- | --- |
| Community Kitchen | Passing an instrument so the clinician stays with the patient |
| Perceptron Robotics | SO-101 arm, Isaac 0.5 model trained on our demonstrations |
| Perceptron Perception | Overhead camera: full slots and the return spot |
| Photon | The phone call, and the summary text on the same thread |
| DubHacks NEXT | Later plan: a monthly fee per dental chair |
| MLH Gemini API | Speech becomes one command from the current tray |
| MLH MongoDB Atlas | The event log and the success tables |
| MLH Vultr | The public page |
| MLH GoDaddy Registry | The domain on the QR code |
| MLH Commit Fellowship | Form sent after we submit |
| MLH DEV writing | The Devpost writeup in `docs/DEVPOST.md` |

## Team

Anish (arm and training), Caiden (controller and voice), Brandon (camera and the public server), Evan (dashboard, ledger, and this page).
