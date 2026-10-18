# Backup slides

Owner: Caiden. Five slides in Google Slides. Shown only if the arm fails at judging, and used as title cards in the video. The story, numbers and names match `docs/PITCH.md`. Sources for every number are in the Sources table there.

Fill `[measured]` from `GET /stats` and the dashboard tables on Sunday morning. If a number is not there yet, delete the line instead of leaving the bracket on a slide.

## Slide text (paste into Google Slides)

**1. Surgeons need a second pair of hands**
- A surgical tech job takes about 120 days to fill.
- Without one, the surgeon looks away from the patient, puts down what they're holding, and searches the tray.
- In one Mayo Clinic study, about 1 in 5,500 operations left an item inside the patient. Most of those counts were called correct.
- US hospital staff have about 385,000 needle and sharps injuries a year.
- Small print: Periop Leader 2024; Cima et al., J Am Coll Surg 2008; CDC.

**2. Scrub**
- Ask out loud. The instrument arrives handle first. The gripper lets go when you take it.
- Operating room tray: scalpel handle, hemostat, Mayo scissors.
- Scalpels go to a safe spot, never hand to hand.
- Set a tool in the return spot and it goes back to its slot.
- Say "count" and it reads what's still out. The case summary arrives by text.

**3. How it works**
- Picture: `docs/media/system.png` (same as `docs/media/system.svg`).
- A phone call to a Photon number. An ElevenLabs voice agent. Gemini turns the words into one command from the tray.
- Perceptron Isaac 0.5, fine-tuned on our own demonstrations, does the pick and the return.
- One overhead camera: a hand tracker finds the open hand, Perceptron vision reads the tray.
- Only the controller moves the arm. "Stop" skips Gemini and freezes the arm until a person resets it.
- Every event goes to MongoDB Atlas.

**4. Results**
- Success by item and by lighting (bright, normal, dim), with the tries and a 95% range: [measured].
- Median request to hand: [measured] s over [measured] handoffs.
- Second setting, the robotics bench tray (needle-nose pliers, wire cutters, hex key): new demonstrations and one settings file, no new code. [measured] minutes.

**5. Business**
- Surgery centers first, starting in training labs. A monthly fee per operating room.
- Planning numbers: $750 per room per month plus $1,500 setup. Assumptions until we talk to buyers.
- Runs on an open-source arm that costs a few hundred dollars. The software is ready for a medical-grade arm.
- Helps scrub techs. Doesn't replace them. Research prototype, not a medical device.

Link to the deck:
