# Devpost text

Owner: Evan (tasks E5, E7). Draft from `docs/PROPOSAL.md` and what is actually in the repo (`docs/STATUS.md`). Anish reviews before it is submitted. Plain words. No buzzwords. No em dashes.

This file is ready to paste. Evan submits the draft on Devpost by **Sat 10:00 PM** (DubHacks deadline 10:30 PM). Final text, with measured numbers filled in, is due **Sun 9:30 AM** (locks at 10:00).

Do not invent a success rate. Leave the `[measured]` slots until the arm tests are logged.

## Tracks to tick

- Title: Community Kitchen
- Sponsored: Perceptron Robotics, Perceptron Perception, Photon
- Non-sponsored: DubHacks NEXT, MLH Gemini API, MLH Vultr, MLH MongoDB Atlas, MLH GoDaddy Registry, MLH Commit Fellowship, MLH DEV writing

## Project name

Scrub

## Tagline

A robot arm that passes instruments when you ask out loud.

## Inspiration

Dentists and surgeons work with an assistant who hands them instruments. Clinics cannot hire enough of those assistants. In Q3 2025, 69% of dentists who were recruiting called the search extremely or very hard (ADA Health Policy Institute). A surgical technologist job stays open about 120 days. When nobody is there, the clinician turns away from the patient, puts down what they are holding, and searches the tray.

The same pause happens on a robotics bench. Both hands are on the work, and the next tool is across the table.

## What it does

Scrub is a robot arm that passes instruments by voice. A clinician asks out loud. Scrub picks the instrument from the tray and brings it to an open hand, handle first. It lets go when the person pulls, or when they say "got it."

A scalpel never goes hand to hand. Scrub sets it in a fixed safe spot and says "scalpel down." That follows the operating-room habit of passing sharps one at a time, in a called-out spot.

When an instrument is done, it goes in the return spot. Scrub puts it back in its slot. Say "count" and Scrub reads back what is still out, so a tool is not left behind at the end of a case.

One system runs three trays. Switching trays is a different settings file, not new code.

- Operating room: scalpel handle, hemostat, Mayo scissors
- Dental office: mouth mirror, explorer, cotton pliers
- Robotics bench: needle-nose pliers, wire cutters, hex key

Plain names work. So do the names clinicians and techs actually say. "Kelly" is the hemostat. "Mayo" is the scissors. "Allen key" is the hex key.

## How we built it

A phone on speaker calls a Photon number. ElevenLabs turns the speech into text. Gemini turns that text into one command from the current tray, so it cannot invent an instrument that is not on the tray. The word "stop" never waits on Gemini. It freezes the arm immediately.

A camera watches the tray and the clinician's hand. MediaPipe finds the open hand. Perceptron's vision model says which slots are full and whether the return spot is occupied. A fine-tuned Isaac 0.5 model, trained on our own demonstrations, is what runs instructions such as "pick the hemostat" and "return the hemostat" on an SO-101 arm. Those demonstrations are being recorded this weekend.

Only the controller moves the arm. It checks the grasp, sends sharps to the safe spot, and stops on the word "stop", the spacebar, or the button on the dashboard. After a stop, the arm stays frozen until someone presses reset.

MongoDB Atlas stores every event and every measured trial. If Atlas is down, the same events sit in a local file and upload when the connection comes back. The dashboard shows the live camera, the current step, the current lighting, what is out, the handoff time, and the success tables. If the tray camera is reusing an old reading, the page says "vision stale." A public page shows the count and those tables to anyone with the link. The database address stays on the server.

## Challenges

Operating lights are bright, and steel instruments throw glare. Every item is recorded and tested in bright, normal, and dim light so the result is a table, not a guess.

Handing someone a scalpel is the wrong habit, so that one item has its own path. The arm, the camera, the voice agent, and the log are separate programs. They share a short list of messages, which is what let four people build them at the same time.

The phone number, the overhead camera, and the arm setup are the parts that still need a person in the room. The software path can be run without them, on a fake arm.

## Accomplishments

Working in the repo as of Saturday evening:

- Three tray files, with the names people actually say. Only the scalpel is marked sharp.
- A live dashboard on the controller. A handover on the fake arm updates the step, the log, what is out, and the seconds from request to hand. The page also shows the current lighting, the success tables, and a warning when the tray reading is stale. Stop and reset are on the page. Spacebar stops the arm.
- A ledger that records every controller event. Success rates come from measured trials. The median handoff time comes from the events. The same numbers are on a public read-only page.
- The controller runs the full handover on the fake arm, including the miss, the retry, the wait for a pull, and the freeze when the hand is lost.
- Typed speech ("grab me the kelly") becomes a hemostat handover through Gemini. A real phone call is still waiting on the Photon number.
- The camera code locks exposure, finds an open hand, and posts the tray. Slot boxes, the camera-to-arm fit, and a lighting-test log can be run without guessing at the file format.

The real-arm numbers go here on Sunday morning, after the tests:

- Request to hand, median: [measured] seconds
- Success rate by item: [measured]
- Success rate in bright, normal, and dim light: [measured]

## What we learned

The useful version of this job is small. Pass the instrument, put it back, keep the count, and do not hand someone a sharp. Extra names are a list on the tray file. Stop has to be its own path, because a round trip to a model is too slow when someone says stop.

## What's next

Dental offices come first, as a monthly fee per chair. The sterile setup is simpler than an operating room, and the staffing gap is already measured. A medical-grade arm is the later version of this weekend's arm. After that, Scrub can hand over the next instrument before it is asked for, using the step of the procedure.

## Built with

Python, FastAPI, HTML, JavaScript, MongoDB Atlas, Gemini, ElevenLabs, Photon, Perceptron (Isaac 0.5 and the vision API), MediaPipe, LeRobot, SO-101, Vultr, GoDaddy

## Video shot list (E7, not pasted into Devpost)

Edit a 2 to 3 minute video from these shots. Record each one a few times and keep the cleanest take. The spoken script is in `docs/PITCH.md`. Phone audio has to be clear: put a second phone or the laptop mic next to the speakerphone.

- [ ] 1. Title card, about 5 seconds. (Caiden's slide 1.)
- [ ] 2. Brandon's hands are busy. He says "hemostat" to the speakerphone. Close-up of the pick, the hand receiving it handle first, and the gripper opening when he pulls. Dashboard shows the handoff seconds.
- [ ] 3. "Scalpel." The scalpel goes to the safe spot. Scrub says "scalpel down." It does not go to the hand.
- [ ] 4. Return. Hemostat goes in the return spot. Scrub says "returning the hemostat" and puts it back in its slot.
- [ ] 5. Evan turns the lamp on. Glare shows on the steel. A handoff still succeeds. Cut to the lighting table on the dashboard.
- [ ] 6. Swap to the dental tray and ask for the mouth mirror. Swap to the bench tray and ask for the pliers.
- [ ] 7. "Count." The voice reads back what is out. Then the summary text arrives on the phone.
- [ ] 8. Dashboard: the live camera, what is out, and the success tables. Hold long enough to read the numbers.
- [ ] 9. Close on the team and the arm.

Separate from this edit: Anish records the Perceptron arm video (A12) as one unedited roll of picks and returns, with the success table at the end. That file is for the robotics track, not this 2 to 3 minute cut.

Before upload, replace the `[measured]` slots above with the numbers on the dashboard tables. Upload the video and submit the final Devpost by Sun 9:30 AM.
