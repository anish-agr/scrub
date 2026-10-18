# Live demo run

Surgical first. The operating room tray (scalpel handle, hemostat, Mayo scissors) is the demo. The robotics bench tray (needle-nose pliers, wire cutters, hex key) comes second, to show a new setting needs new demonstrations and a settings file, not new code.

The words to say are in `docs/PITCH.md`. This file is who stands where, what each person does, and what to do when something fails. The beat times match the demo console at `http://localhost:8000/demo`.

Numbers: say a success rate or a time only once it is on the dashboard. Until then it is `[measured]` and you skip the sentence.

## Roles

| Person | Stands | Speaks | Runs |
| --- | --- | --- | --- |
| Anish | Next to the judge, facing them | The problem, "This is Scrub", the second tray, the close | Decides "the arm is dead, go to backup" (he owns the arm) |
| Caiden | At the demo laptop, one hand near Space | Sharps and stop, the judge's turn, the return and the count | The demo console keys, the stop key, the reset between judges |
| Evan | Beside the lamp and the spare tray, out of the camera | The lighting test and the tables | Lamp on and off, swaps the trays, puts instruments back between judges, turns the dashboard screen to the judge |
| Brandon | Across the tray from the arm, as the clinician | Hand tracking | The phone call on speaker. Asks for each instrument and takes the handoffs. Keeps a spare phone |

Stop rule: anyone who sees a problem says "stop" out loud. Caiden hits Space at the same moment.

## Setup (before the first judge)

Commands run from the repo root on Caiden's Mac.

1. Power strip on. Arm powered and clamped. Clear space around it.
2. Start everything:
   ```
   .venv/bin/python -m controller.run_all --arm real --vision real --tunnel --ledger
   ```
   It waits for each part and prints every URL: dashboard, demo console, nurse console, tablet, vision preview, voice health, the tunnel and the judge page. Add `--judge` if a judge will touch the laptop (then the controller only takes handover, count, stop and got it).
3. Paste the printed tunnel URL plus `/v1` into the ElevenLabs agent's Custom LLM Server URL. Free tunnels change every start and end after 60 minutes, so recheck this before each judging block.
4. In a second terminal, check the running stack without moving the arm:
   ```
   .venv/bin/python -m controller.run_all check --url http://localhost:8000 --vision-url http://localhost:8001 --voice-url http://localhost:3000
   ```
   Everything should read PASS. "handover -> ledger" says SKIP on the real arm. That is expected. The check switches to the bench tray and back, so run it before you lay out the tray.
5. Surgical tray on the blue towel: scalpel handle, hemostat, Mayo scissors in their slots. Return spot and safe spot empty.
6. Lamp off. Overhead camera picture looks normal at `http://localhost:8001/`.
7. Dashboard `http://localhost:8000/` on the screen facing the judge. Tablet view `/tablet.html` across the room if there is space.
8. Demo console `http://localhost:8000/demo` on the laptop. Press `1` (surgical), then `R` (reset and clear the count). The preflight row should be all "ok".
9. Brandon calls the Photon number on speaker. Volume up. Second phone or the laptop mic next to it if we are filming. Say "check the tray". Scrub should answer that the tray is ready. Then one test: "hemostat", take it, put it back.
10. Bench tray within Evan's reach. Backup video open on the laptop. Slides open (`docs/SLIDES.md`).

## The 3-minute run

The console's run clock starts when Caiden presses Enter on "This is Scrub". Each arm beat moves on by itself when the arm is done. The sharps, return and lighting beats run a little long. The second tray beat has slack to make it up.

| Time | Who | What happens | Judge sees | If it fails |
| --- | --- | --- | --- | --- |
| 0:00 | Anish speaks. Brandon stands with his hands busy | The problem: the scrub tech shortage and the search for the tray | A clinician who can't reach | Nothing can fail. Keep talking |
| 0:30 | Anish, then Brandon says "Hemostat." | Scrub says "hemostat coming", picks it, brings it to Brandon's open hand handle first. He pulls and the gripper opens | The handoff and the seconds on the dashboard | No answer on the call: Caiden presses `C` (sends the cue's request). Anish says "Same command, typed instead of spoken." A miss: Scrub retries once by itself. A second miss: Scrub says so. Anish: "It tells you when it can't. It never guesses." Move on |
| 0:50 | Brandon says "Scalpel." Caiden speaks | The arm sets the scalpel on the safe spot. Scrub says "scalpel down." Brandon picks it up from the spot | The scalpel never comes to the hand | Anything heads the wrong way: Space at once. Caiden: "That's the stop. It holds until a person resets it." Then `R` |
| 1:05 | Caiden invites the judge. Then Brandon speaks | The judge says "scissors" (or "Mayo") to the phone. Brandon steps back so the judge's hand is the only open hand | Mayo scissors arrive in the judge's hand | Not heard: "Once more, close to the phone." Still nothing: Caiden presses `C`. If the judge asks for something odd: "Good one. Today it hands instruments, counts and stops." |
| 1:20 | Brandon sets the hemostat in the return spot. Caiden speaks | After about 2 seconds, Scrub says "returning the hemostat" and puts it in its slot | The return, then the count line on the dashboard | Not picked up in 5 s: outside judge mode, Brandon says "return the hemostat." In judge mode (return is not allowed), Evan slots it by hand. Do not claim the automatic return unless it worked |
| 1:40 | Evan turns the lamp on and speaks. Caiden presses `L` (bright). Brandon asks for any instrument | Glare on the steel. The handoff still works. Evan points at the lighting table | The live table by lighting | A miss in glare: it retries once. Evan: "This is why we test bright, normal and dim." Lamp off. Do not say a rate that is not on the table |
| 2:00 | Evan: lamp off, swap to the bench tray. Caiden: `L` back to normal, then `2` once the tray is down. Brandon: "Needle-nose pliers." Anish speaks | The pliers arrive | The dashboard shows the robotics bench tray | `2` refused: the arm is busy. Wait for idle and press `2` again. Still failing: show the bench row of the table and say it in words. Never fake it |
| 2:30 | Brandon: "Count." Then "End of case." Caiden, then Anish | Scrub reads what is out. The summary text arrives on Brandon's phone | The count read aloud, the text on the phone | No text: Caiden runs `curl -XPOST localhost:3000/summary`. Still none: show the case page on the dashboard. Count looks wrong: "The camera also checks the count," and move on |
| 3:00 | Anish | "Questions?" | | Answers by area, see `docs/QNA.md` |

## The 60-second version

For a judge in a hurry. Press `K` on the console for the short cue cards.

| Time | Who | Say | Judge sees | If it fails |
| --- | --- | --- | --- | --- |
| 0:00 | Anish | "Hospitals can't hire enough scrub techs. A surgical tech job takes about 120 days to fill. So the surgeon stops to search the tray. This is Scrub. You ask out loud." | The tray, the arm, the dashboard | Nothing |
| 0:15 | Brandon: "Hemostat." | | The hemostat arrives handle first. The seconds on the dashboard | No answer: Caiden presses `C`. A miss: it retries once |
| 0:30 | Caiden | "Your turn. Ask for the scissors." | Mayo scissors arrive in the judge's hand | Not heard: `C` |
| 0:45 | Brandon: "Count." Anish | "It keeps the count. Scalpels go to a safe spot, never hand to hand. And a second tray works with no new code. It's a research prototype. Questions?" | The count read aloud | Skip the text. Show the count on the dashboard |

Skip the scalpel, return, lamp and bench tray in the short version. Show them during questions if there is time.

## Between judges (about 60 seconds)

1. Caiden runs `.venv/bin/python -m controller.run_all reset`. It waits for the arm to go idle, resets it (this also clears a stop), clears the count, loads the surgical tray and sets normal light. It prints "READY for the next judge". (On the console, `R` resets and clears the count, `1` loads surgical, `L` sets normal.)
2. Evan puts every instrument back in its slot. Return spot and safe spot empty. Lamp off.
3. Brandon checks the call is still live. If it went quiet, hang up and call again. Say "check the tray". Scrub should say the tray is ready.
4. Look at the dashboard: count 0, step idle, no "vision stale".
5. Every hour: check the tunnel is still up (`curl <tunnel>/health`). If not, restart it and paste the new URL into ElevenLabs.

## When something fails

| What fails | What you see | What to do | Who |
| --- | --- | --- | --- |
| Call drops or no answer | No "heard" on the dashboard | Brandon calls again. Twice failed: use the console (`C`) or the dashboard item buttons. "Same controller, typed instead of spoken" | Brandon, Caiden |
| Wrong word heard | Scrub asks "Which instrument?" | Say it again, closer to the phone. Then `C` | Brandon, Caiden |
| Wi-Fi down | Tunnel, Gemini and Photon unreachable | Use the console and the dashboard buttons. Stop still works with no network. The public judge page may lag | Caiden |
| Grasp missed | "checking", then a retry | It retries once, then says it missed. Evan resets the item. Continue | Evan |
| Arm heads the wrong way | Motion toward the wrong place | Space or "stop". Explain the latch. `R` | Caiden |
| Hand not found | Scrub says it has no hand and sets the item on the safe spot | Brandon opens his palm in the camera's view. "It won't move to a hand it can't see." Try once more | Brandon |
| Hand leaves mid-move | Scrub says "Lost your hand. Holding." | That is the safety rule working. Say so. `R` carries the item to the safe spot | Caiden |
| Vision stale | Dashboard says "vision stale" | Check the camera cable and `http://localhost:8001/` | Brandon |
| Lamp breaks detection | Missed detections under the lamp | Lamp off. Point at the table | Evan |
| Stopped and refusing | "I'm stopped. Reset me first." | `R` on the console or `run_all reset` | Caiden |
| Summary text missing | No text on the phone | `curl -XPOST localhost:3000/summary`. Then show the case page | Caiden |
| MongoDB down | Ledger errors in the terminal | Events go to a local file and upload later. Say that if asked | Evan |
| Arm dead | No motion, errors, stop will not clear | Anish calls it. Caiden presses Ctrl-C in the run_all terminal, then runs `.venv/bin/python -m controller.run_all backup`. The sim arm plays a full run on the same dashboard. Or press `B` on the console for the backup video, then the slides | Anish decides, Caiden runs |

`run_all backup` will not start while the real-arm controller holds port 8000. Stop it first, or run the backup beside it with `.venv/bin/python -m controller.run_all backup --base-port 8100` and show `http://localhost:8100/`.

## Rules for the table

- Say a number only if it is on the dashboard. Otherwise skip the sentence.
- Never claim clinical use. Say "research prototype".
- Never say Scrub prevents retained items or replaces scrub techs. It adds a second check and helps them.
- Stay at the table the whole round.
