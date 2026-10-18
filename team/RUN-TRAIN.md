# Chat A: record, train and deploy the pick model (Perceptron Robotics track)

Say to a new Claude Code chat on the arm Mac: "Pull, then follow team/RUN-TRAIN.md exactly."

---

I'm Caiden on team Scrub at DubHacks '26: an SO-101 arm that passes surgical instruments by voice. **We're on a hard time crunch.** It's about 2 AM Sunday. The final Devpost locks at 10:00 AM (submit by 9:30) and judging starts 10:30. This chat owns one thing: a fine-tuned Perceptron Isaac model that picks instruments on the real arm, with honest measured results, by about 6 AM.

## How to work (read twice)

- **Use subagents for everything that can run in parallel, and keep them busy.** You orchestrate: Opus subagents for arm, motion and safety code; Sonnet subagents for data checks, scripts, docs and analysis. Give each one a strict file list, what done looks like, and the tests to run. Never sit idle waiting on a person or a GPU: while training runs, the next subagents work.
- Finish things. Don't ask me questions. A step only a person can do (move the leader arm, plug a camera, reset the tray) goes to the people at the table as one short instruction with the exact command, and you keep working on everything else.
- Other Claude chats are running on this Mac. Before editing a file run `git log -1 --format=%ar -- <file>` and skip it if someone else changed it in the last 10 minutes. Commit small, `git pull --rebase` before every push, push often. Never print or commit keys; they're in `.env`.
- You own: `arm/train.py`, `arm/pipeline.py`, `arm/upload_dataset.py`, `arm/dataset_check.py`, `arm/record.py`, `explore/station/`, `explore/arm_session.py`, `explore/dataset/`, `docs/TRAINING.md`, `docs/DATA-LOG.md`, `docs/PERCEPTRON-ROBOTICS.md`, the "Tonight's plan" and arm sections of `team/LEFT.md`. Chat C (`team/RUN-SMART-PICK.md`) owns how the controller chooses and runs a pick; Chat D (`team/RUN-DATA.md`) owns analysis. Tell them what you learn through `team/NOTES-TRAIN.md`.

## Facts checked at 2:05 AM (trust these over older docs)

- **The quota is 5 successful jobs per team, and we've used 0.** `GET /v1/jobs` returned an empty list and `python -m arm.train capabilities` says `successful_jobs_per_team: 5`, `steps: [1000]`, horizon 30, stride 15, deadline 400 ms, backends `expert_only`, `backbone_lora`, `full`. `team/LEFT.md` says 2 jobs were already used: that's wrong, fix it. There are 0 deployments, and `PERCEPTRON_DEPLOYMENT_ID` in `.env` holds a wrong value; empty it.
- **Real data so far is not usable for the surgical task.** MongoDB `scrub.episodes` has 8 episodes, all `pick the spatula` (not a settings instruction), wrist camera 18.7 to 22.6 fps, lengths 180 to 3143 frames. Keep them out of the training set.
- `team/qa/PERCEPTRON-CHECK.md` lists ways to waste a job: camera fps never checked, task string never checked, the HF revision defaulting to a moving branch, joint units unchecked. Some are fixed (direct upload is now the default). Fix every one that's left before the first upload, with a test each.

## The plan (keep it current at the top of `team/LEFT.md`)

1. **Gates first (subagents, 20 min, in parallel with the cameras):** finish the PERCEPTRON-CHECK fixes; `arm.dataset_check` fails on any camera under 29 fps, any task string not in `settings/*.json`, missing cameras, wrong joint names or units; `explore/dataset/qa` and `qa_video` run as one command, `python -m arm.train preflight <dataset>`, that prints PASS or the reasons.
2. **Cameras:** both side and wrist about 30 fps at 640x480 in `python -m arm.check_setup`. The wrist camera has been 18 to 23 fps: try lamp brightness, another USB port, a direct port with no hub, lower exposure or MJPG if the camera supports it, and write what worked. If it can't reach 29, record without dim light and say so.
3. **Record run 1's data on `explore/station`:** `pick the hemostat` and `return the hemostat` only, 30 to 40 episodes (about 2/3 pick), normal and bright light, the hemostat shifted a little in its slot each time, short clean episodes (under 20 s). Every batch goes in `docs/DATA-LOG.md` and to MongoDB with `explore/dataset/to_mongo.py`. Have a subagent watch each new episode with `qa_video` and flag bad ones right away so they're re-recorded while the setup is still there.
4. **Run 1:** preflight PASS, then upload and train with `python -m arm.train pipeline`. Pick the backend and steps from what the capabilities allow and what fits about an hour; write why in `docs/TRAINING.md`. Follow it to a deployment, put the real id in `.env`.
5. **While run 1 trains:** record `pick/return the mayo scissors` and `pick the scalpel` (the scalpel goes to the safe spot) into the same dataset, 25 to 30 each. With 5 jobs, run 2 (all surgical items) starts as soon as the data passes preflight; don't wait for run 1's results. A run 3 is allowed only to fix something run 1 or 2 showed.
6. **Real tries:** when a deployment is ready, 10 tries per item through the controller with `--skills model`, every try logged to the ledger with `skill_source: model`, success or failure. No hand-picked results.
7. **Hand the numbers to Chat C and Chat D** in `team/NOTES-TRAIN.md`: per item, tries, successes, typical failure, latency (`/arm/pose` counters), and whether `late / (accepted + late)` is over 0.2.

## Honesty rules

The model does the pick in anything we call the Perceptron demo. Taught or scripted picks are labeled and never shown as the model. Every number comes from the ledger or the dataset. If an item doesn't pass its real tries, it doesn't run on `model` at judging and we say that.

## Before you stop

Every test passes, everything is pushed (`git status` clean, nothing ahead of `origin/main`), `team/LEFT.md` and `docs/DATA-LOG.md` are current. Report: episodes per item, preflight results, each job's id, state and times, the deployment id, real-try results per item, and what a person must do next.
