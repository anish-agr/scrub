# STS3215 thermal behaviour and settings (SO-101)

Scope: Feetech STS3215 as used in the SO-100/SO-101. Tags: [V] = read in a primary/near-primary source (Feetech datasheet, lerobot source, memory-table transcriptions). [U] = unverified, inferred, or from a single retailer or community page.

Key primary source: the Feetech STS3215 product specification (A/0, 2020-04-10, 7.4 V variant), machine-translated copy: https://core-electronics.com.au/attachments/uploads/sts3215-smart-servo-datasheet-translated.pdf

## Bottom line first

- Your 12.2 V supply is only legitimate for the 12 V variant (C018 etc.). Check the variant before anything else (section 1). If the follower is the 7.4 V kit, 12 V is outside spec: the datasheet lists working input 4-7.4 V and over-voltage protection above 7.4 V.
- Heat is I^2R in the motor winding. Current comes from (a) static torque holding gravity/payload, (b) hunting around the target with P-gain and a one-tick deadband, (c) accelerating/reversing, (d) stall/overload. Nothing on the arm "idles cold" while torque is enabled and the pose is held against gravity.
- The easy registers to move are P_Coefficient (lower), the dead zones (raise from 1), Acceleration, Torque_Limit, Max_Temperature_Limit/Protection_Current (protect), and the 12 V-specific voltage limits. Verify each with Present_Current and Present_Temperature logs.

## 1. Variants

| Variant | Voltage | Gear | Stall torque / current | Source |
|---|---|---|---|---|
| C001 | 7.4 V (4-7.4 V) | 1/345 | 19.5 kg.cm / 2.5 A @7.4 V; 16.5 kg.cm / 2 A @6 V; no-load 150 mA; rated 5 kg.cm @ 650 mA; terminal R 2.5 ohm; Kt 8 kg.cm/A | datasheet [V]; retail copy https://aifitlab.com/products/feetech-sts3215-servo-motor |
| C018 | 12 V (4-14 V; Waveshare says 6-12.6 V) | 1/345 | 30 kg.cm / 2.7 A @12 V; no-load 180 mA; rated 10 kg.cm; op temp -10/-20 to +60 C | https://openelab.io/products/feetech-sts3215-c018-servo-12v ; https://www.waveshare.com/wiki/ST3215_Servo [V retail] |
| C044 | 7.4 V (5-8.4 V) | 1/191 | 27.4 kg.cm / 3.8 A @7.4 V; no-load 420 mA; op -20..+60 C | https://openelab.io/products/feetech-sts3215-c044-servo-7 [V retail] |
| C046 | 7.4 V | 1/147 | 14.4 kg.cm @7.4 V | https://evelta.com/sts3215-c046-7-4v-1-147-gear-ratio-magnetic-encoding-metal-gear-dual-axis-ttl-serial-bus-servo-motor/ (search snippet) [U] |
| C047 | 12 V | 1/191? | not verified | [U] |

Note the datasheet's own "operating range -20..60 C" and an "over-heat: torque off above 70 C" protection (section 7-11) coexist: 70 C is the shutdown, 60 C is the rated ambient/operating ceiling.

Kits (SO-ARM100 repo, https://github.com/TheRobotStudio/SO-ARM100, and LeRobot docs https://huggingface.co/docs/lerobot/en/so101):
- Follower: 6x 1/345 (C001, 7.4 V) in the default BOM, with a 5 V supply; the repo says a 12 V version exists for "more powerful motors" and then needs a 12 V 5 A+ supply. Seeed/other vendors sell a 12 V (C018) follower. [V]
- Leader: 1x 1/345 (shoulder lift), 2x 1/191 (pan, elbow), 3x 1/147 (wrist flex, wrist roll, gripper), all 7.4 V. [V, from LeRobot doc table]
- A 12 V leader must not be chained to a 12 V rail if it is 7.4 V hardware.

What happens if a 7.4 V variant sees 12 V: datasheet says over-voltage protection above 7.4 V (customisable), so with default limits it should throw a voltage error / unload; if the limit register was raised, the winding sees ~1.6x voltage. Motor torque constant stays the same but PWM duty needed for a given torque drops, and stall current at 12 V would be about 12/2.5 = 4.8 A (arithmetic from the 2.5 ohm datasheet resistance) [U], well above the 2.5 A rated stall and beyond the thermal design. No source documents lifetime numbers for this misuse; the sensible reading is "outside spec, expect hot and short-lived" [U].

How to tell which you have:
- Max_Voltage_Limit (addr 14, 0.1 V/LSB): one Japanese write-up (https://zenn.dev/usagi1975/articles/2026-05-18-000_sts3215-python) and a pythonic ST3215 register page (https://github.com/Mickael-Roger/python-st3215) show factory 80 (8.0 V) and Min 40 (4.0 V) - 7.4 V unit. The commanderfun register reference (https://github.com/commanderfun/STS3215/blob/main/REGISTER_REFERENCE.md) shows 140 / 50 - consistent with a 12 V unit. Both [V, but each from one unit]. If your Max_Voltage_Limit reads 140 you have a 12 V motor; if it reads 80 and you run 12.2 V, the servo should be erroring on voltage - so someone raised it, or the unit is 12 V.
- Model number 777 / firmware 3.15 is the same for both families (feetech SDK treats STS3215 as 777; zenn page) so it does NOT discriminate. [V]
- The sticker/label on the case ("7.4V" vs "12V", C-code) and Present_Voltage vs supply are the reliable checks. No-load current at fixed speed also differs (150 mA vs 180 mA, near useless).

## 2. Memory table, heat-relevant (STS series; transcription at https://aifitlab-wiki.super.site/feetech-servo-motor-docs/feetech-sts-servo-memory-table-analysis, cross-checked with https://github.com/commanderfun/STS3215/blob/main/REGISTER_REFERENCE.md)

EEPROM (persist if Lock_Flag = 0 when written; lerobot handles this):
- 13 Max_Temperature_Limit: default 70, range 0-100, unit 1 C. Datasheet: torque turned off above 70 C. [V]
- 14 Max_Voltage_Limit / 15 Min_Voltage_Limit: 0.1 V/LSB (see above for defaults). Out of range -> voltage error; releases automatically when back in range. [V]
- 16 Max_Torque_Limit: default 1000 (0.1 % units); copied to Torque_Limit (addr 48, RAM) at power-up. [V]
- 19 Unload_Condition and 20 LED_Alarm_Condition: bit masks selecting which error flags unload the motor / flash the LED. Bit layout is the same as the status byte. [V]
- 21 P (Kp, default 32 in commanderfun, "scaled 1/4"), 22 D (Kd, default 32, "scaled 1/8"), 23 I (default 0), 25 Integral_Limit. [V]
- 24 Minimum starting torque (0.1 %).
- 26 CW / 27 CCW dead zone: default 1, range 0-16, 0.087 deg per LSB (one encoder tick; 4096 counts/rev). [V]
- 28 Protection_Current: 0-2047 in 6.5 mA units (max 500 x 6.5 = 3250 mA). One table says default 511, another 0; unverified. [V units]
- 34 Protective_Torque (the "Holding torque after overload", default 20 %), 35 Protection_Time (10 ms units, default 200 = 2 s, max ~2.5 s), 36 Overload_Torque (default 80 %), 38 Over_Current_Protection_Time (10 ms units, default 200 = 2 s). [V]

RAM: 40 Torque_Enable (0/1/2 damping), 41 Acceleration (0 = max, else ~8.7 deg/s^2 per LSB) , 46 Goal_Velocity (~0.0146 RPM = 1 step/s per LSB; bit 15 direction), 48 Torque_Limit (0.1 %), 55 Lock.
Feedback: 56 position (0.087 deg), 58 velocity, 60 Present_Load, 62 Present_Voltage (0.1 V), 63 Present_Temperature (C), 65 Status, 69 Present_Current (x 6.5 mA).

Present_Load: NOT torque in N.m; it is the signed PWM duty of the current-control output (range about +-1000, bit 10 = direction; 0.1 % per LSB) per the python-st3215 register page [V]. At a constant supply, duty 1000 = full voltage. Present_Current x 6.5 mA is the better heat proxy, but note a hobby-grade sense reading, so use the trend, not the absolute value [U].

Status byte (addr 65), 1 = condition present: bit0 voltage, bit1 encoder/sensor, bit2 temperature, bit3 current (over-current), bit4 angle (python-st3215) or "torque enabled" (hexdocs/aifitlab - sources disagree), bit5 overload. [V/disputed for bit4] https://hexdocs.pm/feetech/0.2.2/Feetech.Error.html

What each protection does (datasheet 7-11, [V]):
- Overload: torque held above Overload_Torque (default 80 % of stall) for Protection_Time (2 s) -> output drops to Protective_Torque (20 %); flag clears when a new position command is sent.
- Over-current: current above threshold (datasheet says 2 A, for the 7.4 V variant) for Over_Current_Protection_Time (2 s) -> output turned off; cleared by re-sending a position command.
- Over-voltage / under-voltage: protects outside 4-7.4 V default, auto-release.
- Over-temperature: torque off above Max_Temperature_Limit (70 C); on this model the datasheet does not say it auto-resumes - treat as needs cool-down and torque re-enable [U].
LeRobot's gripper settings (Max_Torque_Limit 500, Protection_Current 250 = 1625 mA, Overload_Torque 25) are from the source of lerobot (https://github.com/huggingface/lerobot/blob/main/src/lerobot/robots/so_follower/so_follower.py), commented "50 % ... to avoid burnout". Note Protection_Current 250 is only ~50 % of the 500-count (3.25 A) ceiling, and for a 12 V motor with 2.7 A stall it is ~60 % of stall. [V]

## 3. Heat sources in a position-servo

- Winding loss P = I^2 R. Datasheet R = 2.5 ohm (7.4 V variant); Kt ~ 8 kg.cm/A at the output (19.5 kg.cm / 2.5 A). A 12 V C018 is 12 V / 2.7 A = ~4.4 ohm equivalent [U, computed]. Rated condition (5 kg.cm, 650 mA, 7.4 V) -> ~1.1 W in the winding; stall -> ~15 W. A 12 V unit at its 10 kg.cm rating is probably ~1 A -> ~4 W [U]. Power goes as torque^2, so halving gravity torque (better posture, lighter wrist payload) quarters the heat.
- Holding vs moving: for a position servo the closed loop supplies whatever current balances gravity indefinitely. Shoulder lift and elbow dominate (arm weight at long lever).
- P gain: the controller outputs PWM ~ Kp x error. With a high Kp, even one encoder tick of error asks for a large duty; combined with backlash (datasheet ~0.5 deg, 1/345 box) and quantisation, the servo can limit-cycle ("hunt") and burn current while holding still. Lower P reduces this but increases steady-state sag under load (the I term is 0 in lerobot). Kpower's general guidance: raise P until oscillation, back off by half, then add D (https://www.kpower.com/insight_servo/7851.html) [generic]. LeRobot sets P=16 (half of default 32), D=32 and I=0 explicitly to stop shakiness (so_follower.py, linked in section 2).
- Dead zone: 1 tick = 0.087 deg by default, below backlash. Raising to 2-4 (0.17-0.35 deg) stops the driver reacting to sub-backlash error and is the standard anti-hunting knob [mechanism V from register semantics; effect size U].
- Acceleration / velocity: the leader command jumps; with Acceleration = 0 (max) the follower slams to each new target, producing current peaks (and in the gear train, shock). Acceleration=40 is a sensible smoothing step (about 350 deg/s^2 if the 8.7 deg/s^2 unit is right [U]); Goal_Velocity=1200 steps/s ~ 17.5 RPM ~ 105 deg/s [U, unit derived from 0.087 deg/step]. Check this does not add tracking lag you care about for teleop latency.
- Driver (H-bridge) losses add to winding loss, typically small versus winding at these currents [U]. A 12 V winding has higher resistance (roughly 4.4 ohm computed), so for the same output torque it draws less current than a 7.4 V motor, but I^2R still sets the heat.
- Mechanical: tight screws touching the case cause drag and current spikes that can burn the servo (Waveshare note, https://www.waveshare.com/wiki/ST3215_Servo [V]). Check horn clearance, cable strain, and the 3D-printed pockets squeezing the case.

## 4. Thermal limits and time constants

- Datasheet ratings: operating -20..+60 C (ambient/operating; the C018 listing says -10..60 C), shutdown 70 C. Life test: >100,000 cycles with 60-degree sweeps at 1/5 stall torque (0.25 s move, 0.5 s stop) at 25 C [V]. That duty is intermittent and light; there is no published continuous-duty rating other than "rated torque" (5 kg.cm / 650 mA at 7.4 V; 10 kg.cm at 12 V) [V].
- Present_Temperature is an internal (board/winding region) reading in whole degrees; the case runs cooler than the sensor in transient conditions [U]. A plastic case with small thermal mass heats in minutes: your 54-61 C in ~6 min means a power of order several watts in a ~55 g body (55 g x ~1 J/gK ~ 55 J/K; 35 K rise in 360 s needs roughly 5 W if no cooling) [U, order-of-magnitude arithmetic; losses to air would raise this figure].
- Third-party claim that continuous-current torque derates 10-15 % per 10 C above 25 C ambient (https://github.com/tomwhipple/biped-robot/issues/6) is unsourced; treat as [U].
- Life at 60-70 C: no Feetech lifetime-vs-temperature data found. General engineering rule (not STS-specific) is that winding insulation and grease life roughly halve per 10 C [U]. 3D-printed PLA mounts soften around 55-60 C, so mechanical alignment can drift before the servo trips [U]. Practical target: stay under ~50 C steady-state, treat 60 C as the datasheet ceiling.
- Max_Temperature_Limit: consider lowering from 70 to 60-65 so the servo unloads before damage; lerobot does not change it.

## 5. Recommended settings to try (apply per motor; change one at a time)

| Register | Current | Try | Why / how to verify |
|---|---|---|---|
| Max_Voltage_Limit | ? read it | 7.4 V unit: do not use 12 V. 12 V unit: 140 (default) | Confirms variant; verify Present_Voltage ~12.2 V and Status bit0 = 0 |
| P_Coefficient | 16 | 10-12 on shoulder_lift/elbow; test 16 vs 10 | Hold a pose 60 s, log Present_Current mean/std and Present_Position jitter; hunting shows as current oscillating at idle. Watch for position sag |
| D_Coefficient | 32 | leave 32 (or 16-24 if D noise heats) | Compare current spread |
| CW/CCW_Dead_Zone | 1 | 2-3 | Same hold test; check ticks of steady-state error |
| Acceleration | 40 | 20-60 range | Peak Present_Current during a step command should fall; check latency |
| Goal_Velocity | 1200 | keep | Peaks in current, tracking lag |
| Torque_Limit (RAM) / Max_Torque_Limit | 1000 | 700-800 on shoulder, wrist; 500 on gripper (already) | Caps duty/current; confirm arm still holds pose, no sag; Present_Load peak should clip |
| Protection_Current | 511/0 | 300-400 counts (about 2.0-2.6 A) on big joints; gripper 250 | Over-current flag (status bit3) not tripping in normal teleop |
| Overload_Torque / Protection_Time | 80 / 200 | 60-70 % and 100-150 on arm joints; gripper keep 25 | Tripping in a deliberate stall test, then re-sending position clears it |
| Max_Temperature_Limit | 70 | 60-65 | Verify servo unloads (status bit2) in a deliberate test, ideally after cooling |

(Specific numbers in the "Try" column are starting points of mine, not Feetech recommendations [U]. I found no authoritative Feetech guidance on gains for the SO-101 other than the lerobot values.)

## What to measure on our arm

1. Read per motor: Max_Voltage_Limit, Min_Voltage_Limit, Present_Voltage, Max_Temperature_Limit, Protection_Current, Overload_Torque, Protection_Time, P/I/D, dead zones, Acceleration. Photograph the labels (7.4 V vs 12 V, C-code).
2. Log Present_Current (x 6.5 mA), Present_Load (PWM duty), Present_Temperature at 10 Hz for each joint for 2 minutes in three states: torque on holding the rest pose; torque on holding a horizontal-arm pose; during scripted teleop.
3. In the hold state, compute std of Present_Current and Present_Position: any oscillation at idle is hunting; fix with lower P / larger dead zone.
4. A/B each change (P 16 -> 12 -> 8, dead zone 1 -> 3, Torque_Limit 1000 -> 750) with the same 5-minute scripted trajectory; record temperature slope in C/min for every joint, not just the peak.
5. Find which joints heat: expect shoulder_lift/elbow from gravity. If wrist roll or gripper heats at rest, suspect mechanical binding or the gripper holding a closed object.
6. Measure supply current at the 12 V input during hold and teleop (bench supply display) and compare with the sum of Present_Current x 6.5 mA; large mismatch means the 6.5 mA scaling or the variant is not what is assumed.
7. Deliberately trigger the gripper overload once and confirm which status bit and how it clears.
8. Check mechanical drag: power off, move each joint by hand, check screws against the case.
