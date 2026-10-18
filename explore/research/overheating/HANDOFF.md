# Handoff: keep the SO-101 follower from overheating

For whoever (person or coding agent) picks up the thermal work. Read [README.md](README.md) first for the findings; this page is what to do next and how.

## Where things stand (Oct 17, 23:30)

- **Main cause, measured:** with torque on at 12 V the servos self-heat about 5 C in 4 minutes while holding still, even at 0 mA. Powered idle is 45-47 C, the datasheet operating limit is 60 C (shutdown 70 C), so there are only a few degrees of headroom before any real load.
- **Fixed in software** (`explore/arm_session.py`): cool-down failsafe (60 C trip, fold to rest, torque off, resume at 50 C or when cooling levels off), gentle mode (Acceleration 40, Goal_Velocity 1200, 0.4 deg deadband, `max_relative_target` 15), joint stall guard, gripper guard, clamp to calibrated range, slow catch-up at 45 deg/s, torque off on exit at rest, preview before recording, episodes ended by Done/Enter.
- **Logging:** every recorder session writes 2 Hz telemetry to `~/scrub-logs/thermal/*.jsonl` and MongoDB `scrub.thermal` (`MONGODB_URI` in `.env`). Schema in README.md.
- **Not yet known:** servo variant (labels), whether a fan fixes it, which register changes help.

## Commands

```
cd ~/Documents/dubhacks/dubhacks-2026
.venv/bin/python explore/thermal_log.py watch                 # live temperatures from MongoDB
.venv/bin/python explore/thermal_log.py snapshot              # every heat-related register, both arms (recorder stopped)
.venv/bin/python explore/thermal_log.py idle 30               # temperatures every 30 s while the arm sits
.venv/bin/python explore/thermal_log.py upload                # push local rows MongoDB is missing
.venv/bin/python explore/thermal_analyze.py --hours 6         # report: per-motor C/min, holding vs moving, by phase, events
.venv/bin/python explore/thermal_analyze.py --session <id> --out report.md
.venv/bin/python explore/arm_session.py --side C920 --wrist icspring                    # teleop
.venv/bin/python explore/arm_session.py --side C920 --wrist icspring --task "pick the spatula" --episodes 10   # record (preview, then Enter)
```

## Next experiments (one change at a time, 10 minutes each, start at or below 47 C)

| # | Change | How | Expect if it helps |
| --- | --- | --- | --- |
| 1 | Baseline | Teleop a fixed routine (reach, grab, lift, hold 5 s, return) for 10 min | C/min per motor, time to 60 C |
| 2 | Desk fan on the arm | Same routine | Lower C/min on every motor, plateau below 55 C |
| 3 | Torque off during resets | Add to `arm_session.py`: when phase is `resetting` and the arm is folded for 3 s, disable torque; enable (goal = present) when the leader moves | Rest periods cool instead of heat |
| 4 | P 16 to 12 on shoulder_lift and elbow | Write `P_Coefficient` after LeRobot's configure (same place as gentle mode) | Lower holding current, no visible sag |
| 5 | Dead zone 1 to 3 | `CW_Dead_Zone` / `CCW_Dead_Zone` (EEPROM: write with torque off) | Less hunting current at rest |
| 6 | Torque_Limit 1000 to 750 on the body joints | RAM register 48 after configure | Lower stall heat; check it still lifts the spatula |
| 7 | Lower supply voltage (only if labels say 12 V parts) | 9-10 V bench supply | Lower idle self-heating; check torque |

Log each run as its own session (restart the recorder), note the change in the session row or a snapshot, and compare with `thermal_analyze.py --session`.

## Hardware checks only a person can do

1. Read the servo labels on two follower motors and one leader motor: C001 = 7.4 V (overvolted at 12.2 V), C018/C047 = 12 V.
2. Room temperature, and whether the arm sits in still air or near a heat source.
3. Supply voltage under a fast multi-joint move (should stay above 11.5 V).
4. Torque off: move each joint by hand; any gritty or stiff joint is binding.
5. Cameras and the arm on separate USB ports (a shared hub has dropped all six motors and a camera at once).

## Rules

- Only edit `explore/` and `sim/` (Caiden's), never `arm/`, `vision/`, `dashboard/`, `settings/`, `ledger/` (see `AGENTS.md`). Write changes for other owners as a note.
- Never print or commit keys (`.env`). Never move the arm without the person at it; reads (temps, registers) are fine while no session holds the port (`pgrep -f arm_session.py`).
- Don't open the cameras or the arm port while `explore/arm_session.py` runs; read its page API (`http://localhost:8090/status`) instead.
- Commit only your files, `git pull --rebase --autostash`, push.

## Prompt to start an agent on this

```
You are continuing the SO-101 overheating work in ~/Documents/dubhacks/dubhacks-2026 for Caiden.
Read AGENTS.md, then explore/research/overheating/README.md and HANDOFF.md (this plan), then
explore/arm_session.py, explore/thermal_log.py and explore/thermal_analyze.py.

Goal: the follower arm runs for long recording sessions without reaching 60 C.

1. Run `.venv/bin/python explore/thermal_analyze.py --hours 12` and summarize what the latest
   telemetry in MongoDB scrub.thermal says: which motors heat fastest, in which phase, holding
   vs moving, and whether heating tracks load or current.
2. Work through the "Next experiments" table in HANDOFF.md one change at a time. Implement code
   changes only in explore/ (e.g. torque off during resets, P/dead-zone/Torque_Limit writes next
   to gentle mode in arm_session.py), test them against stubbed motors first, commit each.
3. For anything that needs the arm moving or a person (running the routine, a fan, labels,
   supply voltage), stop and tell Caiden exactly what to run and what to watch for, then
   analyze the resulting session with thermal_analyze.py and record the result in a new
   "Results" section at the bottom of HANDOFF.md (change, session id, C/min per motor, verdict).
Never print keys, never move the arm without Caiden, never open the arm port or cameras while
explore/arm_session.py is running. Keep every change small and measured.
```

## Results

| Date | Change | Session | Hottest motor C/min | Peak C | Verdict |
| --- | --- | --- | --- | --- | --- |
| Oct 17 | Torque-on hold at rest, no movement | experiment rows (kind "experiment") | ~3 in minute 1, ~0.5 after | 55 (gripper) | Self-heating with torque on is the main term |
