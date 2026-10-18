# What's left (Sat 5:05 PM)

Evan's tasks (E1 to E7) aren't listed here; he's on them. As of 5 PM he has pushed settings, the dashboard, the ledger, the tables page and a Devpost draft, and `controller.test_flows` (28/28) and `vision.test_vision` still pass with them in. `docs/STATUS.md` stays the checklist; this file is the gap list. Whoever finishes an item deletes it here in the same commit.

## Agents running now (stay in your scope)

| Agent | Works on | May edit |
| --- | --- | --- |
| Caiden, session 1 (orchestrator) | L1 to L10 below | `controller/` (except `trials.py`), `voice/`, `arm/check_setup.py`, `arm/record.py`, `controller/run_all.py`, `README.md` "Running it", `docs/SLIDES.md`, `explore/` |
| Evan, Cursor (Grok only) | E3 to E7 | `dashboard/`, `ledger/`, `settings/`, `docs/DATA-LOG.md`, `docs/DEVPOST.md` |
| Brandon, Cursor (Grok only) | B5, B6, B8 | `vision/`, `docs/PERCEPTRON.md` |
| Anish, Codex | R1 to R4, Q1, Q2 below | `arm/` except `check_setup.py` and `record.py`; `docs/BRINGUP.md`; `controller/trials.py` (new file only) |
| Anish, Antigravity | G1, G2 below | `docs/PITCH.md`, `docs/QA.md` |

## More work (Q, R, G)

| # | What | Who |
| --- | --- | --- |
| Q1 | `docs/BRINGUP.md`: the exact step-by-step for tonight, with commands: ports, cameras, calibration ids, taping, measuring poses, the first teleop, recording, the dataset check, training, the first live skill, calibration with Brandon, the first handoff. Each step lists what you should see and what to do if you don't | Codex |
| Q2 | `controller/trials.py`: runs the success tests in `docs/PLAN.md` (N tries per item and lighting through the controller, logging each with `ledger.log_test`), with a prompt to the operator between tries | Codex |
| Q3 | `docs/AUDIT.md`: read every part against `docs/CONTRACTS.md` and list mismatches and likely bugs, by owner. Done in the final verification pass | Caiden, final pass |
| Q4 | A sim backup: a recorded full run on the MuJoCo sim arm with voice and the dashboard, in case the real arm fails at judging | Caiden, final pass |
| R1 | `python -m arm.train pipeline`: check a local dataset first (fps, camera names and sizes, joint names, episode count, cadence), register the Hugging Face repo, wait for validation, train, follow, wait for a ready deployment, write `PERCEPTRON_DEPLOYMENT_ID` into `.env` | Codex |
| R2 | `arm/teach.py`: torque off, move the arm by hand, press a key to save the current joints as home, carry or safe-spot in `arm/rig.json`, and mark the handoff-region corners | Codex |
| R3 | `Arm.prepare(instructions)` in `real_arm.py` that pre-opens robot sessions, for Caiden's L2. Optional method, so the contract doesn't change | Codex |
| R4 | Live bring-up with Anish once the arm is plugged in and the team key is in: capabilities, `real_arm --dry-run` against the real joints, the five-point `move_to` check, gripper load sign | Codex |
| G1 | `docs/PITCH.md`: tighten the 3-minute script and judge Q&A against what's built, with `[measured]` slots for the numbers. Plain words, no buzzwords, no em dashes | Antigravity |
| G2 | Browser QA: start the stack with the fake arm and `vision --fake`, click through the dashboard and the public page, try every control, and write bugs by owner in `docs/QA.md` | Antigravity |

## After everyone finishes: the final pass

When Caiden session 1, Codex, Antigravity and Evan's Cursor are done, Caiden runs one verification pass with subagents: Q3 (the audit), Q4 (the sim backup), every test in the repo, the full stack on the sim arm, and small fixes anywhere. That pass is the last software step before the hardware work takes over.

## Blockers only people can clear

| What | Blocks | Who |
| --- | --- | --- |
| **Perceptron Robotics team key (coming soon).** The key we have is the vision key (`api.perceptron.inc`, in `PERCEPTRON_API_KEY`); it gets 401 on `robotics.perceptron.inc`. When the team key arrives it goes in `PERCEPTRON_TEAM_API_KEY`, then run `python -m arm.train capabilities` | training (A5, A10), live inference (A6), `python -m arm.train capabilities` | Anish |
| **Photon number** answering calls | C3, the voice prize, the summary text | Caiden |
| **Arm physical setup:** ports, both cameras (`side`, `wrist`), calibration with fixed ids, tray and cameras taped | all recording, A6 to A8 live, B5, B6 | Anish + one person |
| **Overhead camera for `vision/`:** a third USB webcam, separate from `side` and `wrist` | B5, B6, B8 | Brandon |

## Code agents can finish now (no hardware)

| # | What | Files |
| --- | --- | --- |
| L1 | Codex's 4 handoff items in `arm/README.md` ("Handoff to Caiden"). 8153bd3 covered the latched freeze; check the rest: no gripper load means wait for `got_it` without crashing, a failed `set_down_safe_spot()` is reported (not counted as out), and put-back is done only when tray perception shows the item in its slot (not just `max_s`) | `controller/` |
| L2 | Pre-open Perceptron robot sessions for the current setting's instructions when the setting changes, so the first motion doesn't wait on a grant. Expose 401/409/503 from the arm as events and spoken lines | `controller/` (calls into `arm/` through the interface only) |
| L3 | P4 demo mode: one key per setting, a reset that homes the arm and clears the count, a "judge mode" that only allows handover, count and stop | `controller/` |
| L4 | C7: end-of-case summary sent as a Photon text to the same thread. Make it work with a stub until the number exists | `voice/` |
| L5 | Voice end to end without a phone: a script that sends text to `voice/` the way ElevenLabs would and checks the command reaches the controller and the reply line comes back. Measure latency | `voice/` |
| L6 | `arm/check_setup.py` (ports, cameras at 640x480 at 30 fps, real fps, one test frame each) and `arm/record.py` (builds and runs `lerobot-record` with `use_degrees=true`, fps 30, episode 25 s, reset 10 s, one repo `<HF_USER>/scrub`, `--resume` when it exists, appends to `docs/DATA-LOG.md`, `--print-only`). Anish allows these two new files in `arm/` | `arm/check_setup.py`, `arm/record.py` |
| L7 | One command that starts the whole stack for a demo or test: controller (fake, sim or real arm), vision (real or `--fake`), voice, and opens the dashboard. Plus a full-stack smoke test on the sim arm | `controller/run_all.py` |
| L8 | README "Running it" section with the real commands, once L7 works | `README.md` (Anish allows) |
| L10 | Full-stack check with Evan's parts: the controller serves `dashboard/`, events reach the ledger (buffer file when Mongo is down), `GET /stats` returns the tables, settings load. Report mismatches to Evan rather than editing his folders | read only outside `controller/` |
| L9 | P2: the 5-slide backup deck outline and slide text in `docs/SLIDES.md`; system diagram as an image | `docs/SLIDES.md`, `explore/` |

## Needs the arm (people, with agents helping)

In order:
1. A3: set up and calibrate, measure home, carry and safe-spot poses and the handoff region into `arm/rig.json`.
2. A7 live: five `move_to` points within about 2 cm.
3. Gripper load: check the sign and size of the jump when someone pulls, then turn on release on pull.
4. A4: record the operating room set (75). Check the cadence line and replay episode 0.
5. A5: run 1. **We only get 2 successful runs.**
6. While it trains: B5 slot boxes and B6 camera-to-arm calibration (Brandon with Anish), then record dental and bench into the same dataset.
7. A6 live: real "pick the hemostat" from the controller with `--real-arm`.
8. A8: first real handoff by voice (target 10:30 PM).
9. A10: run 2 on everything (target 11 PM).
10. C8: ten clean full runs. B8: lighting tests. A11: the success tables.

## Presentation and submission (not Evan's)

- P1 pitch script with measured numbers (Anish). Caiden helps.
- A12 Perceptron arm video (Anish).
- P5 three rehearsals Sunday, under 3 minutes.
- Sunday 8:30 AM: repo made public, history checked for keys, README final.
- P6 Commit Fellowship form after submitting.
