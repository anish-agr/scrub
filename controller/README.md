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
- Hand tracking counts as running if a Hand arrived in the last 5 s. Then the arm waits up to 10 s for an open, seen hand with a `target` and `path_clear`, and freezes if the hand is lost (older than 0.5 s) or the path blocks while moving; one retry, then it sets the item at the safe spot. The lines differ: "Lost your hand. Holding." vs "Something's in the way. Holding." After a freeze the arm waits for the hand again, so "Hand open, please." can show a second time.
- Tracking stays "running" for 5 s after the last Hand post. Fake-hand drills need about a 6 s gap between them, or the next handover waits for a hand instead of using the saved spot.
- Out of region: if the point 8 cm short of the hand is refused, the arm goes straight to the hand slowly. Only if the hand point itself is refused does it say "That's out of my reach" and set the item down (`/fake/force {"out_of_region": 2}` forces that). With no Hand posts at all it goes to the saved spot (`handoff_spot` in `arm/rig.json`, else `[0.22, -0.10, 0.18]`).
- `return` with no item takes the return-spot item from a fresh TrayState, else the last item out.
- `count` answers at once, even mid-handover. Up to 3 handovers queue; `stop` clears the queue.
- Switching trays (`POST /setting`) only works when idle or stopped, and clears `out`.
- `ledger` is used if `ledger.log` exists; otherwise `/stats` comes from memory.

## Extra endpoints (not needed by other parts)

- `GET /setting`: the current setting file (the voice server can read item ids and aliases here).
- `GET /events/recent?n=50`: the last events, for a page that loads mid-run.
- `POST /fake/pull`: simulate the clinician tugging the item (sim arm), otherwise the same as `got_it`.
- `POST /fake/force` with `{"miss_grasp": 1, "out_of_region": 1, "skill_fail": 1, "no_pull": 1}`: the next fake-arm calls fail that way (testing C6).

## Tests

`.venv/bin/python -m controller.test_flows` forces every failure case on the fake arm (grasp miss and retry, empty slot, no pull, `got_it`, no hand, hand lost mid-move, path blocked, out of region, stop mid-pick, sharp set-down, return and count, rejects). About 20 s, prints `17/17 passed`.

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
```

`python -m controller.smoke --return` runs a full pass in the sim, putting items in the return spot itself. The sim's pick is scripted, so it tests the controller, timing, reach and region limits, not the Isaac policy.
