# Devpost text

Owner: Evan. Ready to paste before 10:30 PM Saturday. Plain words. No buzzwords. No em dashes.

Paste into the Devpost form from **Project name** through **Built with**. Leave this note out. Leave the video sections out of the form. Evan submits the draft by 10:00 PM Saturday (see `docs/PLAN.md`).

Measured arm numbers stay as `[measured]` until the tests are logged on Sunday morning. Do not invent a success rate.

## Project name

Scrub

## Tagline

A robot arm that passes instruments when you ask out loud.

## Tracks to tick, and where each one is used

- **Community Kitchen (title).** The job itself: a clinician asks, and Scrub passes the instrument so they do not turn away from the patient to search the tray.
- **Perceptron Robotics.** The SO-101 arm. A fine-tuned Isaac 0.5 model runs "pick the hemostat" and "return the hemostat" from our own demonstrations.
- **Perceptron Perception.** Their vision API on the overhead camera. It says which slots are full and whether the return spot holds an instrument. That drives the grasp check, the automatic return, the count check and "check the tray".
- **Photon (including best voice agent).** The whole case runs over a call to the Photon number. Texts in (restock, what's out) and the end-of-case summary out use the same thread.
- **DubHacks NEXT.** The business case in `docs/NEXT.md`: surgery centers first, a monthly fee per operating room, with the break-even worked out.
- **MLH Gemini API.** Turns what was said into one command from the current tray, with structured output. It cannot invent an instrument that is not on the tray. It also writes the end-of-case summary and reads texts.
- **MLH MongoDB Atlas.** Stores every event and every measured trial. The success tables are read from there.
- **MLH Vultr.** The public judge page runs on a Vultr server.
- **MLH GoDaddy Registry.** Our domain points at that page. It is on the QR code at the table.
- **MLH Commit Fellowship.** The form Anish sends after we submit.
- **MLH DEV writing.** A post after the event (draft in `docs/DEV-POST.md`).

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

A phone on speaker calls a Photon number. ElevenLabs turns the speech into text. Gemini turns that text into one command from the current tray. The word "stop" never waits on Gemini. It freezes the arm immediately.

A camera watches the tray and the clinician's hand. MediaPipe finds the open hand. Perceptron's vision model says which slots are full. The Isaac 0.5 model, trained on our own demonstrations, runs the pick and the return on an SO-101 arm. Those demonstrations are being recorded this weekend.

Only the controller moves the arm. It checks the grasp, sends sharps to the safe spot, and stops on the word "stop", the spacebar, or the button on the dashboard. After a stop, the arm stays frozen until someone presses reset.

MongoDB Atlas stores every event and every measured trial. If Atlas is down, the same events sit in a local file and upload when the connection comes back. The dashboard shows the live camera, the current step, the current lighting, what is out, the handoff time, and the success tables. Each rate shows the number of tries and a 95% range. If the tray camera is reusing an old reading, the page says "vision stale."

The public page (hosted for judges) has the count, those tables, and a link to each case. A case page lists every event, the handoff times, and what was out at each moment. A tablet view across the room shows the step, what is out, and stop and reset in large type. The dashboard can also name the instrument that usually comes next. That line is only a suggestion. The arm does not move until someone asks.

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

Python, FastAPI, HTML, JavaScript, MongoDB Atlas, Gemini, ElevenLabs, Photon, Perceptron (Isaac 0.5 and the vision API), MediaPipe, LeRobot, SO-101, Vultr, GoDaddy

## Video shot list (after the arm works, not pasted into the Devpost form)

Edit a 2 to 3 minute video from these shots once the real arm can hand an instrument over. Record each one a few times and keep the cleanest take. The spoken script is in `docs/PITCH.md`. Phone audio has to be clear: put a second phone or the laptop mic next to the speakerphone.

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
