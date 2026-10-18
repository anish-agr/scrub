# Live demo run

Scope: surgical first. The operating room tray is the demo. The robotics bench tray is the second setting, shown to prove a new setting needs only demos and no new code. No dental tray in the demo.

Numbers in [brackets] come from the dashboard tables. Say them only after Sunday's tests are logged. Until then, do not say a number.

## Roles

| Role | Who | Does |
| --- | --- | --- |
| Speaker | Anish | Gives the pitch (one person speaks, see `docs/PITCH.md`). Stands by the judge. Calls the recovery lines |
| Clinician on the phone | Brandon | Hands busy. Calls the Photon number on speaker. Says the instrument words. Receives the handoffs. Brings a second phone as a spare caller |
| Operator | Caiden | At the demo console laptop (`http://localhost:8000/demo`). Keeps a hand near Space. Runs reset between judges |
| Tray resetter | Evan | Puts instruments back in their slots, switches trays, turns the lamp on and off. Watches the dashboard facing the judge |

Anish owns the arm, so he also makes the call on "arm is dead, go to backup."

## Setup checklist (before judges arrive)

- [ ] Power strip on. Arm powered, clamped, area around it clear. Overhead camera seen in `http://localhost:8001/`.
- [ ] `python -m controller.run_all --arm real --vision real --tunnel` is running. Add `--judge` if the console will be handed to a judge.
- [ ] `python -m controller.run_all check` shows the whole stack green (controller 8000, vision 8001, voice 3000).
- [ ] Surgical tray on the blue towel: scalpel handle, hemostat, Mayo scissors in their slots. Return spot and safe spot empty and marked.
- [ ] Lamp off. Normal light. Dashboard at `http://localhost:8000/` facing the judge. Tablet at `/tablet.html` across the room if there is room.
- [ ] Demo console open at `http://localhost:8000/demo`. Press `1` (surgical) and `R` (reset and clear count).
- [ ] Phone on speaker, volume up, second phone or laptop mic next to it. One test call: say "hemostat" once and watch it arrive, then put it back.
- [ ] Bench tray (needle-nose pliers, wire cutters, hex key) set aside within reach of Evan.
- [ ] Backup ready: sim arm works (`python -m controller.run_all backup` tested once), slides open (`docs/SLIDES.md` deck), backup video on the laptop.
- [ ] Everyone knows the stop rule: anyone who sees a problem says "stop". Operator hits Space.

## Between judges

1. Operator runs `python -m controller.run_all reset` (clears the count, surgical tray, normal lighting). On the console, `R` does the reset and clears the count too.
2. Evan puts every instrument back in its slot and clears the return and safe spots. Lamp off.
3. Operator presses `1` to confirm the surgical tray.
4. Brandon hangs up and calls again if the call went quiet.
5. Look at the dashboard: count is 0, step is idle, no "vision stale". Ready.

## 3-minute slot

Anish speaks the whole time. The demo runs during the pitch. Times match `docs/PITCH.md`.

| Time | Who | Say (word for word) | Judge sees | If it fails |
| --- | --- | --- | --- | --- |
| 0:00 | Anish, Brandon stands with hands busy | "Clinics cannot hire enough assistants. A surgical tech job stays open about four months. When nobody is there, the clinician turns away from the patient, puts down what they are holding, and searches the tray." | Brandon holding something, not free to reach | Nothing to fail. Keep talking |
| 0:30 | Anish, then Brandon on the phone | Anish: "This is Scrub. It is an operating room tray, and the clinician just asks." Brandon: "Hemostat." | Scrub answers on speaker. Arm picks the hemostat, brings it to Brandon's open hand, handle first. He pulls, gripper opens. Dashboard shows the handoff seconds | Call drops or no answer: Caiden clicks the hemostat button on the dashboard or presses the console key. Say: "Same command, no phone." Arm misses: Scrub retries once on its own. If it misses again, say "It tells you out loud when it cannot, and it never guesses." Move on |
| 0:50 | Anish, Brandon | Anish: "Scalpels never pass hand to hand." Brandon: "Scalpel." | Arm sets the scalpel on the safe spot. Scrub says "scalpel down" | Arm goes toward the hand: Space at once, then R. Say "That is the stop. It latches until a person resets." |
| 1:05 | Anish to the judge | "Your turn. Ask for the scissors." | Judge says "scissors" (or "Mayo") to the phone. Scrub delivers Mayo scissors to the judge's open hand | Judge not heard: Anish says "Say it once more, close to the phone." Still nothing: Caiden presses `C` on the console (sends the cue's request) and says "That is the console path." If the judge asks for something else, judge mode only allows an instrument, the count, or stop |
| 1:20 | Evan, Anish | Anish: "When a clinician is done, they set it in the return spot." Evan places the hemostat in the return spot | Scrub says "returning the hemostat" and puts it in its slot | Return not seen after 5 s: Caiden says "return the hemostat" into the phone or uses the console. If it still fails, Evan slots it by hand. Say "It does this on its own after two seconds when the camera sees it" only if that worked in testing |
| 1:40 | Evan, Anish | Anish: "Operating room lights are harsh. Steel throws glare." Evan turns on the lamp over the tray | Glare on the steel. Brandon asks for an instrument. It still arrives. Anish points to the lighting table on the dashboard | Miss in glare: Scrub retries once. Say "This is why we log bright, normal and dim: [measured]% in bright, [measured]% in normal." Lamp off afterwards |
| 2:00 | Evan, Anish, Brandon | Anish: "Same arm, same code, second setting." Evan swaps to the bench tray. Caiden presses `2`. Brandon: "Needle-nose pliers." | Arm brings the pliers. Dashboard shows the bench setting | Swap fails: Caiden presses `2` again once the arm is idle (tray switch only works when idle or stopped). If it will not work, show the dashboard bench table and say "Adding this setting took [measured] minutes of demos and no new code." |
| 2:30 | Brandon, Caiden, Anish | Brandon: "Count." Anish: "Scrub reads back what is still out, so nothing is left behind at the end of a case." | Voice reads the count. Caiden sends the end-of-case summary (`POST localhost:3000/summary`). Text arrives on Brandon's phone | Summary text late: show the dashboard count and say "The same summary is on the case page." Count wrong: say "The camera also checks the count" and move on |
| 3:00 | Anish | "Questions." | Team answers by area. See `docs/QNA.md` | None |

At any point, if something is not right: say "stop" or Space, then `R`. A stop is a feature, not a failure. Say so.

## 1-minute version

Anish speaks short. Three beats only: a handoff, the judge's turn, the count.

| Time | Who | Say (word for word) | Judge sees | If it fails |
| --- | --- | --- | --- | --- |
| 0:00 | Anish | "Clinics cannot hire enough assistants, so the doctor turns away to search the tray. This is Scrub. It is an arm that hands you instruments when you ask out loud." | Tray, arm, dashboard | None |
| 0:15 | Brandon | "Hemostat." | Arm hands the hemostat handle first. Dashboard shows the seconds | Call drops: Caiden uses the console. Miss: it retries once. Then say the line |
| 0:30 | Anish, judge | "Now you. Ask for the scissors." | Judge asks. Mayo scissors arrive at their hand | Not heard: Caiden presses `C` |
| 0:45 | Brandon, Anish | Brandon: "Count." Anish: "It reads back what is out. Scalpels go to a safe spot, and it works on a second tray with no new code." | Count read aloud. Summary text arrives if time allows | Skip the text. Show the count on the dashboard |
| 1:00 | Anish | "Training and research prototype. Happy to answer questions." | | |

Skip scalpel, return, lamp and the bench tray in the short version unless the judge asks. Do them in the Q&A if there is time.

## Failure table

| What fails | What you see | What to do | Who |
| --- | --- | --- | --- |
| Call drops or phone silent | No "heard" on the dashboard | Brandon calls again. If it fails twice, use the dashboard item buttons or the console keys. Say "Same controller, typed instead of spoken" | Caiden |
| Phone audio not heard | Wrong word or nothing | Say it again, closer. Use `C` on the console | Brandon, Caiden |
| Wi-Fi down | Tunnel and Gemini unreachable; voice stops | Use local voice through the demo console and the dashboard buttons. Stop still works with no network because it skips Gemini. Public judge page may be stale | Caiden |
| Arm misses the grasp | "checking" then a retry | Scrub retries once. If it misses again it says so out loud. Say the line: "It reports a miss instead of guessing." Reset tray, continue | Anish, Evan |
| Arm goes wrong or slow | Moves toward the wrong place | Space or "stop". Then R. Explain the latch | Caiden |
| Arm dead or will not move | Errors, no motion, stopped latch will not clear | `python -m controller.run_all backup`. It switches to the MuJoCo sim arm and plays a scripted full run. Then switch to the slides and the backup video | Anish decides, Caiden runs |
| Hand not found | Scrub says "No hand." and sets the item at the safe spot | Brandon opens his palm in view of the camera. Say "It will not move to a hand it cannot see." Try once more | Brandon |
| Vision stale | Dashboard says "vision stale" | Check the camera cable and `http://localhost:8001/`. The arm still runs on the saved spot | Brandon |
| Lighting breaks the camera | Missing detections under the lamp | Lamp off. Say the lighting table numbers | Evan |
| Stop pressed | Arm frozen; handovers refused with "I'm stopped. Reset me first." | Space or "stop" freezes it. R resets, rearms and clears the count. Run `python -m controller.run_all reset` between judges | Caiden |
| Summary text does not arrive | No text on the phone | Show the case summary on the dashboard. Say the text is sent through Photon | Caiden |
| MongoDB down | Ledger errors | Events go to a local file and upload later. Say that | Evan |
| Judge asks something odd | Console in judge mode only passes instrument, count, stop | Say "Good one, we do not do that yet." Do not improvise a motion | Anish |

## Rules for the table

- Never say a success rate unless it is on the dashboard. Use [measured] until it is.
- Never claim clinical use. Say "training and research prototype."
- Stay at the table the whole round.
