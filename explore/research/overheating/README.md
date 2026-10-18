# Why the SO-101 follower overheats, and how to keep it running

Owner: Caiden (explore/). Started Oct 17, 2026, after repeated overloads and crashes during teleop and recording.
Read this first; the detail is in the three research sections and in the telemetry.

| File | What it covers |
| --- | --- |
| [01-servo-physics.md](01-servo-physics.md) | STS3215 variants, memory table, protections, heat sources, register values to try |
| [02-arm-mechanics.md](02-arm-mechanics.md) | gravity load per joint, kit variants, binding, power supply, ranked hardware causes |
| [03-software-and-reports.md](03-software-and-reports.md) | LeRobot and phosphobot issues, control-side causes, telemetry cost, long-running strategies |
| [HANDOFF.md](HANDOFF.md) | next experiments, hardware checks, rules, and a ready prompt for the next agent |
| `explore/thermal_log.py` | telemetry to MongoDB + local files: `watch`, `snapshot`, `idle`, `upload` |
| `explore/thermal_analyze.py` | report from the telemetry: which motor heats, how fast, under what load and phase |

## Bottom line

1. **Having torque on at 12 V is the main heat source, not the work the arm does.** Measured tonight (below): holding still at the folded rest pose with zero current on four joints, every motor rose about 5 C in 4 minutes, fastest in the first minute, flattening toward the mid 50s. With torque off, powered motors idle at 45-47 C (the leader arm, which never has torque on, sits there too). The datasheet operating limit is 60 C and shutdown is 70 C. So the arm starts every session with only a few degrees of headroom, and any real load (gripper squeeze, a blocked joint, gravity at full reach) uses it up in minutes.
2. **Stalls made it worse and caused the crashes:** the gripper squeezing a metal instrument (overload trip), the wrist pressing past its calibrated range into the hard stop, the folded arm pushing into its stops with torque left on after exit. These are fixed in software (guards, recalibration, torque off at rest).
3. **Unknowns to check by hand:** the servo variant (label C001 = 7.4 V part overvolted at 12.2 V; C018/C047 = 12 V part). Every motor's Max_Voltage_Limit reads 140 (14 V), which hints 12 V parts, but the leader normally uses 7.4 V servos and reads the same, so read the labels. Also room temperature and airflow.

## What the arm has (snapshot Oct 17, 23:10; `thermal_log.py snapshot`, also in MongoDB)

| | Follower | Leader |
| --- | --- | --- |
| Servo | STS3215, model 777, firmware 3.15 | same |
| Supply | 12.2-12.4 V | 12.1-12.3 V |
| Max_Temperature_Limit | 70 C | 70 C |
| Max / Min voltage limit | 14.0 / 4.5 V | 14.0 / 4.5 V |
| P / D / I | 16 / 32 / 0 (LeRobot) | 32 / 32 / 0 (factory) |
| Torque limit, body joints | 1000 (100%), Protection_Current 3000 (effectively off), Overload_Torque 80 | same |
| Torque limit, gripper | 500, Protection_Current 250, Overload_Torque 25 (LeRobot) | factory |
| Acceleration / Goal_Velocity | 40 / 1200 (our gentle mode) | 254 / 0 (max) |
| Idle temperature, torque off | 45-48 C | 45-47 C |

Calibration was redone tonight (wrist_flex range moved off the encoder wrap: 813-3192). Backups of the old file sit next to `~/.cache/huggingface/lerobot/calibration/robots/so_follower/scrub_follower.json`.

## What happened (timeline)

- ~20:30 gripper (id 6) tripped overload while squeezing; LeRobot's read raised `[RxPacketError] Overload error!` and the session crashed; motor 6 then dropped off the bus until power-cycled.
- ~20:50 after exit, all six follower motors at 54-61 C **with torque still on**, the folded pose pushing into the stops; wrist_flex flagged overload, reading ~20 deg past its calibrated minimum (encoder wrap).
- ~21:25 restart skipped the slow ease because torque was off, so LeRobot drove a 345 deg wrist_roll gap at full speed; the roll motor then counted past one turn (5150), which broke `lerobot-calibrate` ("Magnitude ... exceeds 2047") until a 12 V power cycle.
- ~22:10 a recording lost all six motors at once ("There is no status packet") together with the wrist camera: a USB or power blip.
- 23:10-23:30 measurements below.

## Measurements

**Idle, torque off (powered):** both arms 45-48 C. Unpowered for a while, the follower read 37-42 C, so powered idle adds roughly 5-8 C on its own.

**Torque on, holding the folded rest pose (goal = present position, nothing moving), 4 min:**

| motor | current | 0 min | 1 min | 2 min | 4 min |
| --- | --- | --- | --- | --- | --- |
| shoulder_pan | 0 mA | 46 | 49 | 50 | 51 |
| shoulder_lift | 358 mA | 48 | 51 | 53 | 53 |
| elbow_flex | 0 mA | 46 | 49 | 50 | 50 |
| wrist_flex | 0 mA | 48 | 51 | 52 | 53 |
| wrist_roll | 0 mA | 49 | 51 | 52 | 53 |
| gripper | 84 mA | 50 | 53 | 54 | 55 |

Joints drawing no measurable current heated as much as loaded ones, so the dominant term is the servo electronics with torque enabled, not winding current. Raw rows: MongoDB `thermal`, `kind: "experiment"`.

## Ranked causes and what to do

1. **Torque-on self-heating at 12 V, little headroom (measured).**
   - Torque off whenever the arm isn't moving: the recorder already does this on exit at rest and on cool-down. Next: drop torque during long resets once the arm is folded.
   - **Airflow:** a small desk fan on the arm is the cheapest test. Log a session with and without it and compare C/min in `thermal_analyze.py`.
   - Keep sessions short (record in batches of 5-10 episodes) and let the cool-down do its job (60 C trip, resume at 50 C or when cooling levels off).
   - Experiment: the 12 V variant runs from 4-14 V; a 9-10 V supply would cut driver losses (and torque). Only after the label check.
2. **Stalls: gripper squeeze, joints pressing into stops (history: overloads, crashes).** Fixed: gripper guard (gentle squeeze, eases on strain, overload or 62 C), joint stall guard (holds instead of pushing), clamp to calibrated range, recalibrated wrist, torque off at rest on exit, max_relative_target 15, catch-up at 45 deg/s.
3. **Gravity holding on shoulder_lift** (358 mA even folded; about 8 kg.cm at full reach per 02). Rest folded between episodes; a counterbalance spring or band at the shoulder is the mechanical fix (02, section 3).
4. **Variant or supply** (unverified): read the labels; measure the supply under a fast multi-joint move (should stay above 11.5 V); separate USB ports or a powered hub for the cameras.
5. **Control settings** (try one at a time, measure C/min): P 16 to 12 on shoulder_lift and elbow, dead zone 1 to 2-3, Torque_Limit 1000 to 750 on the body joints. Values and verification steps in 01, section 5.

## Telemetry: what is logged and how to use it

Every recorder session (`explore/arm_session.py`) logs automatically. Rows go to `~/scrub-logs/thermal/<session>.jsonl` and, with `MONGODB_URI` in `.env`, to MongoDB database `scrub`, collection `thermal`. Uploads run on a background thread; anything that didn't reach MongoDB is sent later with `thermal_log.py upload` (no duplicates: unique index on `session` + `seq`).

| kind | when | fields |
| --- | --- | --- |
| `session` | session start | `source`, `pid`, `task`, `root` (dataset), `mode` (record, preview, teleop), `settings` (all thermal thresholds and gentle-mode values in force) |
| `sample` | 2 Hz while the arm is driven | `phase` (preview, recording, resetting, teleop), `loop_hz`, `motors.<name>.{temp, load, pos, goal, current, volt, held, limp}` (temp, current, volt refresh every 2 s; current in 6.5 mA units; load is signed PWM duty about +-1000) |
| `event` | guard actions and lifecycle | `event`: `cooldown_trip`, `joint_hold`, `gripper_overload`, `experiment_end`; plus motor, load, temp, pos, goal |
| `event` / `grasp_start` | claw closes on an object (guard's blocked detection) | `pos`, `goal`, `load`, `temp`, `torque_limit` (hold level applied), `n_in_episode` |
| `event` / `grasp_end` | leader opens past the contact point | `duration_s`, `peak_load`, `pos`, `goal`, `load`, `temp` |
| `event` / `claw_closed_empty` | claw fully closed on nothing (`pos` <= 6) | `pos`, `goal`, `load`, `temp` |
| `event` / `episode_start` | LeRobot starts an episode | `episode`, `task`, `root` |
| `event` / `episode_end` | recording window closed | `episode`, `reason` (done, rerecord, stop, camera_down, cooldown, timeout, or a guard text like "elbow_flex too hot"), `duration_s`, `frames` (control-loop observations), `grasps`, `empty_closes`, `peak_temps` by motor |
| `event` / `episode_saved` | dataset episode written | `episode` (dataset index), `frames`, `duration_s`, `cadence` (the entry written to `<root>-cadence.json`), `session_done` |
| `event` / `episode_discarded` | episode thrown away and re-recorded | `episode`, `reason` |
| `event` / `phase` | every recorder phase change | `from`, `to` |
| `event` / `control` | every page or Enter action | `action` (next, rerecord, stop, start, enter_start), `accepted`, `phase` |
| `event` / `session_end` | process exit | `reason` (completed, interrupted, exit, error: Type, plus "(cooldown)"), `episodes_saved` |
| `cooling` | every 10 s during a cool-down | `temps` by motor id |
| `idle` | `thermal_log.py idle` | `temps`, `torque`, `voltage` |
| `snapshot` | `thermal_log.py snapshot` | every heat-related register per motor, both arms |
| `experiment` | ad-hoc tests | `phase`, `temps`, `current_mA`, `elapsed_s` |

All rows carry `t` (unix seconds), `session`, `seq`, `host`.

```
.venv/bin/python explore/thermal_log.py watch              # live temperatures from MongoDB, from any machine with the URI
.venv/bin/python explore/thermal_analyze.py --hours 6      # report: per-motor C/min, holding vs moving, by phase, gravity, events, ranked causes
.venv/bin/python explore/thermal_log.py snapshot           # registers on both arms (recorder stopped)
.venv/bin/python explore/thermal_log.py idle 30            # log temperatures every 30 s while the arm sits
```

Example queries (mongosh or pymongo):

```
db.thermal.find({kind: "event"}).sort({t: -1}).limit(20)
db.thermal.find({kind: "sample", "motors.gripper.temp": {$gte: 55}}, {t: 1, phase: 1, "motors.gripper": 1})
db.thermal.aggregate([{$match: {kind: "sample"}}, {$group: {_id: "$session", peak: {$max: "$motors.gripper.temp"}, n: {$sum: 1}}}])
```

## How to run an experiment

1. Start cool (all motors at or below 47 C; `thermal_log.py snapshot` shows them).
2. Change one thing: fan on, a register value, supply voltage, a guard threshold. Write it in the session's notes, or run a snapshot first so the registers are on record.
3. Record or teleop a fixed routine for 10 minutes.
4. `thermal_analyze.py --session <id>` for each run; compare C/min per motor, holding-still vs moving, and time to the 60 C trip.
