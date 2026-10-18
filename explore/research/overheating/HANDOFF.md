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

## For Anish: rest at home between commands (real arm)

The controller now parks the arm: after a command finishes at home and nothing is queued for 2 s it calls `arm.rest()`, and it calls `arm.wake()` before the next command (`controller/core.py`, `REST_AFTER_S`; test `rests_at_home_then_wakes_for_the_next_command`). It skips this when the arm has no `rest`, so `arm/real_arm.py` needs:

- `rest()`: be at home (call `go_home()` if not), then torque off on all six motors (`bus.disable_torque()`); the playback loop must not re-enable torque while resting.
- `wake()`: write Goal_Position = Present_Position for all six, then `bus.enable_torque()`. Nothing moves.

Home (measured Oct 18, folded, stays put with torque off: `explore/home_pose.py test` PASS, drift under 1 deg) for `arm/rig.json` `"home"`, raw steps in joint order pan, lift, elbow, wrist_flex, wrist_roll, gripper:

```
[2063, 849, 3041, 2825, 1942, 1511]
```
Degrees: pan 2.8, lift -102.2, elbow 97.7, wrist_flex 72.3, wrist_roll -9.3, gripper 4.8. Also in `explore/home_pose.json`.

### Oct 17 continuation: telemetry audit; baseline still required

Read MongoDB with `thermal_analyze.py --hours 12` from Anish's Windows checkout
(`C:\Users\anish\Documents\GitHub\dubhacks-2026`); no local `.venv`, so used Python 3.10.11.
159 rows across five sessions: two snapshots, 24 experiment rows, 126 recorder samples,
two guard events and five session rows. Report: [telemetry-review-20261017.md](telemetry-review-20261017.md).
No hardware ports/cameras opened, no arm moved, no servo settings changed.

**Analysis correction:** the old analyzer joined different recorder sessions into 60 s windows,
including gaps. Its apparent recording rates (e.g. gripper 2.61 C/min) were not valid
within-session measurements. Reports now separate sessions, split windows at phase changes
and outages, require at least 54 s coverage, report heat/current correlation, and keep missing
measurements unknown. Experiment rows now have their own per-motor whole-run/early/late rates.
Offline checks: `python -m unittest discover -s explore -p test_thermal_analyze.py -v`.

#### Measured hold (not a new experiment or a 10-minute baseline)

Change: existing torque-on hold, phase `torque_on_hold`, session **20261017-231317-0f3d**,
24 readings over 230.2 s. Rates below are OLS over the whole run; temperature is nonlinear
(the early heating is faster). Peak is the highest reported value, not an external measurement.

| Motor | C/min | Start / end / peak C | Reported current mA range | Verdict |
| --- | --- | --- | --- | --- |
| shoulder_pan | 1.03 | 46 / 51 / 51 | 0-6 | Heats while holding with little reported current |
| shoulder_lift | 1.07 | 48 / 53 / 53 | 312-358 | Largest holding current, not fastest heating |
| elbow_flex | 0.84 | 46 / 50 / 50 | 0 | Heats despite reported zero current |
| wrist_flex | 0.95 | 48 / 53 / 53 | 0 | Heats despite reported zero current |
| wrist_roll | 0.99 | 49 / 53 / 53 | 0 | Heats despite reported zero current |
| gripper | 1.13 | 50 / 55 / 55 | 46-91 | Fastest whole-run heating; hottest |

This supports torque-on self-heating as a concern, but **does not establish driver/electronics
losses as the dominant cause**: reported current resolution, thermal lag, starting temperatures
and the absence of a matched torque-off control prevent that conclusion. The hold has no load
series. Heating does not simply rank with current across motors; no reliable within-motor
heat/load/current correlation is available from the short recorder runs.

| Change / phase | Session | Duration | C/min per motor | Verdict |
| --- | --- | --- | --- | --- |
| Existing preview | 20261017-232247-e34f | 2.0 s | All unknown (too short) | Cannot compare holding vs moving or phases |
| Existing recording | 20261017-232326-6dbb | 11.6 s | All unknown (too short) | shoulder_lift hold guard fired once; no thermal ranking |
| Existing preview | 20261017-232721-a219 | 48.1 s | All unknown (too short) | elbow_flex hold guard fired once; peak gripper 55 C |

No resetting samples exist in this window. **Do not conclude recording is hotter than preview,
or holding hotter than moving.** No run establishes a plateau below 60 C for long sessions.

#### Caiden: next action is experiment #1, not new motor settings

1. Be physically at the arm. Check follower/leader servo labels before another 12 V run:
   C001 is the 7.4 V variant; if present or uncertain, stop and resolve the supply rating.
   Keep supply, airflow, payload and software unchanged for the baseline; note room temperature.
2. From the Mac repo, check `pgrep -fl '[a]rm_session.py'`. If anything is running, **do not**
   start another session, snapshot or idle monitor. Read `http://localhost:8090/status` or
   `.venv/bin/python explore/thermal_log.py watch` instead (MongoDB only). Stop the old session
   normally and confirm the port is free before continuing; stop any standalone idle monitor too.
3. With the recorder stopped: `.venv/bin/python explore/thermal_log.py snapshot`.
   Start only with every follower motor at or below 47 C. If powered idle cannot reach that,
   stop and report it rather than changing the starting-temperature criterion.
4. With a clear workspace, empty claw initially and the leader aligned for safe start-up, run:

   ```sh
   .venv/bin/python explore/arm_session.py
   ```

   This is camera-free teleop, matching experiment #1. Repeat the same reach, grab a blunt
   instrument (e.g. spatula), lift, hold 5 s, return, release and fold routine for up to 10 min.
   Keep the rhythm/payload identical in the later fan run. Watch the live motor temperatures,
   guard notices, binding, grip strain, sag and USB losses. End early on unsafe behavior or if
   a motor approaches 60 C; never bypass the 60 C cool-down. Note elapsed time/temperature and
   any guard/cool-down. Do not let the supervisor silently restart into a second measured run.
   Fold safely before normal Ctrl-C; a raised arm intentionally keeps torque on at exit.
5. After the run, without opening hardware, run:

   ```sh
   .venv/bin/python explore/thermal_analyze.py
   .venv/bin/python explore/thermal_analyze.py --session <session-id-from-report> --out explore/research/overheating/baseline-report.md
   ```

   Send the session id, elapsed time, label codes, room temperature, airflow/payload and any
   observed issue. If the Mac was offline, with network restored run
   `.venv/bin/python explore/thermal_log.py upload` so this agent can read the session.
   We will append per-motor C/min and the verdict here, then proceed to **#2 fan only** after
   cooling back to the same start condition. #3 reset torque-off and register experiments remain
   unimplemented/pending, not stacked onto the baseline.
