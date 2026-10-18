# Next pass: Perceptron track done right, everything integrated (prompt for Caiden's Claude, Opus 5.5)

Say to Claude Code on the arm Mac: "Pull, then follow docs/NEXT-PASS-PROMPT.md exactly. Take as long as it needs."

---

I'm Caiden on team Scrub at DubHacks '26. It's Sunday after midnight. The final Devpost locks at **10:00 AM** (we submit by 9:30), judging starts 10:30 in the HUB Ballroom. Pull first.

## Read first, then trust the evidence over this file

`docs/OVERVIEW.md`, `docs/STATE.md`, `docs/AUDIT.md`, `docs/HARDWARE-TODO.md`, `docs/ACCOUNTS-TODO.md`, `docs/PERCEPTRON-ROBOTICS.md`, `explore/research/overheating/README.md`, `explore/research/overheating/HANDOFF.md`, `HANDOFF.md`, and `git log --since="12 hours ago" --stat`. Then check the real state on this Mac: `ls ~/scrub-dataset*`, `python -m arm.check_setup --no-cameras`, `python -m arm.train deployments`, `python -m deploy`.

At midnight the files said: the software is written and combed (every Critical and High in `docs/AUDIT.md` fixed with tests); 0 episodes in `~/scrub-dataset`; no training job; side camera (C920) not seen; wrist camera about 22.6 fps; `arm/rig.json` unmeasured; no slot boxes or camera-to-arm calibration; the follower overheats with torque on; the team key gave 401 here (Anish DM'd the working one: put it in `.env` as `PERCEPTRON_TEAM_API_KEY` and confirm `python -m arm.train deployments` no longer says 401).

## The goal

1. **For the Perceptron Robotics track:** the fine-tuned Isaac model visibly does the pick on the real arm, in a short video and live for the Perceptron judge at our table. They judge creativity, task difficulty and technical execution, and arm teams must submit a short video of the working demo.
2. **For everything else:** a judge asks for an instrument on the phone call and the real arm hands it over reliably, every time, by 8 AM.
3. **Every tool and account we signed up for is used in the product for real, and we can show where.**

## What "doing the Perceptron track properly" means (rules for this pass)

- **The model does the manipulation in anything we call the Perceptron demo.** The pick (approach, grasp, lift) comes from Isaac predictions through `arm/real_arm.py` `run_skill`. Our code around it is fine and is the technical-execution story: smoothing, speed and joint limits, the claw guard, the thermal guard, the grasp check, and the planned move from carry to the person's hand. Say it in one line everywhere: "The fine-tuned model picks; our code keeps it safe and carries it to the hand."
- **Taught skills (scripted waypoints, Phase 2) are a backup, never presented as the model.** Every event carries `skill_source` (`model` or `taught`), the dashboard and ops page show it, and the Perceptron video never contains a taught pick.
- **Don't burn the quota.** We have 2 successful training jobs. Before any upload: `explore/dataset/qa` and `python -m arm.dataset_check` must pass (cadence about 30 Hz on both cameras, no dark wrist frames, one task string per instruction, episode count as planned). Print the exact plan and wait for the dataset to pass before `arm.train`.
- **Task difficulty is our edge:** voice request, a learned pick of a thin metal instrument, handle-first handoff to a moving hand, release when pulled, sharps to the safe spot. Make sure each of those is real in the video, or cut the claim.
- **Every number on screen or in the Devpost comes from the ledger or the dataset.**

## Do we demo live? (answer this and write it into `docs/DEMO.md`)

Yes, plan for both. The video is required and is the thing that's judged no matter what. Perceptron judges come to our table in the Ballroom, so bring the arm, the tray and the lamp to the table if we're allowed to. Write a short message for Anish to send the Perceptron staff (their Discord or in person): can the SO-101 come to the Ballroom table, is there power there, and do they want the live demo or only the video. Until they answer, `docs/DEMO.md` has three ready levels, in this order, each with exact commands and who does what:
1. Live, real arm, model picks the hemostat (or every item it passes), taught for the rest, labeled.
2. Live, real arm, taught skills only, labeled.
3. Sim backup (`python -m controller.run_all backup --offline --loop --pause 2`) next to the recorded real-arm video.

## How to work

Multi-agent: you orchestrate and run subagents in parallel with strict file scopes (Opus for arm, controller, voice and safety; Sonnet for docs, scripts and pages). Subagents don't commit. You review every diff, run the tests, commit one item at a time, `git pull --rebase` before every push. Before editing a file run `git log -1 --format=%ar -- <file>` and skip it if someone else changed it in the last 10 minutes. Never print or commit keys. Finish every phase without asking me; write questions into the final report instead.

**Other agents may still be working. Don't touch their files:**
- Codex: `design/`, `dashboard/`, `ledger/public/`, `sim/web/`, `controller/nurse.html`, `controller/demo.html`, `video/`
- Brandon's Cursor: `vision/`, `deploy/`
- Evan: `docs/DEVPOST.md`, `docs/DEV-POST.md`, `docs/ACCOUNTS-TODO.md`

You own `arm/`, `controller/` (except those two HTML files), `voice/`, `explore/`, `sim/` (except `sim/web/`), `settings/`, and the other docs. Optional contract fields are fine (write them into `docs/CONTRACTS.md`); never rename or remove a field. If another owner's file needs a change, write the exact change into the final report.

## Phase 1: one arm path (the live demo gets the recorder's fixes)

Right now the reliability work lives in `explore/arm_session.py` (1266 lines: bus reads retried 3x, wrist_roll held to +-150 deg, overload flag cleared at startup, gripper torque by situation 15/35/50%, dead zone 3, thermal telemetry and the cool-down guard, lift and pulled-out detection). The live demo runs through `controller/` -> `arm/real_arm.py`, which has the claw guard and none of the rest.
1. Move the shared hardware layer into `arm/` (for example `arm/hardware.py` and `arm/thermal.py`): bus retries, joint limits, overload clearing, gripper torque by situation, the thermal guard, and the handoff detector. `explore/arm_session.py` and `arm/real_arm.py` both import it. Keep `arm_session` working: it's the recorder.
2. In `arm/real_arm.py`: retries on every bus read, stop a skill and go limp-safe when a motor passes the thermal limit from the overheating research, low torque between cases, gripper torque by situation.
3. Use the pulled-out detector for release: the controller opens the gripper when the grip load collapses while the hand is there (the person took it), or on "got it". Wire it into `controller/core.py` and the WAIT step.
4. Tests for each with the fake bus, then one run on the sim, then the exact real-arm steps for me.

## Phase 2: taught skills as the labeled backup

1. `arm/taught.py`: per item and direction, a few joint waypoints (approach above the slot, descend, close, lift to carry; return is the reverse into the slot), played with the same smooth motion, guards, limits and stop as Phase 1. Taught by hand with `python -m arm.teach` (torque off, a key saves each waypoint), saved in `arm/skills/<setting>/<item>-<direction>.json`.
2. If vision is ready, shift the approach by the slot's measured offset; if not, play it as taught (the tray is taped).
3. Controller flag `--skills model|taught|auto`. `auto` uses the model for an item when a deployment exists and that item passed its last 3 real tries, else taught. `skill_source` on every event; the voice reply never hides it.
4. `docs/TEACH.md` (under 15 minutes per item) and `python -m arm.taught --check` (replays each skill slowly with no instrument).

## Phase 3: the smallest honest training run

- Fix the cameras first (`docs/HARDWARE-TODO.md` steps 1 and 2): both about 30 fps at 640x480 in `python -m arm.check_setup`. If the wrist camera can't reach 30, find the USB port, light or setting that does, and write what worked.
- Record the hemostat only: "pick the hemostat" and "return the hemostat", 30 to 40 episodes in normal and bright light, with `arm.record` (it runs `arm_session`). Log each batch in `docs/DATA-LOG.md`.
- QA, then run 1. While it trains, finish Phases 1, 2, 4 and 5. When the deployment is ready, run 10 real tries through the controller with `--skills model` and log them; the hemostat goes to `model` only if it passes.
- Run 2 (more items) only if there's time and clean data before about 5 AM.
- Put the plan, commands and a timeline at the top of `docs/HARDWARE-TODO.md` ("Tonight's plan") and keep it current.

## Phase 4: every tool, integrated and proven

Write `docs/INTEGRATION.md`: one row per tool with what it does in Scrub, the file and function that calls it, the command that proves it works, and PASS/FAIL from running it now. Make every row PASS or say exactly what's missing (a key, an account step) and who does it.

| Tool | Where it must be used |
| --- | --- |
| Perceptron robotics API | fine-tune (`arm/train.py`, `arm/pipeline.py`), live inference (`arm/real_arm.py`) |
| Perceptron vision API | detect on the tray and the hand (`vision/`, recognition bench) |
| Gemini | words to one command (`voice/`), tray check from an image, the doctor's error summary |
| ElevenLabs | the voice agent on the call (Custom LLM to `voice/`) |
| Photon | the phone number, the call and the end-of-case text |
| MongoDB Atlas | the ledger and thermal telemetry |
| Vultr + GoDaddy | the public page and the case replay link in the text |
| Tiger Data, Backboard | whatever `docs/ACCOUNTS-TODO.md` says we use them for; if nothing real, say so and drop the track claim |
| Hugging Face | the dataset upload for training |
| MediaPipe | the hand at the handoff spot |
| MuJoCo | the sim backup and the joint-data reconstruction in the video |
| `video/` | built by Codex; check `python -m video demo-assets` runs end to end and that it reads our real ledger and dataset paths |

Then make `python -m controller.run_all` start the full real stack in one command (controller, vision, voice, ledger) with the same flags we'll use at judging, and print every URL.

## Phase 5: recognition, measured

`explore/recognition/bench.py` (don't edit `vision/`) on real frames from the cameras and saved tray images: Perceptron detect per item (found, box quality, latency), Gemini image input (name the instruments in a crop; check a tray against the expected list), OCR only if something has printed text, MediaPipe on gloved hands. Write `docs/RECOGNITION.md` with a table (method, what it recognizes, accuracy, latency) and the recommendation for the live demo. If something clearly beats the current path, write the exact change for Brandon's `vision/` there.

## Phase 6: one place to watch everything

- `controller/ops.html` (use `design/scrub.css` if it exists): controller step and events, `skill_source` per item, arm temperatures and loads, both camera fps, vision freshness, voice turns, API latencies (predict, detect, Gemini), last errors. Fold in `explore/thermal_web.py` rather than running two pages.
- `python -m controller.doctor`: checks every service, key presence (never values) and log, and asks Gemini to turn recent errors into a short plain list of what's wrong and what to do.

## Phase 7: finish the audit and make the words match

- Fix the Medium and Low items in `docs/AUDIT.md` that matter for tomorrow, and mark each.
- Update `docs/STATE.md`, `docs/STATUS.md` (check the boxes that are really done), `docs/HARDWARE-TODO.md`, `docs/DEMO.md` and `docs/PITCH.md` for what will really run: which items use the model, which use taught, which tools are live.
- List every claim in `docs/DEVPOST.md` that doesn't match reality in the final report (Evan owns that file).

## Final report

1. Tests passing per part.
2. Phase 1: which fixes moved into the live path, and the real-arm steps.
3. Taught skills: items ready in the sim, steps to teach them on the real arm.
4. Training: episodes recorded, QA result, job state and times, real-try results.
5. `docs/INTEGRATION.md` table with PASS/FAIL.
6. The recognition table and recommendation.
7. What the ops page and doctor show now.
8. Audit items fixed and left; Devpost claims that need changing.
9. The demo level we're on and the message for the Perceptron staff.
10. The exact list of what a person has to do next, in order, with who.
