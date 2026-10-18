# Backup slides

Owner: Caiden (task P2). Five slides in Google Slides. Shown only if the arm fails at judging, and used as title cards in the video. Content comes from `docs/PROPOSAL.md` and `docs/PITCH.md`.

1. **The problem:** clinics can't hire enough assistants (the ADA and surgical tech numbers). The doctor turns away to search the tray.
2. **Scrub:** ask out loud, the instrument arrives handle first, sharps go to the safe spot, items go back, the count.
3. **How it works:** the system diagram at `docs/media/system.svg` (`docs/media/system.png` is the same picture; use the PNG in Google Slides). Photon call, Gemini, controller, Isaac 0.5 fine-tuned on our demos, hand tracker, Perceptron vision.
4. **Results:** the success tables by item and lighting, the median request-to-hand time, minutes to add the bench setting.
5. **Business:** operating rooms first, priced per tray or room per month. Next: a medical-grade arm.

## Slide text (paste into Google Slides)

Numbers in [brackets] come from `GET /stats` and the dashboard tables on Sunday morning. Scope: surgical first, the bench tray as the second setting. No dental tray in the demo. Stats are from `docs/PITCH.md`; check each against its source before the deck goes out.

**1. Clinics can't hire the second pair of hands**
- A surgical tech job stays open about four months.
- Without one, the doctor turns away from the patient, puts down what they're holding, and searches the tray.

**2. Scrub**
- Ask out loud. The instrument arrives handle first, and the gripper lets go when you take it.
- Operating room tray first: scalpel handle, hemostat, Mayo scissors. Scalpels go to a safe spot, never hand to hand.
- Set an instrument in the return spot and it goes back to its slot.
- Scrub keeps the count and reads back what's out. The case summary arrives by text.

**3. How it works**
- Picture: `docs/media/system.svg` (PNG: `docs/media/system.png`).
- Phone call (Photon) to an ElevenLabs voice agent. Gemini turns the words into one command from a fixed list.
- The controller is the only thing that moves the arm. Stop skips Gemini and freezes the arm.
- Perceptron Isaac 0.5, fine-tuned on our own demonstrations, picks the item. A hand tracker finds the open palm; Perceptron vision watches the tray.
- Every event goes to MongoDB for the count and the success tables.

**4. Results**
- Success rate by item and lighting (bright, normal, dim): [table].
- Median request to hand: [x.x] s over [n] handoffs.
- Second setting, the robotics bench tray (needle-nose pliers, wire cutters, hex key): [n] demos and [measured] minutes, no new code.

**5. Business**
- Operating rooms and surgical teams first, priced per tray or room per month. [measured] price after we talk to buyers.
- Runs on an open-source arm that costs a few hundred dollars; the software is ready for a medical-grade arm.
- Training and research prototype. No clinical claims.

Link to the deck:
