# Tracks: what we enter and what we can say at each table

Rules (Hacker Guide): exactly 1 title track, at most 3 sponsored side tracks, any number of non-sponsored ones. Facts follow `devpost/FACTS-0718.md`. Each track lists what its judges want, what we can claim, the proof to show, and what not to say.

Recommended: Community Kitchen; Perceptron Robotics, Perceptron Perception and SideShift (or Photon in place of SideShift only if a call is found in Photon "Recent calls" or ElevenLabs "Call history" for 07:00 to 07:03 Sunday); DubHacks NEXT, MLH Gemini, MLH MongoDB Atlas, MLH Vultr, MLH Commit Fellowship, and MLH DEV if the post is published.

## Title track: Community Kitchen (health, accessibility, civic)

- **Their angle:** projects that serve people's health and access.
- **Say:** operating rooms are short of scrub techs (a surgical tech opening takes about 120 days to fill, [Periop Leader 2024](https://www.periopleader.com/survey-staffing-woes-ease-slightly-but-challenges-remain/)); when the tech is missing the surgeon looks away from the patient to search the tray. Scrub fetches the named instrument, holds it out, lets go when it is pulled or told "let go", never touches the patient, and logs every pass.
- **Show:** the arm video, the station page Talk tab.
- **Don't say:** that it is cleared for surgery or used on patients.

## Sponsored 1: Perceptron Robotics

- **Their angle:** their SO-101 and pre-trained checkpoint, your own demonstrations, a new task; judged on creativity, task difficulty and technical execution; a video of the working arm is required. Fine-tuning is allowed, not required.
- **Say:** we recorded 29 demonstration episodes on their arm (24 usable, 9.0 min) with our own recording station (`explore/station`), wrote our own control and safety layer (thermal guard, gripper guard, joint stall hold, speed caps, stop that freezes in place), and the real arm handed a scalpel into a hand twice on Oct 18 (06:39:20 and 07:02:37, the second asked for by voice). Each real pick replays our demonstrations: autopick's `average` mode cuts an instrument's demos at the grasp, lift and hand-off and median-averages them into one path, peaking at 45 deg/s. We also fine-tuned their pre-trained Isaac checkpoint on our own 14-episode "pick the scalpel" dataset: job `job_629682f9575271b687e2c734`, submitted 08:49 Oct 18 (expert_only, 1000 steps), training at step 411 of 1000 at 09:08. Task difficulty: thin, shiny steel; magnets under the jaw tape so steel doesn't slip; glare.
- **Show:** the arm video; `~/scrub-logs/station-20261018-065728.log` lines 07:02:14 to 07:02:37; `explore/station/autopick.py`; the dataset counts in `docs/DATA.md`; `python -m arm.train status job job_629682f9575271b687e2c734` and `~/scrub-logs/train-run-1.log` for the job.
- **Don't say:** that the picks come from a fine-tuned model, or that the fine-tuned model moved the arm. The job was still training at 09:08 and `python -m arm.train deployments` returned `{"items": []}`; recheck both before submitting. Our local QA flagged 10 of the 14 episodes it trained on.

## Sponsored 2: Perceptron Perception

- **Their angle:** creative uses of their vision API out of the box (localization, OCR, captions, video).
- **Say:** detect reads the tray and reports what is missing (HTTP 200 in about 1.8 s); OCR on `perceptron-mk1.5` reads the printed count sheet and reports where it disagrees with Scrub's count (5 of 5 rendered sheets correct, 1.8 to 2.3 s, `docs/INTEGRATION.md`). Gemini is the OCR fallback.
- **Show:** `vision/tray.py`, `vision/reading.py`, the vision page on :8001.
- **Don't say:** that Perceptron's API drives the real arm's picks (the station uses a local detector and demo replays), or OCR accuracy on real paper sheets (measured on rendered sheets).

## Sponsored 3 (pick one)

### SideShift (recommended unless the Photon call is confirmed)

- **Their angle:** the strongest startup idea of the weekend, any stack; judged in person.
- **Say:** buyer is hospital perioperative leadership; operating-room time costs about $36 a minute ([Childers and Maggard-Gibbons, JAMA Surgery 2018](https://jamanetwork.com/journals/jamasurgery/fullarticle/2673385)); break-even at about 22 OR minutes a month (`docs/BUSINESS.md`); a $250-class arm instead of a staffing gap.
- **Show:** `docs/BUSINESS.md`, the video.
- **Don't say:** market sizes or pilot customers that aren't in `docs/BUSINESS.md`.

### Photon (only with a confirmed call)

- **Their angle:** an agent live on a Photon channel; voice agents on a phone number called out.
- **Say:** the number +1 785 867 1047 routes through Photon SIP to our ElevenLabs agent and `voice/`; the shared iMessage line could not take calls, so we moved to the SMS number.
- **Show:** the call history entry for 07:00 to 07:03, if found.
- **Don't say:** that a phone call moved the arm unless that entry exists. The Photon text listener errors (projectId validation), so don't claim summary texts were delivered.

## Non-sponsored

| Track | Say | Proof |
| --- | --- | --- |
| DubHacks NEXT | Buyer, price, break-even about 22 OR minutes a month at about $36 a minute | `docs/BUSINESS.md` |
| MLH Best Use of Gemini API | `gemini-3.8-flash` turns a spoken request into one command whose item must come from the tray's fixed list (structured output, enum of item ids); known names skip Gemini and answer locally in under 25 ms | `voice/src/parse.ts`, `voice/README.md` |
| MLH Best Use of MongoDB Atlas | Atlas holds the event ledger (70,975 events) and the arm's motor temperature log (`scrub.thermal`) | `ledger/logbook.py`, `explore/thermal_log.py`, `docs/DATA.md` |
| MLH Best Use of Vultr | The public judge page runs on a Vultr server | http://144.202.95.111/, `deploy/` (confirm the page shows current text first) |
| MLH Commit Fellowship | Working prototype on a real staffing problem | Tick it, then mlh.link/commit-fellowship-form after submitting |
| MLH DEV writing | Only if a post is published on dev.to | the draft in `devpost/DEV-POST.md` |

## Not entering

| Track | Why |
| --- | --- |
| Cloudforce, VEYZL, T-Mobile, SpaceXAI | Each needs a separate project or unrelated data |
| MLH GoDaddy Registry | No domain registered |
| MLH Tiger Data, MLH Backboard | Nothing runs against them |
| A separate MLH ElevenLabs track | None listed in the guide; ElevenLabs is in Built with |

## Numbers safe to quote anywhere

29 episodes, 24 usable, 9.0 min recorded; 35 real station runs on Oct 18 (7 calibrate); 2 real handoffs into a hand (scalpel, 06:39 and 07:02); 1 Perceptron fine-tuning job (training at 09:08, 0 deployments); thermal guard checks every 2 s, rests with torque off at 60 C, resumes at 50 C; autopick peak 45 deg/s; voice replies on the station path in about 20 to 100 ms. Never quote ledger success rates (0 trustworthy real tries in the ledger).
