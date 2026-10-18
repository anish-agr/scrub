# What's left (Sun Oct 18, 1:45 AM)

The one list of what is left before judging. It replaces STATUS, WORKING-NOW, NEXT, TASKS, PLAN, HARDWARE-TODO and ACCOUNTS-TODO. What exists and works now is in `team/STATE.md`. If something is done, it is not here; delete an item when it is done.

Commands are bash on the arm Mac, from the repo root. `.venv/bin/python` is the Python. One process owns the arm ports and the cameras at a time: stop teleop, the recorder or station, `arm.teach`, the controller and `python -m vision` before the next step. Follower `/dev/tty.usbmodem5C821089781`, leader `/dev/tty.usbmodem5C821067211`, calibration ids `scrub_follower` and `scrub_leader`. Never paste a key into chat, a doc or a commit.

Fixed deadlines: final Devpost submitted by 9:30 AM (locks 10:00, needs the public repo and the 2 to 3 minute video), everyone in the HUB Ballroom at 10:20, judging from 10:30.

Roles: Anish arm, training and the pitch. Caiden controller, voice and tools. Brandon vision and the clinician hand. Evan tray, lamp, `docs/DATA-LOG.md`, Devpost and the video edit.

## People only

Ordered by deadline. Arm items point to a step in "Tonight's plan" and a procedure in "Arm procedures" below.

### Training quota (checked, no action)
The earlier "2 jobs used" is wrong. Checked 2:05 AM Oct 18: `GET /v1/jobs` is empty, capabilities `successful_jobs_per_team` 5 with 0 used, 0 deployments; about 65 of 1200 shared GPU hours used. The 14 `pick the spatula` episodes in `~/scrub-dataset` are not training data; surgical training data goes in `~/scrub-surgical` (`team/RUN-TRAIN.md`).

### Restart vision and the controller on the new builds (Brandon for vision, Caiden for the controller, by 2:00)
Vision on :8001 is an older `--fake` build: its `/health` has no `fps` or `detect_p50_ms`. The controller on :8000 is a fake-arm build with no `skills` in `/state`.
1. Ctrl+C the old `python -m vision --fake` (or `kill` its pid from `ps aux | grep "vision --fake"`).
2. With the overhead camera plugged in: `.venv/bin/python -m vision`. It binds 127.0.0.1 now. If a phone or tablet must show the stream, start it with `VISION_HOST=0.0.0.0 .venv/bin/python -m vision`.
3. `curl -s localhost:8001/health`: you should see `camera: true`, `fps` and, after a few detects on the real camera, `detect_p50_ms`. Write that number in the chat; `TRAY_STALE_S` (8 s) must stay above it.
4. Restart the controller the same way (or stop it and use `run_all`), then `curl -s localhost:8000/state` should include `skills`.

### Cache the MediaPipe model (Brandon, by 2:00)
`vision/models/` is empty, so the first `python -m vision` downloads the hand model. Run `.venv/bin/python -m vision` once on internet (the restart above does it), then `ls vision/models` should list the model file. After that vision starts offline.

### Devpost draft check (Evan, by 2:30)
STATUS never confirmed the Saturday draft. Open https://devpost.com, the DubHacks '26 project, Edit: confirm the team, the draft text from `team/DEVPOST.md` and the tracks. Per `docs/INTEGRATION.md`, do not tick MLH Tiger Data or MLH Backboard unless their keys land (see below).

### Arm night run (Anish, Evan, Brandon, Caiden, 1:45 to 8:15)
The ordered run is "Tonight's plan" below: cameras, tape, teleop test, poses, run 1 data, gates, run 1, more data and taught skills, real tries, run 2, more tries, filming. Each step names who and which process owns the arm.

### Teach poses and set hardware_verified (Anish, by 2:30; hardware_verified after procedure 10)
`arm/rig.json` has a measured `home`, but `carry` and `safe_spot` are null and `hardware_verified` is false. Teach them with procedure 5. Set `hardware_verified: true` only after the five-point reach check and the gripper load check pass (procedure 10). `arm.taught --check` on the arm and the real-arm controller need it.

### Teach the taught skills (Anish, by 4:15)
`arm/skills/surgical/` is empty. Teach pick and return for `hemostat`, `mayo_scissors` and `scalpel` with `docs/TEACH.md`, about 15 minutes per item:
`.venv/bin/python -m arm.teach skill hemostat pick --setting surgical --supported-and-empty`
`.venv/bin/python -m arm.teach skill hemostat return --setting surgical --supported-and-empty`
Check without the arm: `.venv/bin/python -m arm.taught --check --setting surgical --fake` (every item `ok`, final PASS). Check on the arm once `hardware_verified` is true: `.venv/bin/python -m arm.taught --check --setting surgical`. The plan records no bench episodes, so the bench tray has no real-arm skill unless someone also teaches `--setting bench` items.

### Real-try measurements: latency, sessions, pull release (Anish and Caiden, during plan step 8, by 5:10)
1. M6 and M7: after 5 picks on the real arm, `curl -s localhost:8000/arm/pose | jq .counters`. If `late / (accepted + late)` is over 0.2, move the arm Mac to a phone hotspot or a wired link and measure again.
2. M8: if the controller start prints 3 or more `HTTP 409` lines, the deployment caps sessions. Say so in the chat; Caiden decides whether to pre-open fewer.
3. Pull release: close the gripper on a real hemostat and read the held load, then have a person pull and read it again (procedure 10.2). Set `PULL_COLLAPSE_FRAC` in `.env` to a share between the pulled and held loads (default 0.3; `0` turns it off). If the load does not change, leave it off and release on "got it".
4. If the hand flickers open and closed in the vision preview and stops the approach, set `HAND_CLOSED_READS=0` in `.env` and restart the controller.

### Smart pick on the real arm: safe zone, tries per method, policy (Anish teaches, Caiden runs tries, when the arm is free between Chat A's recordings, by 7:00)
Built and tested on the fake and sim arms (`docs/PICKING.md`); no real try yet. On the real arm no method can pick until these are done: `model` needs a deployment, `taught_adjusted` a taught pick (above), `ik` `vision/calibration.json` (below).
1. Safe zone (with the poses above): tape a 10 cm square at least 15 cm from the handoff box and off the path to the hand. `.venv/bin/python -m arm.teach --port /dev/tty.usbmodem5C821089781 --robot-id scrub_follower --supported-and-empty`, hold the scalpel's set-down pose (blade down, pointed away from the handoff side) over the square, `s`, `q`. It must print no "move it at least 15 cm away" line. Until `arm/rig.json` has `safe_zone`, the real arm refuses the scalpel.
2. Controller in smart mode: `.venv/bin/python -m controller --real-arm --setting surgical --skills smart`, vision running. Check `curl -s localhost:8000/state | jq '.skills.policy, .safe_zone'` (problems `[]`).
3. 10 tries per item per ready method, spotter on the stop: `.venv/bin/python -m controller.trials --settings surgical --actions handover --lighting normal --tries 10 --methods taught_adjusted,ik` (add `model` once Chat A has a deployment; drop a method that isn't ready). Each try asks you to confirm the physical result.
4. Policy: `.venv/bin/python -m controller.picker --setting surgical` prints method, n, ok, Wilson lower bound and median time per item and writes `data/skill_policy.json`. Copy the table into `docs/PICKING.md` "Per item, measured" and the honest line into `team/PITCH.md`.
5. Check on the arm once: "hand me the scalpel" ends at the safe zone, and a hand put in the zone before set-down gets "Clear the safe spot".

### Slot boxes and camera-to-arm calibration (Brandon with Anish, by 6:30)
`slot` and `return_spot` are null in `settings/surgical.json` and `settings/bench.json`, and `vision/calibration.json` does not exist. Procedure 8 (B5 and B6). Brandon marks slot boxes on his own view while Anish records; calibration needs the arm still and the controller stopped.

### Lighting tests (Brandon, by 6:30)
With the real overhead camera: `.venv/bin/python -m vision.lighting --all-conditions --csv ~/scrub-lighting.csv` (bright, normal, dim in turn). Post the hand, detect and stale rates per light in the chat.

### Backup video (Evan or Caiden, by 7:00)
Screen-record the sim backup with the dashboard open: `.venv/bin/python -m controller.run_all backup --offline --loop --pause 2`. Stop any stack on :8000 first. Label it as the sim in the video. Used for demo level 3 (`team/DEMO.md`).

### Perceptron staff message (Anish, by 8:00)
Send the message in `team/DEMO.md` ("Message for Anish to send the Perceptron staff"): can the arm come to the Ballroom, is there an outlet, live or video only. Adjust it to what is true (do not say a fine-tuned model runs until a deployment passes tries).

### Backup slide deck (Caiden, by 8:00)
Build the 5-slide Google Slides deck from `team/SLIDES.md` (diagram `docs/media/system.png`) and paste the link in `team/SLIDES.md` and the chat. Leave the success-table slide marked "to fill from the ledger" until plan step 13.

### Perceptron arm video and demo video (Anish operates, Evan films and edits, Caiden runs `video/`, 7:15 to 8:15)
Plan step 12 and procedure 14. Real tries only. Write ledger events for the cut with `.venv/bin/python -m video export-ledger`, then render `.venv/bin/python -m video render --edl video/edl/perceptron-arm.yaml --bindings edit.json --output renders/perceptron-arm.mp4` (`video/README.md`, `docs/VIDEO-TOOL.md`). The demo video (2 to 3 minutes) uses `video/edl/demo.yaml` and the shot list in `team/DEVPOST.md`. Upload both. Say "cleaned" if a failed try is cut. Never call it clinically validated.

### Domain and HTTPS (Evan or Brandon, by 8:30)
No domain is bought, so `SCRUB_PUBLIC_URL` is empty and the replay link in the summary text has no host. Steps in `deploy/README.md` (GoDaddy, HTTPS):
1. MLH GoDaddy Registry offer on the DubHacks sponsor page, buy one short domain.
2. Manage DNS: A record `@` to `144.202.95.111`, TTL 600; CNAME `www` to `@`, TTL 600.
3. HTTPS from a Windows machine (this Mac has no `pwsh`): `powershell -File deploy/enable_https.ps1 -Target root@144.202.95.111 -Domain <domain> -Email <school email>`.
4. Add `SCRUB_PUBLIC_URL=https://<domain>` to `.env`; `.venv/bin/python -m deploy` shows Vultr public page PASS on the domain.
If not done by 8:30, the QR card and Devpost use `http://144.202.95.111/` and MLH GoDaddy is dropped from the tracks.

### Make the repo public (Anish, the repo owner, at 8:30)
Run the commands in `team/HIDE.md` (README-PUBLIC becomes README, `team/`, `AGENTS.md` and `CLAUDE.md` are removed, push), then on GitHub `anish-agr/dubhacks-2026`, Settings, Change visibility, Public (or `gh repo edit anish-agr/dubhacks-2026 --visibility public --accept-visibility-change-consequences`). The history was scanned for keys on Oct 17 (no hits, `.env` never committed); rerun `git log -p | grep -iE "api_key|secret|mongodb\+srv"` on anything added since.

### Tiger Data and Backboard: keys or drop (Evan, by 9:15)
`TIGER_DATABASE_URL`, `BACKBOARD_API_KEY` and `BACKBOARD_ASSISTANT_ID` are missing; the pages run from the local ledger. Either add them (Tiger: https://console.cloud.timescale.com, new service, copy the `postgresql://...` URL into `TIGER_DATABASE_URL`; Backboard: https://app.backboard.io, API key plus an assistant named Scrub; then `.venv/bin/python -m deploy` PASS), or leave them out. `team/DEVPOST.md` already leaves both out; add them back only after `deploy` shows PASS.

### Fill the measured numbers and pick the demo level (Evan for Devpost, Caiden for docs, Anish reviews, 8:15 to 9:15)
Plan step 13. Fill every `[measured]` and "to fill from the ledger" in `team/PITCH.md`, `team/DEVPOST.md` and the slides from `curl -s localhost:8080/api/stats` (real-arm tries only). Mark anything unproven as unproven; claim "fine-tuned" only for items whose model picks passed. Anish picks the demo level from `team/DEMO.md` (level 1 `--skills auto`, level 2 `--skills taught`, level 3 sim backup next to the real video).

### Final Devpost (Evan, by 9:30)
Upload the demo video, paste the final text from `team/DEVPOST.md`, link the public repo, check the tracks, submit. Screenshot in the chat.

### Pack for the Ballroom (everyone, 9:15 to 9:30)
Arm, power strip, spare USB cable, laptop, tape, trays, towel, lamp, phone. In the HUB Ballroom by 10:20.

### MLH Commit Fellowship form (Anish, after the Devpost submit, by 10:00)
https://mlh.link/commit-fellowship-form.

### Rehearsal (everyone, 9:30 to 10:20 and in line)
Three runs of `team/DEMO.md`, under 3 minutes twice in a row. Anish speaks, Brandon is the clinician hand, Caiden runs the stack and the stop key (Space), Evan swaps trays and the lamp. Judging command on the real arm: `.venv/bin/python -m controller.run_all --real --tunnel`. Between judges: `.venv/bin/python -m controller.run_all reset`.

### Phone call (Anish, by 4:00, so it can be rehearsed; must work before 6:00)
Built and tested from code (Oct 18, 2:40 AM): the ElevenLabs agent "Scrub" answers every call phrase through the public tunnel ("hemostat" about 0.9 s to the first spoken line, "stop" about 0.1 s), a second call at once hears "Scrub is busy", any number may call, `run_all --real` re-points the agent on every tunnel URL and self-checks it. **Blocker: no number that can take calls.** Photon's docs say "Shared lines cannot take calls", and our project is on the shared plan, so the old `setup` step would never ring. Full steps with what you should see: `voice/README.md` "Anish: the steps left".
1. app.photon.codes, Dubhacks, Voice, Lines: buy a US SMS number (confirm the price; may need Pro, $25/month). It shows in Lines.
2. On that line: Inbound calls on, `sips:sip.rtc.elevenlabs.io:5061`, TLS, media encryption Auto, no credentials, Save.
3. On the arm Mac: `cd voice && npm run photon -- use-line +1<the new number>`. You should see `[env] wrote PHOTON_LINE in .env` and `[agent] imported +1... and assigned the agent`.
4. `npm run photon -- add-user +1<Anish's mobile>` and `PHOTON_SUMMARY_TO=+1<Anish's mobile>` in `.env` (the end-of-case iMessage; iPhone only).
5. Stop the voice server on :3000 and the cloudflared tunnel (`kill <pid>`, never `pkill`), then `.venv/bin/python -m controller.run_all --real`. The table shows `public self-check OK` and `phone (call it) +1...`. (The voice on :3000 now is old code: no timings, no busy line, no `/talk`.)
6. Call from any phone. Say "hemostat", "got it", "what's out", "read the count sheet", "take back the hemostat", "stop", "end of case". Then text the number "add a second hemostat to the surgical tray" from the phone in step 4.
7. Record 30 s of a real call (screen and audio: QuickTime, New Screen Recording, with the phone on speaker) into `data/video/raw/`.
If no number by 6:00: judges talk to the same agent at `https://elevenlabs.io/app/talk-to?agent_id=<ELEVENLABS_AGENT_ID>` in a browser, and `http://localhost:3000/talk` if the network fails. Photon is then claimed for texts only, if step 4 works.

### Photos for recognition and the printed props (Caiden or Brandon, at the arm when it is free, about 20 min, by 6:30)
1. Print at 100% on US Letter from `explore/recognition/props/`: `count_sheet_surgical.html` twice, `tray_tag_surgical.html`, `pack_labels.html`. On one count sheet write a date, a case number, your name, Initial 1, 1, 1 and Closing 1, 0, 1.
2. Take the photos in `docs/RECOGNITION.md` "Photos to take" (about 140 frames): `.venv/bin/python -m explore.recognition.capture --set tray1 --camera overhead --light normal`, then `--camera wrist` for the gripper shots. Phone photos work with `--import <folder>`.
3. Tell Caiden. Caiden runs `.venv/bin/python -m explore.recognition.bench --images data/recognition/tray1 --repeat 2 --max-calls 120`, replaces "Real tray (pending photos)" in `docs/RECOGNITION.md` with the numbers, decides whether Gemini becomes the second opinion in `controller/traycheck.py`, and reruns the readers on the photographed props.

### Count sheet demo beat (Caiden, only after step 3 above, by 8:15)
Hold the written count sheet under the overhead camera and say "read the count sheet". If Scrub reads it right 3 times in a row, add a 20-second beat to `team/DEMO.md`: read the sheet at the start, "end of case" at the end, and Scrub says where the sheet and its count disagree. If not, leave it out.

### Perceptive track decision (Anish, by 8:30)
`docs/INTEGRATION.md` "Track claims" lists the Perceptron perceptive capabilities Scrub uses now (detect, OCR, captions, video QA) with proof commands. Decide whether to enter that track as one of our 3 sponsored tracks.

### Test records in Atlas (Evan, by 9:00)
An OCR test on Oct 18 at about 1:55 AM wrote fake-arm records to Atlas under case `surgical-1792313826`: one handover, three `read` events and two `caption` records, all with `fake_arm: true`. Filter `fake_arm` out of the public tables or delete that case.

### vision test on macOS (Brandon)
`vision.test_pipeline.ProfileTests.test_short_sim_source_loop_stays_bounded` fails on the arm Mac (`rss_start` is 0), also on a clean `origin/main`. The test reads process memory in a way that returns 0 here.

### Thermal baseline experiment (Caiden, only when the arm is free; not needed for the demo)
TH2 in `explore/research/overheating/HANDOFF.md`: baseline experiment 1, then fan-only experiment 2, every follower motor at or under 47 C at the start, up to 10 minutes of the fixed routine, never bypass the 60 C cooldown. Analyze with `.venv/bin/python explore/thermal_analyze.py --session <id>` and append the C/min per motor to HANDOFF Results.

### DEV post (Anish, after the event)
https://dev.to, New Post, the writeup from the last section of `team/DEVPOST.md`, the MLH hackathon tag, link it in Devpost.

## Tonight's plan

### Training re-plan at 2:40 AM (Chat A, `team/RUN-TRAIN.md`; this replaces the training rows of the table below)

Checked: 5 successful jobs per team, 0 used, 0 deployments. The station is stopped. Side camera (C920) 30.0 fps. Wrist camera (icspring) 22.6 fps in every mode (default, MJPG, YUY2) at brightness 147, so light is not the cause; ffmpeg gets 22.58 fps at 640x480@30 too. All four USB devices (both arm buses, both cameras) share one USB 2.0 hub on one Mac port, and the Mac's two other USB controllers are empty.

| Clock | Step | Who |
| --- | --- | --- |
| now | Move the wrist camera (icspring) off the hub to a free Mac port (USB-C adapter), then `.venv/bin/python explore/camera_fps.py icspring`. If it still prints under 29, record anyway with the override below and say so | person at the arm |
| 2:50 to 3:40 | Run 1 data: `.venv/bin/python explore/station/station.py --task "pick the hemostat" --root ~/scrub-surgical --port 8090`. 24 `pick the hemostat`, 12 `return the hemostat` (task buttons on the page), under 20 s each, hemostat shifted a little in its slot each time, normal and bright light. A red RE-RECORD banner means record that one again. Push each batch: `.venv/bin/python explore/dataset/to_mongo.py --root ~/scrub-surgical` | Anish drives, Evan resets |
| 3:40 | Stop the station (Ctrl-C). `.venv/bin/python -m arm.train preflight ~/scrub-surgical` must print `PREFLIGHT PASS`. If the wrist stayed slow: `SCRUB_ACCEPT_CAMERA_FPS=wrist=22 .venv/bin/python -m arm.train preflight ~/scrub-surgical` (printed as a warning, written in `docs/TRAINING.md`) | Chat A |
| 3:45 | Run 1: `.venv/bin/python -m arm.train pipeline ~/scrub-surgical --cadence-report ~/scrub-surgical-cadence.json --idempotency-key scrub-run-1` (direct upload, standard, expert_only, 1000 steps). Same env override if used | Chat A |
| 3:50 to 4:40 | While run 1 trains: same station, same root, `pick/return the mayo scissors` and `pick the scalpel` (to the safe spot), 25 to 30 each. Run 2 on the whole root as soon as it passes preflight (key `scrub-run-2`) | Anish, Evan |
| deployment ready | 10 real tries per item with `--skills model`, every try in the ledger with `skill_source: model` | all |

Written 00:45 for 00:45 to 09:30. Goal: a fine-tuned model that passes real tries, and a Perceptron arm video. Training is the only thing on a clock, so the data steps come first and everything else runs while it trains. Times are targets; if a step slips, cut in the order at the end. At 1:45 nothing in the repo shows step 1 or later done, and no recorder holds the ports.

Rule for every step: one process owns the arm ports and the cameras. Stop the one before it first. The recorder is `.venv/bin/python -m arm.record` (over `explore/arm_session.py`) or the persistent station `.venv/bin/python explore/station/station.py --task "pick the hemostat" --root ~/scrub-dataset` (page http://localhost:8090; Space starts and saves, Backspace discards, Escape is KILL and drops a raised arm).

Facts at 00:50: `arm.train deployments` returns an empty list, `status deployment` on the id in `.env` returned HTTP 404, and no job or dataset id is written in any doc. Treat run 1 as the first real job unless the job ids from Anish say otherwise.

| Clock | Step | Who | Owns the arm and cameras |
| --- | --- | --- | --- |
| 00:45 to 01:00 | 1. Cameras to 30 fps at 640x480: `.venv/bin/python -m arm.check_setup --side C920 --wrist icspring --seconds 3` (procedures 1 and 2). Lamp on, direct USB ports. If the wrist camera will not reach 28 fps, write what fixed it in `docs/DATA-LOG.md` notes | Anish at the cameras, Caiden reads the output | `arm.check_setup` only |
| 01:00 to 01:15 | 2a. Tape the base, tray outline, slots, return spot and both camera mounts (procedure 3). Cameras never move after this | Anish, Evan | none |
| 01:15 to 01:20 | 2b. One slow teleop test (procedure 4) | Anish | `explore/arm_session.py` |
| 01:20 to 01:40 | 2c. Teach `home`, `carry`, `safe_spot` and the handoff box into `arm/rig.json`, plus the shoulder_lift offset (procedure 5). Torque stays off after exit | Anish; Caiden reviews `arm/rig.json` | `arm.teach` only |
| 01:40 to 02:30 | 3. Run 1 data: hemostat only, 30 to 40 episodes, "pick the hemostat" and "return the hemostat", normal and bright light (about 20 pick, 10 to 20 return, half per light). `--print-only` first (procedure 6). Cadence about 30 Hz after each episode. Log every batch in `docs/DATA-LOG.md` | Anish drives the leader; Evan resets, moves the lamp, writes the log | the recorder only. Brandon marks slot boxes on his own laptop view, no ports from this Mac |
| 02:30 to 02:50 | 4. Gates, read-only on the dataset: `.venv/bin/python -m explore.dataset.qa --root ~/scrub-dataset --out ~/qa.html`, `.venv/bin/python -m arm.dataset_check ~/scrub-dataset --cadence-report ~/scrub-dataset-cadence.json`, then `.venv/bin/python -m arm.train pipeline ~/scrub-dataset --cadence-report ~/scrub-dataset-cadence.json --check-only`. Then the video check: `.venv/bin/python -m explore.dataset.qa_video --dataset ~/scrub-dataset --report ~/qa_video.md` (one Perceptron call per episode; `--no-api` for the free dark-camera check only). On the 7 episodes at 1:30 AM it flagged a failed grasp on 0, 2, 3, 5 and 6, a drop on 3, and episode 4 picking scissors instead of the spatula. Drop or re-record flagged episodes before upload. Replay episode 0 (procedure 7.3). Fix every FAIL, re-record those episodes. Every item in "Perceptron pre-flight" ticked | Caiden runs QA, Anish replays | `lerobot-replay` for the replay, then nothing |
| 02:50 to 03:05 | 5. Upload and start run 1 (procedure 7.6, key `scrub-run-1`). Anish says "approve" out loud; Caiden checks the printed job id and the command first. Job id in the chat and in `docs/TRAINING.md` | Anish, Caiden | none (cloud) |
| 03:05 to 04:15 | 6. While run 1 trains (about 45 min plus queue and export): record the Mayo scissors and the scalpel (pick ends at the safe spot), normal and bright, about 25 pick and 10 return each. Then teach taught skills for hemostat, scissors, scalpel (`docs/TEACH.md`). Follow the job in another terminal: `.venv/bin/python -m arm.train follow <job-id>`. Do not change the run-1 folder or cadence file until the deployment is ready unless you snapshotted them (`docs/TRAINING.md`) | Anish and Evan record, then Anish teaches. Caiden watches the job and runs QA on new batches | the recorder, then `arm.teach`, one at a time |
| 04:15 | 7. Check run 1: `.venv/bin/python -m arm.train deployments` shows a ready deployment and `PERCEPTRON_DEPLOYMENT_ID` is set. If not ready by 04:45, keep recording and teaching and ask the Perceptron staff | Anish, Caiden | none |
| 04:20 to 05:10 | 8. 10 real tries for the hemostat with the model: `.venv/bin/python -m controller --real-arm --skills model` plus vision, ask by `curl` or voice (procedure 9). Brandon is the hand, Evan resets, Caiden holds Space. Log each try (`controller/trials.py` or the ledger). Take the latency, session and pull-release readings (People only) | all four | the controller only |
| 05:10 to 05:20 | 9. Run 2 on the full surgical dataset if QA is clean (key `scrub-run-2`, procedure 11). The last run. Start no later than 05:30 so it finishes before 07:00 | Anish, Caiden | none |
| 05:20 to 06:30 | 10. While run 2 trains: 10 tries per item with `--skills taught` for the scissors and the scalpel, ledger rows labeled `taught`. Brandon finishes slot boxes and `vision/calibration.json` (procedure 8). Evan starts `.venv/bin/python -m video ingest` on clips filmed so far. Sleep in shifts, at most two asleep at once | all | the controller only |
| 06:00 | Feature freeze: only fixes and tests from here | all | |
| 06:30 to 07:15 | 11. Run 2 ready: 10 tries per item with `--skills model` (hemostat, scissors, scalpel). An item goes to `model` only if it passes its last 3 tries; `--skills auto` then picks per item. If run 2 is not ready by 07:15, use run 1 only | all four | the controller only |
| 07:15 to 08:15 | 12. Film with `video/`: real tries only, cleaned only, the ledger success table as the end card, `video/edl/perceptron-arm.yaml` | Anish operates, Evan films and edits, Caiden runs `video/` | the controller for filming, then nothing |
| 08:15 to 09:15 | 13. Devpost: video, measured numbers from the ledger, unproven marked unproven. Fill `team/PITCH.md` and `team/SLIDES.md` blanks. Choose the demo level (`team/DEMO.md`) | Evan, Caiden, Anish | none |
| 09:15 to 09:30 | 14. Submit on Devpost. Pack for the Ballroom | everyone | none |

What to cut if time runs short, first to last: sleep stays; drop the dim and extra-light batches; drop run 2 and use run 1 plus taught skills (level 1 still says which source each item used); the bench tray is not in this plan; 10 tries per item becomes 5 and the table says 5. Never cut QA before an upload and never film with a failed try removed without saying "cleaned" in the video.

## Perceptron pre-flight

Tick every box before spending a training run. Perceptron allows 2 successful jobs per team; never start a speculative or replacement job. Sources: `docs/TRAINING.md` (Gates before each training run), `docs/PERCEPTRON-ROBOTICS.md` Part 1.

- [ ] The job ids from Anish are checked (`arm.train status job <id>`) and the quota left is known.
- [ ] `PERCEPTRON_DEPLOYMENT_ID` is empty or names a real deployment.
- [ ] `.venv/bin/python -m arm.train capabilities` answers HTTP 200: `standard`, `expert_only`, horizon 30, RTC and 1000 steps allowed. Result written in `docs/ARM.md`.
- [ ] `.venv/bin/python -m deploy` shows Perceptron robotics PASS. Hugging Face also passes (`HF_USER=caidenm11`), but the default pipeline uploads straight to Perceptron and does not need it.
- [ ] Counts meet the plan for this run, every episode logged in `docs/DATA-LOG.md`.
- [ ] Every episode has a measured 29 to 31 Hz loop and side and wrist cameras at 29 to 31 fps (the pipeline refuses otherwise; `SCRUB_ACCEPT_CAMERA_FPS=wrist=22` lowers the wrist floor on purpose and prints a warning). Every task is an exact `pick the <item>` or `return the <item>` from `settings/surgical.json` (the 13 "pick the spatula" episodes in `~/scrub-dataset` fail this).
- [ ] A stable snapshot: encoding finished, nothing writing to the folder.
- [ ] `.venv/bin/python -m explore.dataset.qa --root ~/scrub-surgical --out ~/qa.html --captions` has no FAIL (the pipeline runs the same QA and blocks on a FAIL; a gripper false alarm passes only with `--accept-qa-fail <eps>` after a person watched that episode). Read the caption report for failed grasps.
- [ ] `.venv/bin/python -m arm.dataset_check ~/scrub-dataset --cadence-report ~/scrub-dataset-cadence.json` passes.
- [ ] Episode 0 replayed on the real follower with a spotter (procedure 7.3); for run 2 also one episode of each new item.
- [ ] `.venv/bin/python -m arm.train pipeline ~/scrub-dataset --cadence-report ~/scrub-dataset-cadence.json --check-only` exits 0 with fps 30.
- [ ] Upload source chosen: the default `--source upload` sends the checked folder straight to Perceptron and saves the dataset id before any bytes move (registering counts against Perceptron's dataset quota, so run it once). Only with `--source hf`: the dataset is pushed as `caidenm11/scrub` and the 40-character commit SHA is passed as `--revision`.
- [ ] The idempotency key is `scrub-run-1` or `scrub-run-2`, and the resume state file `.env.pipeline-<key>.json` is not deleted.
- [ ] Anish says "approve" out loud and Caiden has read the full command.

## Arm procedures

Kept from the old hardware list. Commands and what you should see.

1. **Wrist camera (icspring) to 30 fps** (Anish or Caiden, 15 min). On Oct 17 it ran 22.6 fps; LeRobot needs 30. Plug it directly into a Mac port, lamp on so the grasp area is bright, close every app using a camera. Run `.venv/bin/python -m arm.check_setup --wrist icspring --seconds 3`. You should see `wrist ... 640x480 ... 30.x ... PASS` and a bright saved frame showing the jaws and the table. Under 28 fps: another port on the other side, another cable, a brighter lamp. If it passes only in bright light, record bright and normal only and say so in `docs/DATA-LOG.md`. Never record under 29 Hz.
2. **Side camera (C920) seen** (Anish or Caiden, 5 min). Plug it in directly, run `.venv/bin/python -m arm.check_setup --no-cameras`; you should see `HD Pro Webcam C920`, `icspring camera`, `MacBook Pro Camera`. Missing: another cable and port, replug; last resort another 640x480 webcam passed with `--side <name part>`. Then `.venv/bin/python -m arm.check_setup --side C920 --wrist icspring --seconds 3`: both roles PASS at about 30 fps and a final `PASS`. If the C920 reports 30 but looks choppy (repeated frames), the room is too dim.
3. **Tape** (Anish and one person, 10 min). Arm base, tray outline, slots, return spot, both camera mounts. Keep the safe spot clear and apart from the handoff region.
4. **Slow teleop test** (Anish, 5 min). `.venv/bin/python explore/arm_session.py --side C920 --wrist icspring`, open http://localhost:8090, move the leader slowly through the full range. You should see the follower copy it, both feeds live, the loop at about 30 Hz and no "joint guard" lines. Ctrl+C. On `joint guard: wrist_flex ... outside its calibrated range`: `.venv/bin/python explore/calibrate_follower.py` (cycle the 12 V power first if a motor reads past one turn). Without hardware, `.venv/bin/python explore/arm_session.py --check` says whether `~/scrub-dataset` is ready to train.
5. **Teach poses** (Anish, 20 min). Support the empty arm by hand, nothing else on the port. `.venv/bin/python -m arm.teach --port /dev/tty.usbmodem5C821089781 --robot-id scrub_follower --supported-and-empty`. Move by hand, then key plus Enter: `h` home, `c` carry, `s` safe spot, `a` and `b` opposite corners of the handoff box (at least 1 cm apart on every axis), `p` print, `q` quit. Torque stays off. You should see `home`, `carry`, `safe_spot` and the region in `arm/rig.json`, and `hardware_verified` still false. Measure the shoulder_lift offset (rest reads about -103.7 deg, past the URDF limit of -100; suggested +4 deg) and the joint signs, put them in `arm/rig.json`, then `.venv/bin/python -m arm --dry-run --self-test` must still pass.
6. **Record** (Anish drives, one person resets). Look first: `.venv/bin/python -m arm.record --task "pick the hemostat" --lighting bright --episodes 5 --side C920 --wrist icspring --print-only`, then the same without `--print-only`. Keys: `n` or right arrow ends an episode, `r` or left arrow re-records, `q` or Esc saves and quits. Cadence about 30 Hz after each episode; under 29, close apps and re-record. Exact task words are in `docs/TRAINING.md` (`pick the mayo scissors`, `return the hemostat`, ...). After each batch one new row should be in `docs/DATA-LOG.md`; if not, `.venv/bin/python -m ledger log --setting surgical --item hemostat --direction hand-out --lighting bright --demos 5 --dataset local --notes "cadence ok"`. Throw away bad or blocked-camera episodes.
7. **Check, replay, run 1** (Anish).
   1. QA: `.venv/bin/python -m explore.dataset.qa --root ~/scrub-dataset --out ~/qa.html`, open it, fix every FAIL.
   2. Variety: `PYTHONPATH=. .venv/bin/python explore/dataset/variety.py --root ~/scrub-dataset --out ~/variety.html`.
   3. Replay episode 0 (clear workspace, blunt object, nobody in the path): `lerobot-replay --robot.type=so101_follower --robot.port=/dev/tty.usbmodem5C821089781 --robot.id=scrub_follower --robot.use_degrees=true --dataset.repo_id=<HF_USER>/scrub --dataset.root=$HOME/scrub-dataset --dataset.episode=0`. It should repeat the recorded move.
   4. Local check: `.venv/bin/python -m arm.dataset_check ~/scrub-dataset --cadence-report ~/scrub-dataset-cadence.json` and `.venv/bin/python -m arm.train pipeline ~/scrub-dataset --cadence-report ~/scrub-dataset-cadence.json --check-only`: no problems, every episode 29 to 31 Hz.
   5. Push to the Hub and note the commit SHA (`docs/TRAINING.md`).
   6. Run 1: `.venv/bin/python -m arm.train pipeline ~/scrub-dataset --cadence-report ~/scrub-dataset-cadence.json --repo-id <HF_USER>/scrub --revision <HF_COMMIT> --idempotency-key scrub-run-1 --backend standard --mode expert_only --steps 1000 --confirmed-replay --confirmed-hf-matches-local`.
   7. You should see the dataset ready, validation passed, a job id, then a ready deployment and `PERCEPTRON_DEPLOYMENT_ID` written to `.env`. If the reply is lost, rerun the same command with the same key; never a new key. Validation failed: `.venv/bin/python -m arm.train validation <dataset id>`, fix, make a new dataset.
8. **Slot boxes and calibration** (Brandon, with Anish for B6). B5: overhead camera index set (`CAMERA_INDEX` from the shell or `.env`), `.venv/bin/python -m vision` in its own terminal, `curl -s http://localhost:8001/snapshot -o ~/scrub-tray.jpg`, `.venv/bin/python -m vision.mark_slots --setting surgical --image ~/scrub-tray.jpg`, then `--setting bench`. You should see `slot` and `return_spot` filled in both settings files; check with `curl -s localhost:8001/tray_check`. Wrong place means the camera moved: re-snapshot. B6: real camera, controller stopped, arm still. `.venv/bin/python -m vision.calibrate`, one line per point `pixel_x pixel_y arm_x arm_y arm_z` in meters, 6 to 8 spread points, then a blank line, plus held-out points. Accept only if the held-out error is under about 2 cm (the command writes the file even when it is not). Restart vision, check http://localhost:8001/ shows a non-null `target` for a hand and `path_clear` changes with an obstacle. Save one real hand height for the clinician with `POST /clinician` (default 0.18 m).
9. **First real tries** (Anish, Caiden). `.venv/bin/python -m controller --real-arm --setting surgical` (add `--skills model` or `taught`). It must not move on connect. `curl -s -XPOST localhost:8000/command -H 'content-type: application/json' -d '{"action":"handover","item":"hemostat","source":"keyboard"}'` with a spotter and the stop in reach (`curl -XPOST localhost:8000/stop`). You should see pick, carry, slow approach, release only after a pull or `got_it`, then home. Reset after a stop: `curl -XPOST localhost:8000/reset -H 'content-type: application/json' -d '{"clear_count":false}'`. An item that fails often gets 10 more episodes before run 2.
10. **Reach and gripper load checks** (Anish, before `hardware_verified`).
    1. Reach: 5 spread points inside the handoff box (corners and center) with `move_to`, measure the tip with a ruler: each within about 2 cm, handle toward the person. A miss means fixing signs, offsets or the base transform in `arm/rig.json` and repeating all five.
    2. Gripper load: close on a real item and on air, read the signed `Present_Load` both times (`arm/real_arm.py` `gripper_load()`), then once more while a person pulls. No usable change means pull release stays off and the demo uses "got it".
    3. Both pass: measured poses, region and limits in `arm/rig.json`; `.venv/bin/python -m arm.train contract <DEPLOYMENT_ID>`, check six joints in order, absolute targets, two cameras, horizon and rate 30, RTC delay 12, pin its `contract_id` in `verified_contract_id`; set `hardware_verified: true`; `.venv/bin/python -m unittest arm.test_kinematics arm.test_real_arm -v` still passes.
11. **Run 2** (Anish, the last run). Same pipeline command with `--idempotency-key scrub-run-2`, a newly pinned revision of the whole dataset, the same gates. It starts from the base model. Confirm a new ready deployment with `.venv/bin/python -m arm.train deployments`.
12. **Voice handoff on the real arm** (Caiden, Anish). Real arm up, voice on :3000. `curl -s -XPOST localhost:3000/heard -H 'content-type: application/json' -d '{"text":"grab me the kelly"}'` (moves the real arm). You should hear "Hemostat coming.", see the handover, release on "got it", home. "stop" must hold the arm at any point.
13. **Success tests** (Anish, Evan, a spotter). `.venv/bin/python -m controller.trials --plan-only` shows the full 195-trial matrix; tonight's plan uses 10 tries per item instead. Start with `.venv/bin/python -m controller.trials --settings surgical --items hemostat --lighting normal --actions handover --tries 2` and widen. A person confirms physical success after each try; failures count. Each try lands in the ledger and the dashboard tables.
14. **Perceptron arm video** (Anish, 15 min). One clean real handoff from request to home, side and wrist views plus the arm in frame. A labeled sim backup next to it. Save outside the repo, upload for Devpost.

## Team decisions still open

| Decision | Why it matters | Decide by |
| --- | --- | --- |
| May the real arm use the saved spot when vision is down? | After 5 s with no Hand posts, the arm goes to the saved spot without a hand check. "Only toward an open hand" holds only while vision runs (`team/AUDIT.md` Low) | before plan step 8 (4:20) |
| Is the 400 ms deadline measured from the right moment? | It is measured after the frame is grabbed and encoded, so image age at execution can reach about 580 ms. Decide from the `counters.late` reading in plan step 8 (`team/AUDIT.md` M6, M7) | 6:00 feature freeze |

## Code

Everything planned is built and its tests pass (`team/STATE.md`). These are open because each sits in a folder another session or owner was editing during this pass.

| What | Who | Why it is still open |
| --- | --- | --- |
| Link the judges' data page: add `<a href="data.html">Data</a>` after the Memory link in each `ledger/public/*.html` nav, and add `data.html` to `PAGES` in `design/test_ui.py` | Evan | Chat D could only add `ledger/public/data.html` and `/api/data` |
| Training data: drop and re-record the episodes listed in `team/NOTES-DATA.md` (regenerated every 30 min by `.venv/bin/python -m explore.analysis`) before a training job | Chat A (Anish) | the list changes as episodes arrive |
| The 344 `fake_arm: false` events in Atlas from before 2:20 AM are leaked test runs (0.4 s handoffs), not the arm. `explore.analysis` leaves them out; filter them from any public table too (do not delete without the team) | Evan | read-only data chat |
| `video/` test `test_every_command_on_markerless_synthetic_assets` fails in a fresh worktree because the Playwright browser is not installed under `data/video/browser`. Install it once: `PLAYWRIGHT_BROWSERS_PATH=$PWD/data/video/browser .venv/bin/python -m playwright install chromium` | Caiden | environment setup, only on a new checkout |
