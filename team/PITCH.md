# Pitch

Under three minutes, spoken at the table over the live arm (or over the video on the laptop if the arm can't run there). The table plan and the failure fixes are in `team/DEMO.md`. Questions are in `team/QNA.md`.

Every number in this file is in the Sources table below or in `team/FACTS-0718.md`. If a number isn't in one of those, skip the sentence. Never guess a number.

## What we say about the pick

The pick on the real arm is a skill we taught it from our own recorded demonstrations. The voice request plays the averaged demonstration for that instrument (`voice/src/station.ts`, `explore/station/autopick.py` mode `average`). Say it that way: "a skill we taught it from our demonstrations".

No Perceptron training job has run on those demonstrations: 0 jobs and 0 deployments at 07:20 (`team/FACTS-0718.md` c). No model pick is on the arm or in the video. Don't say "fine-tuned model picks". If someone asks, the answer is in `team/QNA.md` question 1.

## Who does what

| Person | Where | Speaks | Also does |
| --- | --- | --- | --- |
| Anish | Next to the judge, facing them | The problem, "This is Scrub", the close | Calls "go to the video" if the arm can't run |
| Caiden | At the laptop | The handoff, stop and continue, the safety rules | Runs the station page and the voice server; KILL is Esc on the station page |
| Evan | Beside the tray | The return and the video shots (short) | Puts instruments back between judges, starts the video on the second laptop |
| Brandon | Across the tray from the arm, in the lab coat and gloves | The clinician's lines | Asks for each instrument, takes the handoffs |

## The script

About 330 spoken words, about 2:30 at 130 words a minute. That leaves time for the arm.

**0:00 The problem (Anish).**

> Every operation has a scrub tech. They hand the surgeon each instrument and keep the count. Hospitals can't hire enough of them. A surgical tech job takes about 120 days to fill.
>
> Without one, the surgeon looks away from the patient and searches the tray. When an instrument is missing, the case waits. One study found those delays ran about ten minutes a case.

**0:30 The first handoff (Anish, then Brandon).**

> This is Scrub. You ask for what you need, out loud.

Brandon: "Hemostat."

Caiden:

> It picks the hemostat with a skill we taught it from our own demonstrations on this arm. It carries it to the handoff point at a capped speed and holds the handle out. It lets go when he pulls, or when he says "let go". Then it goes straight home on its own.

**1:00 The scissors, with a stop (Caiden, then Brandon).**

Brandon: "Mayo scissors." Partway through the move, Brandon: "Stop."

> Anyone can say stop. The arm freezes where it is, still holding the scissors, and waits.

Brandon: "Continue." The scissors arrive, he pulls, the arm goes home.

> "Continue" picks up where it left off. If something is wrong, KILL cuts the motors at once.

**1:30 How it stays safe (Caiden).**

> Every move is speed-capped and kept inside each joint's range. The gripper stops squeezing once it touches the tool. It reads the motor temperatures every two seconds, and if one reaches 60 degrees it goes home and turns its motors off until it cools.

**1:45 The return and the video (Evan).**

> Done with a tool? On the real arm today, a person puts it back. That's labeled manual return in our video. The video also shows the returns in simulation, using an electromagnet pickup, labeled as simulation, and the shots we can't do at the table.

No lighting line. Lighting isn't logged per try on the real arm (`team/FACTS-0718.md` d), so don't give lighting results.

**2:05 The close (Anish).**

> Scrub runs on an open-source arm that costs a few hundred dollars. We'd start in surgical training labs, where there's no patient, then surgery centers. It helps scrub techs. It doesn't replace them. It's a research prototype, not a medical device. Questions?

## If a beat fails

Keep talking. The fix for each beat is in `team/DEMO.md`. A stop is a feature, so say so.

## The short version (60 seconds)

> Hospitals can't hire enough scrub techs. A surgical tech job takes about 120 days to fill. This is Scrub. You ask out loud.

Brandon: "Hemostat." The arm hands it over and goes home.

> That pick is a skill we taught it from our demonstrations. It lets go when you pull, goes home on its own, and freezes when anyone says stop. It's a research prototype. Questions?

## Do not say

- A safe spot, or "scalpels never go hand to hand". The safe-spot step is gone.
- That it tracks the hand, or holds when the hand moves away. The camera frame rate is too low to track a hand. The arm goes to a fixed handoff point and holds the tool out. "Slows near the handoff point" is coded only in the controller that drives the sim (`controller/core.py:42`, `SPEED_NEAR`); on the real arm say "at a capped speed".
- That a fine-tuned model does the picks.
- A second tray (bench or dental). Three instruments only: scalpel, hemostat, Mayo scissors.
- That it texts a case summary, keeps working if a motor goes down, or returns tools by itself on the real arm.
- Tiger Data, Backboard or GoDaddy.
- That Scrub prevents retained items, replaces scrub techs, is sterile, or is ready for patients. Anything about FDA being easy.

## Sources

Every outside number was checked against its source on Oct 17, 2026. Say only these numbers.

| What we say | Source |
| --- | --- |
| A surgical tech job takes about 120 days to fill | Periop Leader (OR Manager) survey, Aug 28, 2024: "Filling a surgical technologist position takes an average of 120 days." https://www.periopleader.com/survey-staffing-woes-ease-slightly-but-challenges-remain/ |
| Instrument delays ran about ten minutes a case | Nichol et al., BMC Surgery 2024, 7 pediatric operating rooms: "The average length of delays per case was 10.16 min." Most errors were missing instruments. https://doi.org/10.1186/s12893-024-02407-1 |

What the arm does, checked in code on Oct 18:

| What we say | Where |
| --- | --- |
| Our own numbers | `team/FACTS-0718.md`: 29 recorded episodes, 24 usable, 9.0 minutes (`docs/DATA.md`, 06:49). Real handoffs taken by a hand with the jaw checked empty: 2, both scalpel (06:39, 07:02). Hemostat offered twice, no confirmed handoff. Mayo scissors: 0 episodes, 0 runs. Ledger real-arm tries: 0 |
| The pick plays the averaged demonstrations for that instrument | `voice/src/station.ts` (`run` with `mode: "average"`), `explore/station/autopick.py` `average_demos` |
| Lets go on a pull, or on "let go" / "got it" | `explore/station/autopick.py` `_handoff_tick` (load change, jaw moved, or a joint pushed 2 degrees, held 0.15 s); `voice/src/station.ts` (`release`) |
| Goes home after the handoff | `explore/station/autopick.py` (`handed over; home, motors off`) |
| "Stop" freezes in place, "continue" resumes | `voice/src/station.ts` (stop sends `pause`, continue sends `resume`); `explore/station/station.py` `_dispatch` (`frozen where it is`); `autopick.py` `pause`, `tick` holds every joint |
| KILL cuts the motors | `explore/station/station.py` `_kill_now` (broadcast torque off) |
| Speed cap and joint range | `autopick.py:42` `MAX_DEG_S = 45` (peak per joint); `explore/arm_session.py:222-223, 484-491` motor speed cap and acceleration; `station.py:234` `max_relative_target=15.0`; `station.py:1467` calls `explore/arm_session.py:209-219` `clamp_follower` (every goal kept inside the calibrated range) |
| Gripper stops at contact plus a small squeeze | `explore/arm_session.py` `GRIP_SQUEEZE`, `guard_gripper` |
| Temperatures every 2 s; at 60 C it goes home, motors off; cooled at 50 C | `explore/arm_session.py` `guard_joints` (2.0 s read); `arm/thermal.py` `COOL_TRIP, COOL_RESUME = 60, 50`; `explore/station/station.py` `_thermal` |

The other outside numbers (8,600 openings, 385,000 sharps injuries, 1 in 5,500 retained items, $36 an OR minute, 35% fewer incidents with hands-free passing) are sourced in `team/CONTEXT.md` Part 1, section 4. Use them only in answers (`team/QNA.md`).
