# Pitch

Three minutes, spoken over the live demo. The beats and times match the demo console (`http://localhost:8000/demo`) and the table in `docs/DEMO.md`. Questions are in `docs/QNA.md`.

Fill every `[measured]` from the dashboard tables (`GET /stats`) on Sunday morning. If a number is not on the dashboard yet, skip the sentence. Never guess a number.

## Which level this script is for

This script is level 1 of `docs/DEMO.md`: the live real arm, the fine-tuned model for the items that passed their real tries, taught skills for the rest, every pick labeled on the dashboard. One line goes in everywhere: "The fine-tuned model picks; our code keeps it safe and carries it to the hand."

Every claim below must run at the table or be in the Perceptron video. Real-try success rates are "to fill from the ledger" until the ledger has them; skip the sentence if it is still empty.

- Level 2 (taught only): say "In this run the pick is a skill we taught by hand, labeled on the screen. The fine-tuned model is shown in our video." Do not say the model is running.
- Level 3 (sim next to the video): say "This arm is a simulation. The video beside it is the real arm running our fine-tuned model." Same safety and controller story.
- In the 2:00 beat, "we fine-tuned Perceptron's Isaac model" holds only for the items that are `model` on the dashboard. For a `taught` item say "this one is a taught skill".

## Who does what

| Person | Where they stand | Speaks | Also does |
| --- | --- | --- | --- |
| Anish | Next to the judge, facing them | The problem, "This is Scrub", the second tray, the close | Calls "go to backup" if the arm dies |
| Caiden | At the demo laptop, one hand near Space | Sharps and stop, the judge's turn, the return and the count | Runs the console keys and the stop key |
| Evan | Beside the lamp and the spare tray | The lighting test and the tables (short) | Lamp on and off, swaps trays, resets the tray |
| Brandon | Across the tray from the arm, as the clinician | Hand tracking (short) | Asks for each instrument on the phone, takes the handoffs |

## The script

Spoken words only. About 400 words, which is about 3 minutes at 130 words a minute.

**0:00 The problem (Anish).** Brandon stands with his hands busy.

> Every operation has a scrub tech. They hand the surgeon each instrument and keep the count. Hospitals can't hire enough of them. A surgical tech job takes about 120 days to fill.
>
> So the surgeon looks away from the patient, puts down what they're holding, and searches the tray. And when an instrument is missing, the case waits. One study found those delays ran about ten minutes.

**0:30 The first handoff (Anish, then Brandon).**

> This is Scrub. You ask for what you need, out loud.

Brandon: "Hemostat."

> Scrub picks it from the tray with the fine-tuned model [if the dashboard says `model` for the hemostat; otherwise say "with a skill we taught"]. The fine-tuned model picks; our code keeps it safe and carries it to the hand, handle first, and lets go when he pulls. The dashboard times every handoff and labels the source.

**0:50 Sharps and stop (Caiden).** Brandon: "Scalpel."

> Scalpels never go hand to hand. Nurses and techs get cut most often while passing sharps. US hospital staff have about 385,000 needle and sharps injuries a year. So Scrub sets the scalpel on a safe spot and says "scalpel down." Anyone can say stop, and the arm freezes until a person resets it.

**1:05 The judge's turn (Caiden, then Brandon).**

> Your turn. Ask for the scissors.

The judge asks. The Mayo scissors arrive in their hand.

Brandon:

> A camera over the tray finds your open hand ten times a second. The arm slows down near it. If your hand leaves, the arm holds still.

**1:20 Return and count (Caiden).** Brandon sets the hemostat in the return spot.

> Done with a tool? Set it in the return spot. Scrub puts it back in its slot by itself. It also keeps the count. That matters. A Mayo Clinic study found an item left inside a patient about once in every 5,500 operations. Most of those counts had been called correct.

**1:40 Glare and the tables (Evan).** Evan turns the lamp on over the tray.

> Operating lights are bright, and steel throws glare. So we test every item in bright, normal and dim light. Brandon, ask again.

Brandon asks for any instrument. It arrives.

> Every try is saved in MongoDB. This table is live. [measured] percent in bright light, [measured] in normal. The range next to each one shows how sure we are.

**2:00 A second tray (Anish).** Evan turns the lamp off and swaps to the bench tray. Caiden presses `2`. Brandon: "Needle-nose pliers."

> Scrub is built for the operating room. But this is a robotics bench tray. Same arm, same code. The bench tray is not part of tonight's real-arm tries. Say this beat only if the bench tray ran on the real arm today; otherwise skip it and use the sim or the video. Time to add a tray: [to fill from the ledger].

**2:30 The close (Brandon, Caiden, Anish).** Brandon: "Count." Then: "End of case."

Caiden:

> It reads back what's still out. When the case ends, the summary comes as a text on the same phone.

Anish:

> Scrub runs on an open-source arm that costs a few hundred dollars. We'd sell it per operating room, starting with surgery centers. It helps scrub techs. It doesn't replace them. This is a research prototype, not a medical device. Questions?

## If a beat fails

Keep talking. The fix for each beat is in the "If it fails" column of `docs/DEMO.md`. A stop is a feature: say so.

## Sources

Every number above was checked against its source on Oct 17, 2026. Say only these numbers.

| What we say | Source |
| --- | --- |
| A surgical tech job takes about 120 days to fill | Periop Leader (OR Manager) survey, Aug 28, 2024: "Filling a surgical technologist position takes an average of 120 days." https://www.periopleader.com/survey-staffing-woes-ease-slightly-but-challenges-remain/ (excerpt shown on https://periopleader.com/tag/surgical-technologists) |
| Instrument delays ran about ten minutes | Nichol et al., BMC Surgery 2024, 7 pediatric operating rooms: "The average length of delays per case was 10.16 min." Most errors were missing instruments. https://doi.org/10.1186/s12893-024-02407-1 |
| About 385,000 needle and sharps injuries a year to US hospital staff | CDC Sharps Safety: "approximately 385,000 needlesticks and other sharps-related injuries to hospital-based healthcare personnel each year." https://www.cdc.gov/sharpssafety/ |
| Nurses and techs get cut most often while passing sharps | American Nurse, citing data from 87 US hospitals: injuries to nurses and technicians "most often occurred when they passed or disassembled devices." https://www.myamericannurse.com/practical-strategies-to-prevent-surgical-sharps-injuries/ |
| An item left inside about once in 5,500 operations, most with a correct count | Cima et al., J Am Coll Surg 2008 (Mayo Clinic, 191,168 operations): "approximately 1:5,500 operations", and 21 of 34 (62%) had a count reported as correct. https://pubmed.ncbi.nlm.nih.gov/18589366/ and https://psnet.ahrq.gov/issue/incidence-and-characteristics-potential-and-actual-retained-foreign-object-events-surgical |

Also checked, used in `docs/QNA.md` and `docs/NEXT.md` only:

| What we say | Source |
| --- | --- |
| About 8,600 openings a year for surgical assistants and technologists | US Bureau of Labor Statistics, Occupational Outlook Handbook (2025 to 2035): "About 8,600 openings for surgical assistants and technologists are projected each year, on average, over the decade." https://www.bls.gov/ooh/healthcare/surgical-technologists.htm |
| Hands-free passing used at least 75% of the time: 35% fewer incidents | Stringer et al., Public Health Reports 2009: "the HFT-associated reduction in rate was 35%" (cuts, glove tears and contamination together). https://pmc.ncbi.nlm.nih.gov/articles/PMC2708668/ |
| Operating room time costs about $36 a minute | Childers and Maggard-Gibbons, JAMA Surgery 2018: "The mean cost of OR time was $36 to $37 per minute using financial data from California's short-term general and specialty hospitals in FY2014." https://jamanetwork.com/journals/jamasurgery/fullarticle/2673385 |
| RoboNurse-VLA, a 2024 research robot scrub nurse driven by voice | arXiv 2409.19590, submitted Sep 29, 2024. https://arxiv.org/abs/2409.19590 |

Do not say on stage: that Scrub prevents retained items (it adds a second check), that it replaces scrub techs, that it is ready for patients, or anything about FDA being easy. See `explore/research/SURGEON_RESEARCH.md` section 6.

## Demo video (2 to 3 minutes, required)

The shot list and the edit plan are in `docs/DEVPOST.md` ("Video shot list" and "Video edit plan"). The spoken track can reuse this script. Anish records the separate Perceptron arm video: one unedited roll of picks and returns across items and lighting, with the success table at the end.
