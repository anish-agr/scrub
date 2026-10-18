# What's left (Sat Oct 17, after the comb pass)

The software is finished for the demo: every planned feature is built, the comb fixed every critical and high finding (`docs/AUDIT.md`), and every test suite passes. What remains is hardware and accounts, which only people can do. Two ordered lists replace this file:

- **`docs/HARDWARE-TODO.md`**: every arm, camera, recording, training and test step, in order, with the exact command for this Mac, what you should see, and what to do if you don't. Start at step 1 (the wrist camera).
- **`docs/ACCOUNTS-TODO.md`**: every key and account (Perceptron team key, Hugging Face, ElevenLabs agent, Photon line, MongoDB on this Mac, Vultr, GoDaddy, Devpost, Commit Fellowship, DEV), with where to get it and whether it works now.

`docs/STATUS.md` stays the checklist. `docs/STATE.md` is the map of the system. `docs/WORKING-NOW.md` says who is editing what.

> **Scope (Sat 6:30 PM): no dental tools, so the dental setting is dropped.** Scrub is surgical first. The demo runs the operating room tray, plus the robotics bench tray to show a second setting with no new code. `settings/dental.json` stays in the code but isn't recorded or demoed.

## Decisions the team still owes

| Decision | Why it matters | Where |
| --- | --- | --- |
| May the real arm use the saved spot when vision is down? | Today, after 5 s with no Hand posts, the arm goes to the saved spot without a hand check. "Only toward an open hand" holds only while vision runs | `docs/AUDIT.md` Low |
| Is the 400 ms deadline measured from the right moment? | Image age at execution can reach about 580 ms. Decide after reading `counters.late` on `/arm/pose` during the first real handovers | `docs/AUDIT.md` M6, M7 |

## Software left (small, owned)

| What | Who |
| --- | --- |
| `explore/arm_session.py`: refuse to record while another process holds the follower port (`arm.backends.port_holders`), like `arm.record` and `arm.teach` already do | Caiden |
| `docs/OVERVIEW.md` section 2: "and turnover is high" has no source; use "a surgical tech job takes about 120 days to fill (Periop Leader, 2024)". Section 7: the gripper guard and heat watching now hold for the real arm too (comb H6) | Anish |
| P2: build the Google Slides deck from `docs/SLIDES.md` and paste the link there | a person |
| Q4: screen-record `python -m controller.run_all backup` with the dashboard as the backup video | Evan or Caiden |

## Sunday, before judging

- Fill every `[measured]` in `docs/PITCH.md`, `docs/DEVPOST.md` and the slides from `GET /stats` (real-arm tries only; fake-arm rows are left out).
- E7 demo video (2 to 3 min) from the shot list in `docs/DEVPOST.md`; A12 Perceptron arm video.
- P5: rehearse three times with the roles in `docs/DEMO.md`, under 3 minutes.
- 8:30 AM: `docs/README-PUBLIC.md` becomes `README.md`, repo made public (history already scanned: no keys).
- 9:30 AM: final Devpost submitted. P6 Commit Fellowship form after.
