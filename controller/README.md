# controller

Owner: Caiden. Tasks C1, C2, C5, C6, C8 in `docs/TASKS.md`.

FastAPI on port 8000. Owns the arm and every safety rule. Endpoints and messages are in `docs/CONTRACTS.md`. Serves `dashboard/` at `/` (a placeholder page with item buttons until `dashboard/index.html` exists).

## Run

```
python3.10 -m venv .venv && .venv/bin/pip install -r controller/requirements.txt   # once, from the repo root
.venv/bin/python -m controller                # fake arm (default), port 8000, surgical tray
.venv/bin/python -m controller --real-arm     # imports arm/real_arm.py (class Arm or RealArm)
.venv/bin/python -m controller --sim-arm      # MuJoCo SO-101 from sim/, see "Testing in the sim" below
```

Options: `--port`, `--setting surgical|dental|bench`, `--motion-s 0.2` (fake arm seconds per motion), `--pull-s 2` (fake arm: simulated pull this long after reaching the hand; `0` = wait for `got_it`).

Try it:

```
curl -XPOST localhost:8000/command -H 'content-type: application/json' -d '{"action":"handover","item":"hemostat","source":"keyboard"}'
curl -XPOST localhost:8000/stop
curl localhost:8000/state
websocat ws://localhost:8000/events      # or open http://localhost:8000/
```

## Files

| File | What |
| --- | --- |
| `server.py` | the endpoints |
| `core.py` | state, events, the step machine (one worker thread runs arm calls; `stop` never waits on it) |
| `lines.py` | every line Scrub says (`say`). Change wording here only |
| `fake_arm.py` | the arm interface with sleeps, plus forced failures |
| `settings.py` | loads `settings/<id>.json`, built-in defaults until those files exist |

## Behaviour other parts should know

- Every spoken line arrives as an Event `say`. The `say` in the `/command` reply repeats it; the voice server should speak events only, so lines aren't said twice.
- A `command` event goes out for every command, with extra fields `action`, `heard`, `source`, `accepted`, `reason`.
- Handover: `finding` (skipped with "I don't see the X" if a fresh TrayState says the slot is empty) → `picking` → `checking` (gripper ≥ 0.95 means it closed on nothing; a fresh TrayState still showing the item also fails) → one retry → `moving_to_hand` (carry pose, then to 8 cm short of the target at speed 0.3, then in at 0.1) → `waiting_for_pull` (load jump over `PULL_LOAD_DELTA`, default 80, or `got_it`; 30 s) → `releasing` → `homing`.
- Sharp items (`"sharp": true`) go `setting_down` to the safe spot instead: "Scalpel down."
- **Stop latches.** The real arm stays frozen after `freeze()` until `resume()` (`arm/real_arm.py`), and so does the fake arm. After `stop` or an `error`, handover and return are refused with "I'm stopped. Reset me first." until `POST /reset` (the dashboard's clear-stop button). Reset rearms, homes, and if the gripper still holds an item, sets it at the safe spot instead of opening where it froze. Reset keeps the count (an item held at the stop counts as out); `POST /reset {"clear_count": true}` clears it for a fresh demo run.
- Hand tracking counts as running if a Hand arrived in the last 5 s. Then the arm waits up to 10 s for an open, seen hand with a valid `target` and `path_clear` (else it sets the item down: "No hand."). While moving it freezes if the hand is lost (older than 0.5 s) or the path blocks, and holds like a stop: "Lost your hand. Holding." or "Something's in the way. Holding." No automatic retry; a reset carries the item to the safe spot.
- An arm exception, or `set_down_safe_spot()` returning False ("Couldn't set it down. Holding."), freezes the arm and goes to `error`.
- Pull: a load change of more than `PULL_LOAD_DELTA` either way (the bus value is signed; measure it on the real arm), or `got_it`. If `gripper_load()` has no reading, Scrub says "Say got it when you have it." and waits for `got_it`.
- Grasp check: gripper at or above `GRIPPER_CLOSED` (0.95) means it closed on nothing. The tray check runs after the lift to carry, using only a non-stale TrayState from at least 1 s after the pick. A return counts only if a later TrayState shows the item back in its slot (when tray vision is running).
- Tracking stays "running" for 5 s after the last Hand post. Fake-hand drills need about a 6 s gap between them, or the next handover waits for a hand instead of using the saved spot.
- Out of region: if the point 8 cm short of the hand is refused (and the hand watcher didn't freeze it), the arm goes straight to the hand slowly. Only if the hand point itself is refused does it say "That's out of my reach" and set the item down (`/fake/force {"out_of_region": 2}` forces that). With no Hand posts at all it goes to the saved spot (`handoff_spot` in `arm/rig.json`, else `[0.22, -0.10, 0.18]`).
- `return` with no item takes the return-spot item from a fresh TrayState, else the last item out.
- `count` answers at once, even mid-handover. Up to 3 handovers queue; `stop` clears the queue.
- Switching trays (`POST /setting`) only works when idle or stopped, and clears `out`.
- `ledger` is used if `ledger.log` exists; otherwise `/stats` comes from memory.

## Extra endpoints (not needed by other parts)

- `GET /setting`: the current setting file (the voice server can read item ids and aliases here).
- `GET /events/recent?n=50`: the last events, for a page that loads mid-run.
- `POST /fake/pull`: simulate the clinician tugging the item (sim arm), otherwise the same as `got_it`.
- `GET /demo`: the judging console (P4). Keys 1/2/3 load the surgical, dental and bench trays, R resets and clears the count, Space or Esc stops (latched), C sends the current cue's request, G is got it. A 3:00 clock with the PITCH.md beats and who does what, and a rehearsal log for P5. `demo.html` is a copy of `explore/prototypes/48-judge-run.html`.
- `POST /fake/force` with `{"miss_grasp": 1, "out_of_region": 1, "skill_fail": 1, "no_pull": 1, "no_load": 1}`: the next fake-arm calls fail that way (testing C6).

## Tests

`.venv/bin/python -m controller.test_flows` forces every failure case on the fake arm (grasp miss and retry, tray grasp check, stale tray, empty slot, no pull, no load reading, load drop, `got_it`, no hand, hand lost and path blocked holding until reset, failed set-down, arm exception, out of region, stop mid-pick, mid-move and while holding out, sharp set-down, return checked against the tray, count, rejects). About 40 s, prints `30/30 passed`.

## Full runs (Checkpoint 1, C8)

`.venv/bin/python -m controller.smoke` runs a full pass against a live controller: every item handed over (simulated pull on fake/sim arms), then the count. `--return` adds put-backs, `--runs 10 --human` is the C8 ten-in-a-row check on the real arm (a person takes each item and resets the tray), `--url` points elsewhere. It prints each line Scrub said, request-to-hand times, and the clean streak.

## Testing in the sim

`.venv/bin/python -m controller --sim-arm` runs the controller on the MuJoCo arm and, in the same process, the sim server on `--sim-port` (8002): watch it at `http://localhost:8002/web/viewer.html` (Live mode) and use `http://localhost:8002/stream` as a fake camera. Needs `sim/requirements.txt`. Run it in a normal terminal so Ctrl-C works.

`controller/sim_vision.py` stands in for `vision/`: a TrayState every second from where the sim's instruments really are, and a Hand at 10 Hz when switched on. Knobs:

```
curl -XPOST localhost:8000/sim/hand -H 'content-type: application/json' -d '{"on": true}'        # hand tracking on (default off = saved spot)
curl -XPOST localhost:8000/sim/hand -H 'content-type: application/json' -d '{"seen": false}'     # lose the hand (try it mid-move)
curl -XPOST localhost:8000/sim/hand -H 'content-type: application/json' -d '{"path_clear": false}'
curl -XPOST localhost:8000/sim/hand -H 'content-type: application/json' -d '{"target": [0.25, -0.1, 0.15]}'
curl -XPOST localhost:8000/sim/return_spot -H 'content-type: application/json' -d '{"item": "hemostat"}'  # clinician sets it down
curl -XPOST localhost:8000/fake/pull                                                              # clinician tugs
curl -XPOST localhost:8000/sim/scene_reset                                                        # every item back in its slot, then a reset
```

`python -m controller.smoke --runs 3 --return` runs full passes in the sim, putting items in the return spot itself and resetting the scene between runs. The sim's pick is scripted, so it tests the controller, timing, reach and region limits, not the Isaac policy.
