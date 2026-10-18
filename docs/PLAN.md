# Plan

All times Pacific. Base is HSEB after lunch. The HUB closes overnight. Where the arm lives depends on Perceptron (fill in after the workshop).

## Deadlines that can sink us

| When | What |
| --- | --- |
| **Sat 10:30 PM** | Devpost draft (overview and tracks). Ours goes in by 10:00 PM |
| **Sun 10:00 AM** | Final Devpost locks. It needs a public GitHub repo and the demo video (2 to 3 min). No video means no judging. We submit by 9:30 |
| Sun 10:20 AM | Everyone in the HUB Ballroom with the gear |
| Sun 10:30 AM on | Judging. Pitch under 3 minutes. Stay at the table the whole round |

The repo goes public Sunday morning before submitting. Keys must never be committed, since the history becomes public too.

## Tracks we enter

- **Title:** Community Kitchen
- **Sponsored (max 3):** Perceptron Robotics, Perceptron Perception, Photon (including best voice agent)
- **Non-sponsored:** DubHacks NEXT, MLH Gemini API, MLH Vultr, MLH MongoDB Atlas, MLH GoDaddy Registry, MLH Commit Fellowship (fill the form at mlh.link/commit-fellowship-form), MLH DEV writing (a post after the event)

What each one needs from us:

| Track | Needs |
| --- | --- |
| Perceptron Robotics | Fine-tuned Isaac 0.5 on our task, a video of the working arm. Judged on creativity, task difficulty, technical execution |
| Perceptron Perception | Their vision API doing real work: tray state, grasp check, returns, the count |
| Photon | The agent on a Photon number. Voice for the voice prize, the summary text on the same thread |
| Gemini | Speech to command with structured output, the end-of-case summary |
| MongoDB Atlas | The ledger |
| Vultr | The public dashboard runs on a Vultr server |
| GoDaddy | The dashboard's domain |
| DubHacks NEXT | A real business case: surgery centers and operating rooms first, priced per room |

## Saturday

| Time | Anish | Caiden | Brandon | Evan |
| --- | --- | --- | --- | --- |
| 12:30 to 1:15 | Perceptron workshop, notes into `docs/ARM.md` | Workshop, laptop open: controller on the fake arm (C1) | Workshop: camera and hand tracker (B1) | Workshop: settings files (E1) |
| 1:15 to 2:00 | Lunch, walk to HSEB. Perceptron code, repo collaborators, Devpost team (A2) | Lunch. C1 | Lunch. B1 | Lunch. E1, start E2 |
| 2:00 to 2:15 | **Kickoff at HSEB:** everyone has the repo, `.env` filled, contracts read, tasks clear | | | |
| 2:15 to 4:30 | Arm setup and calibration, poses, tape positions (A3) | C1 pushed by 2:30, then the Photon call (C3) | Hand tracker, camera stream (B2, B3) | Dashboard on the fake arm (E2) |
| 4:30 to 6:00 | Operating room demos with Evan (A4) | Gemini commands, stop path, spoken replies (C4) | Tray perception (B4) | Arm crew (E4), ledger (E3) |
| **6:00** | **Checkpoint 1:** a spoken request on the call runs every step on the fake arm and shows on the dashboard | | | |
| 6:00 to 7:00 | Dinner. Start fine-tuning run 1 before eating (A5) | Dinner | Dinner | Dinner |
| 7:00 to 10:00 | `real_arm.py`, `move_to` (A6, A7) | Real controller flows (C6) | Calibration with Anish (B6), slot boxes (B5) | Devpost draft (E5), ledger |
| **10:00** | Evan submits the Devpost draft | | | |
| 10:00 to 10:30 | First real handoff (A8) | A8 with Anish | A8 with Anish | Dashboard during A8 |
| **10:30 PM** | **Checkpoint 2:** Devpost draft in. First real handoff by voice | | | |
| 10:30 to 2:00 | Bench demos and extra operating room demos (A9), run 2 (A10) | Summary text, sharps call-outs (C7) | `path_clear`, saved hand spots (B7) | Tables, Vultr, domain (E6) |
| **2:00 AM** | **Checkpoint 3:** the operating room and bench settings, put-back and the count working | | | |

## Overnight and sleep

Decide at Checkpoint 2 who goes home and who stays, so at least two people are always working and one of them can run the arm. Whoever leaves takes work that runs alone (a fine-tuning run, a test batch) and comes back by 6 AM. Nobody sleeps in the work rooms.

| Time | What |
| --- | --- |
| 2:00 to 6:00 | Fix what's weak. Tests in three lighting setups (B8). Ten clean full runs (C8). Extra demos for any item under 70% success, then a run 3 if time allows |

## Sunday

| Time | What |
| --- | --- |
| **6:00 AM** | **Feature freeze.** Only fixes and tests from here |
| 6:00 to 7:00 | Fill the success tables (A11). Record one clean full run as a backup video |
| 7:00 to 8:30 | Record the demo video and the Perceptron arm video. Evan edits |
| 8:30 to 9:00 | README with run steps, repo made public, scan the history for keys, Devpost text final with measured numbers |
| 9:00 to 9:30 | Breakfast (HUB, 9:00 to 10:30). **Final Devpost submitted by 9:30** |
| 10:20 | HUB Ballroom with the arm (if allowed), the trays, the towel, the lamp, the phone, the power strip |
| 10:30 on | Judging workshop, then our round. Rehearse the 3-minute demo twice while waiting |

## Testing (Sunday 6 AM, logged with `ledger.log_test`)

| Test | Tries | Record |
| --- | --- | --- |
| Operating room items in bright, normal, dim | 10 per item per setup (90) | success, retries, request-to-hand time |
| Bench items in normal and bright | 5 per item per setup (30) | success, retries |
| Put-back for every item | 5 per item (45) | success |
| Adding the bench setting | once | minutes from the first bench demo to the first working bench handoff |

If time is short, run the operating room row first. It's the one the pitch points at.

## The demo (3 minutes, pitch spoken over it)

| Time | Said | Happens |
| --- | --- | --- |
| 0:00 | The staffing numbers | A teammate stands as the clinician, hands busy |
| 0:30 | "This is Scrub." | "Hemostat." Scrub answers on speaker, the hemostat arrives handle first, the gripper lets go on the pull. The dashboard shows the time |
| 0:50 | The sharps line | "Scalpel." It goes to the safe spot. "Scalpel down" |
| 1:05 | "Try it." | The judge asks for the scissors and gets them |
| 1:20 | The return line | The hemostat goes in the return spot. "Returning the hemostat," back to its slot |
| 1:40 | The lighting line | Lamp on, glare on the steel, another request works. Point at the lighting table |
| 2:00 | A second setting | Swap to the robotics bench tray, ask for the pliers. Same model, no new code |
| 2:30 | The close | "Count." Scrub reads what's out, and the summary text arrives |

Short version for a rushed judge: 0:30, 1:05, 2:30. The judge asking for an instrument is what sells it, so rehearse that step most. Anish speaks; Caiden runs the dashboard and stop key; Brandon is the clinician; Evan swaps trays and the lamp.

## Arm slot schedule

- **We have the arm for the entire competition.** No slots to plan around; the only limits are people, the 2 training runs and time.
- Order:
    1. Now: setup, calibration, both cameras fixed and taped, operating room set (75).
    2. Run 1 on the operating room set as soon as it's recorded (about 1 hour including export). Target: started by 5 PM.
    3. While run 1 trains: the bench set and extra operating room demos go into the same dataset with `--resume`.
    4. Test run 1, add 10 more demos for any weak item.
    5. Run 2 on everything by about 11 PM. That leaves the night for the real handoff, put-back, tests and the success tables.
- We only get 2 successful training runs (see `docs/PERCEPTRON-ROBOTICS.md`), so check each dataset before training on it.
- Still unknown: whether the arm comes to judging.
