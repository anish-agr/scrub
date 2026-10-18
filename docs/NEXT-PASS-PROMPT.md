# The full pass: sync, Perceptron track done right, everything integrated, repo cleaned (prompt for Caiden's Claude, Opus 5.5)

Say to Claude Code on the arm Mac: "Pull, then follow docs/NEXT-PASS-PROMPT.md exactly. Use as many subagents as it needs and take as long as it needs."

This is the only prompt to run. It replaces every older prompt file (`docs/PROMPTS.md`, `docs/COMB-PROMPT.md`, `docs/TRAINING-HANDOFF-PROMPT.md`, the first two versions of this file). Those move to `team/` in Phase 9.

---

I'm Caiden on team Scrub at DubHacks '26. It's Sunday after midnight. The final Devpost locks at **10:00 AM** (we submit by 9:30), judging starts 10:30 in the HUB Ballroom. Every other agent run has finished, so you own the whole repo now.

## How to work

- **Go wide with subagents.** You orchestrate. Split every phase into as many parallel subagents as the file scopes allow, and run phases in parallel when they don't share files. Opus for `arm/`, `controller/`, `voice/`, safety and anything that moves the motors; Sonnet for docs, scripts, pages, checks and research. Give each subagent a strict list of files it may edit, what done looks like, and the tests to run.
- Subagents don't commit. You review every diff, run the tests, and commit one item at a time with a plain message. `git pull --rebase` before every push.
- Thoroughness beats speed. The one thing that runs on the clock is training (Phase 3): start its human steps early so the GPU time overlaps with everything else.
- Never print or commit keys. Keys live only in `.env`.
- Finish every phase without asking me. Anything only a person can do (plug in a camera, move the arm by hand, paste a key, click in an account) goes into a short list with exact steps; keep working on everything else while it waits.
- Write every new doc, UI string and voice line plainly (rules in Phase 9). Don't rewrite old code comments in this pass: that's a separate small job later (`docs/DESLOP-PROMPT.md`).

## Phase 0: sync everything into `main` (first, before anything else)

Work exists outside `main` and you can't see it yet:
1. **Branch `anish/local-main-0050`** (pushed from Anish's laptop): 31 commits that never reached `main`. It holds the whole restyle (`design/` with the shared paper and monitor system, and restyled `dashboard/`, `dashboard/tablet.*`, `ledger/public/*`, `sim/web/*`, `controller/nurse.html`, `controller/demo.html`), plus copies of the `video/` commits that are already on `main` under other hashes, plus four thermal commits (`5006e86`, `8a34b30`, `f6f5bbc`, `9371fda`) that conflict with your `explore/thermal_analyze.py`. Bring in every restyle commit; skip the `video/` duplicates (check with `git cherry` or by diff); merge the thermal changes by hand, keeping whichever behavior is right and both test files. Run every test after.
2. **Branch `origin/caiden/thermal-handoff-20261018`**: 4 commits not in `main` (thermal audit docs). Merge what isn't already there.
3. List every other remote branch with commits not in `main` (`git branch -r --no-merged origin/main`). Merge or explain each.
4. Then on this Mac: `.env` has `PERCEPTRON_TEAM_API_KEY` (Anish DM'd it) and `python -m arm.train deployments` no longer says 401.

## Phase 1: understand what exists, then update the scope

Read `docs/OVERVIEW.md`, `README.md`, `AGENTS.md`, `docs/CONTRACTS.md`, `docs/STATE.md`, `docs/AUDIT.md`, `docs/HARDWARE-TODO.md`, `docs/ACCOUNTS-TODO.md`, `docs/PERCEPTRON-ROBOTICS.md`, `docs/TRAINING.md`, `docs/VIDEO-TOOL.md`, `docs/DESIGN-SYSTEM.md`, `explore/research/overheating/README.md`, every folder's README, and `git log --since="16 hours ago" --stat`. Run every test suite and every `--help` / `--check` / `--dry-run` command the READMEs name, and record what passes.

Then rewrite the scope in `docs/OVERVIEW.md` (sections 3 to 6) to match what's built now. A lot was added after it was written: the thermal telemetry and cool-down guard, gripper torque by situation, rest and wake between commands, lift and pulled-out handoff detection, the recorder's page and controls, dataset QA, the video tool, the shared design system, the sim backup, the public page on Vultr. Say what's real, what's partly done and what was dropped, and keep dental dropped. This becomes the source of truth the rest of the pass works from.

## Phase 2: one arm path for the live demo

The reliability work lives in `explore/arm_session.py` (the recorder): bus reads retried 3x, wrist_roll held to +-150 deg, overload flag cleared at startup, gripper torque by situation (15/35/50%) with dead zone 3, thermal telemetry and the cool-down guard, lift and pulled-out detection. The live demo runs `controller/` -> `arm/real_arm.py`, which has the claw guard and none of that. `controller/` now calls `arm.rest()` and `arm.wake()` between commands, and the real arm doesn't implement them yet.
1. Move the shared hardware layer into `arm/` (for example `arm/hardware.py`, `arm/thermal.py`, `arm/handoff.py`). `explore/arm_session.py` and `arm/real_arm.py` both import it, and the recorder keeps working.
2. `arm/real_arm.py`: retries on every bus read, joint limits, gripper torque by situation, `rest()` and `wake()` from the overheating research (`explore/research/overheating/HANDOFF.md`), stop a skill and go safe when a motor passes the thermal limit.
3. Release on pull: the controller opens the gripper when the grip load collapses while the hand is at the handoff spot, or on "got it". Wire it into `controller/core.py` at the WAIT step.
4. Tests for each with the fake bus, a run in the sim, then the exact real-arm steps for me.

## Phase 3: the Perceptron Robotics track, done completely and properly

**What they judge:** creativity, task difficulty and technical execution. Arm teams submit a short video of the working demo, and Perceptron judges come to our table in the Ballroom.

**Rules for this track:**
- The fine-tuned Isaac model does the manipulation (approach, grasp, lift) in anything we call the Perceptron demo, through `run_skill` in `arm/real_arm.py`. Our code around it is the technical-execution story: smoothing, speed and joint limits, the claw guard, the thermal guard, the grasp check, and the planned move from carry to the person's hand. One line everywhere: "The fine-tuned model picks; our code keeps it safe and carries it to the hand."
- Taught skills (Phase 4) are a labeled backup and never appear as the model. Every event carries `skill_source` (`model` or `taught`), and the dashboard, ops page and voice reply show it.
- We have 2 successful training jobs. Nothing uploads until `explore/dataset/qa` and `python -m arm.dataset_check` pass: about 30 Hz on both cameras, no dark wrist frames, one task string per instruction, the planned episode count.
- Task difficulty is our edge (a voice request, a learned pick of a thin metal instrument, handle first to a moving hand, release when pulled, sharps to the safe spot). Each claim is real in the video or it's cut.

**The run plan.** Write it at the top of `docs/HARDWARE-TODO.md` ("Tonight's plan") with times and keep it current. One process owns the arm ports and the cameras at a time.
1. Cameras (`docs/HARDWARE-TODO.md` steps 1 and 2): both about 30 fps at 640x480 in `python -m arm.check_setup`. If the wrist camera won't reach 30, find the port, light or setting that does, and write what worked.
2. Tape the setup, one slow teleop test, teach `home`, `carry`, `safe_spot` and the handoff box into `arm/rig.json` (steps 3 to 5).
3. **Run 1:** record the hemostat only ("pick the hemostat", "return the hemostat"), 30 to 40 episodes in normal and bright light, with `arm.record`. Log each batch in `docs/DATA-LOG.md`. QA, upload, train (about an hour plus export).
4. **While run 1 trains,** record the Mayo scissors and the scalpel into the same dataset (the scalpel pick goes to the safe spot), and teach the taught skills.
5. When run 1's deployment is ready: 10 real tries through the controller with `--skills model`, logged to the ledger. The hemostat goes to `model` only if it passes.
6. **Run 2** on the full surgical dataset if the data is clean, started as soon as run 1 is checked. Then 10 tries per item.
7. Film the Perceptron arm video with `video/` (`video/edl/perceptron-arm.yaml`): real tries, cleaned only, success table from the ledger.

## Phase 4: taught skills as the labeled backup

1. `arm/taught.py`: per item and direction, a few joint waypoints (approach above the slot, descend, close, lift to carry; return is the reverse), played with the same motion, guards, limits and stop as Phase 2. Taught with `python -m arm.teach` (torque off, a key saves each waypoint) into `arm/skills/<setting>/<item>-<direction>.json`.
2. If vision is calibrated, shift the approach by the slot's measured offset; otherwise play it as taught (the tray is taped).
3. Controller flag `--skills model|taught|auto`. `auto` uses the model for an item when a deployment exists and that item passed its last 3 real tries, else taught.
4. `docs/TEACH.md` (under 15 minutes per item) and `python -m arm.taught --check` (replays each skill slowly with no instrument).

## Phase 5: every tool and account, integrated and proven

Write `docs/INTEGRATION.md`: one row per tool with what it does in Scrub, the file and function that calls it, the command that proves it, and PASS or FAIL from running it now. Fix every FAIL that code can fix. For the rest, write exactly what's missing and who does it. Drop any track claim with no real use behind it.

| Tool | Where it must be used |
| --- | --- |
| Perceptron robotics API | fine-tune (`arm/train.py`, `arm/pipeline.py`, `arm/upload_dataset.py`), live inference (`arm/real_arm.py`) |
| Perceptron vision API | detect on the tray and the hand (`vision/`), the recognition bench |
| Gemini | words to one command (`voice/`), tray check from an image, the doctor |
| ElevenLabs | the voice agent on the call (Custom LLM to `voice/`) |
| Photon | the phone number, the call, the end-of-case text |
| MongoDB Atlas | the ledger and the thermal telemetry |
| Vultr + GoDaddy | the public page and the replay link in the text |
| Tiger Data, Backboard | whatever `docs/ACCOUNTS-TODO.md` says; if nothing real, say so |
| Hugging Face | dataset upload if the pipeline uses it |
| MediaPipe | the hand at the handoff spot |
| MuJoCo | the sim backup and the joint-data reconstruction in the video |
| `video/` | `python -m video demo-assets` end to end, and it reads our real ledger and dataset paths |

Then `python -m controller.run_all` starts the full real stack in one command (controller, vision, voice, ledger) with the flags we'll use at judging, and prints every URL.

## Phase 6: the demo at judging

Write `docs/DEMO.md` with three ready levels, exact commands, and who does what at the table:
1. Live, real arm: model where it passed, taught for the rest, labeled.
2. Live, real arm, taught only, labeled.
3. The sim backup (`python -m controller.run_all backup --offline --loop --pause 2`) next to the recorded real-arm video.

Add a short message for Anish to send the Perceptron staff: can the SO-101 come to our Ballroom table, is there power there, and do they want a live demo or only the video. Make `docs/PITCH.md` and the slides match the level we'll really be on.

## Phase 7: recognition and monitoring

- `explore/recognition/bench.py` on real camera frames and saved tray images: Perceptron detect per item (found, box quality, latency), Gemini image input (name the instruments in a crop; check a tray against the expected list), OCR only where there's printed text, MediaPipe on gloved hands. Write `docs/RECOGNITION.md` (method, what it recognizes, accuracy, latency) and the recommendation. Apply it to `vision/` if it clearly beats the current path.
- `controller/ops.html` (on `design/scrub.css`): controller step and events, `skill_source` per item, arm temperatures and loads, both camera fps, vision freshness, voice turns, API latencies (predict, detect, Gemini), last errors. Fold in `explore/thermal_web.py`.
- `python -m controller.doctor`: checks every service, key presence (never values) and log, and asks Gemini to turn recent errors into a short list of what's wrong and what to do.

## Phase 8: make the repo and the code agree

- Fix the Medium and Low items in `docs/AUDIT.md` that matter for judging, and mark each.
- Run a fresh comb with subagents, one per folder: read every file, find bugs, dead code, unused files, and anything the docs claim that the code doesn't do (or the reverse). Fix it, with a test where it can break.
- Every command in every README and doc runs as written. Every `requirements.txt` and `package.json` matches the imports. Every folder README says what's in the folder now.
- Promote what's worth keeping from `explore/` into the product folders, and move what isn't used into `team/` (Phase 9).
- Merge duplicate docs into one each: `DEVPOST.md` and `DEV-POST.md`, `PERCEPTRON.md` and `PERCEPTRON-ROBOTICS.md`, `TRAINING.md` and `TRAINING-HANDOFF-PROMPT.md`, `NEXT.md` and this file, `STATE.md` / `STATUS.md` / `LEFT.md` / `WORKING-NOW.md`.
- `docs/STATUS.md`: tick only the boxes the evidence proves.
- `docs/DEVPOST.md` and `docs/README-PUBLIC.md`: every claim matches what runs, every number comes from the ledger or the dataset, and the tracks listed are the ones `docs/INTEGRATION.md` proves.

## Phase 9: one folder for the team's files (hidden later)

Make `team/` and move into it everything about how we worked rather than what Scrub is. The test: would a judge reading the public repo need this file to understand, run or trust Scrub? If yes it stays in `docs/` or its folder; if no it goes to `team/`.
- Goes to `team/`: every prompt file (this one included, at the end of the pass), `TASKS`, `STATUS`, `STATE`, `LEFT`, `WORKING-NOW`, `PLAN`, `PROPOSAL`, `NEXT`, `HARDWARE-TODO`, `ACCOUNTS-TODO`, `PITCH`, `QNA`, `SLIDES`, `DEVPOST` drafts, `VIDEO-SCRIPT`, `VIDEO`, `DEMO`, `AUDIT`, `docs/DESLOP-PROMPT.md`, `explore/IDEAS-BACKLOG.md`, `explore/prototypes/` (the 57 idea prototypes), the status-board mockups, and research notes the product doesn't cite.
- Stays: `README.md`, `docs/OVERVIEW.md`, `docs/CONTRACTS.md`, `docs/SETUP.md`, `docs/ARM.md`, `docs/BRINGUP.md`, `docs/TRAINING.md`, `docs/TEACH.md`, `docs/PERCEPTRON-ROBOTICS.md` and its OpenAPI file, `docs/DESIGN-SYSTEM.md`, `docs/VIDEO-TOOL.md`, `docs/RECOGNITION.md`, `docs/INTEGRATION.md`, `docs/DATA-LOG.md`, `docs/media/`, and every folder's README.
- Use `git mv` so history follows. Then grep the whole repo (code, tests, scripts, pages, `AGENTS.md`) for every moved path and fix each reference. `arm/record.py`, `ledger/logbook.py`, `ledger/shots.py`, `controller/server.py` and `arm/test_perceptron.py` read paths under `docs/`. Run every test after.
- `AGENTS.md` and `CLAUDE.md` stay at the root for now and point at the new paths.
- Write `team/HIDE.md` with the exact commands to hide it before the repo goes public (`git rm -r team/` plus moving `AGENTS.md`/`CLAUDE.md` in, commit, push), and say that the files stay in git history. Don't run them.

**Writing rules for everything new in this pass** (docs, UI copy, voice lines, commit messages): short and plain. No em dashes. No "it's not X, it's Y". No rhetorical questions, colon reveals or one-line paragraphs for effect. No filler (honestly, really, actually, simply, just, very). No decorative AI words (delve, leverage, seamless, robust as praise, crucial, unlock, empower). No emojis. Real units and real numbers only.

## Final report

1. Phase 0: what was merged, what was skipped and why.
2. Tests passing per folder.
3. The new scope summary from `docs/OVERVIEW.md`.
4. Phase 2: which fixes are now in the live arm path, and the real-arm steps.
5. Training: episodes recorded per item, QA results, both jobs' state and times, real-try results per item and skill source.
6. Taught skills ready, and the teach steps for what's left.
7. The `docs/INTEGRATION.md` table.
8. The demo level we're on, and the message for the Perceptron staff.
9. The recognition table and what changed in `vision/`.
10. What the ops page and doctor show now.
11. Audit and comb items fixed and left.
12. What moved to `team/`, and every path reference that was fixed.
13. The exact list of what a person has to do next, in order, with who.
