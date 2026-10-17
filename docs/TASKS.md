# Tasks by person

We vibe code: agents write the code from these tasks, and people test on the hardware and make the calls. Everyone works in parallel from the start. Nobody waits on the real arm, because the controller's fake arm stands in until the model works.

How to start an agent: `docs/PROMPTS.md`. Which model to use for what: also there.

Rules that keep us from colliding:
- **Edit only your own files** (table below and in `AGENTS.md`). Need a change somewhere else? Message the owner.
- **Work on `main`, small commits, `git pull --rebase` before every push.** With separate folders, conflicts should be rare.
- **Contracts are fixed** (`docs/CONTRACTS.md`). Code to them with fake data, and the pieces connect.
- **Tick your boxes in `docs/STATUS.md`** (your section only) as tasks pass. Agents read it to find the next task.
- **Post in the group chat** when you finish a "done when," when you're blocked, or when you hit a rate limit.

| Person | Owns | Tools | Agent budget |
| --- | --- | --- | --- |
| Anish | `arm/`, the arm and training, `docs/ARM.md`, `docs/PERCEPTRON-ROBOTICS.md`, `docs/PLAN.md`, `docs/TASKS.md`, `docs/PITCH.md` | Claude Pro, Codex | Small. Most of his time is at the arm |
| Caiden | `controller/`, `voice/`, `docs/CONTRACTS.md`, `.env.example`, `.gitignore` | Claude Max, Cursor Pro, Codex | Largest. Takes overflow jobs |
| Brandon | `vision/`, `docs/PERCEPTRON.md`, `docs/SLIDES.md`, the Perceptron API key | Cursor Pro | Medium |
| Evan | `dashboard/`, `ledger/`, `settings/`, `docs/DATA-LOG.md`, `docs/DEVPOST.md` | Cursor Pro | Medium |

## Priority

Core tasks build the demo. Stretch tasks (marked **stretch**) wait until Checkpoint 3 (Sun 2 AM) passes, unless the core ones are done early. Agents don't start stretch tasks on their own.

## Rate limits

- **Caiden's Claude Max is the team's big budget.** If your tool runs out, post the task ID, the files and the "done when" in the chat, and Caiden's agent picks it up. It still edits only your files, and you review.
- **Anish (Claude Pro, Codex):** Pro resets in roughly 5-hour windows. Codex does the API client and the IK math. Claude is saved for debugging on the real arm.
- **Brandon and Evan (Cursor Pro):** Auto mode for routine work. A stronger model only for a hard bug. Check usage in Cursor's settings at dinner.
- **Ways to save budget:**
    - Use the start prompt in `docs/PROMPTS.md`, so the agent reads only what it needs.
    - Keep one task per chat. Start a new chat for the next task.
    - Paste the exact error. Don't just say "fix it."
    - Run installs yourself.
    - Never let an agent read datasets, logs or `node_modules`.

## Anish: arm, data, fine-tuning

| # | When | Task | Done when |
| --- | --- | --- | --- |
| A1 | 12:30 to 1:15 | Perceptron workshop. Fill the "Workshop notes" table in `docs/ARM.md`: slot times, cameras, gripper load, training time, vision API | Notes pushed |
| A2 | 1:15 to 3:00, before arm time | `arm/perceptron.py`: a client for the Robotics API per `docs/PERCEPTRON-ROBOTICS.md` and `docs/perceptron-openapi.json` (datasets, uploads, jobs, deployments, session grant, robot session, predict, reset, delete). `arm/train.py` CLI: register a dataset (Hugging Face or upload), wait for validation, start a job, follow it, print the deployment id. `arm/upload_dataset.py` for direct upload | `python -m arm.train capabilities` prints the capabilities with our team key |
| A3 | first arm slot | Connect and calibrate the follower and leader, teleoperate, set up the `side` and `wrist` cameras at 640x480, 30 FPS. Tape the tray, slot and return-spot positions. Save the home, carry and safe-spot poses and the handoff region in `arm/rig.json` | `lerobot-teleoperate` works with both cameras; poses saved |
| A4 | first arm slot | Record the operating room set with Evan: per item 15 "pick the X" + 10 "return the X", a third each in bright, normal and dim (75 total) | Dataset on the Hub or ready to upload; counts in `docs/DATA-LOG.md` |
| A5 | right after A4 | Fine-tuning run 1 with `arm/train.py` | Job running; ETA posted in the chat |
| A6 | while run 1 trains | `arm/real_arm.py` implementing the arm interface in CONTRACTS: `run_skill` opens a robot session for the instruction and runs the predict loop (side + wrist images, six-value state) until done, `max_s` or `freeze`. Plus gripper position and load, poses from `rig.json` | The controller runs a real "pick the hemostat" with `--real-arm` |
| A7 | while run 1 trains | `move_to(x, y, z)`: inverse kinematics from the SO-101 URDF, a speed limit, the handoff-region check | The arm reaches 5 test points within about 2 cm |
| A8 | by 10:30 PM | First real handoff with Brandon's calibration and Caiden's controller | Hemostat goes from the tray to a hand by voice |
| A9 | evening slots | Record dental, then bench (75 each), with Evan or Brandon. 10 extra demos for any item that failed after run 1 | All logged |
| A10 | by about 1 AM | Fine-tuning run 2 on all three settings | All 9 items pick on the real arm |
| A11 | Sun 6 to 7 AM | Run the tests in `docs/PLAN.md` and log them with `ledger.log_test` | Success tables full |
| A12 | Sun 7 to 8:30 AM | Record the Perceptron arm video (required for the robotics track) | Uploaded |

## Caiden: controller and voice

Build the fake-arm controller first. It unblocks everyone else.

| # | When | Task | Done when |
| --- | --- | --- | --- |
| C1 | 12:30 to 2:30 | `controller/`: FastAPI on port 8000 with every endpoint in CONTRACTS, `fake_arm.py`, the step machine for handover, return and count, `WS /events`, `dashboard/` served at `/`, settings loaded from `settings/`. Import `ledger` if it exists, skip it if not | A handover sent with curl runs every step on the fake arm and the events show on the WebSocket |
| C2 | by 2:30 | Push C1 and post "controller is up" in the chat | Brandon and Evan point their parts at it |
| C3 | 2:30 to 4:30 | `voice/`: the Photon number answers a call. The ElevenLabs agent is on the call through Photon's guide. What it hears reaches `voice/` on port 3000 through a tunnel (cloudflared or ngrok) | Words said on the call print in the voice server |
| C4 | 4:30 to 6:00 | Gemini structured output: the action enum plus the item ids from the current setting. "stop" skips Gemini and calls `POST /stop`. The agent speaks each event's `say` line | "Grab me the kelly" on the call becomes `handover hemostat`, and Scrub answers out loud |
| C5 | **6:00 PM** | **Checkpoint 1** with everyone | A spoken request runs end to end on the fake arm and shows on the dashboard |
| C6 | 6:00 to 10:30 | Real controller flows: the grasp check (gripper stopped short of closed and the slot is empty), one retry then say so, `wait_for_pull` (load jump or `got_it`, 30 s), stop on hand lost or path blocked, slow near the hand, the request-to-hand timer | Each failure case passes on the fake arm by forcing it |
| C7 | 10:30 to 2:00 | End-of-case summary: Gemini writes it from the ledger and Photon texts it to the same thread. "Scalpel down" call-out | The summary arrives on the phone |
| C8 | overnight | Integration lead: full runs on the real arm, fix what breaks between parts, cut voice latency | Ten full runs in a row with no code fix |
| C9 | any time | Overflow jobs from the chat | |

## Brandon: vision (camera, hand tracker, tray perception)

One process owns the overhead camera, so the hand tracker and tray perception share it. Brandon has the Perceptron API key and posts it in the chat for everyone's `.env`.

| # | When | Task | Done when |
| --- | --- | --- | --- |
| B1 | 12:30 to 2:00 | `vision/camera.py`: open the overhead camera with fixed exposure and white balance. One frame grabber both parts read from. `CAMERA_INDEX` from `.env` | A preview shows the tray, and brightness doesn't jump when a lamp turns on |
| B2 | 2:00 to 3:30 | `vision/hand.py`: MediaPipe hand landmarker (Tasks API), palm center, the open-palm check (all five fingertips farther from the wrist than their middle joints). POST a Hand to `/vision/hand` about 10 times a second | Works with nitrile gloves on; `seen` and `open` are right |
| B3 | by 3:30 | MJPEG stream on port 8001 (`/stream`) with item boxes and the palm dot | The dashboard shows it |
| B4 | 3:30 to 5:30 | `vision/tray.py`: the Perceptron vision API about once a second. Map detections to slot boxes and the return spot, POST a TrayState to `/vision/tray`. If the API is slow or down, keep the last good state and mark it stale. Write what works into `docs/PERCEPTRON.md` | Lifting an item off the tray shows on the dashboard within about 2 seconds |
| B5 | when the camera is mounted | `vision/mark_slots.py`: click to mark each slot and the return spot, print the boxes. Send them to Evan for `settings/` | All three trays have boxes |
| B6 | 6:30 to 9:30 | `vision/calibrate.py` with Anish at the arm: 6 to 8 gripper points, pixel and arm positions, fit image to table (a homography), save `vision/calibration.json`. `target` is the point a few cm short of the palm at the saved hand height | The palm target is within about 2 cm of the gripper check |
| B7 | 9:30 to midnight | `path_clear` (false if a hand or arm is between the gripper and the target). Saved hand height per clinician | Both tested by hand |
| B8 | overnight | Test the hand tracker and perception in bright, normal and dim light. Second person at the arm when Anish needs one | Results in the chat |

## Evan: dashboard, ledger, settings, Devpost

| # | When | Task | Done when |
| --- | --- | --- | --- |
| E1 | 12:30 to 1:30 | `settings/surgical.json`, `dental.json`, `bench.json` per CONTRACTS: items, aliases ("kelly" for hemostat, "mayo" for the scissors, and so on), `sharp`, instructions. Boxes stay `null` until Brandon sends them | Three valid files pushed |
| E2 | 1:30 to 3:30 | `dashboard/`: one static page (plain HTML and JS). Live camera (`<img src="http://localhost:8001/stream">`), the current step, what's out, the event log, setting and lighting pickers, a big stop button, the spacebar as stop. A fake event list until C2 lands | A fake-arm handover shows live from the controller |
| E3 | 3:30 to 5:00 | `ledger/`: MongoDB Atlas (mlh.link/mongodb), `log`, `log_test`, `stats` per CONTRACTS. Buffer to `ledger/buffer.jsonl` when Mongo is down | Events from a fake run show in Atlas |
| E4 | arm slots | Arm crew with Anish: reset the tray between demos, switch the lighting, keep `docs/DATA-LOG.md` | The log matches the dataset |
| E5 | 7:00 to 10:00 | `docs/DEVPOST.md`: the Devpost draft from `docs/PROPOSAL.md` (overview and tracks). Anish reviews. **Submit on Devpost by 10:00 PM** (due 10:30) | Draft submitted; screenshot in the chat |
| E6 | 10:30 to 2:00 | Success tables and handoff times on the dashboard from `/stats`. A public read-only page on Vultr at a GoDaddy domain that reads MongoDB (the count and the tables) | The domain loads the live tables |
| E7 | Sun 7 to 9 AM | Edit the demo video (2 to 3 min) from the shot list in `docs/PITCH.md`. Final Devpost text with measured numbers | Video uploaded, Devpost final by 9:30 |

## Presentation (everyone)

Judging is at our table: a 3-minute pitch over a live demo, then questions. The demo video is required for judging to happen at all.

| # | Who | When | Task | Done when |
| --- | --- | --- | --- | --- |
| P1 | Anish | Sat evening draft, Sun 6 AM final | `docs/PITCH.md`: the 3-minute script with measured numbers filled in, and the judge Q&A | Script final |
| P2 | Brandon | Sun by 8 AM | A 5-slide backup deck (Google Slides), outline in `docs/SLIDES.md`: the problem, Scrub, how it works, the success tables, the business case. Used only if the arm fails at judging, and as the video's title cards | Link in the chat |
| P3 | Evan | Sun 7 to 9 AM | Demo video (E7) | Uploaded |
| P4 | Caiden | Sat night | A demo mode on the controller: one key per setting switch, a reset that homes the arm and clears the count. Records a clean backup full run on Sunday morning | Works with the dashboard |
| P5 | everyone | Sun 9:30 to 10:20 and in line | Rehearse the demo three times. Roles: Anish speaks, Brandon is the clinician, Caiden runs the dashboard and stop key, Evan swaps trays and the lamp | Under 3 minutes twice in a row |
| P6 | Anish | after submitting | MLH Commit Fellowship form (mlh.link/commit-fellowship-form). DEV post after the event (**stretch**) | Submitted |

## Who's at the arm

Recording takes two people: one moves the leader arm, one resets the tray and keeps the log. Anish is always one of them. Evan is the default second, and Brandon covers when Evan is mid-task. Put the slot times in `docs/PLAN.md` once known.

## Backups

- Voice on the call fails by 6 PM: type the commands on the dashboard, or speak through the laptop mic to the ElevenLabs agent. Photon still carries the summary text.
- The vision API is too slow: the count comes from the controller's own log, and the grasp check becomes a pixel check (did the slot change?).
- The hand tracker isn't ready for the first real handoff: hand off to the clinician's saved spot.
- Only one tray works by 2 AM: the operating room tray is the demo.
