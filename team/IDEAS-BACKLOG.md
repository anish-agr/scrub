# Ideas backlog (not the task list)

> Written before we found this repo's plan. The real tasks are in `team/LEFT.md` and `team/LEFT.md`. Paths here (`reach/...`) refer to an older local prototype. Use this list for ideas only and pass any you want built to the folder's owner.


Goal: keep several coding agents busy for ~24h on work that does not block on the arm, while the humans own
the physical task, data collection and fine-tuning. Every task below is independent, owns its own files,
and has a test or visible check so an agent can finish it alone.

## How agents use this file
1. Pick the first `TODO` task in the highest-priority lane whose `deps` are `DONE`.
2. Change its status to `DOING (agent-name, HH:MM)` before starting. Never take a `DOING` task.
3. Stay inside the files listed in `owns`. Need a change elsewhere? Add a new `TODO` task with what you need, don't edit.
4. Done means: tests pass (`cd reach/backend && ../.venv/bin/python -m pytest -q`), mock mode still works, then set `DONE`
   and add one line under it: what changed and how to see it.
5. Follow `reach/CONTRACT.md` (LLM never drives the arm, safety only in `safety_check()`, STOP latches, no em dashes).
6. Model: use `sonnet` for build tasks, `haiku` for research, copy, tests and docs. `opus` only for the P0 integration review.

Priority: P0 = demo breaks without it. P1 = scores Design/Functionality. P2 = side-track stacking. P3 = wow / stretch.

---

## Lane S: Surgeon assistant (TOP PRIORITY: this is the team's chosen idea)
Context: `prototypes/SURGEON_BRIEF.md`, `prototypes/SURGEON_RESEARCH.md`. Core primitive: pick an instrument from a fixed
tray slot and present it handle-first into an open-palm zone. Props only, no real sharps. Prototypes 24-35 in the gallery.
- [ ] S1 `TODO` P0 **Instrument task menu.** Add `handoff(instrument)`, `return_to_tray`, `present_count_tray` and `scan_tray` to TASKS. Add a tray-slot map config (`config/tray.json`: slot id, instrument, pose name). owns: a new TODO for the core.py edit, plus `config/tray.json`.
- [ ] S2 `TODO` P0 **Instrument detector.** Perceptron `/v1/detect` with few-shot exemplars (one photo per prop instrument), mapped to tray slots. Add mock fixtures. owns: `backend/instruments.py`. deps: A4.
- [ ] S3 `TODO` P0 **Palm gate.** Detect an open palm in the handoff zone that stays still for 0.5s, so release happens only then. Detect hand closure to confirm the handoff. This is a safety input to `safety_check()`. owns: `backend/palm_gate.py`.
- [ ] S4 `TODO` P0 **Voice instrument requests.** Push-to-talk, then a transcript (Web Speech or Perceptron/Gemini audio), then the instrument enum, with synonyms (Kelly/hemostat/clamp, Adson/forceps, Mayo/scissors). Keep the keyword fallback. owns: `backend/nlu_surgical.py`.
- [ ] S5 `TODO` P0 **Scrub console live.** Port `24-scrub-nurse.html` to the real WS events, with handoff latency per request. deps: S1-S4, B1.
- [ ] S6 `TODO` P1 **Count ledger.** Track sponges and instruments in and out (detections over time), reconcile at close, and keep the closing gate locked until the counts match. Port `25-count-guardian.html`. owns: `backend/count_ledger.py`.
- [ ] S7 `TODO` P1 **Preference cards.** Per-surgeon instrument order and next-instrument prediction (Backboard memory, with a simple Markov fallback from logged handoffs). Feeds the "anticipated next" queue. owns: `backend/prefs.py`.
- [ ] S8 `TODO` P1 **Handoff demo recording plan.** A script plus scenario cards for 50+ handoff demos (6 instruments x tray slots x hand positions). Connects to C4/C5. owns: `docs/surgeon_data_plan.md`.
- [ ] S9 `TODO` P1 **Handoff eval.** N-trial eval scoring correct instrument, handle-first orientation, latency and retries, with Wilson CIs. Port `34-handoff-challenge.html`. deps: C6.
- [ ] S10 `TODO` P1 **Sterile/keep-out zones.** Zone editor and speed scaling by human distance, from `30-sterile-guardian.html`. owns: `backend/zones.py`. deps: A9.
- [ ] S11 `TODO` P2 **OR timeline.** Log phases, handoffs and counts to Tiger Data and render `29-or-timeline.html` from it. deps: D3.
- [ ] S12 `TODO` P2 **Photon to the circulating nurse.** Count discrepancy and missing-instrument texts with a snapshot. deps: D1.
- [ ] S13 `TODO` P2 **Skill coach.** Score a box-trainer video with Perceptron video Q&A (JIGSAWS gestures plus timing). Port `28-skill-coach.html`. owns: `tools/skill_score.py`.
- [ ] S14 `TODO` P1 **Surgeon pitch.** Finalize `35-surgeon-pitch.html` with verified stats from SURGEON_RESEARCH.md and real numbers.
- [ ] S15 `TODO` P1 **Safety + disclaimer pass.** Every surgical page says it is a training/research prototype, and no clinical claims appear (see "risky claims" in SURGEON_RESEARCH.md).

## Lane A: Core platform (P0)
- [ ] A1 `TODO` P0 **LeRobotArm backend.** Implement `ArmBackend` for the real SO-101 using LeRobot (`lerobot.robots.so101_follower`). Each named step runs the policy for N seconds, or a scripted pose for approach/retreat. Read `HARDWARE=1`, falling back to MockArm. owns: `backend/arm_lerobot.py`. check: mock tests still pass, plus a dry-run script that prints the planned calls.
- [ ] A2 `TODO` P0 **Policy server adapter.** Client for the Perceptron fine-tune/inference endpoints (and a local ACT/SmolVLA fallback): `get_action(obs) -> joint targets`, with timeout, retries and a latency metric. owns: `backend/policy_client.py`. check: unit test against a fake HTTP server.
- [ ] A3 `TODO` P0 **Camera service.** OpenCV capture for wrist + overhead cams, an MJPEG stream at `/api/camera/{name}.mjpg`, `snapshot()` JPEG, and a synthetic test-pattern camera in mock mode. owns: `backend/camera.py`. deps: none. check: open the stream in a browser.
- [ ] A4 `TODO` P0 **Perceptron perception client.** Reference: `reach/docs/perceptron.md` (`/v1/detect` returns pixels, chat tags use a 0-1000 grid). Object localization -> `Detection[]` (normalized boxes), OCR, captioning, video event detection. Cache results, back off on rate limits, mock fixtures in `tests/fixtures/`. owns: `backend/perception.py`.
- [ ] A5 `TODO` P0 **Verification step.** Before/after snapshot diff + "is the target on the tray?" check with a perception question, so `verify` returns a real bool + confidence. owns: `backend/verify.py`.
- [ ] A6 `TODO` P0 **Watchdog + e-stop hardening.** Heartbeat from the UI. If the WS drops for over 2s while running, auto-stop. Keyboard Esc global. Torque-off path. owns: `backend/watchdog.py`, plus a new TODO for the main.py wiring.
- [ ] A7 `TODO` P0 **Integration review (opus).** Wire A1-A6 into `main.py`, then run a full mock + hardware dry run. Only this task edits `core.py`/`main.py`.
- [ ] A8 `TODO` P1 **Replay recorder.** Persist every run (frames at 5fps, joint states, plan, events) to disk and SQLite for the replay UIs. owns: `backend/recorder.py`.

- [ ] A9 `TODO` P1 **Multilook safety tick.** One Perceptron multilook call per ~1s: hand in workspace? target visible? gripper holding? Feeds `safety_check()` inputs. owns: `backend/perception_tick.py`. deps: A4.
- [ ] A10 `TODO` P2 **Few-shot personal objects.** Upload one photo of "my mug" as an exemplar so `/v1/detect` finds that exact object. Small UI to manage exemplars. owns: `backend/exemplars.py`, `frontend/exemplars.html`.
- [ ] A11 `TODO` P3 **Audio events.** Sound-event detection (smoke alarm, kettle whistle, "stop" shouted) through the Perceptron audio input, raising the STOP or an alert. owns: `backend/audio_events.py`.

## Lane B: Frontend productization (P1, Design 20%)
Turn the strongest prototypes in `prototypes/` into real pages served by FastAPI that talk to the real `/api` + `/ws`.
- [ ] B1 `TODO` **Shared design system.** One `frontend/ds.css` (tokens, light/dark, buttons, STOP, cards) taken from the chosen prototype aesthetic. Every page imports it.
- [ ] B2 `TODO` **Mission Control live.** Port `01-mission-control.html` to real WS events (state, detections, plan, step, safety). deps: B1.
- [ ] B3 `TODO` **Digital twin live.** Port `02-digital-twin.html` and drive the joints from a new WS event `joints {q[6]}`. Adds a TODO for the backend event. deps: B1.
- [ ] B4 `TODO` **Accessible user UI.** Port `07-one-switch.html` as the main end-user page (switch scanning, dwell, voice). deps: B1.
- [ ] B5 `TODO` **Caregiver dashboard.** Port `06-family-hub.html` onto `/api/activity`, `/api/trials`, plus memory endpoints. deps: B1.
- [ ] B6 `TODO` **Judge Arena live.** Port `11-judge-arena.html` onto `/api/trials` + `/api/mock/move`. deps: B1.
- [ ] B7 `TODO` **Pitch mode.** Finalize `17-pitch-mode.html` with real numbers pulled from `/api/trials` at load.
- [ ] B8 `TODO` **Accessibility audit (haiku).** axe-core or a manual pass over every page: contrast, focus order, 44px targets, aria-live. File fixes as new TODOs.
- [ ] B9 `TODO` **Mobile pass.** Every page usable at 390px. Screenshot each page with Playwright into `docs/screens/`.

## Lane C: Robot learning tooling (P1, Perceptron track + "Data Surgeon" angle)
- [ ] C1 `TODO` **Dataset doctor CLI.** Load a LeRobot dataset (HF repo id or a local path) and flag idle head/tail frames, joint velocity spikes, gripper chatter, dropped frames and out-of-distribution start poses. Output JSON + a summary. owns: `tools/dataset_doctor.py`.
- [ ] C2 `TODO` **Episode Studio live.** Port `03-data-surgeon.html` to read C1's JSON + real episode videos. deps: C1.
- [ ] C3 `TODO` **Auto instruction synthesis.** Gemini: key frames per episode -> instruction + 5 paraphrases, written into the dataset `task` field. owns: `tools/instruct_synth.py`. (Gemini track)
- [ ] C4 `TODO` **Coverage planner.** From the start-pose heatmap, tell the operator where the next demos should go. Feeds the recorder randomization cards. owns: `tools/coverage.py`.
- [ ] C5 `TODO` **Recorder UI live.** Port `04-teleop-recorder.html` around `lerobot-record` (subprocess wrapper, episode counter, scenario cards). deps: C4.
- [ ] C6 `TODO` **Eval harness.** Scripted N-trial eval with randomized placements. Writes trials into Tiger Data/SQLite and computes Wilson CIs per policy. owns: `tools/eval.py`.
- [ ] C7 `TODO` **Failure classifier.** Classify each failed trial (missed grasp, slip, wrong object, collision, timeout) with a VLM over the before/after frames. Feeds `12-failure-lab`. owns: `tools/failure_classify.py`.
- [ ] C8 `TODO` P3 **HIL corrections queue.** "Teach me" button saves the scene and queues a corrective demo slot.

## Lane D: Sponsor integrations (P2, max 3 sponsored + unlimited non-sponsored)
- [ ] D1 `TODO` **Photon sidecar.** Node `spectrum-ts` service `POST /send {to,text,photo_b64}` per `reach/docs/photon.md`. owns: `photon-sidecar/`.
- [ ] D2 `TODO` **Photon conversation flows.** Approval YES/NO/CALL, remote command, clarification list, STOP text latches, 5 min escalation, daily digest. owns: `backend/notify.py` (extend), tests in `test_notify.py`.
- [ ] D3 `TODO` **Tiger Data telemetry.** Hypertable `joint_telemetry(ts, run_id, q[6], effort)`, `trials`, continuous aggregate for success rate per hour. owns: `backend/tsdb.py`, `sql/`.
- [ ] D4 `TODO` **Backboard memory.** Write episodic memories (object seen at place/time + snapshot) and answer "where are my glasses?" with citations. owns: `backend/memory.py`.
- [ ] D5 `TODO` **Gemini NLU upgrade.** Replace the keyword `nlu.py` with Gemini function-calling restricted to the `TASKS` enum, keeping the keyword fallback. owns: `backend/nlu.py`.
- [ ] D6 `TODO` **MongoDB Atlas** activity/event store as an alternative `store.py` backend (only if we pick that track over Tiger).
- [ ] D7 `TODO` **Vultr deploy.** Dockerfile + one-command deploy of the dashboard + policy server to a Vultr GPU/VM. owns: `deploy/`.
- [ ] D8 `TODO` **GoDaddy domain.** Register a domain (code MLHDH2684) and point it at the Vultr box. Human task, the agent writes the steps.
- [ ] D9 `TODO` P3 **Solana devnet receipts.** Memo tx per completed task (community kitchen proof-of-impact). Only if the story fits.

- [ ] D10 `TODO` P1 **VEYZL AI safety audit.** Connect the GitHub repo, run audits on PRs (EU AI Act, NIST AI RMF, ISO 42001), fix at least 2 findings in the code (e.g. human-confirm gate, audit log, disclaimer), and write up "how findings changed the build" in `docs/veyzl.md`. Fits the medical-device safety story.
- [x] D11 `DONE` (startup/01-04 + startup-case.html) P2 **Startup framing.** One-page market + business model for SideShift / Commit Fellowship / DubHacks NEXT (scrub tech shortage, training-lab first customer). owns: `docs/startup.md`.

## Lane E: Pitch, docs, submission (P1, haiku)
- [ ] E1 `TODO` **Devpost draft** (due Sat 10:30 PM): overview, tracks, built-with. owns: `docs/devpost.md`.
- [ ] E2 `TODO` **Architecture diagram** SVG (camera -> perception -> planner -> safety gate -> policy -> SO-101, plus side services).
- [ ] E3 `TODO` **Demo video shot list + script**, 2:30 max, with a "judge moves the object" shot.
- [ ] E4 `TODO` **Q&A prep.** 25 likely judge questions with crisp answers (success rate, data count, why not IK, safety).
- [ ] E5 `TODO` **README** with run instructions, mock mode and a hardware checklist.
- [ ] E6 `TODO` **DEV.to post draft** (DEV Writing Challenge, after the event).

## Lane F: Quality (continuous)
- [ ] F1 `TODO` **Test expansion.** Every endpoint in CONTRACT.md has a test, including 409/422 paths and the STOP latch.
- [ ] F2 `TODO` **Chaos test.** Random WS disconnects, slow policy, camera dropout, perception 500s. The system degrades safely.
- [ ] F3 `TODO` **Load/latency.** Measure detect -> plan -> first motion latency and show it in Mission Control.
- [ ] F4 `TODO` **Code review pass** every ~4h over the last changes, filing findings as TODOs.

## Lane Q: Prototype QA (haiku/sonnet, quick wins)
Smoke test: `node <scratch>/smoke.mjs` style check (load each prototype in headless Chrome, look for page errors, horizontal scroll at 390px).
- [ ] Q1 `TODO` `08-sous-chef-voice.html` shows "Arm stopped and locked" right on load. It should start unlatched.
- [ ] Q2 `TODO` `14-task-composer.html`: 25px horizontal scroll at 390px, and the graph canvas looks empty at first paint. Auto-run the first preset.
- [ ] Q3 `TODO` Click-through every prototype's main scenario (agents only syntax-checked most of them) and fix what breaks.
- [ ] Q4 `TODO` After any prototype changes, run `python3 prototypes/build_gallery.py` to refresh the gallery index.

## Lane P: More prototypes (whenever the queue is low)
Ideas not yet prototyped. One HTML file each in `prototypes/`, same rules as `prototypes/BRIEF.md`:
- (building: 18-pill-check) P1 Pill organizer with weekly slots and OCR on the bottle label vs the prescription
- (building: 19-under-sink-sorter) P2 Under-sink chemical sorter (OCR hazard labels, keep bleach away from ammonia)
- P3 Tremor-assist stabilizer view (EMG/IMU signal -> arm holds the bowl steady)
- (building: 20-telepresence) P4 Remote telepresence: a family member drives the arm from their phone with latency-safe waypoint control
- (building: 23-skill-store) P5 Robot "skill store": share fine-tuned skills between households, ratings and success stats
- P6 Kitchen inventory AR view: tap an item in the camera to see what it is, its expiry and recipes
- P7 Night mode / sleep companion: water bottle fetch with dim UI and a soft voice
- (building: 21-care-fleet) P8 Multi-robot fleet view for a care home (5 arms, alerts, staff assignment)
- (building: 22-train-your-bot) P9 Gamified "train your robot" for kids: give demos, watch it learn, earn badges
- P10 Ops screen for the arm-sharing schedule across all 20 teams at the event (could even be offered to organizers)
