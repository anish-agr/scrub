# DEV post draft (MLH DEV writing track)

For after the event, not part of the Devpost form. Publish on dev.to only if someone has time; the MLH DEV track counts only a published post. Every claim here comes from `devpost/SUBMISSION.md` and `devpost/FACTS-0718.md`; add nothing that isn't in them.

Title: Building Scrub: a robot arm that passes surgical instruments by voice

---

In an operating room the scrub tech passes each instrument the moment the surgeon names it. Hospitals can't hire enough of them: a surgical tech opening takes about 120 days to fill ([Periop Leader, 2024](https://www.periopleader.com/survey-staffing-woes-ease-slightly-but-challenges-remain/)). At DubHacks '26 (Oct 17 to 18) four of us built Scrub, an SO-101 robot arm that hands over the instrument you ask for out loud, then lets go when you pull it.

## What it does

You say "get the hemostat", "can I have the knife" or only "scalpel". The arm picks that instrument from the tray, carries it at a capped speed to a fixed handoff point and holds the handle out. It lets go when you pull it or say "let go", closes the jaw to check it is empty and goes home. "Stop" freezes it where it is until you say "continue", "go home" or "kill".

On Oct 18 the real arm handed a scalpel into a hand twice, at 06:39 and 07:02. The second was asked for by voice: "can you get me the scalpel" at 07:02:14, handle offered at 07:02:34, pulled out by hand at 07:02:35, jaw checked empty at 07:02:37.

## How the picks work

Each real pick is a replay of our own recorded demonstrations. We recorded 29 episodes with a leader arm (24 usable, 9.0 minutes). Autopick's "average" mode takes every usable demo of one instrument, cuts each at the same moments (start, above the item, grasp, lift, hand-off) and takes the median point by point, peaking at 45 degrees a second. The wrist camera delivered 22.6 fps on a shared USB 2.0 hub, the training validator wants 30, and the side camera moved after episode 17, so no training job ran until Sunday morning. At 08:49 we submitted a Perceptron fine-tuning job (`job_629682f9575271b687e2c734`) on a 14-episode "pick the scalpel" dataset that passed the validator; at 09:08 it was training at step 411 of 1000 with no deployment. No pick in the video comes from a model.

## The parts

- **Voice:** a local word match answers known instrument names and "stop" in under 25 ms. Anything else goes to Gemini (`gemini-3.8-flash`) with structured output whose item field is an enum of the tray's item ids, so it can't name an instrument that isn't there.
- **Vision:** Perceptron's detect reads the tray, and its OCR on `perceptron-mk1.5` read the printed count sheet correctly on 5 of 5 rendered sheets.
- **Ledger:** every event and the arm's motor temperatures go to MongoDB Atlas. A read-only public page runs on Vultr.
- **Simulation:** a MuJoCo SO-101 runs the controller's full flow, including a grasp check and a slow final approach that the real arm path does not have yet.

## What broke

The servos overheated holding still. With torque on at the folded rest pose, every motor rose about 5 C in 4 minutes. We cooled them with wet paper towels while we wrote the thermal guard: it checks motor temperatures every 2 s, sends the arm home with torque off at 60 C and resumes at 50 C. After that the hottest reading was 57 C.

Thin steel slipped out of the gripper, so we put magnets under the jaw tape. The magnets then lifted instruments off the tray during camera calibration, so the calibration sweep moved up to 8 cm and 4.5 cm above the table.

We also planned for the arm to set the scalpel down at a safe spot instead of passing it hand to hand. The arm couldn't do that step reliably, so we cut it.

## What's next

Deploy the scalpel fine-tune and run it on the arm. One clean dataset per instrument with fixed cameras at 30 fps, then a fine-tuning job per instrument, so the arm can find an instrument wherever it lies. Mayo scissors on the real arm (0 real runs so far). The controller's grasp check and slow zone on the real arm. Tagged ledger rows for every real handoff, so success rates come from real runs.

Code: https://github.com/anish-agr/dubhacks-2026
