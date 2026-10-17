# Rules for coding agents (Claude Code, Codex, Cursor)

This repo is vibe coded: agents write the code, people test it on the hardware and decide. Everything an agent needs is in this repo. Don't scan every file; follow the steps below.

## Start here

The person will tell you their name (Anish, Caiden, Brandon or Evan). Then:

1. Read `README.md` (the system), `docs/CONTRACTS.md` (the messages every part uses) and your person's section of `docs/TASKS.md`.
2. Run `git pull --rebase`. Open `docs/STATUS.md`. Your person's next task is the first unchecked box in their section.
3. Read the README in the folder that task lives in, and the files already there.
4. Build it. You have full permission inside your person's files: install packages, create files, run commands and servers, commit and push. Don't ask for approval or plans. Only stop for something only a human can do (a key, plugging in a device, testing on the arm, the camera or a phone).
5. Finish it. Test against the task's "done when" with fake inputs (the controller's `--fake-arm`, fake events, saved images) and fix it until it passes. For anything only a human can check, tell the person exactly what to run and what they should see.
6. When it passes, commit only your person's files, `git pull --rebase`, `git push`. Tick the box in `docs/STATUS.md` (your person's section only) and add one line on what works and how to run it. Push that too.
7. Go straight to the next unchecked task. Keep going until your person's tasks are done or they stop you.

If you're stuck for more than about 20 minutes on one problem, stop and tell the person what you tried. They may hand it to Caiden, who has the largest agent budget.

## The project

Scrub: an SO-101 robot arm that passes instruments by voice. Built Oct 17 to 18, 2026 at DubHacks. Working beats polished. Hackathon scope: the simplest code that meets "done when."

## Ownership

| Folder or file | Owner |
| --- | --- |
| `controller/`, `voice/`, `explore/`, `docs/SLIDES.md`, `docs/CONTRACTS.md`, `.env.example`, `.gitignore` | Caiden |
| `arm/`, `docs/ARM.md`, `docs/PLAN.md`, `docs/TASKS.md`, `docs/PITCH.md` | Anish |
| `vision/`, `docs/PERCEPTRON.md` | Brandon |
| `dashboard/`, `ledger/`, `settings/`, `docs/DATA-LOG.md`, `docs/DEVPOST.md` | Evan |
| `docs/STATUS.md` | everyone, own section only |

- Only edit files your person owns. If a change elsewhere is needed, stop and write the exact change so your person can send it to the owner.
- Never change `docs/CONTRACTS.md` unless you're working for Caiden. Adding an optional field there is fine; renaming or removing one needs the whole team.
- Each folder has its own `requirements.txt` (or `package.json` in `voice/`). No shared root dependency file.
- Learned something other agents will need (an API's quirks, a working command)? Put it in your folder's README.

## Code rules

- Python 3.10. FastAPI and uvicorn for servers. `httpx` or `requests` for HTTP. Plain HTML and JavaScript for the dashboard, no build step.
- TypeScript on Node 20 for `voice/`.
- Python parts run as `python -m <folder>` from the repo root.
- Keys come from environment variables in `.env` at the repo root (use `python-dotenv` or `dotenv`). Never write a key into code, a commit, a log line or a test. `.env.example` lists the names.
- Only the controller moves the arm. Nothing else imports `arm/`.
- `stop` must always work: never block the controller's event loop, and `freeze()` must be callable from any thread.
- Each part must run alone with fake inputs matching the contracts, so it can be tested without the arm.
- Keep files small and the code direct. Don't add frameworks beyond the ones named here.

## External docs

| What | Where |
| --- | --- |
| LeRobot SO-101 | https://huggingface.co/docs/lerobot/so101 |
| SO-101 URDF and MuJoCo model | https://github.com/TheRobotStudio/SO-ARM100/tree/main/Simulation |
| Photon 2.0 docs | https://photon.codes/docs |
| Photon + ElevenLabs voice guide | https://photon.codes/docs/beta/cookbooks/voice/elevenlabs |
| ElevenLabs agents | https://elevenlabs.io/docs |
| Gemini structured output | https://ai.google.dev/gemini-api/docs/structured-output |
| MediaPipe hand landmarker (use the Tasks API) | https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker |
| Perceptron vision API and fine-tuning | from the workshop; Brandon writes what works into `docs/PERCEPTRON.md` |

If a doc page and these files disagree, the doc page wins for the API and these files win for our design.

## Don'ts

- No `git push --force`, `git reset --hard` or history rewrites.
- Don't read `data/`, `outputs/`, `.venv/`, `node_modules/` or recorded datasets.
- Don't commit datasets, videos or model weights.
- Don't loop on package installs. If one fails twice, report it.
- Don't start a task someone else owns because it looks unfinished. Tell your person.
