# Codex: "Which one?" (ask back when a request matches more than one instrument)

For Codex on Anish's Windows laptop. Paste the block below into a fresh Codex chat. It starts with zero context, so the block tells it how to get it.

---

```
You're working on Scrub, a DubHacks '26 project: an SO-101 robot arm that passes surgical instruments by voice over a phone call. We're on a hard time crunch. Final Devpost by 9:30 AM Sunday, judging at 10:30. Work without asking me questions, finish the feature, test it, and push it. Use parallel sub-tasks or agents if you can.

The repo is github.com/anish-agr/dubhacks-2026. Other agents on another computer (Caiden's Mac, where the arm is) are pushing to main every few minutes, and the design has shifted a lot tonight. Never pull or push in C:\Users\anish\Documents\GitHub\dubhacks-2026 itself: its main is out of sync. Make your own worktree:

  cd C:\Users\anish\Documents\GitHub\dubhacks-2026
  git fetch origin
  git worktree add -b codex/which-one ..\dubhacks-2026-codex origin/main
  cd ..\dubhacks-2026-codex
  Copy-Item ..\dubhacks-2026\.env .env      (never print it, never commit it)

## Step 1: learn what the project is now (20 minutes, read only)

Plans changed overnight, so learn from the code and the history, not from old docs:
- Read team/CONTEXT.md Part 1 (the whole project in one place), then team/LEFT.md, docs/INTEGRATION.md, docs/PICKING.md, docs/CONTRACTS.md, explore/station/README.md.
- Run `git log --since="6 hours ago" --stat` and read the last 40 commit messages. Right now the real arm runs through explore/station (the recording station, with a Run mode where explore/station/autopick.py drives the arm by itself: Perceptron detect plus Gemini find the handle, the arm picks it and offers it to a hand). The full product path is voice/ (TypeScript, Gemini parses words into one command) -> controller/ (FastAPI, port 8000, --skills smart picks a method per item via controller/picker.py) -> arm/.
- Write what you learned in 15 lines at the top of your final report.

## Step 2: build "Which one?"

When a request could mean more than one instrument, Scrub asks back instead of guessing, and the next thing the person says settles it.

Two ways it happens:
1. **By name.** The words match more than one item in the current tray. Example: the bench tray has two screwdrivers, a flathead and a Phillips, and the person says "screwdriver". Scrub says "Which screwdriver: the flathead or the Phillips?" Settings need a way to say two items share a word: add an optional `group` field (for example `"group": "screwdriver"`) and give each item a short distinguishing `variant` word ("flathead", "Phillips", "curved", "straight"). Add a Phillips and a flathead screwdriver to settings/bench.json as a working example (with pick and return instructions in the existing format), and a curved and a straight hemostat example only in tests, so the surgical tray used for training doesn't change.
2. **By sight.** The camera sees two of the same item, for example after a restock ("add a second hemostat"). Scrub says "I see two hemostats: the left one or the right one?" Left and right are from the surgeon's side of the table; use the tray's slot positions or the detected boxes to decide which is which, and say "the one closest to you" when there are more than two.

The answer can be the variant word ("Phillips"), a position ("left", "the right one", "closest", "the first one"), a number ("the second"), or the full name. "Either", "any" or "you pick" picks the one with the best measured success rate, or the nearest one. "Never mind" or "cancel" drops it. "Stop" always stops the arm at once, even while a question is waiting. A question waits about 15 seconds; then Scrub says "I'll wait for you to ask again" and clears it.

Where the code goes (read each file first, change as little as possible, keep every existing test passing):
- voice/src/parse.ts and voice/src/turn.ts: detect the ambiguity before calling the controller (deterministic matching first; Gemini's schema gets an optional `clarify` action with candidates only for phrasing the rules don't catch), keep the pending question per call or text thread, and resolve the next utterance against it. The spoken question goes back through the same reply path as other lines, so it works on the phone call and in texts.
- controller/: accept an optional `instance` hint on a handover command (`{"variant": "phillips"}` or `{"side": "left"}` or `{"slot": 2}`), pass it to the picker and the locate step so the arm goes to that one, and emit a `clarify` event (`say`, `candidates`, `item`) when the controller itself finds the ambiguity (the by-sight case). Add the optional fields to docs/CONTRACTS.md. Never rename or remove a field.
- explore/station/autopick.py: when detection returns more than one candidate for the target, use the hint if there is one, else ask through the station page (two buttons: left and right) and log it.
- The dashboard and ops page: show a waiting question ("Which screwdriver: flathead or Phillips?") in the existing event log style. Use design/scrub.css only; no new styles beyond what the design system already has.
- settings/README.md and voice/README.md: document `group`, `variant` and the hint.

What already exists, so you build on it instead of duplicating it: an unknown request gets "Which instrument? You can say: call the hemostat a clamp" (`controller/lines.py` `unknown`, `controller/core.py` around the teaching hint), clinics can teach new words ("call the hemostat a clamp" writes `settings/<id>.local.json`), and voice drops stale spoken lines (`voice/src/turn.ts`). There is no multi-turn question with a pending state yet, and no left/right resolution. That's what you add.

After "Which one?" works and is pushed, add conversation context on the same pending-state machinery, each with tests:
- "Another one" or "same again" repeats the last item handed in this call; "the other one" means the other candidate from the last question.
- "Put it back" or "take it back" means the last item handed to this person.
- If the item asked for is already out ("hemostat" while the only hemostat is in the surgeon's hand), say "The hemostat is with you" instead of failing, and offer the second one if the camera sees one.
- When Gemini's parse is unsure (a low-confidence or two-way parse), confirm before moving: "Mayo scissors?" and go on "yes", drop on "no".
- Log every question and answer as events (`clarify`, `clarify_answer`, with the time to answer) so the data page can show how often Scrub had to ask and how fast people answered.

## Step 3: prove it

- Unit tests in voice (npm test) for: two names match, the variant answer, left/right, "the second", "either", "cancel", "stop" during a question, the timeout, a text thread and a call each keeping their own question, and a single match never asking.
- Controller tests with the fake arm for the hint reaching the picker and the by-sight `clarify` event.
- An end-to-end run on the sim: start `python -m controller.run_all --offline --base-port 8300 --setting bench --no-open`, send "screwdriver" through the voice path (or POST the same command the voice server sends), answer "Phillips", and check the arm picks that one. If the sim has only one screwdriver body, add a second one to the sim scene the same way the other items are defined, and say so.
- Run every test suite you touched: `python -m pytest -q controller voice` (and `cd voice; npm test`), `python -m pytest -q explore/station`, `python -m pytest -q sim/test_sim.py`.

## Step 4: land it on main safely

- Commit in small pieces with plain messages. Before each push: `git fetch origin; git rebase origin/main`, rerun the tests for what you touched, then `git push origin HEAD:main`.
- Before editing any file, run `git log -1 --format=%ar -- <file>`. If someone else changed it in the last 10 minutes, rebase first and re-read it, so you don't overwrite their work.
- If a rebase conflicts in a file another agent is actively changing, keep their version, re-apply your change on top, and test again.
- When done: `git status` clean and nothing ahead of origin/main. Remove your worktree only after the push succeeds.

## Writing rules for any text a person will see or hear

Short and plain, in the voice of an operating room ("Which hemostat: curved or straight?"). No em dashes, no emojis, no filler words.

## Final report

What you learned about the current system (15 lines), what you built, each test suite and its result, the sim run's output, the commits on main, and anything left for a person.
```
