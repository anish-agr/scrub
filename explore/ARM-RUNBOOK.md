# Arm runbook: recording, safety, heat and data on the recording Mac

Owner: Caiden (explore/). The one page that ties together the Oct 17-18 bring-up work: how to record, how the arm
is protected, what we learned about overheating, where the data lives and what is still open. Details live in
the linked READMEs. Every command runs from the repo root with `.venv/bin/python`.

## Record a session (today's way)

1. Nothing else may hold the arm: `pgrep -fl "arm_session|station/station.py|lerobot-"` prints nothing.
2. Start the recording station once and leave it running (arms, cameras and dataset open once; no timers, no episode limit):
   ```
   .venv/bin/python explore/station/station.py --task "pick the hemostat" --root ~/scrub-surgical
   ```
   `--task` must be an exact instruction from `settings/*.json` (pick/return the hemostat, mayo scissors, scalpel, bench items). Free text needs `--any-task` and is marked NOT FOR TRAINING. Change the task between episodes with the task buttons or the task box.
3. Page http://localhost:8090. It starts with **motors off**: press **Motors on**, then **Start episode** (Space), do the demo, **Save episode** (Space) or **Discard** (Backspace). **KILL** (Escape) turns torque off at once and discards the open episode; a raised arm drops. **Home + motors off** glides to the saved home, then torque off.
4. Watch temperatures on http://localhost:8093 (its buttons go through the station while it runs).
5. Stop with **Ctrl-C once** and let it finish: it parks, closes the dataset properly (the last episode's index is only written then) and turns torque off. Never force-quit it.
6. After a session: `.venv/bin/python explore/dataset/to_mongo.py` (fills in video locations), `.venv/bin/python -m explore.dataset.qa --root <dataset> --out ~/qa.html` (re-record FAILs), `.venv/bin/python explore/thermal_analyze.py` (heat report).

The older per-batch recorder `explore/arm_session.py` still works and holds the shared guards the station imports.

## What is where

| Path | What |
| --- | --- |
| `explore/station/` | The recording station (single process, page on :8090). Flags and controls in its README |
| `explore/arm_session.py`, `arm_ui.*` | The shared safety layer (guards, park, cool-down, gentle mode) and the older recorder |
| `explore/home_pose.py`, `home_pose.json` | Save / show / test the folded home pose; `home`, `on`, `off` |
| `explore/calibrate_follower.py` | Recalibrate the follower safely (pre-checks, forced calibration, range check) |
| `explore/thermal_log.py`, `thermal_analyze.py`, `thermal_web.py` | Telemetry to MongoDB, the heat report, the live temperature site with arm buttons |
| `explore/dataset/` | `qa.py` (episode QA), `to_mongo.py` (joint data to MongoDB), `retask.py` (fix an episode range's task text), `replay.py`, `variety.py`, `aim.py` |
| `explore/research/overheating/` | Why it overheats: README (findings, schema), 01-03 research, HANDOFF (experiments, real-arm notes) |
| `controller/core.py` | Rests the arm at home between commands (`REST_AFTER_S`, `arm.rest()` / `arm.wake()`) |

## Safety layer (all in software, all logged)

- **Gentle mode:** Acceleration 40, speed cap ~105 deg/s, 0.4 deg deadband on leader jitter, LeRobot `max_relative_target` 15.0 (must be a float), big gaps catch up at 45 deg/s.
- **Guards:** a blocked joint holds instead of pushing; the claw uses 15% torque idle-shut, 35% holding, 50% moving, and eases off on strain, overload or 62 C; goals are clamped inside the calibrated range; wrist roll is limited to +-150 deg.
- **Park and rest:** the folded home pose stays put with torque off (`home_pose.py test` PASS, drift < 1 deg). The station and recorder park there; the controller rests there between commands.
- **Cool-down:** any motor at 60 C discards the open episode, parks, turns torque off and unlocks at 50 C (or when cooling levels off).
- **Bus robustness:** reads retry 3x; writes and reads accept replies that carry a status flag (the elbow at home sits a few steps past its range and flags every reply); KILL also broadcasts torque off (ID 254) so no flag can block it.
- **Startup:** the station connects with every goal = present position and torque off; nothing moves until Motors on.

## Why it overheated (measured)

- With torque on at 12 V, every servo self-heats about 5 C in 4 minutes even holding still at 0 mA; powered idle with torque off is 45-47 C (both arms); the datasheet operating limit is 60 C, shutdown 70 C. So headroom was a few degrees.
- The crashes were stalls on top of that: the gripper squeezing a metal instrument (overload trip), joints pressing into their stops with torque left on after exit, the wrist past its range.
- 56 C is within spec; the cost of heat is a pause, not damage. Torque off at home is the main fix; a 12 V relay would remove the remaining idle heat.
- Full write-up and telemetry schema: `explore/research/overheating/README.md`.

## Data

- **Dataset on disk** (LeRobot v3; what training reads): `~/scrub-dataset` has 14 episodes (as of Oct 18 02:20). Episodes 0-2 are `pick the spatula` and weak (barely move / no grasp); episodes 3-13 were relabelled to `pick the scalpel handle` with `retask.py` (backup at `~/scrub-dataset.backup-20261018-021651`). Episode 4 is 105 s, mostly idle. Neither label is a settings instruction, so new training data goes in a fresh root with exact instructions (see step 2).
- **MongoDB** (`MONGODB_URI`, cluster0.vzwywla, database `scrub`): `thermal` (temperatures at 2 Hz, grasps, lifts, pull-outs, episode lifecycle, button presses), `episodes` (one doc per episode: task, 30 Hz follower state and leader actions, timestamps, video locations, handoff result), `events` (team ledger). Videos stay on disk (too big for the free tier); push the dataset to Hugging Face to share them.
- **Handoff tracking:** each episode logs grab -> lift (tip rises >= 3 cm, from the URDF model) -> pulled out by hand (grip load collapses while the leader still holds shut) and `handoff_success`.

## Known issues and open items

| Item | Status / what to do |
| --- | --- |
| Elbow range ends 4 steps short of its folded stop | Tolerated in code; recalibrate and sweep the elbow fully into the fold to remove the flag |
| Wrist roll counts past one turn after hand-turning or a fast move | Don't turn the claw by hand with torque off; recover by turning back and power-cycling the 12 V (USB alone is not enough) |
| Wrist camera 13-23 fps (needs 30) | Own USB port, check the cable, more light |
| USB / power drops (all motors silent at once) | Arm and cameras on separate ports or a powered hub; seat the 12 V and motor cables |
| `arm/real_arm.py` rest()/wake() and rig home | Being added by the full-pass session; home raw values `[2063, 849, 3041, 2825, 1942, 1511]` |
| Controller asks "pick the scalpel" | Matches settings; train on exact settings instructions so run time and training agree |
| Servo variant (C001 7.4 V vs C018/C047 12 V) | Read the labels; Max_Voltage_Limit 140 hints 12 V parts |

## Incident log (short)

- Oct 17 ~20:30 gripper overload crash; ~20:50 all motors 54-61 C with torque on after exit; ~21:25 full-speed 345 deg wrist-roll snap broke calibration; recalibrated (wrist range moved off the encoder wrap).
- Oct 17 ~22:10 and later: whole-bus drops ("no status packet") with a camera, likely USB/power.
- Oct 18 ~00:00 save looked broken (LeRobot saves after the reset); fixed by trigger-ended episodes, then the station.
- Oct 18 01:10-01:40 station first runs: int `max_relative_target` TypeError; elbow status flags blocked KILL/Motors on/start-up; all fixed.
