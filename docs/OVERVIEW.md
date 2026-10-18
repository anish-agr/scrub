# Scrub: the whole project in one document

Read this first. It explains every idea, decision and part of the project, and where everything lives. Other docs go deeper; this one ties them together. If another doc disagrees with this one on **what we're building**, this one wins. For **current status**, `docs/STATUS.md` and (once the comb pass writes it) `docs/STATE.md` win.

DubHacks '26, Oct 17 to 18, 2026. Team: Anish, Caiden, Brandon, Evan.

---

## 1. Scrub in one paragraph

Scrub is a robot arm that works as a surgeon's second pair of hands. The surgeon asks for an instrument out loud over a phone call on speaker. The SO-101 arm picks it from the tray, brings it to the surgeon's open hand handle first, and lets go when they take it. Scalpels never go hand to hand: Scrub sets them in a fixed safe spot. When the surgeon sets an instrument in the return spot, Scrub puts it back in its slot. Scrub keeps a running count of every instrument out and reads it back on request, and texts a summary at the end of the case. The picking is learned (we fine-tune Perceptron's Isaac 0.5 model on our own demonstrations); the move to the hand is planned from a hand tracker.

## 2. The problem

- Operating rooms depend on scrub techs who pass instruments and keep the count. There aren't enough of them: surgical tech jobs stay open for months, and turnover is high.
- When nobody is there to pass, the surgeon stops, looks away from the patient, puts down what they're holding and searches the tray.
- Counts are a safety step: an instrument or sponge left inside a patient (a "retained surgical item") is a serious, costly error, and manual counts miss things.
- Sharps injuries happen during hand-to-hand passing, which is why operating rooms pass sharps hands-free.

Sources and numbers: `docs/PROPOSAL.md` (sources section), `docs/NEXT.md`, `explore/research/SURGEON_RESEARCH.md`. **Any number used in the pitch, slides or Devpost must be checked against its source first.** `SURGEON_RESEARCH.md` section 6 lists risky claims to avoid on stage.

## 3. What Scrub does (the user's view)

| The surgeon | Scrub |
| --- | --- |
| Says "hemostat" (or "Kelly", "grab me the kelly") | Says "hemostat coming", picks it, checks the grasp, lifts it, brings it to the open hand handle first, and stops a few cm short |
| Takes it (pulls) or says "got it" | Opens the gripper, goes home, logs the time from request to hand. Pulling is detected from the grip load collapsing while the hand is at the handoff spot (release on pull, in progress, see section 4) |
| Says "scalpel" / "knife" | Puts it at the safe spot and says "scalpel down". Never hand to hand |
| Sets an instrument in the return spot | Sees it, says "returning the hemostat", puts it back in its slot (auto return) |
| Says "count" / "what's out" | Reads back what's out, checked against the camera |
| Says "check the tray" | Compares the tray to the expected items and says what's missing |
| Says "stop" | Freezes instantly (skips Gemini). A person must reset it |
| Says "end of case" | Texts a case summary to the same phone thread, with a link to the case replay |
| Texts "add a second hemostat to the surgical tray" | Logs a restock and replies |
| Says "call the hemostat a clamp" | Learns the new word for this clinic |

Between commands the arm rests. After the arm is home and nothing has been queued for 2 s, the controller calls `arm.rest()`: torque off on all six motors, nothing written. Before the next command it calls `arm.wake()`: each motor's goal is set to where it already is, then torque comes on, so nothing moves. `GET /state` reports `resting`. The fake and sim arms implement both. The real arm gets them tonight (section 4).

Every pick and return carries a skill source on its events, `model` (the fine-tuned Isaac model) or `taught` (a replayed, labeled backup). The dashboard, the ops page and the voice reply show it. This lands tonight.

## 4. Scope decisions, and what is real

### Decisions and why

| Decision | Why |
| --- | --- |
| **Surgical first.** Operating room tray: scalpel handle, hemostat, Mayo scissors | The strongest story (staffing, counts, sharps) and the instruments we have |
| **Robotics bench tray is the second setting:** needle-nose pliers, wire cutters, hex key | Shows that a new setting needs new demonstrations and a settings file, and no new code |
| **Dental is dropped.** `settings/dental.json` stays on disk but is hidden everywhere a judge looks | We have no dental tools to record with |
| **Handoff goes to the person's actual hand**, not a fixed spot | A hand tracker plus calibration adapts to each clinician |
| **The fine-tuned model picks, and our code keeps it safe and carries it to the hand.** The model does approach, grasp and lift. Our code does smoothing, speed and joint limits, the claw guard, the thermal guard, the grasp check, and the planned move from carry to the hand | The model learns grasps from demos. The hand position changes every time, so a planned move is safer and more accurate |
| **Voice over a real phone call** (Photon + ElevenLabs) | Clinicians already ask out loud, and it qualifies for Photon and the voice prize |
| **Gemini turns words into one action and one item**, from a fixed list | It cannot invent an item that is not on the tray. "Stop" never waits for Gemini |
| **Only 2 training runs** | Perceptron's quota is 2 successful jobs per team. Run 1 is the hemostat, run 2 is the full surgical set. Nothing uploads until dataset QA passes |
| **One dataset, one calibration, fixed cameras** | Each training run starts from the base model and takes one dataset |
| **Taught skills are a labeled backup, never presented as the model** | If the model fails an item on the table, the demo still runs, and it says which source moved the arm |
| **The arm lives on Caiden's Mac** | Recording and live runs happen there. One process owns the arm ports and cameras at a time |
| **A sim backup stays ready** | If the arm fails at the table, the MuJoCo arm plays a full run next to the recorded real-arm video |

### Real (built, tested, runs today)

- **Controller, voice, vision, ledger, dashboard, settings, sim, deploy.** Tested on the fake arm and the sim arm: `controller.test_flows` 67/67, `controller.test_run_all` 30, `vision` 41, `ledger` 15, `sim` 16, `arm` 94, voice `npm test` and `tsc` clean. `python -m controller.run_all check` passes on its own fake stack.
- **One-command stack and the backup.** `python -m controller.run_all` starts the controller, vision, voice and (with `--ledger`) the ledger and prints every URL. `run_all backup` plays a full run on the sim arm. `run_all reset` clears between judges.
- **Rest and wake between commands** in the controller, on the fake and sim arms.
- **Thermal telemetry and the cool-down guard (recorder).** Every recorder session samples each motor at 2 Hz (temperature, load, position, goal, current, voltage) to `~/scrub-logs/thermal/` and to MongoDB. At 60 C the guard stops the arm and cools it, and it resumes at 50 C or when cooling levels off. `explore/thermal_analyze.py` reports which motor heats, how fast, and in which phase. `explore/thermal_web.py` serves a live temperature site on port 8093. Findings and the ranked causes are in `explore/research/overheating/README.md`. The main heat source is torque on at 12 V, so the arm now rests with torque off.
- **Gripper torque by situation (recorder).** 15% when idle and shut, 35% when holding, 50% when moving, with a dead zone of 3. Overload flags are cleared at startup, bus reads are retried 3 times, and wrist_roll is held to plus or minus 150 degrees.
- **Lift and pulled-out handoff detection (recorder).** Lift is the gripper tip height from the SO-101 model, at least 3 cm while holding. Pulled-out is the grip load collapsing while the leader still holds shut. Each episode ends with `lift_m`, `pulled` and `handoff_success`, and the report shows the handoff per episode.
- **The recorder's page and controls (`explore/arm_session.py`, port 8090).** Both camera feeds and the loop rate, `n`/right arrow ends an episode, `r`/left arrow re-records, `q`/Esc saves, "End session" on the page, "Home + motors off" (glides to the saved home pose at 30 deg/s, then torque off) and "Motors on" (holds in place, then catches up to the leader). The home pose is in `explore/home_pose.json`.
- **Dataset QA (`explore/dataset/`).** `qa` marks each demo PASS, WARN or FAIL (length, frozen arm, gripper, joint jumps, dropped frames, dark or frozen cameras, state lag). `variety` shows where grasps happened and where to record next. `replay` plays the recorded joints in the sim beside the real video. `aim` checks camera level and brightness. `arm.dataset_check` and `arm.train pipeline --check-only` gate every upload.
- **Perceptron Robotics API client** (`arm/perceptron.py`, `arm/train.py`, `arm/pipeline.py`, `arm/upload_dataset.py`) with the team key accepted (HTTP 200 from `python -m deploy`).
- **The video tool (`video/`).** `python -m video` has `corners`, `ingest`, `topdown`, `clean`, `find`, `overlay`, `cards`, `render`, `preview` and `demo-assets`. Every simulated or reconstructed shot is labeled, every number on screen comes from the ledger or the dataset, and speed changes carry a "2x" tag. Spec: `docs/VIDEO-TOOL.md`. 24 of its 25 tests pass here; the card test needs Playwright, which is not installed on the arm Mac yet.
- **The shared design system (`design/`).** One stylesheet, `design/scrub.css`, with a paper theme and a monitor theme, copied by `design/sync.py` into the dashboard, the tablet view, the ledger pages and the sim viewer. The nurse and demo consoles keep their approved styling inside isolated blocks. Spec: `docs/DESIGN-SYSTEM.md`.
- **The public page on Vultr.** `http://144.202.95.111/` serves the judge page from MongoDB through nginx. `bash ledger/push_public.sh root@<ip>` updates it.

### Partly done

- **The real-arm path through the controller has never run on hardware.** `arm/real_arm.py` has the claw guard, the stale-move guard and the 30 Hz streaming. It does not yet have the recorder's retries, limits, gripper torque, thermal stop, `rest()` or `wake()`. Tonight's shared hardware layer fixes that (below).
- **Rig and vision calibration.** `arm/rig.json` is an unmeasured template (`hardware_verified: false`). `vision/calibration.json` does not exist. Slot boxes are not marked, so the hand target and tray slots are defaults.
- **Cameras.** At the last check the wrist camera ran at about 23 fps and was dark, and the side camera was not seen. Recording needs both at about 30 fps (`python -m arm.check_setup`).
- **Training data.** No batch is logged in `docs/DATA-LOG.md` yet. No model has been tested on the arm.
- **Accounts.** Perceptron, Gemini, ElevenLabs and MongoDB pass `python -m deploy`. Photon answers HTTP 403 and its phone line and SIP inbound are not confirmed. `ELEVENLABS_AGENT_ID` and `HF_TOKEN` are empty. HTTPS and the domain for the public page wait on GoDaddy.
- **Tiger Data and Backboard.** The series and memory pages run from the local ledger. Both keys are empty, so neither service is in use. Any track claim for them is cut unless that changes.
- **Design review.** The restyle is checked by script and by fetching every page. Browser screenshots are pending, and the design tests need updating after the `skill_source` edits to the dashboard land.

### In progress tonight (other agents, landing within hours)

- **The shared arm hardware layer in `arm/`**, used by both the recorder and the live arm: bus read retries, joint limits, gripper torque by situation, thermal telemetry, `rest()` and `wake()`, and a stop that goes safe when a motor passes the thermal limit (raising `ArmFault`, which the controller turns into an error event that holds the arm). The recorder keeps working on it.
- **Release on pull** in the controller: open the gripper when the grip load collapses while the hand is at the handoff spot, or on "got it".
- **Taught skills as a labeled backup.** `arm/taught.py` plays a few joint waypoints per item and direction, taught with `python -m arm.teach`. The controller flag `--skills model|taught|auto` picks the source. `auto` uses the model for an item once a deployment exists and the item passed its last 3 real tries. Every event carries `skill_source`.
- **An ops page** (`controller/ops.html`): controller step, `skill_source` per item, arm temperatures and loads, camera rates, API latencies and last errors.
- **A doctor command** (`python -m controller.doctor`): checks every service and key (never values) and asks Gemini to turn recent errors into a short list.
- **A recognition bench** (`explore/recognition/bench.py`): Perceptron detect, Gemini image input and MediaPipe on real frames and saved tray images, with accuracy and latency, written up in `docs/RECOGNITION.md`.

### Dropped

- **Dental.** No tools, no recordings, hidden everywhere a judge looks.
- **A third setting.** The proposal's three trays are two.
- **The idea prototypes.** The gallery in `explore/prototypes/` is inspiration only and moves to `team/` before the repo goes public.
- **Claims with no real use behind them.** Any track claim that `docs/INTEGRATION.md` cannot prove with a command is cut.

## 5. How the system fits together

```
phone on speaker
  -> Photon number -> ElevenLabs agent (speech) -> voice/ (Gemini: words to command)
                                                     |
                                                     v
vision/ (overhead camera: tray + hand) ----------> controller/ ----> arm/ ----> SO-101
                                                     |                |
                                                     |                +-- model skill: Perceptron Isaac 0.5
                                                     |                +-- taught skill: arm/taught.py (backup)
                                                     |                +-- fake arm or sim arm (sim/) for tests and the backup demo
                                                     v
                           ledger/ (MongoDB) + dashboard/ + ops page + public page (Vultr)
```

Only the controller moves the arm. Everything else sends it information. The messages between parts are fixed in `docs/CONTRACTS.md`. A picture is in `docs/media/`.

| Part | Folder | Port | What it does | Built on |
| --- | --- | --- | --- | --- |
| Controller | `controller/` | 8000 | The brain: queue of commands, the step-by-step handoff (find, pick, check grasp, move to hand or safe spot, wait for pull, release, home, log), return, count, tray check, every safety rule, rest and wake between commands. Serves the dashboard, the nurse console and the demo page. `run_all.py` starts the whole stack | FastAPI |
| Arm | `arm/` | | Connects to the SO-101 (LeRobot), runs the fine-tuned model (sends side and wrist images plus 6 joint angles, plays the returned moves at 30 Hz), the hand-reaching math (`move_to`, inverse kinematics), pose teaching, taught skills, the training pipeline. The shared hardware layer (reads, limits, torque, heat) is being added so the recorder and the live arm use the same code | LeRobot, Perceptron Robotics API |
| Vision | `vision/` | 8001 | The overhead camera: MediaPipe finds the open hand and turns it into an arm target; Perceptron's vision API finds instruments and maps them to tray slots; tray check; lighting tags; event clips; a video stream with boxes | OpenCV, MediaPipe, Perceptron detect |
| Voice | `voice/` | 3000 | The ElevenLabs agent's custom LLM endpoint: Gemini parses each phrase, "stop" goes straight to the controller, replies are spoken; texts in and out on the Photon thread; end-of-case summary | TypeScript, Gemini, Photon |
| Ledger | `ledger/` | 8080 | Logs every event and test result to MongoDB Atlas (with a local file if Mongo is down), success tables with ranges, and the public pages: judge page, case list, case replay, QR table card. Runs on Vultr for the public | MongoDB |
| Dashboard | `dashboard/` | served at 8000 | What judges watch: live camera, current step, what's out, event log, tray and lighting pickers, stop and reset. `tablet.html` is a large-text view | plain HTML/JS |
| Settings | `settings/` | | One file per tray: items, the words people say, which item is sharp, slot boxes, the model instructions | JSON |
| Sim | `sim/` | 8002 | A MuJoCo model of the SO-101 with the same arm interface. Used for testing without hardware, as the backup demo, and for replaying recorded joints | MuJoCo |
| Design | `design/` | | The shared stylesheet and its sync and check scripts | CSS |
| Video | `video/` | | Cleans real footage and builds the demo video and the Perceptron arm video from the ledger and dataset | OpenCV, ffmpeg |
| Deploy | `deploy/` | | Puts the public page on a Vultr server; `python -m deploy` checks every key and service | |
| Recorder and tools | `explore/` | 8090, 8093 | The recorder page, the temperature site, dataset QA and the overheating research. These are real tools; the rest of `explore/` is not (section 11) | LeRobot, MongoDB |

**One arm path.** The recorder (`explore/arm_session.py`) got every reliability fix first. The live demo goes through `controller/` and `arm/real_arm.py`. Tonight both move onto one hardware layer in `arm/`, so what makes recording safe also makes the live arm safe.

**Skill sources.** The arm objects (`FakeArm`, the sim arm and `arm/real_arm.py`) all take `run_skill(instruction, max_s, source)`. `source="model"` calls the deployment. `source="taught"` plays a taught skill. The controller picks the source per item from `--skills`, and tags the start and end events of each pick and return.

**Telemetry.** Arms may offer `telemetry()`, which returns temperatures, loads, the hottest motor and whether the arm is cooling. `GET /state` carries it as `arm_telemetry`, along with `skills` and `latency_ms`, for the ops page.

## 6. Data and training (plain version; details in `docs/TRAINING.md`)

1. A person moves the **leader** arm and the **follower** copies it. The recorder (`python -m arm.record`, which runs `explore/arm_session.py`) saves both cameras (`side`, `wrist`, 640x480, 30 fps) and the 6 joint angles. One try is one **episode**. The recorder page on port 8090 shows both feeds and the loop rate.
2. Each episode is labeled with its exact instruction: `pick the hemostat`, `return the hemostat`. One model learns every item and both directions.
3. The recorder protects the arm while it records: joint limits, gripper torque by situation, retried bus reads, and the cool-down guard. It marks each episode with lift, pulled-out and handoff success, so a handover that did not lift or release is easy to find.
4. We vary the item's position slightly and the lighting (bright, normal, dim), because operating lights cause glare on steel. Every batch gets a row in `docs/DATA-LOG.md`.
5. Before anything uploads, dataset QA must pass: about 30 Hz on both cameras, no dark wrist frames, one task string per instruction, and the planned episode count. `python -m explore.dataset.qa` and `python -m arm.dataset_check` run it.
6. The dataset goes to Hugging Face. Perceptron fine-tunes Isaac 0.5 on it (about an hour plus export) and gives us a deployment. Run 1 is the hemostat only. While it trains we record the Mayo scissors and the scalpel (its pick goes to the safe spot) into the same dataset and teach the backup skills. Run 2 uses the full surgical set if the data is clean.
7. `arm/real_arm.py` streams camera frames and joint angles to the deployment and plays back the moves it returns. A late or stale move is never played.
8. The model has no "done" signal, so our code decides when a pick is finished (gripper closed and still, or a time limit), checks the grasp, and the camera confirms the slot is empty.
9. An item goes to `model` only after it passes real tries through the controller, logged to the ledger. Until then it runs on a taught skill and is labeled that way. The Perceptron arm video (`video/edl/perceptron-arm.yaml`) shows real tries only, cleaned, with the success table from the ledger.

The fine-tuned model picks; our code keeps it safe and carries it to the hand.

Targets per item are in `docs/TRAINING.md`. The step-by-step operator walkthrough is `docs/TRAINING-HANDOFF-PROMPT.md` (written for Windows; translate to the Mac).

## 7. Safety design

- Stop works from every state, by voice, the stop button or the spacebar, and skips everything else.
- After a stop, a person must reset before Scrub moves again.
- The arm only enters a bounded handoff region, only toward an open hand, slows near the hand, and stops if the hand is lost or something crosses the path.
- Sharps go to the safe spot, never to a hand.
- A late or stale model move is never executed; the arm holds instead.
- The gripper eases off before overloading; motor heat and stalls are watched.
- Scrub never touches the patient. In a clinic it would run under a sterile drape on a medical-grade arm.

## 8. Tracks and what each one gets from us

| Track | What we show |
| --- | --- |
| **Community Kitchen** (title) | Health care staffing gap; a working assistant a judge can use live; clean dashboard and table |
| **Perceptron Robotics** | Isaac 0.5 fine-tuned on our own demos, one language-conditioned model for every item and both directions, success rates by item and lighting, the required arm video |
| **Perceptron Perception** | Their vision API doing real work: tray state, grasp check, auto return, the count, tray check, labeled event clips |
| **Photon** (+ best voice agent) | The whole case runs over a call to the Photon number; texts in (restock, what's out) and the summary out on the same thread |
| DubHacks NEXT | The business case in `docs/NEXT.md`: surgery centers first, priced per operating room per month |
| MLH Gemini | Speech to command with structured output, the summary, texts |
| MLH MongoDB Atlas | The ledger, case replay, success tables |
| MLH Vultr + GoDaddy | The public judge page on a Vultr server at our domain |
| MLH Commit Fellowship | Tick on Devpost + a form |
| MLH DEV | A post after the event (draft in `docs/DEV-POST.md`) |

## 9. What already exists (prior work) and what's different

Robot scrub nurses are an active research area (Penelope, Gestonurse, RoboNurse-VLA and newer VLA scrub nurses). None is on the market. Scrub differs by: a cheap open-source arm, voice over a real phone call, handoff to the actual hand, put-back to the exact slot, the automatic count with a camera check, sharps handled hands-free, more than one setting on one model, and measured lighting robustness. Details: `docs/PROPOSAL.md` (team notes) and `explore/research/SURGEON_RESEARCH.md` section 3.

## 10. The business (summary of `docs/NEXT.md`)

Start with surgery centers and training labs. Sell per operating room per month, priced below the cost of covering unfilled scrub tech shifts. It assists scrub techs rather than replacing them. A medical-grade arm and FDA clearance come later; the software talks to the arm through one interface, so it can move to better hardware. All numbers there are planning estimates and are labeled that way.

## 11. The `explore/` folder: how to treat it

`explore/` is Caiden's agents' scratch area. **It is not the product, and agents must not build features from it.**

| Path | What it is | Use it for |
| --- | --- | --- |
| `explore/arm_session.py`, `arm_ui.*` | The recorder that drives the real arm on the Mac, with camera and motor safety guards | **Real tool.** Being promoted to `arm/record.py` |
| `explore/dataset/` | Checks recorded episodes (cadence, joint limits, camera aim, replay in sim) | **Real tool.** Run it before every training run |
| `explore/bench/` | An on-device tray identifier | Experimental |
| `explore/research/isaac-workshop-notes.md` | The Perceptron workshop deck as notes: commands, quotas, inference timing | **Reference.** Facts summarized in `docs/PERCEPTRON-ROBOTICS.md` |
| `explore/research/SURGEON_RESEARCH.md` | Retained items, staffing, prior robotic scrub nurses, judging, risky claims | **Reference** for the pitch. Check every number |
| `explore/research/01-04` | Startup tracks, medical go-to-market and FDA path, competitors and market, 30 build-out ideas | **Reference** for NEXT and Q&A. Ideas, not plans |
| `explore/research/perceptron-mk15-notes.md`, `TRACKS.md` | Perception API notes, track descriptions | Reference |
| `explore/prototypes/` (59 pages), `status-board/`, `pages/`, `IDEAS-BACKLOG.md` | Clickable mockups and idea lists from brainstorming, many for ideas we didn't build (kitchen, pills, telepresence, surgical skills) | Inspiration only. Planned for removal before the repo goes public |

## 12. Which doc to read for what

| You want | Read |
| --- | --- |
| Rules for agents, who owns which files | `AGENTS.md` |
| Message formats between parts | `docs/CONTRACTS.md` |
| What's done and what's next | `docs/STATUS.md`, `docs/STATE.md` (after the comb), `docs/LEFT.md` |
| Hardware steps left | `docs/HARDWARE-TODO.md` (after the comb), `docs/BRINGUP.md` |
| Accounts and keys left | `docs/ACCOUNTS-TODO.md` (after the comb), `docs/SETUP.md` |
| Training | `docs/TRAINING.md`, `docs/TRAINING-HANDOFF-PROMPT.md`, `docs/PERCEPTRON-ROBOTICS.md` |
| Pitch and demo | `docs/PITCH.md`, `docs/DEMO.md`, `docs/QNA.md`, `docs/SLIDES.md` |
| Devpost and posts | `docs/DEVPOST.md`, `docs/DEV-POST.md`, `docs/README-PUBLIC.md` |
| Business case | `docs/NEXT.md` |
| Original full proposal (some parts outdated: dental, three settings) | `docs/PROPOSAL.md` |
| Bugs found | `docs/QA.md`, `docs/AUDIT.md`, `docs/REVIEW.md` |
| The timeline | `docs/PLAN.md` |

## 13. Glossary

| Word | Meaning |
| --- | --- |
| SO-101 | The open-source robot arm (6 motors). Leader = the one a person moves; follower = the one that copies and does the work |
| LeRobot | Hugging Face's software for recording and running robot arms |
| Isaac 0.5 | Perceptron's robot model. We fine-tune it on our demos |
| Episode | One recorded try of one task |
| Instruction | The text label of a task, like `pick the hemostat`. The model is given the same text at run time |
| Deployment | A trained model ready to call. Its id goes in `.env` |
| Chunk | 30 future moves (1 second) the model returns per request |
| RTC | Real-time chunking: how new chunks blend with the moves already being played |
| Cadence | How many frames per second recording really achieved. Must be about 30 |
| Handoff region | The box of space the arm may enter to hand something over |
| Safe spot | Where sharps are set down |
| Return spot | Where a clinician sets a used instrument for Scrub to put back |
| Ledger | The log of every event and result (MongoDB) |
| Case | One procedure from start to "end of case"; has a `case_id` |
| Fake arm / sim arm / real arm | Controller modes: instant fake responses, the MuJoCo simulation, or the real SO-101 |
