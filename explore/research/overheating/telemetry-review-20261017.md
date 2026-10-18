# Arm thermal reports by session

Rates are never fitted across session boundaries.

# Arm thermal report

3 rows, 0 samples, sessions: 20261017-231032-f8bd

No recorder samples in this session.

# Arm thermal report

25 rows, 0 samples, sessions: 20261017-231317-0f3d

## Experiment: torque_on_hold

OLS rates over this experiment; early/late = first/last 60 s.

| motor | start C | end C | peak C | whole-run C/min | early C/min | late C/min | current mA range |
|---|---|---|---|---|---|---|---|
| shoulder_pan | 46 | 51 | 51 | 1.03 | 3.60 | 0.00 | 0 to 6 |
| shoulder_lift | 48 | 53 | 53 | 1.07 | 3.60 | -0.00 | 312 to 358 |
| elbow_flex | 46 | 50 | 50 | 0.84 | 3.25 | 0.00 | 0 to 0 |
| wrist_flex | 48 | 53 | 53 | 0.95 | 3.08 | 1.54 | 0 to 0 |
| wrist_roll | 49 | 53 | 53 | 0.99 | 2.74 | -0.00 | 0 to 0 |
| gripper | 50 | 55 | 55 | 1.13 | 2.74 | 1.54 | 46 to 91 |

Reported zero current is not proof of zero winding/driver losses; this is an association, not a causal test.

No recorder samples in this session.

# Arm thermal report

6 rows, 5 samples, sessions: 20261017-232247-e34f

Span 23:22 to 23:22 (0.0 min)

## Per motor

| motor | start C | end C | peak C | mean C/min | C/min holding still | C/min moving | mean abs load | mean current mA | heat vs load r | heat vs current r |
|---|---|---|---|---|---|---|---|---|---|---|---|
| elbow_flex | 46 | 47 | 47 | - | - | - | 125.60 | 91.00 | - | - |
| gripper | 50 | 50 | 50 | - | - | - | 27.20 | 79.30 | - | - |
| shoulder_lift | 49 | 49 | 49 | - | - | - | 29.60 | 339.30 | - | - |
| shoulder_pan | 47 | 47 | 47 | - | - | - | 29.60 | 0.00 | - | - |
| wrist_flex | 49 | 49 | 49 | - | - | - | 97.00 | 1.30 | - | - |
| wrist_roll | 49 | 49 | 49 | - | - | - | 37.00 | 0.00 | - | - |

Insufficient continuous coverage for 60 s windows (minimum 54 s). No heating-rate, phase, holding/moving or correlation conclusion is supported.

## Gravity: shoulder_lift abs load by angle

| angle (deg) | mean abs load | samples |
|---|---|---|
| -120 to -100 | 30 | 5 |

## Motor ranking (peak temperature, then heating rate; associations only)

1. **gripper**: peak 50 C, - C/min. insufficient varying windows to assess load/current
1. **wrist_roll**: peak 49 C, - C/min. insufficient varying windows to assess load/current
1. **wrist_flex**: peak 49 C, - C/min. insufficient varying windows to assess load/current
1. **shoulder_lift**: peak 49 C, - C/min. insufficient varying windows to assess load/current
1. **shoulder_pan**: peak 47 C, - C/min. insufficient varying windows to assess load/current
1. **elbow_flex**: peak 47 C, - C/min. insufficient varying windows to assess load/current

# Arm thermal report

26 rows, 24 samples, sessions: 20261017-232326-6dbb

Span 23:23 to 23:23 (0.2 min)

## Per motor

| motor | start C | end C | peak C | mean C/min | C/min holding still | C/min moving | mean abs load | mean current mA | heat vs load r | heat vs current r |
|---|---|---|---|---|---|---|---|---|---|---|---|
| elbow_flex | 48 | 48 | 48 | - | - | - | 90.25 | 47.67 | - | - |
| gripper | 52 | 52 | 52 | - | - | - | 63.83 | 152.75 | - | - |
| shoulder_lift | 50 | 50 | 50 | - | - | - | 112.71 | 534.08 | - | - |
| shoulder_pan | 48 | 48 | 48 | - | - | - | 49.17 | 2.17 | - | - |
| wrist_flex | 50 | 50 | 50 | - | - | - | 54.62 | 0.00 | - | - |
| wrist_roll | 50 | 51 | 51 | - | - | - | 33.62 | 0.00 | - | - |

Insufficient continuous coverage for 60 s windows (minimum 54 s). No heating-rate, phase, holding/moving or correlation conclusion is supported.

## Gravity: shoulder_lift abs load by angle

| angle (deg) | mean abs load | samples |
|---|---|---|
| -20 to 0 | 168 | 2 |
| 0 to 20 | 128 | 8 |
| 20 to 40 | 96 | 14 |

## Guard events

- joint_hold shoulder_lift: 1

## Motor ranking (peak temperature, then heating rate; associations only)

1. **gripper**: peak 52 C, - C/min. insufficient varying windows to assess load/current
1. **wrist_roll**: peak 51 C, - C/min. insufficient varying windows to assess load/current
1. **wrist_flex**: peak 50 C, - C/min. insufficient varying windows to assess load/current
1. **shoulder_lift**: peak 50 C, - C/min. insufficient varying windows to assess load/current
1. **shoulder_pan**: peak 48 C, - C/min. insufficient varying windows to assess load/current
1. **elbow_flex**: peak 48 C, - C/min. insufficient varying windows to assess load/current

# Arm thermal report

99 rows, 97 samples, sessions: 20261017-232721-a219

Span 23:27 to 23:28 (0.8 min)

## Per motor

| motor | start C | end C | peak C | mean C/min | C/min holding still | C/min moving | mean abs load | mean current mA | heat vs load r | heat vs current r |
|---|---|---|---|---|---|---|---|---|---|---|---|
| elbow_flex | 50 | 50 | 50 | - | - | - | 38.20 | 34.85 | - | - |
| gripper | 55 | 55 | 55 | - | - | - | 34.00 | 113.25 | - | - |
| shoulder_lift | 52 | 52 | 52 | - | - | - | 52.30 | 420.02 | - | - |
| shoulder_pan | 51 | 51 | 51 | - | - | - | 35.00 | 3.82 | - | - |
| wrist_flex | 53 | 53 | 53 | - | - | - | 60.76 | 11.53 | - | - |
| wrist_roll | 53 | 53 | 53 | - | - | - | 32.95 | 0.00 | - | - |

Insufficient continuous coverage for 60 s windows (minimum 54 s). No heating-rate, phase, holding/moving or correlation conclusion is supported.

## Gravity: shoulder_lift abs load by angle

| angle (deg) | mean abs load | samples |
|---|---|---|
| -120 to -100 | 35 | 73 |
| -100 to -80 | 60 | 2 |
| -80 to -60 | 140 | 2 |
| -60 to -40 | 212 | 1 |
| -40 to -20 | 107 | 17 |
| -20 to 0 | 36 | 2 |

## Guard events

- joint_hold elbow_flex: 1

## Motor ranking (peak temperature, then heating rate; associations only)

1. **gripper**: peak 55 C, - C/min. insufficient varying windows to assess load/current
1. **wrist_roll**: peak 53 C, - C/min. insufficient varying windows to assess load/current
1. **wrist_flex**: peak 53 C, - C/min. insufficient varying windows to assess load/current
1. **shoulder_lift**: peak 52 C, - C/min. insufficient varying windows to assess load/current
1. **shoulder_pan**: peak 51 C, - C/min. insufficient varying windows to assess load/current
1. **elbow_flex**: peak 50 C, - C/min. insufficient varying windows to assess load/current
