# Backup slides

Owner: Caiden. Five slides in Google Slides. Shown only if the arm fails at judging, and used as title cards in the video. The story, numbers and names match `team/PITCH.md`. Sources for every number are in the Sources table there.

Fill `[measured]` from `GET /stats` and the dashboard tables on Sunday morning. If a number is not there yet, delete the line instead of leaving the bracket on a slide.

## Which level

These slides match level 1 of `team/DEMO.md` (live real arm, model where it passed, taught for the rest). Level 2: change the "Perceptron Isaac" bullet on slide 3 to "taught skills, labeled; the fine-tuned model is in our video". Level 3: add "the arm shown is a simulation; the real-arm video is beside it" to slide 2. Never show a number that is still "to fill from the ledger".

## Slide text (paste into Google Slides)

**1. Surgeons need a second pair of hands**
- A surgical tech job takes about 120 days to fill.
- Without one, the surgeon looks away from the patient, puts down what they're holding, and searches the tray.
- In one Mayo Clinic study, about 1 in 5,500 operations left an item inside the patient. Most of those counts were called correct.
- US hospital staff have about 385,000 needle and sharps injuries a year.
- Small print: Periop Leader 2024; Cima et al., J Am Coll Surg 2008; CDC.

**2. Scrub**
- Ask out loud. The instrument arrives handle first. The gripper lets go when you take it.
- The fine-tuned model picks; our code keeps it safe and carries it to the hand.
- Operating room tray: scalpel handle, hemostat, Mayo scissors.
- Scalpels go to a safe spot, never hand to hand.
- Set a tool in the return spot and it goes back to its slot.
- Say "count" and it reads what's still out. The case summary arrives by text.

**3. How it works**
- Picture: `docs/media/system.png` (same as `docs/media/system.svg`).
- A phone call to a Photon number. An ElevenLabs voice agent. Gemini turns the words into one command from the tray.
- Perceptron Isaac 0.5, fine-tuned on our own demonstrations on this arm, does the pick for the items that passed their real tries. The others use a skill we taught by hand, labeled `taught` on the dashboard.
- The fine-tuned model picks; our code keeps it safe and carries it to the hand: smoothing, speed and joint limits, a claw guard, a heat guard, a grasp check, and a planned move from carry to the hand.
- One overhead camera: a hand tracker finds the open hand, Perceptron vision reads the tray.
- Only the controller moves the arm. "Stop" skips Gemini and freezes the arm until a person resets it.
- Every event goes to MongoDB Atlas.

**4. Results**
- Success by item and by lighting (bright, normal, dim), with the tries and a 95% range: [measured].
- Median request to hand: [measured] s over [measured] handoffs.
- Real tries per item (10 each, model and taught shown separately): [to fill from the ledger].
- Second setting, the robotics bench tray: include only if it ran on the real arm today. Otherwise delete this line.

**5. Business**
- Surgery centers first, starting in training labs. A monthly fee per operating room.
- Planning numbers: $750 per room per month plus $1,500 setup. Assumptions until we talk to buyers.
- Runs on an open-source arm that costs a few hundred dollars. The software is ready for a medical-grade arm.
- Helps scrub techs. Doesn't replace them. Research prototype, not a medical device.

Link to the deck:
