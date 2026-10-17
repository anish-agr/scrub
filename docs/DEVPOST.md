# Devpost text

Owner: Evan (tasks E5, E7). Draft from `docs/PROPOSAL.md`. Anish reviews before it's submitted. Keep it plain: no buzzwords, no em dashes.

Draft due on Devpost **Sat 10:00 PM** (DubHacks deadline 10:30 PM). Final by **Sun 9:30 AM** (locks 10:00).

Measured numbers stay as placeholders until the arm tests are logged. Do not invent a success rate.

## Tracks to tick

- Title: Community Kitchen
- Sponsored: Perceptron Robotics, Perceptron Perception, Photon
- Non-sponsored: DubHacks NEXT, MLH Gemini API, MLH Vultr, MLH MongoDB Atlas, MLH GoDaddy Registry, MLH Commit Fellowship, MLH DEV writing

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

A camera watches the tray and the clinician's hand. MediaPipe finds the open hand. Perceptron's vision model says which slots are full and whether the return spot is occupied. A fine-tuned Isaac 0.5 model, trained on our own demonstrations, runs instructions such as "pick the hemostat" and "return the hemostat" on an SO-101 arm.

Only the controller moves the arm. It checks the grasp, sends sharps to the safe spot, and stops on the word "stop", the spacebar, or the button on the dashboard.

MongoDB Atlas stores every event and every measured trial. The dashboard shows the live camera, the current step, what is out, the handoff time, and the success tables. A public page shows the count and those tables to anyone with the link.

## Challenges

Operating lights are bright, and steel instruments throw glare. Every item is recorded and tested in bright, normal, and dim light so the result is a table, not a guess.

Handing someone a scalpel is the wrong habit, so that one item has its own path. The arm, the camera, the voice agent, and the log are separate programs. They share a short list of messages, which is what let four people build them in parallel.

## Accomplishments

The three tray files, the live dashboard, and the ledger are in the repo. A handover on the fake arm shows on the page as it happens: the step, the event log, what is out, and the seconds from request to hand. The success tables update from the log.

The real-arm numbers go here on Sunday morning:

- Request to hand, median: [measured] seconds
- Success rate by item: [measured]
- Success rate in bright, normal, and dim light: [measured]

## What we learned

The useful version of this job is small. Pass the instrument, put it back, keep the count, and do not hand someone a sharp. Extra names are a list on the tray file. Stop has to be its own path, because a round trip to a model is too slow when someone says stop.

## What's next

Dental offices come first, as a monthly fee per chair. The sterile setup is simpler than an operating room, and the staffing gap is already measured. A medical-grade arm is the later version of this weekend's arm. After that, Scrub can hand over the next instrument before it is asked for, using the step of the procedure.

## Built with

Python, FastAPI, HTML, JavaScript, MongoDB Atlas, Gemini, ElevenLabs, Photon, Perceptron (Isaac 0.5 and the vision API), MediaPipe, LeRobot, SO-101, Vultr, GoDaddy
