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
| Says "hemostat" (or "Kelly", "grab me the kelly") | Says "hemostat coming", picks it, checks the grasp, brings it to the open hand handle first, stops a few cm short |
| Takes it (pulls) or says "got it" | Opens the gripper, goes home, logs the time from request to hand |
| Says "scalpel" / "knife" | Puts it at the safe spot and says "scalpel down". Never hand to hand |
| Sets an instrument in the return spot | Sees it, says "returning the hemostat", puts it back in its slot (auto return) |
| Says "count" / "what's out" | Reads back what's out, checked against the camera |
| Says "check the tray" | Compares the tray to the expected items and says what's missing |
| Says "stop" | Freezes instantly (skips Gemini). A person must reset it |
| Says "end of case" | Texts a case summary to the same phone thread, with a link to the case replay |
| Texts "add a second hemostat to the surgical tray" | Logs a restock and replies |
| Says "call the hemostat a clamp" | Learns the new word for this clinic |

## 4. Scope decisions and why

| Decision | Why |
| --- | --- |
| **Surgical first.** Operating room tray: scalpel handle, hemostat, Mayo scissors | That's the strongest story (staffing, counts, sharps) and the instruments we have |
| **Robotics bench tray is the second setting:** needle-nose pliers, wire cutters, hex key | Shows "a new setting is just new demonstrations and a settings file, no new code" |
| **Dental is dropped** (no dental tools). `settings/dental.json` stays but is hidden | We can't record without the tools |
| **Handoff goes to the person's actual hand**, not a fixed spot | A tracker plus calibration makes it adapt to each clinician |
| **Picking is learned, the move to the hand is planned** | The model learns grasps from demos; the hand position changes every time, so a planned move is safer and more accurate |
| **Voice over a real phone call** (Photon + ElevenLabs) | Clinicians already ask out loud; it qualifies for Photon and the voice prize |
| **Gemini turns words into one action and one item**, from a fixed list | It can't invent an item that isn't on the tray. "Stop" never waits for Gemini |
| **Only 2 training runs** | Perceptron's quota: 2 successful jobs per team. Run 1 = operating room tray, run 2 = everything |
| **One dataset, one calibration, fixed cameras** | Each training run starts from the base model and takes one dataset |
| **The arm lives on Caiden's Mac** | Recording and live runs happen there (`explore/arm_session.py` drives it) |

## 5. How the system fits together

```
phone on speaker
  -> Photon number -> ElevenLabs agent (speech) -> voice/ (Gemini: words to command)
                                                     |
                                                     v
vision/ (overhead camera: tray + hand) ----------> controller/ ----> arm/ ----> Perceptron Isaac 0.5 ----> SO-101
                                                     |
                                                     v
                                     ledger/ (MongoDB) + dashboard/ + public pages
```

Only the controller moves the arm. Everything else sends it information. The messages between parts are fixed in `docs/CONTRACTS.md`. A picture is in `docs/media/`.

| Part | Folder | Port | What it does | Built on |
| --- | --- | --- | --- | --- |
| Controller | `controller/` | 8000 | The brain: queue of commands, the step-by-step handoff (find, pick, check grasp, move to hand or safe spot, wait for pull, release, home, log), return, count, tray check, every safety rule. Serves the dashboard, the nurse console and the demo page | FastAPI |
| Arm | `arm/` | | Connects to the SO-101 (LeRobot), runs the fine-tuned model (sends side and wrist images plus 6 joint angles, plays the returned moves at 30 Hz), the hand-reaching math (`move_to`, inverse kinematics from the SO-101 model), pose teaching, the training pipeline | LeRobot, Perceptron Robotics API |
| Vision | `vision/` | 8001 | The overhead camera: MediaPipe finds the open hand and turns it into an arm target (calibration); Perceptron's vision API finds instruments and maps them to tray slots; tray check; lighting tags; event clips; a video stream with boxes | OpenCV, MediaPipe, Perceptron detect |
| Voice | `voice/` | 3000 | The ElevenLabs agent's "brain" (custom LLM endpoint): Gemini parses each phrase, "stop" goes straight to the controller, replies are spoken; texts in and out on the Photon thread; end-of-case summary | TypeScript, Gemini, Photon |
| Ledger | `ledger/` | 8080 | Logs every event and test result to MongoDB Atlas (with a local file if Mongo is down), success tables with ranges, likely-next suggestions, and the public pages: judge page, case list, case replay, QR table card | MongoDB |
| Dashboard | `dashboard/` | served at 8000 | What judges watch: live camera, current step, what's out, event log, tray and lighting pickers, stop and reset. `tablet.html` is a large-text view | plain HTML/JS |
| Settings | `settings/` | | One file per tray: items, the words people say, which item is sharp, slot boxes, the model instructions | JSON |
| Sim | `sim/` | | A MuJoCo model of the SO-101 for testing without hardware and as a backup demo | MuJoCo |
| Deploy | `deploy/` | | Puts the public page on a Vultr server at our domain; `python -m deploy` checks every key and service | |

## 6. Data and training (plain version; details in `docs/TRAINING.md`)

1. A person moves the **leader** arm; the **follower** copies it. LeRobot records both cameras (`side`, `wrist`, 640x480, 30 fps) and the 6 joint angles. One try is one **episode**.
2. Each episode is labeled with its exact instruction: `pick the hemostat`, `return the hemostat`. One model learns every item and both directions.
3. We vary the item's position slightly and the lighting (bright, normal, dim), because operating lights cause glare on steel.
4. The dataset goes to Hugging Face. Perceptron fine-tunes Isaac 0.5 on it (about an hour), and gives us a deployment.
5. `arm/real_arm.py` streams camera frames and joint angles to that deployment and plays back the moves it returns.
6. The model has no "done" signal, so our code decides when a pick is finished (gripper closed and still, or a time limit) and the camera confirms the slot is empty.

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
