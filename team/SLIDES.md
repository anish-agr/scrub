# Backup slides

Owner: Caiden. Five slides in Google Slides. Shown only if the arm can't run at the table, and usable as title cards in the video. The story and numbers match `team/PITCH.md`. Sources for the outside numbers are in the Sources table there and in `team/CONTEXT.md` Part 1, section 4.

Our own numbers come only from `team/FACTS-0718.md` (ledger, dataset, logs). If a number isn't there, delete the line. Never leave a bracket on a slide.

## Slide text (paste into Google Slides)

**1. Surgeons need a second pair of hands**
- A surgical tech job takes about 120 days to fill.
- Without one, the surgeon looks away from the patient and searches the tray.
- When an instrument is missing, the case waits: about 10 minutes a case in one study.
- Small print: Periop Leader 2024; Nichol et al., BMC Surgery 2024.

**2. Scrub**
- Ask out loud for an instrument. Three on the tray: scalpel, hemostat, Mayo scissors.
- The arm picks it with a skill we taught it from our recorded demonstrations.
- It slows as it nears the handoff point and lets go when you pull.
- After each handoff it goes straight home on its own.
- Say "stop" and it freezes where it is. Say "continue" and it goes on.
- Returns on the real arm are done by hand. Our video shows returns in simulation, labeled.

**3. How it works**
- Picture: `docs/media/system.png` (same as `docs/media/system.svg`).
- Voice: an ElevenLabs agent and our voice server. Instrument names are matched on the laptop, so a request starts the arm right away.
- The arm: an SO-101. We recorded our own demonstrations of each pick with a leader arm. A request plays the averaged demonstrations for that instrument.
- A separate Perceptron training run used the same demonstrations. No model is deployed on the arm.
- Perceptron's vision API: detect checks the tray, OCR reads the printed count sheet. Gemini is the OCR fallback. (Keep this line only if shots 7 and 8 were recorded.)
- Every telemetry row and saved demonstration goes to MongoDB Atlas. The public page runs on Vultr.

**4. Safety, checked in code**
- "Stop" freezes the arm in place. KILL cuts the motors at once.
- Every move is speed-capped and kept inside each joint's range.
- The gripper stops at contact plus a small squeeze.
- Lets go only on a pull or on "let go".
- Motor temperatures every 2 seconds. At 60 C it goes home and turns its motors off until it cools.
- Research prototype. It never touches the patient.

**5. Results and business**
- Real handoffs today, by instrument: from `team/FACTS-0718.md` only. Delete this line if the file has no count.
- Recorded demonstrations: from `team/FACTS-0718.md` only.
- Surgical training labs first (no patient), then surgery centers. A monthly fee per operating room.
- Planning numbers: $750 per room per month plus $1,500 setup. Assumptions until we talk to buyers.
- Runs on an open-source arm that costs a few hundred dollars.
- Helps scrub techs. Doesn't replace them. Not a medical device.

Link to the deck:
