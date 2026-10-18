# Scrub: Devpost submission answers

Every field of the DubHacks '26 Devpost form, ready to paste, in form order. Facts follow `devpost/FACTS-0718.md` (07:20 Sunday) and the logs it cites; numbers from `docs/DATA.md` are the 06:49 refresh. Lines in `<!-- -->` are notes for whoever submits, not form text.

**Thumbnail:** `media/scrub-logo.png` is the Devpost thumbnail and the first gallery image.

Team: Anish (arm, Perceptron training), Caiden (controller, voice, the recording station and autopick), Brandon (vision, deploy), Evan (dashboard, ledger, settings).

## Project name

Scrub

## Tagline

<!-- 99 characters -->
A robot arm that hands a surgeon the instrument they ask for out loud, then lets go when they pull.

## Thumbnail and gallery

media/scrub-logo.png is the Devpost thumbnail and the first gallery image.

## Inspiration

In an operating room the scrub tech stands beside the surgeon, passes each instrument the moment it is named and keeps the count of everything on and off the tray. Hospitals cannot hire enough of them. A surgical tech opening takes about 120 days to fill ([Periop Leader, 2024](https://www.periopleader.com/survey-staffing-woes-ease-slightly-but-challenges-remain/)). When the tech is missing or covering two rooms, the surgeon looks away from the patient, sets down what they are holding and searches the tray themselves.

The count carries its own risk. A Mayo Clinic study found an item left inside a patient about once in 5,500 operations, and in most of those cases the count had been called correct ([Cima et al., 2008](https://pubmed.ncbi.nlm.nih.gov/18589366/)). Sharps are a second hazard. US hospital staff have about 385,000 needle and sharps injuries a year ([CDC](https://www.cdc.gov/sharpssafety/)).

We wanted to take the most repetitive part of that job, fetching a named instrument and holding it out, and give it to a small arm that never looks away, logs every pass and stops the instant someone says so. Scrub never touches the patient, and the surgeon decides when to take each instrument.

## What it does

You say "get the hemostat", "can I have the knife" or only "scalpel". Room names work too ("Kelly" is the hemostat). Scrub's SO-101 arm picks that instrument from the tray, carries it at a capped speed to a fixed handoff point and holds the handle out. It lets go when you pull it or say "let go", closes the jaw to check it is empty and goes home on its own. "Stop" freezes it where it is, motors on, until you say "continue", "go home" or "kill". The arm checks motor temperatures every couple of seconds, goes home and turns the motors off at 60 C, and waits until they cool to 50 C.

On the real arm each pick is a skill we taught it. Autopick's "average" mode takes our recorded demonstrations of one instrument, cuts them at the same moments and median-averages them into one smooth path, peaking at 45 degrees a second. No fine-tuned model runs any pick: our Perceptron fine-tuning job (`job_629682f9575271b687e2c734`, submitted 08:49 Oct 18) was still training at 09:08 and has no deployment. The real arm has handed a scalpel into a hand twice on Oct 18 (06:39 and 07:02, the second asked for by voice) and offered the hemostat twice without a confirmed take. Mayo scissors have no demonstrations yet, so they run only in the MuJoCo simulation, where our controller also checks the grasp before carrying and slows down for the last stretch to the hand.

The controller keeps a running count of what is out and reads it back on request, checked against the overhead camera. Perceptron's vision API reads the tray and says what is missing, and its OCR reads the printed count sheet (5 of 5 rendered sheets correct in 1.8 to 2.3 s) and reports where the sheet and Scrub's count disagree. Every event goes to MongoDB Atlas.

The station page that drives the real arm has a Talk tab: one click turns on an always-listening microphone, commands fire on the first words that make them clear, chatter is ignored, and buttons for Let go, Stop and Return to home sit under the transcript.

## How we built it

Scrub is separate programs that share one short list of messages, so four people could work around one arm. Anish built the arm code and the Perceptron training pipeline (`arm/`), Caiden the controller, voice server, simulation and recording station (`controller/`, `voice/`, `sim/`, `explore/`), Brandon the vision service and the server deploy (`vision/`, `deploy/`), and Evan the dashboard, the ledger and the tray settings (`dashboard/`, `ledger/`, `settings/`). We wrote most of the code with Claude Code and Cursor; 395 of our 493 commits carry their co-author line.

### Hardware

An SO-101 leader and follower pair driven by Feetech STS3215 serial servos. Two USB cameras at 640x480 and 30 fps: a Logitech C920 on the side and a small camera on the wrist. Magnets sit under the tape on the jaw, so camera calibration runs with the instruments out of reach.

### Recording station (`explore/station`)

One long-running process opens both arms, both cameras and the LeRobot dataset once, then runs its own 30 Hz teleop loop with LeRobot's parts (`SOFollower`, `SOLeader`, `LeRobotDataset`). We recorded 29 episodes (24 usable, 9.0 minutes): scalpel handle 11, scalpel 5, hemostat 6, tweezers 4, spatula 3. A saved episode with dropped frames or frozen video gets a red RE-RECORD banner.

Every motor is capped at acceleration 40 and 1200 steps/s, each step moves at most 15 degrees, and a KILL key cuts torque. Motor temperatures are read every 2 s. At 60 C the arm goes home with the motors off and stays locked until the hottest motor is back to 50 C.

Run mode lets a driver steer the arm through those same guards. The AutoPick "average" mode is what moves the real arm on video. It takes every usable demo of one instrument, cuts each at the same moments (start, above the item, grasp, lift, hand-off), resamples each stage and takes the median point by point. Demos whose grasp is more than 25 degrees from the median are left out. It plays at 80% of demo speed, peaking at 45 deg/s, 1.6x slower above 52 C. At the hand-off it holds the instrument out and lets go on a pull (a gripper load jump or the jaw moving) or on "let go", closes to check the jaw is empty, then goes home with the motors off. If nobody takes it in 45 s, it goes home holding it. The page's Talk tab uses the browser's speech recognition, so "get the hemostat", "stop", "continue" or "let go" drive the arm directly.

### Voice (`voice/`)

A Photon phone number connects over SIP to an ElevenLabs agent whose language model is our server, an OpenAI-style `/v1/chat/completions` endpoint that streams the reply back as server-sent events. "Stop" and known instrument words are matched locally first. Anything else goes to Gemini with structured output, where the schema allows only an action and an item id from the current tray, so it can't name an instrument that isn't there. When the station is running, a spoken request goes to it by local match and starts that instrument's averaged replay. The same server texts an end-of-case summary over Photon.

### Controller and simulation (`controller/`, `sim/`)

A FastAPI state machine (finding, picking, checking, moving to hand, waiting for the pull, releasing, homing) runs the sim and a fake arm. Stop never waits on the arm's worker thread. After a stop, commands are refused until someone resets. The controller checks the grasp before carrying and slows from 0.3 to 0.1 speed for the last 8 cm. These two checks exist only in the controller and the MuJoCo simulation, which runs the same arm interface in real time.

### Vision (`vision/`)

Perceptron's `/v1/detect` finds the instruments on the tray, with a local edge-and-color detector when the API is slow. OCR reads the printed count sheet through Perceptron's `perceptron-mk1.5` with a strict JSON schema, and falls back to Gemini. The schemas only allow known item ids.

### Ledger, dashboard and deploy

Every event and the arm's temperature readings go to MongoDB Atlas, buffered to a local file when Atlas is down. The dashboard is one static HTML and JavaScript page on the controller's event socket, with a stop button (spacebar too) and a tablet view. The read-only public page runs on a Vultr Ubuntu server behind nginx, and the database URI never reaches the browser.

## Challenges we ran into

### The servos overheated holding still

At 20:50 Saturday all six follower motors read 54-61 C with torque still on and the folded arm pressing into its stops. The STS3215 operating limit is 60 C and it shuts down at 70 C. At 23:10 we measured it: holding the rest pose, with zero current on four joints, every motor rose about 5 C in 4 minutes. The heat came from having torque on at 12 V. Torque off, they idle at 45-48 C. Around 1 AM we cooled the servos with wet paper towels while we finished the thermal guard. It checks motor temperatures every 2 s, parks the arm with torque off at 60 C and resumes at 50 C. Gentle mode (acceleration 40, speed cap about 105 deg/s) went in at 22:03. After that the hottest logged reading was 57 C, on the gripper.

### The gripper crashed squeezing steel

At 20:30 the gripper (motor 6) hit an overload error squeezing a metal instrument. LeRobot raised the error, the session crashed, and the motor dropped off the bus until we power-cycled it. The supervisor then restarted 39 times in two minutes because only five of six motors answered. Fixes came in steps. At 20:49 an overload eased the claw open instead of ending the session, and the squeeze dropped from 3.0 to 1.5. At 23:41 gripper torque changed by situation: 15% idle and shut, 35% holding, 50% moving. At 03:02 autopick started closing until the handle stopped the jaw, then adding a small squeeze, so the guard and the grip stopped fighting. Thin steel still slipped, so we put magnets under the jaw tape.

### The magnets lifted instruments during calibration

The magnets fixed the grip and broke two other things. A nearly shut jaw holding a thin handle read like an empty jaw, so at 03:54 autopick stopped calling that a miss and let the hand at the offer point decide. During the camera calibration sweep the closed jaw touched down over the tray and the magnets pulled instruments up with it, so at 04:09 the sweep moved to passes at 8 cm and 4.5 cm above the table. At 06:13 the Kelly hemostat's ring slipped out of the jaw on the lift, so the replay now clamps for 0.6 s and squeezes 6 units past the demo's jaw stop before lifting.

### Rate limits and slow calls

Back-to-back Gemini calls in the recognition bench returned HTTP 429, so the bench now waits 3 s between calls and retries once after 20 s. On the arm side, a 429, 503 or 504 from Perceptron used to freeze the arm until a reset. Commit b68c92c (22:33) made those hold the last command and retry, and made the training pipeline wait with backoff on the same request without starting a new job. Autopick's handle finder started on cloud calls: Gemini needed two agreeing answers (up to 3 calls) and ran under a $20 spend cap. At 03:31 a local detector replaced it as the default, at about 8 ms per frame with no network, and it was right on 8 of 8 saved frames.

### Perceptron Robotics training started too late to drive the demo

About 20 teams shared roughly 5 arms on a schedule. The workshop said 2 successful training jobs per team, and the API's capabilities said 5. The validator wants exactly 30 fps from two 640x480 cameras and one camera placement per dataset. Our wrist camera delivered 22.6 fps in every mode on a USB 2.0 hub it shared with both arm buses and the side camera. The side camera then moved after episode 17, so the earlier episodes no longer matched the setup. By the 06:49 refresh we had 29 episodes and 24 usable, spread over five tasks, and no job had run. We then cut a 14-episode "pick the scalpel" dataset that passed Perceptron's validator at 08:49, and `python -m arm.train pipeline` submitted fine-tuning job `job_629682f9575271b687e2c734` (expert_only, 1000 steps) at 08:49. Our own QA had flagged 10 of those 14 episodes (gripper never closes, or action and state diverge by 25 to 33 degrees RMS). At 09:08 the job was training at step 411 of 1000 and nothing was deployed. The picks in the video are replays of our own demonstrations: for each instrument, the demos are cut at the same moments, then median-averaged into one smooth path.

### Hand detection and the scalpel safe spot were cut

The plan had the arm watch the surgeon's hand and hold when it moved away. The camera frame rate was too low to track a moving hand, so we removed hand detection everywhere at 07:08 Sunday, including the dashboard readouts and the pitch. The second plan was to set the scalpel down at a safe spot instead of passing it hand to hand. The arm couldn't do that step reliably, so we cut it from the routine, the sim and the docs too. The real arm kept a speed cap and a release that fires when you pull the instrument or say "let go". The grasp check and the slow zone near the hand exist only in the controller and the sim.

### Photon's shared line could not take calls

We built the phone path as Photon, then SIP into an ElevenLabs agent, then a custom LLM endpoint in `voice/`. Photon's voice docs (checked at 02:11) say shared lines can't take calls, and only the registered phone can text one. We added a `use-line` command and set up a Photon SMS number, +1 785 867 1047, which routes to the agent. The text listener still errors, and no log ties a call on that number to an arm move. A voice turn moved the real arm at 07:02:14, but we can't show it came over the phone, so we don't claim the call.

### Venue Wi-Fi blocked cloudflared

ElevenLabs needed a public URL for our voice server. A cloudflared quick tunnel needs outbound port 7844, which the venue Wi-Fi blocked on Saturday. We switched to Pinggy, an SSH tunnel on port 443 with no account. Through it, a request took 0.5-0.75 s on a fresh connection, about 0.27 s of that TLS. Free Pinggy tunnels end after 60 minutes, so `run_all --real` restarts a dead tunnel, points the agent at the new URL, and checks `/health` through it. Port 7844 opened around 1:30 AM Sunday, and we measured the 2:30 AM turn times through cloudflared.

### Gemini blew the voice latency budget

The voice server gives Gemini 1.5 s to parse a request. The first call after startup often ran past that and fell back to the alias match. We kept the local word match as the first stop: it answers known instrument names, "stop", "got it" and "let go" in under 25 ms at the server. Gemini handles the rest. Turns Gemini parsed had a 624 ms median at 2:30 AM. With the full `gemini-3.8-flash` model at low thinking, a parse took 2.8 s. With the station connected (06:59), turns are matched locally only, so a phrase that names an instrument starts its replay at once.

### Camera-to-table calibration kept failing

Autopick maps side-camera pixels to the table. The first map (02:55) came from the jaw tape in demo episodes 10-13. It was right only near those demos and mirrored on the left. At 03:38 the arm calibrated itself: it visited a grid, found its tape, and fit 13 of 19 points with a 0.3 cm median. Then the camera moved and the tape went from blue to black. Most outliers were frames of a still-moving arm, and detection had to ignore people walking past and the black servos, which move like the tape. At 05:09 the fit became RANSAC over several candidates per grid spot, keeping the old map unless 6 or more spots agree. The grid had also stopped at the tray's far rim, though the arm reaches past 0.44 m, so it moved to 0.22-0.40 m over the instruments.

### Glare and look-alike steel

Perceptron's labels for the scalpel handle flipped with the lighting, and Gemini once boxed the scissors as the handle. From 03:17, a Gemini box had to contain a dark rod to count. The local detector looks for a long, thin dark shape inside the reachable table, and its darkness threshold went through four values in five minutes. At 03:35 it settled on gray 88 or darker: the black handle reads 58-70 and bright steel about 100, and the looser setting had grabbed a steel probe. At 04:27 darkness became relative to the surface around it, so the detector works under other lamps.

### The wrist camera hung on macOS

The wrist camera sometimes stopped delivering frames. A hung macOS camera only reopens in a new process, so at 05:44 the station learned to save, close, and re-exec itself after 15 s of silence while parked. The re-exec never came back up when the camera hung again at 06:51. At 06:57 we moved restarts out of the process. The station writes a marker file and exits with code 75, and `run_station.sh` starts it again in about 15 s. The page's Reconnect button uses the same path, and Ctrl-C still stops everything.

### One process owns the arm and cameras

Only one process can hold each serial port and camera. A stray recorder or station left running blocked the next start: the logs show "follower arm port in use by pid 6986 (station.py)". The recorder and controller now refuse a held port and name the pid. The station opens both arms, both cameras and the dataset once and keeps them open for recording and runs. Some background children ignored SIGINT, so `run_all` falls back to SIGTERM on the process group after 2 s. Before the follower was recalibrated at 21:49, a full-speed 345-degree wrist-roll snap at 21:25 had broken `lerobot-calibrate` ("Magnitude exceeds 2047") until a power cycle.

### Two voices answered at once

The station page's Talk tab speaks in the browser, and `station_voice.py` announced station events out loud. Both answered the same command, so the room heard two replies, one of them "Ready. Move the leader arm...". At 07:43 the page started sending a `page_voice` heartbeat while Talk listens, and `station_voice.py` stays quiet while it gets one. The browser's speech recognition also sent each phrase twice (interim plus final, and again after its own restarts). The station now ignores the same command within 4 s, and result numbering resets each mic session. Voice also lost the station when `.env` was rewritten and the `STATION_URL` line vanished. Since 07:01 it finds the station on its own by checking localhost:8090 every 2 s.

### The sim teleported instruments

The MuJoCo sim's items were kinematic mocap bodies with no contact physics. A grasp attached the item to the jaw, so instruments jumped into the gripper, flickered, or popped in during returns. A units bug (degrees read as radians) also made one sim home move take 85 s, and every handover timed out until we clamped the joint goals. At 06:42 we rebuilt the video sim as a scripted demo: IK keyframes, the jaw closing on each instrument, the held item riding the gripper, and a fixed camera. Every frame is labeled SIMULATION, and the return is labeled as a simulated electromagnet pickup because the real arm's returns were manual.

## Accomplishments that we're proud of

- A spoken "can you get me the scalpel" moved the real SO-101 at 07:02:14 on Oct 18. The station log shows the averaged scalpel demo (episodes 19 and 22) replaying, the handle offered at 07:02:34, the gripper guard reporting "pulled out by hand" at 07:02:35, and "it's gone from the jaw; going home" at 07:02:37.
- Two real handoffs where a hand took the scalpel and the jaw checked empty (06:39:20 and 07:02:37), out of 35 real station runs. The hemostat was offered twice with no confirmed take.
- 29 demonstration episodes recorded with a leader arm (24 usable, 9.0 min): scalpel handle 11, scalpel 5, hemostat 6, tweezers 4, spatula 3.
- A recording station that opens the arms, both cameras and the dataset once, then saves or discards episodes without restarting LeRobot between batches. It has a KILL switch, a cool-down lock and a supervisor that brings it back after a camera hang.
- A thermal guard on every real-arm session: temperatures read every 2 s, rest with torque off at 60 C, resume at 50 C. 16,722 temperature samples sit in MongoDB Atlas; the hottest motor peaked at 57 C (the gripper).
- With the real arm connected, voice turns are matched locally and the reply starts in about 20 to 100 ms; "stop" never waits on Gemini.
- A MuJoCo SO-101 that runs the controller's full flow (scripted pick, grasp check, slow final approach, release on pull, home), which logged 4,511 simulated handoff tries while the real arm was busy recording.
- A Perceptron Isaac fine-tuning job on our own scalpel demonstrations (`job_629682f9575271b687e2c734`), submitted at 08:49 Oct 18 by our pipeline after the dataset passed Perceptron's validator; training at step 411 of 1000 at 09:08.
- 493 commits from four people over the weekend.

## What we learned

**Torque alone heats the servos.** Holding still at the folded rest pose, joints drawing 0 mA rose about 5 C in 4 minutes, as much as the loaded shoulder (358 mA). With torque off they idle at 45 to 48 C against a 60 C operating limit, so every session starts with a few degrees of headroom. We now drop torque at rest and record in batches of 5 to 10 episodes.

**Camera frame rate set what the model could see.** Recording needs both cameras at 30 fps. The wrist camera ran 13 to 23 fps and fell to 18.7 to 22.6 fps on the spatula episodes, below the 25 fps we treat as the training floor. That same rate was too low to follow a moving hand, so the arm holds the tool out at a fixed handoff point.

**Calibration breaks easily.** On Oct 17 a restart with torque off skipped the slow ease and drove a 345 degree wrist-roll gap at full speed. The roll motor counted past one turn and `lerobot-calibrate` failed until a 12 V power cycle. The wrist range also sat on the encoder wrap until we recalibrated it to 813 to 3192.

**A dataset needs one calibration and cameras that never move.** Each Perceptron training run starts from the base model and takes one dataset, so a camera moved mid-recording means starting a new dataset. We wrote dataset QA (frame cadence, dark wrist frames, frozen arm, joint jumps) to gate any upload.

**Latency budgets decide where a command runs.** Through Gemini a turn can wait up to the 1.5 s parse timeout; local alias matching put the first streamed byte out in about 20 ms on Oct 17. "Stop" and known instrument names run locally.

## What's next for Scrub

1. **Deploy the scalpel fine-tune, then record one clean dataset per instrument.** Job `job_629682f9575271b687e2c734` was training at 09:08; once a deployment is `ready`, run it on the arm with `--skills model` and compare it with the averaged replay. Then fixed cameras, one calibration, both cameras at 30 fps, every episode through `explore.dataset.qa` and `arm.dataset_check` (our local QA failed 10 of the 14 scalpel episodes), and one Perceptron Isaac 0.5 fine-tuning job per instrument. A deployed model would let the arm find an instrument wherever it lies instead of replaying an averaged path.
2. **Mayo scissors on the real arm.** There are 0 scissors episodes and 0 real runs; the tray of three is only complete in the simulation.
3. **Bring the controller's checks to the real arm.** The grasp check and the slow zone near the handoff point run only in the controller and sim today. The real arm path (the station) needs both.
4. **Log real tries.** The ledger has 0 real-arm tries. Each real handoff should write a tagged row with request-to-hand time and outcome so success rates by instrument and lighting come from real runs.
5. **Training-lab pilot.** Per `docs/BUSINESS.md`: 20 interviews with surgery center managers and OR leads and two prototype arms in simulation labs (months 1 to 3), then five rooms measuring minutes saved, request-to-hand time and success rate (months 4 to 6). Operating room time costs about $36 a minute ([JAMA Surgery, 2018](https://jamanetwork.com/journals/jamasurgery/fullarticle/2673385)), so at an assumed $792 per room per month Scrub breaks even at about 22 minutes saved per room per month. The pilot has to measure that number.

## Built with

Python, TypeScript, JavaScript, HTML, CSS, Node.js, FastAPI, Uvicorn, LeRobot, NumPy, OpenCV, PyArrow, MuJoCo, Perceptron API, Gemini API, ElevenLabs, Photon, MongoDB Atlas, PyMongo, Vultr, Ubuntu, nginx, SO-101, Feetech STS3215, Logitech C920, Claude Code, Cursor

## Try it out

- Code: https://github.com/anish-agr/dubhacks-2026
- Public judge page (MongoDB Atlas event log, served from Vultr): http://144.202.95.111/
- Video: VIDEO_URL (add before submitting)

## Tracks to tick

<!-- Rules from the DubHacks Hacker Guide: exactly 1 title track, at most 3 SPONSORED side tracks (Perceptron Robotics, Perceptron Perception and Photon each count), unlimited non-sponsored. No MLH ElevenLabs track appears in the guide or the MLH prize list we read, so ElevenLabs goes in "Built with" only. -->

- **Community Kitchen (title track).** Scrub targets operating rooms that can't staff a scrub tech: a surgical tech job takes about 120 days to fill ([Periop Leader, 2024](https://www.periopleader.com/survey-staffing-woes-ease-slightly-but-challenges-remain/)). Proof: the whole repo, `README.md`.
- **Perceptron Robotics (sponsored 1 of 3).** We ran Perceptron's provided SO-101 and recorded 29 demonstration episodes for their checkpoint, and fine-tuned that checkpoint on 14 of them (job `job_629682f9575271b687e2c734`, submitted 08:49, training at 09:08, no deployment). The real arm handed a scalpel to a hand at 06:39:20 and 07:02:37 on Oct 18, both replays of our own demonstrations. Proof: `~/scrub-logs/station-20261018-061828.log`, `~/scrub-logs/station-20261018-065728.log`, `~/scrub-logs/train-run-1.log`, dataset refresh commit `828b958`, `explore/station/autopick.py`.
- **Perceptron Perception (sponsored 2 of 3).** Detect checks the tray (HTTP 200 in 1.8 s) and OCR on `perceptron-mk1.5` reads the printed count sheet (5 of 5 rendered sheets correct, 1.8 to 2.3 s). Proof: `vision/tray.py`, `vision/reading.py`, `docs/INTEGRATION.md` rows "Perceptron vision" and "Perceptron OCR: count sheet".
- **Photon (sponsored 3 of 3), only if a call is confirmed.** The number +1 785 867 1047 routes through Photon SIP to our ElevenLabs agent and `voice/`. No log ties a call on it to an arm move yet, and the texts listener errors. Tick it only after someone finds a call in Photon "Recent calls" or ElevenLabs "Call history" for 07:00 to 07:03 (the voice-driven handoff was at 07:02:14). Proof: `voice/scripts/photon.ts`, commit `fa1a800`, `devpost/FACTS-0718.md` section a.
- **SideShift (sponsored, the third pick if Photon is not confirmed).** SideShift judges the strongest startup idea of the weekend, any stack, in person. Scrub's case is in `docs/BUSINESS.md`: the buyer (hospital perioperative leadership), the price, and break-even at about 22 operating-room minutes a month at about $36 a minute ([Childers and Maggard-Gibbons, JAMA Surgery 2018](https://jamanetwork.com/journals/jamasurgery/fullarticle/2673385)). Tick SideShift or Photon, not both with the two Perceptron tracks (3 sponsored at most).
- **DubHacks NEXT (non-sponsored).** Buyer, price and break-even math (about 22 OR minutes a month at about $36 a minute). Proof: `docs/BUSINESS.md`.
- **MLH Best Use of Gemini API.** `gemini-3.8-flash` turns a spoken request into one command whose item must come from the tray's fixed list (structured output with an enum of item ids). Proof: `voice/src/parse.ts` lines 89-91 and 126, `docs/INTEGRATION.md` Gemini row (HTTP 200 at 07:20).
- **MLH Best Use of MongoDB Atlas.** Atlas holds the event ledger (70,975 docs in `scrub.events`) and the arm's motor temperature log (16,814 rows in `scrub.thermal` at 06:49). Proof: `ledger/logbook.py`, `explore/thermal_log.py`, `docs/DATA.md`.
- **MLH Best Use of Vultr.** The public judge page runs on a Vultr server at http://144.202.95.111/ (HTTP 200 at 07:20). Proof: `deploy/setup_public.sh`, `deploy/scrub-public.service`, `ledger/serve.py`. <!-- At 07:20 the live page still showed old text; confirm Brandon ran deploy/push_public.ps1 before ticking. -->
- **MLH Commit Fellowship (non-sponsored).** Working prototype plus a real staffing problem. Tick it here and send the supplemental form after submitting (see Final checklist).

## Perceptron Robotics track questions

<!-- TRAINING STATUS, checked 09:08 Sunday with `python -m arm.train status job job_629682f9575271b687e2c734` and `python -m arm.train deployments`: status "training", step 411 of 1000, about 1.5 s/step, deployments `{"items": []}`. Before submitting, rerun both and update the status and step below (training / succeeded / failed; deployment id if any). Even with a deployment, the video picks stay demo replays unless the arm is run on it and logged. -->

**What was provided and what we built.** Perceptron provided the SO-101 arm and the pre-trained checkpoint. Everything else is ours. We recorded our own demonstrations at a recording station we wrote on LeRobot's pieces (`explore/station/`): a leader arm teleoperates the follower, side and wrist cameras at 640x480, 30 Hz loop, and a cadence file after every save. The dataset has 29 episodes, 24 usable, 9.0 minutes recorded (scalpel handle 11, scalpel 5, hemostat 6, tweezers 4, spatula 3; no Mayo scissors episodes).

**Control and safety layer (ours).** The station program owns the motors on the real arm. `explore/arm_session.py` caps every motor at acceleration 40 and 1200 steps/s, holds a joint that stalls against a limit for 1 s instead of pushing, and a gripper guard holds at the contact point plus a small squeeze when the jaw stops on something. The station clamps each step to 15 degrees. The thermal guard checks motor temperatures every couple of seconds, goes home and turns torque off at 60 C, and resumes at 50 C; we set those numbers after our motors overheated while holding poses. Autopick moves with a 45 deg/s peak and runs 1.6x slower above 52 C. "Stop" freezes the arm where it is, and it lets go when a hand pulls the instrument or someone says "let go", then checks the jaw closed on nothing before going home.

**What ran, said plainly.** We fine-tuned Perceptron's pre-trained Isaac checkpoint (the SO-100/SO-101 base, step 50,000) on our own 14-episode "pick the scalpel" dataset (`ds_67632415a672136454b58605`), which passed Perceptron's dataset validator at 08:49. `python -m arm.train pipeline` (`arm/pipeline.py`, `arm/train.py`) submitted job `job_629682f9575271b687e2c734` at 08:49:26 Oct 18: backend standard, mode expert_only, action horizon 30, RTC on, 1000 steps. At 09:08 it was training at step 411 of 1000, about 1.5 s a step, and `python -m arm.train deployments` returned `{"items": []}`. Our local QA had flagged 10 of the 14 episodes (gripper never closes, or action and state diverge by 25 to 33 degrees RMS). The picks on video are replays of our recorded demonstrations: autopick "average" mode cuts the demos of one instrument at the same moments and median-averages them into one path. The fine-tuned model has not moved the arm. Log: `~/scrub-logs/train-run-1.log`.

**Task difficulty.** Surgical steel is thin, reflective and lies nearly flat on the tray, so we put magnets under the gripper's jaw tape to hold it (commit `ebd7489`). The handoff has to release into a human hand on a pull and nowhere else.

**Results on the real arm (Oct 18).** 35 station runs (7 calibration). Two scalpel handoffs where a hand took the instrument and the jaw checked empty: 06:39:20 and 07:02:37, the second asked for by voice at 07:02:14. Hemostat offered twice (06:12, 06:22) with no confirmed take. Mayo scissors: 0 real runs.

**Video.** Every real-arm pick in the video is labeled as a taught skill (a demonstration replay). Returning an instrument to the tray is simulated in MuJoCo and labeled "SIMULATED RETURN (electromagnet)"; on the real arm a person puts it back.

## GoDaddy Registry domains

None.

## Feedback about technology we used

**Perceptron Robotics API.** The capabilities endpoint answered every question we had before spending a run: `successful_jobs_per_team` 5, steps 1000, horizon 30, stride 15, deadline 400 ms. A 5-job limit with a 45-minute train made us build a local preflight (`arm/dataset_check.py`) and an offline pipeline self-test so a job would not fail on format. The workshop dataset validator checks the LeRobot format, 30 fps, two 640x480 streams and six float32 state values, but it can't see a slow recording loop: timestamps are frame index / 30, so our wrist camera at 22.6 fps still claimed 30 fps. It also can't judge calibration or units, so we added a measured cadence report. We ran out of time before a job; 0 were submitted.

**Perceptron vision API.** Detect answered the tray check in 1.8 s (HTTP 200), and the recognition bench found 0.4 of items on 5 synthetic cases at a median 2.7 s, so detection on our tray was weak. OCR on `perceptron-mk1.5` with a strict JSON schema read the count sheet correctly on 5 of 5 rendered sheets in 1.8 to 2.3 s and pack labels 4 of 4 in 2.4 to 2.7 s. Strict schema output made the reads easy to validate and fall back from. We only tested rendered props, not photos of the printed sheet.

**Gemini API.** Structured output with an enum of the tray's item ids is the reason we trusted it near an arm: it can't name an instrument that isn't on the tray, and a "clarify" action lets it ask back. `gemini-3.8-flash` at thinking level low took 2.8 s to parse a request with no instrument name. Through the tunnel at 2:30 AM, 9 parsed turns had a 624 ms median (509 to 818 ms). The first call after start often went past our 1.5 s timeout and fell back to the alias match, so known names and "stop" skip Gemini entirely.

**ElevenLabs.** The Custom LLM option let the voice agent call our server's `/v1/chat/completions` directly, so our code decides every reply and the command. Interruptions had to stay on in `client_events` for a caller to say "stop" over Scrub mid-sentence, and with a local "stop" match that came back in 0.07 to 0.11 s through the tunnel. `GET /v1/convai/conversations` returned 0 conversations with our key, so we couldn't confirm call history from code.

**Photon.** The shared line we started with can't take calls, which we learned from Photon's voice docs after setting up routing. Buying an SMS number and importing it into ElevenLabs with our `use-line` script gave us a callable line, +1 785 867 1047. The texts listener never worked: the voice server logged `[texts] stream error ... validation ... projectId` over and over, so inbound texts were never heard and no end-of-case summary was sent.

**MongoDB Atlas.** Atlas stored 70,975 event documents and 16,814 thermal rows with no setup beyond a connection string. The thermal data set our cool-down rule. One lesson: our test suite wrote 422 rows tagged `fake_arm:false` into the same collection, which made fake data look real; a separate database for tests would have avoided that.

**LeRobot.** `SOFollower`/`SOLeader` leader-follower recording worked once we ran our own 30 Hz loop with LeRobot's dataset calls instead of restarting `lerobot-record` per batch, which reconnected arms and cameras every time. The start-up firmware check refused our elbow because it sits past its range at home, so we had to tolerate status flags. We wrote a per-episode cadence report because the dataset metadata says 30 fps regardless of the real loop rate.

**Venue Wi-Fi.** Cloudflared quick tunnels need outbound port 7844, which the venue Wi-Fi blocked on Oct 17 (open again by 1:30 AM Oct 18). An SSH tunnel over port 443 (Pinggy) worked on the same network, at 0.5 to 0.75 s to first byte on a fresh connection, but free tunnels end after 60 minutes and the agent's URL had to be re-pointed each time.

## AI tools used this weekend

- [x] Anthropic (Claude Code). 360 commits carry `Co-Authored-By: Claude Opus 5.5`.
- [x] OpenAI (Codex). Commit `88ece03` adds a Codex prompt, followed by Anish's "ask which one" commits `afc56bb` and `bff59d3`. <!-- No Codex co-author lines in git; evidence is the prompt in 88ece03 and the commits that follow it. Confirm with Anish. -->
- [x] Hugging Face (LeRobot). Recording on LeRobot's `SOFollower`/`SOLeader` and `LeRobotDataset` (`explore/station/README.md`); `HF_TOKEN` passes whoami for the dataset repo (`docs/INTEGRATION.md`).
- [x] Gemini. `voice/src/parse.ts`, `vision/reading.py` OCR fallback, `controller/doctor.py`.
- [x] ElevenLabs. Voice agent `Scrub` with Custom LLM (`voice/scripts/agent.ts`), speech in the room (`explore/arm_voice.py`).
- [x] Vultr. Public page on 144.202.95.111 (`deploy/`).
- [x] Cursor. 35 commits carry `Co-authored-by: Cursor`.
- [x] Other: Perceptron (vision API for detect and OCR; Robotics API for capabilities, dataset validation, one fine-tuning job and deployments queries).

## Generative AI in the hack

Gemini (`gemini-3.8-flash`, thinking level low) turns what a person said into one command, using structured output whose item field is an enum of the tray's fixed item ids, so it can't request an instrument that isn't there. Known instrument names and "stop" are matched locally and never reach Gemini. ElevenLabs does speech to text and speaks Scrub's replies on calls, through a Custom LLM endpoint that points at our voice server. Perceptron's vision API detects what is on the tray and reads the printed count sheet with OCR. We fine-tuned Perceptron's Robotics model (Isaac) on our own 14-episode "pick the scalpel" dataset: job `job_629682f9575271b687e2c734`, submitted at 08:49 Oct 18, was training at step 411 of 1000 at 09:08 with 0 deployments. That model has not moved the arm; the picks on video are replays of our own recorded demonstrations. Most of the code was written with Claude Code, Cursor and Codex and tested by us on the hardware.

## Gemini Project Number

Project IDs: `gen-lang-client-0121141463` and `gen-lang-client-0653014659` (our two Google Cloud projects with Gemini keys).

<!-- Safe to publish: a project ID names the project and grants no access; calling Gemini needs the API key, which stays in .env and is not in the repo. The form asks for the Project NUMBER, which Google shows separately as digits only. The form has one field: enter the project whose key is GEMINI_API_KEY in .env (the voice server and the vision OCR fallback use it). To tell which, open https://aistudio.google.com/apikey, match the key by its last 4 characters (`grep '^GEMINI_API_KEY=' .env | tail -c 5`), and read its project. If the field wants digits, open https://console.cloud.google.com/home/dashboard?project=<that id> and copy "Project number" from the Project info card. If the form allows more, list both IDs. -->

## Final checklist

1. Paste every text field from this file. Submit before 9:30 AM (the form locks at 10:00).
2. Video: upload unlisted to YouTube, paste the URL in the Devpost video field, and open it once logged out to check it plays.
3. Thumbnail: upload `media/scrub-logo.png`.
4. Tracks: tick Community Kitchen, Perceptron Robotics, Perceptron Perception, DubHacks NEXT, MLH Gemini, MLH MongoDB Atlas, MLH Vultr, MLH Commit Fellowship. Third sponsored track: SideShift, or Photon in its place only if a call is confirmed in call history. No more than 3 sponsored tracks (see devpost/TRACKS.md).
5. Gemini Project Number: the project of the key in `.env` (`gen-lang-client-0121141463` or `gen-lang-client-0653014659`; see the note above for how to tell, and for the digits-only number). Leave the domain field as "None".
6. Tick the AI tools listed above.
7. Add all four team members on Devpost (Anish, Caiden, Brandon, Evan) and have each accept the invite.
8. Add the public GitHub repo link.
9. Submit, then open the submitted page and confirm the tracks, video and team show.
10. After submitting, fill the MLH Commit Fellowship supplemental form at mlh.link/commit-fellowship-form.
