# controller

Owner: Caiden. Tasks C1, C2, C5, C6, C8 in `docs/TASKS.md`.

FastAPI on port 8000. Owns the arm and every safety rule. Endpoints and messages are in `docs/CONTRACTS.md`. Serves `dashboard/` at `/` (a placeholder page with item buttons until `dashboard/index.html` exists).

## Run

```
python3.10 -m venv .venv && .venv/bin/pip install -r controller/requirements.txt   # once, from the repo root
.venv/bin/python -m controller                # fake arm (default), port 8000, surgical tray
.venv/bin/python -m controller --real-arm     # imports arm/real_arm.py (class Arm or RealArm)
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
- Hand tracking counts as running if a Hand arrived in the last 5 s. Then the arm waits up to 10 s for an open, seen hand with a `target` and `path_clear`, and freezes if the hand is lost (older than 0.5 s) or the path blocks while moving; one retry, then it sets the item at the safe spot. With no Hand posts at all it goes to the saved spot (`handoff_spot` in `arm/rig.json`, else `[0.22, -0.10, 0.18]`).
- `return` with no item takes the return-spot item from a fresh TrayState, else the last item out.
- `count` answers at once, even mid-handover. Up to 3 handovers queue; `stop` clears the queue.
- Switching trays (`POST /setting`) only works when idle or stopped, and clears `out`.
- `ledger` is used if `ledger.log` exists; otherwise `/stats` comes from memory.

## Extra endpoints (not needed by other parts)

- `GET /setting`: the current setting file (the voice server can read item ids and aliases here).
- `GET /events/recent?n=50`: the last events, for a page that loads mid-run.
- `POST /fake/force` with `{"miss_grasp": 1, "out_of_region": 1, "skill_fail": 1, "no_pull": 1}`: the next fake-arm calls fail that way (testing C6).

## Tests

`.venv/bin/python -m controller.test_flows` forces every failure case on the fake arm (grasp miss and retry, empty slot, no pull, `got_it`, no hand, hand lost mid-move, path blocked, out of region, stop mid-pick, sharp set-down, return and count, rejects). About 20 s, prints `17/17 passed`.
