# Devpost text

Owner: Evan. Ready to paste before 10:30 PM Saturday. Plain words. No buzzwords. No em dashes.

Paste into the Devpost form from **Project name** through **Built with**. Leave this note out. Leave the video sections out of the form. Evan submits the draft by 10:00 PM Saturday (see `team/PLAN.md`).

Measured arm numbers stay as `[measured]` until the tests are logged on Sunday morning. Do not invent a success rate.

## Project name

Scrub

## Tagline

A robot arm that passes instruments when you ask out loud.

## Tracks to tick, and where each one is used

- **Community Kitchen (title).** The job itself: a clinician asks, and Scrub passes the instrument so they do not turn away from the patient to search the tray.
- **Perceptron Robotics (pending).** The SO-101 arm and the fine-tune pipeline work offline and the team key is accepted. There is no deployment yet. Claim "fine-tuned" and live inference only after training run 1 finishes and a model-driven pick is recorded (`docs/INTEGRATION.md`, Track claims).
- **Perceptron Perception.** Their vision API on the overhead camera. It says which slots are full and whether the return spot holds an instrument. That drives the grasp check, the automatic return, the count check and "check the tray".
- **Photon (pending).** Designed: a case over a call to a Photon number, with texts in (restock, what's out) and the end-of-case summary out on the same thread. The phone line is not set up and no real text has gone out. Claim it only after one does.
- **DubHacks NEXT.** The business case (`docs/BUSINESS.md`): surgery centers first, a monthly fee per operating room, with the break-even worked out.
- **MLH Gemini API.** Turns what was said into one command from the current tray, with structured output. It cannot invent an instrument that is not on the tray. It also writes the end-of-case summary and reads texts.
- **MLH MongoDB Atlas.** Stores every event and every measured trial. The success tables are read from there.
- **MLH Vultr.** The public judge page runs on a Vultr server.
- **MLH Commit Fellowship.** The form Anish sends after we submit.
- **MLH DEV writing.** A post after the event (draft at the end of this file).

## Inspiration

Surgeons work with a scrub tech who hands them instruments and keeps the count. Hospitals cannot hire enough of them. A surgical tech job takes about 120 days to fill ([Periop Leader, 2024](https://www.periopleader.com/survey-staffing-woes-ease-slightly-but-challenges-remain/)). When nobody is there, the surgeon looks away from the patient, puts down what they are holding, and searches the tray.

The count and the sharps matter too. One Mayo Clinic study found an item left inside a patient about once in 5,500 operations, and most of those counts had been called correct ([Cima et al., 2008](https://pubmed.ncbi.nlm.nih.gov/18589366/)). US hospital staff have about 385,000 needle and sharps injuries a year ([CDC](https://www.cdc.gov/sharpssafety/)), most often while passing them.

## What it does

Scrub is a robot arm that passes instruments by voice. A clinician asks out loud. Scrub picks the instrument from the tray and brings it to an open hand, handle first. It lets go when the person pulls, or when they say "got it."

A scalpel never goes hand to hand. Scrub sets it in a fixed safe spot and says "scalpel down." That follows the operating-room habit of passing sharps one at a time, in a called-out spot.

When an instrument is done, it goes in the return spot. After about two seconds Scrub puts it back in its slot on its own. Say "count" and Scrub reads back what is still out, checked against the camera. Say "check the tray" before a case and it says what is missing. Say "end of case" and a summary arrives by text.

The demo is the operating room tray first. The robotics bench is the second tray. It uses the same code, new demonstrations and a different settings file.

- Operating room: scalpel handle, hemostat, Mayo scissors
- Robotics bench: needle-nose pliers, wire cutters, hex key

Plain names work. So do the names people actually say. "Kelly" is the hemostat. "Mayo" is the scissors. "Allen key" is the hex key.

## How we built it

The designed path is a phone on speaker calling a Photon number, with an ElevenLabs agent turning the speech into text. The phone number is pending, so the demo also takes typed lines and the browser. Gemini turns that text into one command from the current tray. The word "stop" never waits on Gemini. It freezes the arm immediately.

A camera watches the tray and the clinician's hand. MediaPipe finds the open hand. Perceptron's vision model says which slots are full. The Isaac 0.5 model, to be fine-tuned on our own demonstrations, is meant to run the pick and the return on an SO-101 arm. The demonstrations are being recorded and no model is deployed yet. Until one is, taught waypoint skills do the picks and the events say which source moved the arm.

Only the controller moves the arm. It checks the grasp, sends sharps to the safe spot, and stops on the word "stop", the spacebar, or the button on the dashboard. After a stop, the arm stays frozen until someone presses reset.

MongoDB Atlas stores every event and every measured trial. If Atlas is down, the same events sit in a local file and upload when the connection comes back. The dashboard shows the live camera, the current step, the current lighting, what is out, the handoff time, and the success tables. Each rate shows the number of tries and a 95% range. If the tray camera is reusing an old reading, the page says "vision stale."

The public page (hosted for judges) has the count, those tables, and a link to each case. A case page lists every event, the handoff times, and what was out at each moment. A series page shows handoffs by minute and a memory page answers what usually comes next. Both read the local ledger. A tablet view across the room shows the step, what is out, and stop and reset in large type. The dashboard can also name the instrument that usually comes next. That line is only a suggestion. The arm does not move until someone asks.

## Screenshots

Taken from a fake-arm case, with the overhead camera stand-in running. The real arm photos replace nothing here until Sunday. They are extra.

![Dashboard during a case](media/dashboard.png)

![Tablet view](media/tablet.png)

![One case, played back](media/case.png)

![Public page for judges](media/public.png)

## Challenges

Operating lights are bright, and steel instruments throw glare. Every item is recorded and tested in bright, normal, and dim light so the result is a table, not a guess. The range next to each rate is there so a small number of tries does not look more certain than it is.

Handing someone a scalpel is the wrong habit, so that one item has its own path. The arm, the camera, the voice agent, and the log are separate programs. They share a short list of messages, which is what let four people build them at the same time.

The phone number, the overhead camera, and the arm setup still need a person in the room. The software path can be run without them, on a fake arm.

## Accomplishments

Working in the repo as of Saturday night:

- The operating room tray and the robotics bench tray, on one system. Only the scalpel is marked sharp.
- A live dashboard. A handover on the fake arm updates the step, the log, what is out, and the seconds from request to hand. Stop and reset are on the page. Spacebar stops the arm.
- A ledger of every event, success tables with a 95% range, and a public judge page.
- A case replay, a tablet view, and a "likely next" line that does not move the arm.
- Typed speech ("grab me the kelly") becomes a hemostat handover through Gemini, through the same endpoint the ElevenLabs agent calls. A full case on a real Photon call: [measured].
- The camera locks exposure, finds an open hand, and posts the tray.

The real-arm numbers go here on Sunday morning:

- Request to hand, median: [measured] seconds
- Success rate by item: [measured]
- Success rate in bright light: [measured]
- Success rate in normal light: [measured]
- Success rate in dim light: [measured]
- Minutes to add the bench tray: [measured]

## What we learned

The useful version of this job is small. Pass the instrument, put it back, keep the count, and do not hand someone a sharp. Extra names are a list on the tray file. Stop has to be its own path, because a round trip to a model is too slow when someone says stop.

## What's next

Surgery centers are the first customers, as a monthly fee per operating room. At about $36 a minute of operating room time ([JAMA Surgery, 2018](https://jamanetwork.com/journals/jamasurgery/fullarticle/2673385)), Scrub breaks even if it saves a room about 22 minutes a month. We have not measured that yet, so a pilot comes first. Scrub is a research prototype with no clinical claims, so training labs come before live cases. A medical-grade arm is the later version of this weekend's arm. After that, Scrub can hand over the next instrument before it is asked for, using the step of the procedure.

## Built with

Python, FastAPI, HTML, JavaScript, MongoDB Atlas, Gemini, ElevenLabs, Photon (texts; phone line pending), Perceptron (vision API; Isaac 0.5 fine-tune pending), MediaPipe, LeRobot, SO-101, Vultr

## Video shot list (after the arm works, not pasted into the Devpost form)

Edit a 2 to 3 minute video from these shots once the real arm can hand an instrument over. Record each one a few times and keep the cleanest take. The spoken script is in `team/PITCH.md`. Phone audio has to be clear: put a second phone or the laptop mic next to the speakerphone.

- [ ] 1. Title card, about 5 seconds.
- [ ] 2. Brandon's hands are busy. He says "hemostat" to the speakerphone. Close-up of the pick, the hand receiving it handle first, and the gripper opening when he pulls. Dashboard shows the handoff seconds.
- [ ] 3. "Scalpel." The scalpel goes to the safe spot. Scrub says "scalpel down." It does not go to the hand.
- [ ] 4. Return. Hemostat goes in the return spot. Scrub says "returning the hemostat" and puts it back in its slot.
- [ ] 5. Evan turns the lamp on. Glare shows on the steel. A handoff still succeeds. Cut to the lighting table on the dashboard.
- [ ] 6. Swap to the robotics bench tray and ask for the pliers. Same arm, no new code.
- [ ] 7. "Count." The voice reads back what is out. Then the summary text arrives on the phone.
- [ ] 8. Dashboard: the live camera, what is out, and the success tables. Hold long enough to read the numbers and the ranges.
- [ ] 9. Close on the team and the arm.

Separate from this edit: Anish records the Perceptron arm video as one unedited roll of picks and returns, with the success table at the end. That file is for the robotics track, not this 2 to 3 minute cut.

Before upload, replace the `[measured]` slots above with the numbers on the dashboard tables. Upload the video and submit the final Devpost by Sun 9:30 AM.

## Video edit plan (after the arm works)

Cut one 2 minute film, 16:9, 1080p. No music. Room sound only, with the speakerphone loud enough to hear the ask and the reply. Do not include a failed take, or a shot of the laptop setup. The fake-arm screenshots stay in the written Devpost. This film is the real arm.

Assembly, in this order. Times are the finished cut, not the length of the raw take.

| Time | Picture | Sound | On-screen text |
| --- | --- | --- | --- |
| 0:00 to 0:05 | Arm at rest over the operating room tray. | Quiet room. | Scrub. A robot arm that passes instruments when you ask. |
| 0:05 to 0:28 | Brandon's hands stay on the work. He asks for a hemostat. Cut to the pick, then the handle landing in the open hand, then the gripper letting go when he pulls. | The ask, then "hemostat coming." | Last 3 seconds: the dashboard handoff seconds. |
| 0:28 to 0:42 | Ask for the scalpel. It goes to the safe spot. It does not go to the hand. | "Scalpel down." | Safe spot. |
| 0:42 to 0:58 | Hemostat in the return spot. The arm puts it back in its slot. | "Returning the hemostat." | Return. |
| 0:58 to 1:12 | Lamp on. Glare on the steel. A handoff still finishes. Cut to the lighting table. | The ask only. | Bright, normal, dim. |
| 1:12 to 1:28 | Switch the picker to the robotics bench. Ask for the pliers. Same arm. | The ask, then the reply. | Same code. Different tray. |
| 1:28 to 1:44 | Ask for a count. Then the phone shows the summary text. | The spoken count. | What is still out. |
| 1:44 to 1:56 | Hold the dashboard: camera, what is out, success tables with the ranges. | None. | Long enough to read the numbers. |
| 1:56 to 2:05 | Team and the arm. | None. | Anish, Caiden, Brandon, Evan. DubHacks '26. |

Edit notes:

- Cut on the motion, not on a pause. If a take hesitates, use the next take of that shot.
- Keep one wide shot and one close-up for the hemostat handoff. The close-up has to show the handle, not the tip, arriving first.
- The scalpel shot is the proof it does not go hand to hand. Do not shorten it into the hemostat sequence.
- The lighting shot needs the glare visible before the cut to the table. If the glare is not in frame, reshoot that one.
- The bench shot is one ask. Do not explain the settings file on camera.
- The count and the phone text are one sequence. If the text is late, hold the phone until it arrives, then cut.
- Captions only where the table above says so. White text, bottom left, no animation.
- Export H.264, 1080p, 30 fps, stereo from the mic that was next to the speakerphone.
- Separate file, not part of this cut: Anish's unedited roll of picks and returns for the robotics track, with the success table at the end.

## DEV post

This section is the DEV.to post for the MLH DEV writing track. It is not part of the Devpost form. Publish steps are in `team/ACCOUNTS-TODO.md`. Fill every `[measured]` from the dashboard tables first, or cut the sentence.

Post title: Building Scrub: a robot arm that passes surgical instruments by voice

By Team Scrub (Anish, Caiden, Brandon, Evan) at DubHacks '26.

### The problem

Surgeons work with a scrub tech who hands them instruments and keeps the count. Hospitals can't hire enough of them. A surgical tech job takes about 120 days to fill ([Periop Leader, 2024](https://www.periopleader.com/survey-staffing-woes-ease-slightly-but-challenges-remain/)).

When nobody is there to pass, the surgeon looks away from the patient, puts down what they're holding, and searches the tray.

The count matters. One Mayo Clinic study found an item left inside a patient about once in 5,500 operations, and most of those counts had been called correct ([Cima et al., 2008](https://pubmed.ncbi.nlm.nih.gov/18589366/)). Sharps matter too. US hospital staff have about 385,000 needle and sharps injuries a year ([CDC](https://www.cdc.gov/sharpssafety/)).

Scrub is our weekend answer. You ask for an instrument out loud. A small open-source arm picks it from the tray, brings it to your open hand handle first, and lets go when you pull. Scalpels go to a safe spot instead. Used tools go back to their slots, and Scrub keeps the count.

### How it fits together

Five parts, built in parallel by four people, talking over a short list of HTTP and WebSocket messages:

1. **Voice.** A phone on speaker calls a Photon number (the number is pending). An ElevenLabs agent hears the words. Its language model is our voice server, where Gemini turns them into one action and one item from the current tray. Clinic words work: "Kelly" is the hemostat, "Mayo" is the scissors. "Stop" skips Gemini and goes straight to the controller.
2. **Vision.** One overhead camera. MediaPipe finds the open hand about 10 times a second. Perceptron's vision API finds the instruments and says which slots are full.
3. **Arm.** An SO-101 is meant to run Perceptron's Isaac 0.5, fine-tuned on our own demonstrations, for the pick and the return. Until the model is deployed, taught waypoint skills do the picks, and every event says which one moved the arm. The move to the hand is planned from the camera, because the hand is somewhere new every time.
4. **Controller.** The only thing that moves the arm. It checks every grasp, sends sharps to the safe spot, and freezes on "stop".
5. **Ledger and dashboard.** Every event goes to MongoDB Atlas. The dashboard shows the step, what's out, the handoff time and the success tables.

### Teaching the arm

Hard-coded paths break when a tool sits a little off or the light changes. So we taught the arm from demonstrations.

- A person moves a leader arm. The follower copies it. LeRobot records two cameras (side and wrist) and six joint angles at 30 frames a second.
- Each episode has its exact instruction, like `pick the hemostat` or `return the hemostat`. One model learns every item and both directions.
- The plan: 20 picks and 10 returns for each operating room instrument, 15 picks and 10 returns for each bench tool, across bright, normal and dim light. We recorded [measured] clean episodes.
- The bench tray (needle-nose pliers, wire cutters, hex key) needed new demonstrations and one settings file. No code change. It took [measured] minutes.

### Glare

Operating lights are bright and steel throws glare. With auto exposure, the camera kept changing its gain and the tray went dark around a reflection.

1. At startup we lock exposure and white balance, so a lamp no longer makes the picture flicker.
2. The vision service tags every frame bright, normal or dim from its brightness, and every logged trial carries that tag.
3. We test in all three. Results: bright [measured]%, normal [measured]%, dim [measured]%. Median request to hand: [measured] seconds.

### Safety rules we built in

1. **Sharps never go hand to hand.** Operating rooms pass sharps hands-free for a reason. Scrub sets the scalpel on a fixed safe spot and says "scalpel down."
2. **Every grasp is checked twice.** The gripper position shows whether the jaws closed on something. The camera shows whether the slot is now empty. A miss is retried once, then reported out loud.
3. **Stop is its own path and it latches.** "Stop", the spacebar or the stop button freezes the arm in [measured] ms. It stays frozen until a person resets it.
4. **The hand decides.** The arm slows near the hand. If the hand is lost or something crosses the path, it holds still and says so.
5. **Let go on a pull.** The arm waits with the tool. When you pull, the gripper feels the load change and opens. You can also say "got it."

### What we learned

The useful version of this job is small. Pass the instrument, put it back, keep the count, and never hand someone a blade. Stop has to be its own path, because a round trip to a model is too slow when someone says stop.

### What's next

Surgery centers first, in training labs before any patient. A monthly fee per operating room. At about $36 a minute of operating room time ([JAMA Surgery, 2018](https://jamanetwork.com/journals/jamasurgery/fullarticle/2673385)), Scrub breaks even if it saves a room about 22 minutes a month, and a pilot has to show that. It helps scrub techs. It doesn't replace them. Scrub is a research prototype with no clinical claims.

The code, the recording tools and the tests are open source in our repo.
