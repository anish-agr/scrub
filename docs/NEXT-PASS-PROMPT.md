# Next pass: make the demo work no matter what (prompt for Caiden's Claude, Opus 5.5)

Say to Claude Code on the arm Mac: "Pull, then follow docs/NEXT-PASS-PROMPT.md exactly. Take as long as it needs."

---

I'm Caiden on team Scrub at DubHacks '26. It's Sunday after midnight. The final Devpost locks at **10:00 AM** (we submit by 9:30), judging starts 10:30. Pull first.

## Where we really are (read the evidence, then trust it over this list)

Read `docs/OVERVIEW.md`, `docs/STATE.md`, `docs/AUDIT.md`, `docs/HARDWARE-TODO.md`, `docs/ACCOUNTS-TODO.md`, `explore/research/overheating/README.md` and `HANDOFF.md`, and `git log --since="12 hours ago" --stat`.

- The software is written and combed: `docs/AUDIT.md` lists every Critical and High finding as fixed with tests.
- The hardware path is not working yet. As of midnight, by the files: **0 episodes recorded** (`~/scrub-dataset` doesn't exist, `docs/DATA-LOG.md` has no rows), **no training job**, the side camera (C920) isn't seen, the wrist camera runs about 22.6 fps (needs 30), `arm/rig.json` poses are unmeasured, the slot boxes and the camera-to-arm calibration don't exist, the follower overheats when torque stays on, and the robotics team key answered 401 on this Mac (Anish DM'd the working key).
- Recording 90 episodes plus two training runs is about 4 to 5 hours if nothing breaks. That doesn't fit safely before 9:30.

## The goal of this pass

**A judge asks for an instrument on the phone call and the real arm hands it over, reliably, by 8 AM.** Then, as a separate win, show the fine-tuned Perceptron model working on at least one item for the Perceptron Robotics track. Everything else serves those two.

## How to work

Multi-agent: you orchestrate and run subagents in parallel with strict file scopes (Opus for arm, controller, voice and safety; Sonnet for docs, scripts and pages). Subagents don't commit. You review every diff, run the tests, commit one item at a time, `git pull --rebase` before every push. Before editing a file run `git log -1 --format=%ar -- <file>` and skip it if it changed in the last 10 minutes. Never print or commit keys.

**Other agents are working right now. Don't touch their files:**
- Codex: restyling `design/`, `dashboard/`, `ledger/public/`, `sim/web/`, `controller/nurse.html`, `controller/demo.html`
- Codex: building `video/`
- Brandon's Cursor: `vision/`, `deploy/`
- Evan: accounts and `docs/DEVPOST.md`, `docs/ACCOUNTS-TODO.md`

You own `arm/`, `controller/` (except those two HTML files), `voice/`, `explore/`, `sim/` (except `sim/web/`), and the docs not listed above. Optional contract fields are fine (write them into `docs/CONTRACTS.md`); never rename or remove a field.

## Phase 1: a demo that works without a trained model (do this first)

Build **taught skills**: a deterministic pick and return for each instrument that needs no training.
1. `arm/taught.py`: for each item and direction, a short list of joint waypoints (approach above the slot, descend, close, lift to carry; for return the reverse into the slot), played back with the existing smooth motion, the claw guard, the speed limits and stop. Waypoints come from teaching by hand (`python -m arm.teach` with torque off, a key press saves each waypoint) and live in `arm/skills/<setting>/<item>-<direction>.json`.
2. A small correction from vision if it's ready: shift the approach by the slot's measured offset. If vision isn't ready, play the taught path as is (the tray is taped).
3. The controller picks the skill source: `--skills model|taught|auto`. `auto` uses the Perceptron model for an item when a deployment exists and that item passes its last 3 tries, else taught. Every event carries the optional `skill_source` field, and the dashboard and the voice reply never hide which one ran.
4. Make it gentle on the motors: torque off or low between cases, short holds, the existing thermal guard on, and stop a skill if a motor passes a temperature limit. Use what the overheating research measured.
5. A teach walkthrough a person can follow in under 15 minutes per item (`docs/TEACH.md`), and a check (`python -m arm.taught --check`) that replays each skill slowly with no instrument.
6. Test everything in the sim first (`sim/`), then hand me the exact steps for the real arm.

## Phase 2: the smallest honest training run (for the Perceptron Robotics track)

- Plan the minimum that shows a fine-tuned model working: the hemostat only, "pick the hemostat" and "return the hemostat", about 30 to 40 episodes in normal and bright light, recorded with `arm_session` after the cameras pass (`python -m arm.check_setup`: both cameras about 30 fps at 640x480; fix the side camera first; if the wrist camera can't reach 30 fps, find the setting or USB port that does).
- Run 1 on that. While it trains, finish Phase 1 on the other items. If run 1 works, the hemostat uses `model` and the rest use `taught`; say so plainly in the pitch, the Devpost and the arm video.
- Run 2 only if there is time and data for more items.
- Write the plan with exact commands and a timeline into `docs/HARDWARE-TODO.md` (top section "Tonight's plan").

## Phase 3: what the cameras and models can recognize (measure it, don't guess)

Build `explore/recognition/bench.py` (don't edit `vision/`; Brandon's agent owns it) and run it on real frames from the cameras and on saved images of the surgical and bench trays:
- Perceptron detect (the vision API) per item: found or not, box quality, latency.
- Gemini with image input: name the instruments in a crop, and check a whole tray against the expected list.
- OCR (Perceptron OCR or the Apple Vision OCR in `explore/bench/`) on anything with printed text, such as tray labels or an instrument tag, only if it helps.
- The hand: MediaPipe on gloved hands at the handoff spot.
Write `docs/RECOGNITION.md`: a table of what each method recognizes, accuracy, latency, and a recommendation of what the live demo should use. If something works clearly better than the current path, write the exact change for Brandon's `vision/` in that doc.

## Phase 4: one place to watch everything

- `controller/ops.html` (use `design/scrub.css` if it exists): one page for the person running the demo. Controller step and events, arm temperatures and loads (the thermal telemetry), both camera fps, vision freshness, voice turns, API latencies (Perceptron predict, detect, Gemini), last errors, and the skill source per item.
- `python -m controller.doctor`: checks every service and log, and asks Gemini to turn the recent errors into a short plain list of what's wrong and what to do. It never sends keys.
- Promote what's worth keeping from `explore/` into the product (the thermal guard, the useful bits of `arm_session`), and leave the rest.

## Phase 5: finish the audit and the docs

- Fix the remaining Medium and Low items in `docs/AUDIT.md` that matter for tomorrow, and mark each.
- Update `docs/STATE.md`, `docs/STATUS.md`, `docs/HARDWARE-TODO.md` and `docs/DEMO.md` for the skill sources (taught or model), so the demo script matches what will run.
- Make sure the pitch and Devpost claims match reality: if the model only runs the hemostat, they say that.

## Final report

1. Tests passing per part.
2. Taught skills: which items are ready in the sim, and the steps to teach them on the real arm.
3. The training plan with times, and what state it's in.
4. The recognition table from `docs/RECOGNITION.md` and the recommendation.
5. What the ops page and doctor show right now.
6. Audit items fixed and left.
7. The exact list of what a person has to do next, in order, with who.
