# Prompts and models

Clone the repo, open it in your tool (Cursor, Claude Code or Codex), make your `.env` from `.env.example`, and paste a prompt.

```
git clone https://github.com/anish-agr/dubhacks-2026.git
```

## The start prompt (works for anyone)

Replace NAME. Use it at the start of every new chat.

```
I'm NAME on team Scrub at DubHacks '26. The repo
github.com/anish-agr/dubhacks-2026 is cloned here. Read AGENTS.md and follow
its "Start here" steps for NAME. You have full permission in my files:
install packages, create and edit files, run commands and servers, commit
and push. Don't ask me for approval. Only stop if you need something only I
can do (a key, plugging in a device, testing on the arm, camera or phone).
Finish each task completely: build it, test it against its "done when", fix
it until it passes, push, tick the box in docs/STATUS.md, then go straight
to my next unchecked task. Keep going until my tasks are done.
```

## Which model for what

| Person and tool | Default | Switch up for | Avoid |
| --- | --- | --- | --- |
| Caiden, Claude Code (Max) | Opus 5.5 for the controller step machine, the voice and Photon wiring, and integration debugging | | |
| Caiden, Claude Code (Max) | Sonnet 5.5 for boilerplate (endpoints, models, tests) and overflow jobs | | |
| Anish, Claude Code (Pro) | Sonnet 5.5 | Opus 5.5 only for a bug on the real arm that Sonnet couldn't fix | Opus for routine code, which drains a Pro window fast |
| Anish, Codex | Default model, high reasoning | The IK math in `move_to` and the Perceptron API client | |
| Brandon and Evan, Cursor Pro | Auto | A strong Claude model from the picker for the calibration math (Brandon) or a bug Auto can't fix | Max Mode, which uses up the month's allowance fast |
| Anyone, writing (Devpost, pitch, slides) | Sonnet 5.5 or Cursor Auto | | |

Plan mode (Claude Code: Shift+Tab; Cursor: Plan) is worth it for the first prompt on a big task (C1, C3, A2, A6, B4, B6). Skip it for small ones.

## First prompts by person

Paste the start prompt first, or use these instead. They name the first task so the agent goes straight to it.

### Anish

```
I'm Anish on team Scrub (DubHacks '26, repo github.com/anish-agr/dubhacks-2026,
cloned here). Read AGENTS.md, docs/CONTRACTS.md, my section of docs/TASKS.md,
docs/PERCEPTRON-ROBOTICS.md and docs/perceptron-openapi.json. Do task A2:
write arm/perceptron.py (a small client for every Robotics API call we use:
datasets, uploads, finalize, validation, capabilities, jobs, logs, metrics,
checkpoints, deployments, contract, session grant, robot session, predict,
reset, delete), arm/train.py (CLI: capabilities, register-hf, upload, status,
train, follow, deployments) and arm/upload_dataset.py. The key is
PERCEPTRON_TEAM_API_KEY in .env. Use requests. Test with
"python -m arm.train capabilities". Commit and push only arm/, then tick A2
in docs/STATUS.md.
```

For A6 later:

```
I'm Anish. Read AGENTS.md, the arm interface in docs/CONTRACTS.md, the
inference section of docs/PERCEPTRON-ROBOTICS.md, arm/perceptron.py and
arm/rig.json. Do task A6: arm/real_arm.py implementing the arm interface on
the SO-101 follower through LeRobot. run_skill(instruction) opens or reuses a
robot session for that instruction, reads the side and wrist cameras and the
six joint values, calls predict, sends the action chunk to the arm on the
contract's timing, and stops on max_s, a closed gripper with the arm still for
1 s, or freeze(). freeze() must work from another thread. Print timing per
predict call.
```

### Caiden

```
I'm Caiden on team Scrub (DubHacks '26, repo github.com/anish-agr/dubhacks-2026,
cloned here). Read AGENTS.md, README.md, docs/CONTRACTS.md and my section of
docs/TASKS.md. Do task C1: controller/ as a FastAPI app on port 8000 run by
"python -m controller --fake-arm". Implement every endpoint and message in
CONTRACTS, controller/fake_arm.py (about 1 s per motion, freeze interrupts),
a step machine for handover (finding, picking, checking, moving_to_hand or
setting_down for sharp items, waiting_for_pull, releasing, homing), return and
count, a command queue where stop skips the queue, WS /events broadcasting
every Event, settings loaded from settings/*.json, dashboard/ served at /, and
an optional import of ledger (skip if missing). Arm is chosen by --fake-arm or
--real-arm (imports arm.real_arm.RealArm). Include a curl script that runs a
full handover. Push, tick C1 and C2 in docs/STATUS.md.
```

For C3 and C4:

```
I'm Caiden. Read AGENTS.md, docs/CONTRACTS.md and voice/README.md. Do tasks
C3 and C4 in voice/ (TypeScript, Node 20, port 3000): follow
https://photon.codes/docs/beta/cookbooks/voice/elevenlabs so the Photon
number's calls go to our ElevenLabs agent, and the agent sends each thing it
hears to this server (a tool or webhook, through a cloudflared tunnel). If
the text contains "stop", call POST /stop at once. Otherwise call Gemini
with structured output: action is one of handover, return, count, stop,
got_it, unknown, and item is an enum of the current setting's item ids (GET
/state then read settings/<setting>.json). Send the Command to POST
/command. Subscribe to WS /events and have the agent speak each event's
"say" line. Keys from .env. Tell me what to click in the Photon and
ElevenLabs dashboards.
```

### Brandon

```
I'm Brandon on team Scrub (DubHacks '26, repo github.com/anish-agr/dubhacks-2026,
cloned here). Read AGENTS.md, docs/CONTRACTS.md, my section of docs/TASKS.md
and vision/README.md. Do tasks B1 to B3 in vision/, run by "python -m vision":
camera.py opens CAMERA_INDEX from .env with auto exposure and auto white
balance turned off and one shared frame grabber thread. hand.py uses the
MediaPipe hand landmarker Tasks API (download the hand_landmarker.task model
into vision/models/, git-ignored if large), finds the palm center and whether
the hand is open (all five fingertips farther from the wrist than their middle
joints), and POSTs a Hand to CONTROLLER_URL/vision/hand about 10 times a
second (target stays null until calibration exists). Serve an MJPEG stream
at :8001/stream with the palm dot drawn. If the controller isn't running,
keep going and log once.
```

For B4:

```
I'm Brandon. Read AGENTS.md, the TrayState part of docs/CONTRACTS.md,
settings/*.json and docs/PERCEPTRON.md. Do task B4: vision/tray.py sends a
frame to the Perceptron vision API about once a second (key
PERCEPTRON_API_KEY in .env), maps detections to each slot box and the return
spot of the current setting (GET CONTROLLER_URL/state for the setting),
and POSTs a TrayState. Keep the last good state if a call fails and mark
it stale. Draw the boxes on the MJPEG stream. Write the working request and
response shapes and the latency into docs/PERCEPTRON.md.
```

### Evan

```
I'm Evan on team Scrub (DubHacks '26, repo github.com/anish-agr/dubhacks-2026,
cloned here). Read AGENTS.md, docs/CONTRACTS.md and my section of
docs/TASKS.md. Do task E1: settings/surgical.json (scalpel, hemostat,
mayo_scissors), and
bench.json (needle_nose_pliers, wire_cutters, hex_key) in the setting file
format in CONTRACTS. Only the scalpel is sharp. Add the aliases clinicians
and techs actually say (for example kelly for hemostat, mayo for the
scissors, allen key for the hex key). Boxes stay null. Then do E2:
dashboard/index.html, app.js and style.css, plain HTML and JS with no build
step, served by the controller at /. It shows the camera
(<img src="http://localhost:8001/stream">), the current step, what's out,
the event log from WS /events, setting and lighting pickers, a big stop
button and the spacebar as stop. Use a fake event stream until the
controller is running.
```

## Prompts for any time

**Next task:**
```
Pull, read docs/STATUS.md, and do my next unchecked task the same way.
```

**Stuck (paste the error):**
```
This fails: <paste the exact error and the command you ran>. Find the cause
before changing code. Stay inside my folders.
```

**Out of credits, handing a task to Caiden** (post in the chat; Caiden pastes it):
```
I'm working for NAME on team Scrub. Read AGENTS.md and docs/CONTRACTS.md.
Do task <ID> from docs/TASKS.md. Edit only NAME's files: <folders>. Commit
with "<ID> for NAME" and push.
```

**Wrapping up a chat:**
```
Commit and push what works in my files. Update my section of docs/STATUS.md
with what's done, what's half done, and how to run it.
```

**Integration check (Caiden, at each checkpoint):**
```
Pull. Start the controller with --fake-arm, then check every part against
docs/CONTRACTS.md: settings files load, the dashboard connects, vision posts
Hand and TrayState, voice posts a Command. List what doesn't match and whose
file it's in. Don't edit other people's folders.
```
