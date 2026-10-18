# DubHacks NEXT business case: Scrub

Team Scrub, DubHacks '26.

Scrub is a research prototype, not a medical device. We make no clinical claims. Every number below is either sourced (link in the Sources section) or marked **assumption**. Assumptions are our planning guesses, not results.

## Summary

Scrub is a robot arm that passes instruments when a surgeon asks out loud. It carries each one to the handoff point, slows down as it gets there, lets go when the surgeon pulls it, and goes straight home. It keeps a running count of what's out.

Operating rooms can't hire enough scrub techs. We would sell Scrub per operating room per month, starting with surgery centers, and first in training labs where no patient is involved.

## 1. The first market: surgery centers and operating rooms

### Why surgical first

1. **The job is well defined.** A scrub tech passes instruments, takes them back and keeps the count. Trays, instruments and sharps rules are standard. That makes the task small enough to automate and to measure.
2. **The shortage is real.** A surgical tech job takes about 120 days to fill (Periop Leader survey, 2024). The US projects about 8,600 openings a year for surgical assistants and technologists through 2035 (BLS).
3. **Operating room time is expensive.** It cost about $36 to $37 a minute in California hospitals (JAMA Surgery, 2018, fiscal year 2014 data). Instrument problems, mostly missing instruments, delayed a case about 10 minutes on average in one 2024 study.
4. **Counts and sharps matter.** One Mayo Clinic study found an item left inside a patient about once in 5,500 operations, and 62% of those had a count called correct. US hospital staff have about 385,000 needle and sharps injuries a year (CDC).
5. **A safe way in.** Live operating rooms would need FDA clearance. We start in surgical training and simulation labs, with no patient, and earn clinical use later.

## 2. What it does

Scrub helps scrub techs. It doesn't replace them.

- **Handoff by voice.** The surgeon says "hemostat" or "Mayo scissors." Scrub brings it to the handoff point and slows down as it gets there.
- **Lets go on a pull.** It opens when the clinician takes the tool, or says "got it."
- **Goes home.** After each handoff the arm goes straight home on its own. Putting a tool back is manual in this prototype.
- **Keeps the count.** "Count" reads back what's out, checked against the camera. "Check the tray" says what's missing before the case.

That leaves the scrub tech free for the sterile field and the next step of the case.

## 3. Pricing (assumptions)

- **Subscription:** $750 per operating room per month. **Assumption.**
- **Setup:** $1,500 per room for the arm, the overhead camera and the mount. **Assumption.**
- Over a 3-year contract the setup adds about $42 a month ($1,500 / 36), so the full cost is about **$792 per room per month**.

## 4. Does it pay for itself?

Scrub only pays for itself if it saves the room more than it costs. The cleanest way to measure that is operating room minutes.

- Sourced: operating room time costs about $36 a minute (JAMA Surgery, 2018).
- Full cost: about $792 per room per month (assumption above).
- Break-even: $792 / $36 = **22 minutes of operating room time saved per room per month**. That is about one minute per working day.

| Minutes saved per room per month (**assumption**) | Value at $36 a minute | Scrub cost per month | Net per room per month |
| --- | --- | --- | --- |
| 10 | $360 | $792 | **-$432** (loses money) |
| 22 | $792 | $792 | **$0** (break-even) |
| 30 | $1,080 | $792 | **+$288** |
| 60 | $2,160 | $792 | **+$1,368** |

How to read this:

- Ten minutes is about one instrument delay in the 2024 study. One avoided delay a month does not pay for Scrub. About two or more do.
- The $36 figure is the full average cost of a minute, from 2014 California data. A saved minute is only worth that if the room uses it, for example to fit in another case. So treat the table as the best case for each row.
- We have not measured how many minutes Scrub saves. That is the first thing a pilot has to measure. Until then, the honest claim is the break-even point, not a profit.
- Not counted: fewer sharps injuries, a second count, and covering a shift when no scrub tech is free. Those may matter more than minutes, but we have no measured numbers for them yet.

## 5. Who buys

1. **Surgery centers.** Many rooms, standard trays, repeat procedures. One tray file can roll out to every room.
2. **Hospital operating room groups.** Short on scrub techs and wanting a logged count.
3. **Surgical training and simulation labs.** Standard trays, no patients. This is where we start.

## 6. What we proved this weekend

1. **Voice to handoff on a $250 arm.** A spoken request picks one of three instruments (scalpel handle, hemostat, Mayo scissors) and carries it to the handoff point with a skill we taught it from our own demonstrations.
2. **A checked grasp.** The gripper checks each pick before carrying.
3. **Gentle motion.** Speed and joint limits on every move, and the arm slows as it nears the handoff point. It lets go only on a pull or "got it", then goes home.
4. **Stop.** "Stop" freezes the arm until a person resets it.
5. **Heat.** The thermal guard reads motor temperatures every 2 s while it drives the arm and rests it with torque off.

Success rates by item and lighting go here only once real tries are logged.

## 7. Roadmap

- **Months 1 to 3.** 20 interviews with surgery center managers and operating room leads. Two prototype arms in training labs.
- **Months 4 to 6.** Five training and simulation rooms. Measure minutes saved, request-to-hand time and success rate.
- **Months 7 to 12.** A mounting kit for common operating room tables, a medical-grade arm, and the start of the regulatory path before any use near a patient.

## Sources

- Periop Leader (OR Manager), "Survey: Staffing woes ease slightly, but challenges remain", Aug 28, 2024: https://www.periopleader.com/survey-staffing-woes-ease-slightly-but-challenges-remain/
- US Bureau of Labor Statistics, Surgical Assistants and Technologists: https://www.bls.gov/ooh/healthcare/surgical-technologists.htm
- Childers CP, Maggard-Gibbons M. Understanding Costs of Care in the Operating Room. JAMA Surgery, 2018: https://jamanetwork.com/journals/jamasurgery/fullarticle/2673385
- Nichol PF et al. Observed rates of surgical instrument errors. BMC Surgery, 2024: https://doi.org/10.1186/s12893-024-02407-1
- Cima RR et al. Retained foreign object events in surgical patients. J Am Coll Surg, 2008: https://pubmed.ncbi.nlm.nih.gov/18589366/
- CDC, Sharps Safety: https://www.cdc.gov/sharpssafety/
