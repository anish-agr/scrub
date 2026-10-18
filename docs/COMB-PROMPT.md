# The fine-toothed comb (prompt for Caiden's Claude, Opus 5.5)

Paste everything below the line into a new Claude Code session on the Mac with the arm, or say: "Pull, then follow docs/COMB-PROMPT.md exactly."

---

I'm Caiden on team Scrub at DubHacks '26 (Oct 17 to 18, 2026). The repo is cloned here. Pull first.

This is the most important pass of the weekend. Your job is to understand the entire project, make sure every piece of software is finished and ready to demo, finish anything that isn't, and produce clear lists of what only people can do (hardware and accounts). Take as long as it needs. Do not stop early. Do not ask me for approval. Only stop for something only a person can do, and even then keep working on everything else and put the person-only item on the lists.

## How to work

Use a multi-agent workflow. You are the orchestrator.
- Run many subagents in parallel, one per area. Use Opus for anything touching the controller, the arm, voice, vision or safety. Use Sonnet for docs, UI checks, scripts and inventories.
- Every subagent gets: the files it may read, the files it may edit, the contract sections it must follow, and what "done" means. Subagents never commit.
- You review every diff yourself, rerun all affected tests, then commit one item at a time with a message that names the part and the owner's folder, and push (`git pull --rebase` first). Never force-push or rewrite history.
- Before editing any file, run `git log -1 --format=%ar -- <file>`. If it changed in the last 10 minutes, someone is working on it: don't edit it, note it in `docs/AUDIT.md`, and come back to it at the end.
- Never print, log or commit a key. Read `.env` only to check whether a key is set (set or empty), never its value.
- Contracts: optional fields may be added (and must be written into `docs/CONTRACTS.md`). Never rename or remove a field.

## Phase 0: understand everything (read before changing anything)

Read all of these, fully:
- `docs/OVERVIEW.md` first (it explains every idea, decision and folder, including how to treat `explore/`), then `README.md`, `AGENTS.md`, every file in `docs/` (CONTRACTS, PLAN, TASKS, STATUS, LEFT, QA, BRINGUP, TRAINING, ARM, PERCEPTRON-ROBOTICS, PITCH, SLIDES, DEVPOST, DEV-POST, README-PUBLIC, DATA-LOG, SETUP, PROPOSAL, PROMPTS), and every folder README.
- Every source file in `controller/`, `voice/`, `vision/`, `arm/`, `ledger/`, `dashboard/`, `settings/`, `deploy/`, and the parts of `explore/` that the build uses (`explore/arm_session.py`, `explore/arm_ui.*`, `explore/dataset/`, `explore/research/isaac-workshop-notes.md`).
- `git log --since="18 hours ago" --stat` to see who changed what.

Facts you must hold onto:
- Scope: surgical first (scalpel, hemostat, Mayo scissors). The robotics bench tray (needle-nose pliers, wire cutters, hex key) is the second setting. Dental is dropped: hidden in the UI and pitch, file kept.
- The arm is plugged into this Mac. Recording runs through `explore/arm_session.py`. Perceptron needs exactly two cameras, `side` and `wrist`, at 640x480 and 30 fps, `use_degrees`, one dataset, and allows only **2 successful training runs**.
- Known hardware issue: `explore/dataset/README.md` says the wrist camera ran at about 23 fps and was dark.

Then write `docs/STATUS.md` ("Current state"): a one-page map of the whole system as it actually is now. Every part, what it does, how to start it, what it depends on, its tests, and its status (works, works offline only, partial, missing). This is the file the whole team reads from now on.

## Phase 1: finish every piece of software

Compare the plan (`docs/PLAN.md`, `docs/TASKS.md`, `docs/LEFT.md`, `docs/PROPOSAL.md` tracks section, the demo in `docs/PITCH.md`) with what exists. Anything planned and missing, build it. At minimum, check and finish:
1. `controller/run_all.py`: one command starts the controller (fake, sim or real arm), vision (real or fake), voice and the tunnel, waits until each is healthy, and prints every URL (dashboard, tablet, nurse console, judge page, voice health, tunnel).
2. The recorder: make `explore/arm_session.py` the official path. Add `arm/record.py` and `arm/check_setup.py` as thin wrappers (or move the code), matching `docs/PERCEPTRON-ROBOTICS.md`. Each recorded batch appends a row to `docs/DATA-LOG.md`. `docs/BRINGUP.md` section 6 and `docs/TRAINING.md` must show these exact commands for this Mac (bash, `/dev/tty.usbmodem...` ports).
3. Judge mode (only handover, count and stop), and pre-opening model sessions when the setting changes (L2, L3 in LEFT.md).
4. The README "Running it" section with real, tested commands.
5. The system diagram as an SVG in `docs/media/`, used in the README, the judge page and the slides.
6. `docs/DEMO.md`: the exact live demo minute by minute (surgical tray, then the bench tray), who stands where, who says what, who runs the dashboard and the stop key, what to do if each step fails, the 60-second version for a rushed judge, and the reset between judges.
7. Demo-laptop scripts: start everything, reset between judges, switch trays, and play the sim backup if the arm fails.
8. `docs/QNA.md`: 30+ judge questions (technical, safety, regulatory, business, why Perceptron, why voice, data and training), short answers, and who answers each.
9. `docs/SLIDES.md` final text for the 5-slide backup deck.
10. Every open bug in `docs/QA.md` and every row in `docs/LEFT.md` that is software.
11. Dental hidden everywhere it's user-facing (dashboard, tablet, voice prompts, texts, judge page, Devpost, pitch). Keep the file.
12. **The pitch.** Rewrite `docs/PITCH.md` as a 3-minute pitch spoken over the live demo, split across four speakers: Caiden and Anish carry most of it, Evan and Brandon each have a short part (for example, Evan on the data, the dashboard and the tables; Brandon on vision and hand tracking). Lead with the statistics (the surgical tech shortage, retained surgical items, sharps injuries, time spent searching the tray) and show step by step how Scrub works. Surgical first; the bench tray proves "new setting, no new code". Every statistic has a source link and is checked against that source (drop any number you can't confirm). Use `[measured]` where our own numbers go. Plain words, short sentences, no em dashes, no buzzwords, nothing that sounds AI-written.
13. **Everything presented says the same thing.** The pitch, `docs/DEMO.md`, `docs/QNA.md`, `docs/SLIDES.md`, `docs/DEVPOST.md`, `docs/NEXT-PASS-PROMPT.md` (section "Earlier next-steps notes") (the business case), the judge page, the table card and `docs/README-PUBLIC.md` must tell one consistent story with the same numbers, the same item names, the same tracks and the same speaker roles. Fix any mismatch.
14. Anything else in the plan that has no code yet.

## Phase 2: the comb

Write every finding into `docs/AUDIT.md` by severity (critical, high, medium, low), with file and line, then fix it.
1. **Contracts:** every message, field and endpoint in every part matches `docs/CONTRACTS.md` (controller, voice, vision, arm interface, ledger, dashboard, settings, deploy).
2. **Line by line:** every source file for bugs, race conditions, unhandled exceptions, blocking calls in async code, threads that never stop, missing timeouts on network calls, retries that never give up, wrong units, and secrets in logs.
3. **Safety:**
    - stop works from every state and every thread
    - freeze holds the arm
    - a late or stale model chunk never runs
    - the arm only hands off inside the handoff region and only toward an open hand
    - sharps never go hand to hand
    - reset after a stop needs a person
    - the gripper never squeezes past its limit
    - nothing moves the arm except the controller
4. **Tests:** every test in the repo passes (`controller.test_flows`, `vision.test_vision`, every arm test, ledger, `cd voice && npm test`, deploy checks). Add tests for anything important that has none.
5. **Full stack on the sim arm:** start everything with `run_all` (sim arm, fake vision, voice). Drive complete surgical and bench cases by voice text (`npm run say`) and by text-message stubs. Cover:
    - every item, the scalpel to the safe spot, auto return from the return spot, the count with the camera check, "check the tray", clinic words, switching trays
    - stop mid-move, reset, "got it", hand lost, path blocked
    - the Perceptron vision API failing (it must go stale, not freeze), the controller restarting, MongoDB down
    - Check the dashboard, tablet, nurse console, case replay, judge page, `/stats` and the end-of-case text at every step.
6. **Real-arm readiness:** read `arm/real_arm.py`, `arm/streaming.py`, `arm/sessions.py`, the `--real-arm` path, the recorder, `arm.train pipeline`, `docs/BRINGUP.md` and `docs/TRAINING.md` together. Find anything that will break on first contact with this Mac and the real arm (ports, camera names, units, the 30 Hz loop, network latency, session expiry), and fix it.
7. **Docs match the code:** every command in README, BRINGUP, TRAINING, DEMO and the folder READMEs actually works as written on this Mac.
8. **Judge view:** everything a judge sees looks clean, loads fast and works on a phone. No placeholder text, no "TODO", no dental.
9. **Repo ready to go public:** no keys or tokens anywhere in the history (scan it), no large files, a clean `.gitignore`, and `docs/README-PUBLIC.md` ready to become the README on Sunday.

## Phase 3: understand the hardware state and list it

Find out what is actually done on the hardware, from evidence, not from STATUS.md:
- the ports and cameras `arm_session.py` uses, and whether both cameras deliver 30 fps at 640x480 (run the camera check on this Mac)
- calibration files and ids, `arm/rig.json` (are the poses measured or placeholders?)
- `vision/calibration.json`, the slot boxes in `settings/*.json`, `vision/hand_heights.json`
- how many episodes are recorded (the dataset folder, `docs/DATA-LOG.md`, the cadence reports), per item, direction and lighting, against the table in `docs/TRAINING.md`
- whether any training job or deployment exists (`python -m arm.train status`, `deployments`, read-only)
- the arm_session logs in `~/scrub-logs`

Write `docs/HARDWARE-TODO.md`: an ordered checklist of every hardware step left, each with who does it, the exact command, what you should see, and what to do if you don't. Start with the wrist camera fix. Include the recording count still needed per item and lighting, run 1, run 2, the five-point reach check, the gripper load check, the camera-to-arm calibration, the live handoff, ten clean runs, the success tests, and the Perceptron arm video.

## Phase 4: accounts and keys

Without printing any value, check which keys are set on this Mac's `.env` and what each service answers (`python -m deploy`). Then write `docs/ACCOUNTS-TODO.md`: every account and key the project needs, for each one:
- what it's for and which track it serves
- where to get it (the exact site and clicks)
- which machine's `.env` needs it
- whether it's set and working now

Cover Perceptron (robotics team key and vision key), Hugging Face, Gemini, ElevenLabs (the agent and the Custom LLM URL), Photon (the number, SIP inbound, the project id and secret), MongoDB Atlas, Vultr, GoDaddy, Devpost (team, tracks ticked, draft submitted), the MLH Commit Fellowship form, and DEV.

## Phase 5: organize

- Update `docs/STATUS.md` from the evidence: tick what's actually done, untick what isn't, and one line each on how to run or check it.
- Empty `docs/LEFT.md` of everything finished. What remains should only point to HARDWARE-TODO.md and ACCOUNTS-TODO.md.
- Mark docs that are out of date at their top ("Superseded by ...") instead of deleting them.
- Make sure a new person can open `README.md`, then `docs/STATUS.md` ("Current state"), and understand the whole project in five minutes.

## Final report

When everything is done, reply with:
1. Tests: counts passing per part.
2. What you built in Phase 1.
3. What you fixed in Phase 2, by severity.
4. Anything still failing, and why.
5. The top of `docs/HARDWARE-TODO.md` (the next five hardware steps).
6. The top of `docs/ACCOUNTS-TODO.md` (every account not done yet).
7. Files you skipped because someone was editing them.
