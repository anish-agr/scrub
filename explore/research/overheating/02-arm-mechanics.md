# SO-101 follower overheating: mechanical and hardware causes

Scope: STS3215 x6, 12.2 V supply, motors at 54-61 C within minutes of teleop (gripper, wrist_flex, shoulder_lift hottest), resting pose with shoulder_lift ~-103 deg and elbow ~97 deg against stops, wrist_flex once wrapped past range into its hard stop.
Evidence grading: [V] = read on the cited page; [E] = my own estimate from cited numbers; [U] = unverified/inferred. Community evidence on heat specifically is thin (searches of the SO-ARM100 and lerobot issue trackers returned no "overheating" issue for SO-101); most conclusions below combine datasheet facts, one measured thermal test, and physics.

## 1. Gravity load per joint and servo limits

### Servo limits
- STS3215 datasheet (Feetech, 2020): 7.4 V variant stall 19.5 kg.cm (16.5 at 6 V), stall current 2.5 A (7.4 V), rated torque 5 kg.cm at 650 mA, Kt 8 kg.cm/A, operating temp -20..60 C, torque output cut off above 70 C. Overload protection: enters after being blocked at >80% of stall for 2 s (clears when a new position command is sent); over-current protection at running current >2 A for 2 s. [V] https://core-electronics.com.au/attachments/uploads/sts3215-smart-servo-datasheet-translated.pdf
- 12 V variant (C018/C047): 30 kg.cm, stall 2.7 A, no-load 0.18 A, 1/345. [V] https://openelab.io/it/products/feetech-sts3215-c018-servo-12v ; https://robotshop.com/products/feetech-12v-30kgcm-magnetic-encoding-servo-sts3215
- Register defaults: Max Temperature Limit 70 C (0x0D), Max Torque 1000 (0x10), Protection Current 511 x 6.5 mA = 3.3 A (0x1C), Overload Torque 80% (0x24), Protection Time 200 x 10 ms (0x23), Acceleration 0 = max (0x29). [V] https://aifitlab-wiki.super.site/feetech-servo-motor-docs/feetech-sts-servo-memory-table-analysis
- Important: the 60 C figure is the *operating* limit, not the shutdown. Your 54-61 C readings are at the edge of spec, and the servo will not protect itself until 70 C.

### Link data (SO-101 URDF, official repo)
Link masses: base 0.147 kg, shoulder 0.100, upper arm 0.103, lower arm 0.104, wrist 0.079, gripper 0.087 plus moving jaw 0.012 (about 0.63 kg total; motors are included in link masses, a stated "~800 g" arm weight likely includes cables/hardware). Joint offsets: shoulder_lift to elbow ~0.116 m (sqrt(0.11257^2+0.028^2)), elbow to wrist_flex ~0.135 m, wrist_flex to fingertip roughly 0.16 m. [V from URDF, derived lengths are mine] https://raw.githubusercontent.com/TheRobotStudio/SO-ARM100/main/Simulation/SO101/so101_new_calib.urdf

### Estimated static gravity torque, arm fully extended horizontal [E]
Using point masses at approximate COMs (upper arm 0.058 m, forearm 0.068 m past elbow, wrist link ~0.165 m, gripper ~0.235 m):
| Joint | Torque (kg.cm) | % of 30 kg.cm (12 V) | % of 16.5-19.5 kg.cm (7.4 V) |
|---|---|---|---|
| shoulder_lift | ~8 | ~27% | ~45% |
| elbow_flex | ~4 | ~14% | ~25% |
| wrist_flex | ~1.2 | ~4% | ~7% |
| gripper | ~0 (no gravity, load is grasp/stall) | - | - |
At 12 V, holding 8 kg.cm needs about 8/11 = 0.7 A (Kt ~11 kg.cm/A, scaled from the 12 V stall 30 kg.cm / 2.7 A), i.e. roughly 2 W of I^2R if winding resistance is ~4.4 ohm (12 V / 2.7 A) [E]. Rated (continuous) torque is 5 kg.cm at 7.4 V [V], so 8 kg.cm sustained at the shoulder already exceeds the rated continuous figure of the 7.4 V version and is well above the 12 V version's likely continuous rating [U: no 12 V rated figure found].
Folded (arm rest pose, links stacked near the base): moment arms shrink to a few cm, gravity torque at shoulder_lift falls to ~1-2 kg.cm and the elbow near ~1 kg.cm [E]. So at the rest pose gravity is not the heat source; end-stop pressing is (see section 5).
Takeaway: shoulder_lift is the dominant gravity joint, elbow second, wrist_flex small. Wrist_flex and gripper heat therefore point to stall/contact or binding rather than gravity.

### Which joints overheat first in community reports
- Gripper: the lerobot follower code itself caps the gripper at Max_Torque_Limit 500 (50%), Protection_Current 250 (50%), Overload_Torque 25 "to avoid burnout" [V] https://raw.githubusercontent.com/huggingface/lerobot/main/src/lerobot/robots/so_follower/so_follower.py . lerobot issue #2819: gripper servo went stiff then failed; maintainer said it breaks "if it is overloaded for too long", likely fully closing on an object [V] https://github.com/huggingface/lerobot/issues/2819 . This is the best-supported "gripper first" evidence.
- shoulder_lift: SO-ARM100 issue #66, "Motor #2 (shoulder_lift) Overload", intermittent overload/disconnect; answer was to swap motor to another joint and replace if the fault follows it [V] https://github.com/TheRobotStudio/SO-ARM100/issues/66 .
- Measured thermal data (issue #134): a 1 kg static load held 10+ h stabilized at 48 C; continuous +/-90 deg oscillation reached 71 C after ~110 min and tripped 70 C; acceleration setting mattered ("accel = 2 -> overheat; accel = 5 -> stable ~60 C" as reported) [V, single user, voltage not stated] https://github.com/TheRobotStudio/SO-ARM100/issues/134 . Implication: a healthy servo under moderate load plateaus near 48-60 C, so 54-61 C in minutes is plausible for a servo doing sustained work but should not climb further; if it keeps climbing, something is stalling.
- No Reddit/YouTube thread with joint-specific temperature counts could be retrieved; treat any "shoulder first" claim beyond the above as [U]. The roboticscenter.ai forum threads on SO-101 overheating and USB brownouts are only open prompts with no answers (no data) https://roboticscenter.ai/forum/posts/so-101-servo-overheating-and-current-limit-settings-for-educators-schools-intermediate .

## 2. Kit variants, wrong parts, wrong supply

Official BOM (TheRobotStudio SO-ARM100 README): follower = 6x STS3215 7.4 V 1/345 (C001); leader = 1x C001 (1/345), 2x C044 (1/191), 3x C046 (1/147), all 7.4 V on a 5 V supply. Optional upgrade: 12 V STS3215 (30 kg.cm) in the follower with a 12 V 5 A+ supply. [V] https://raw.githubusercontent.com/TheRobotStudio/SO-ARM100/main/README.md ; LeRobot doc leader table: base 1/191, shoulder_lift 1/345, elbow 1/191, wrist_flex/roll/gripper 1/147 [V] https://huggingface.co/docs/lerobot/so101
Seeed wiki: follower is C001/C018/C047 (7.4 V or 12 V), all 1/345; leader always 7.4 V and "watch out that you plug in the right power supply ... otherwise you might burn your motors". Standard kit 5 V, Pro kit 12 V. [V] https://wiki.seeedstudio.com/lerobot_so100m_new/
Known problems from variants:
- All motor boxes carry the same model number; the gear ratio and voltage are only in the code (C0xx) on the sticker. One builder installed wrong servos and had to rebuild [V] https://note.com/laplust/n/n1ce78dcea58b?hl=en ; another stresses reading stickers across four models of 12 V/7.4 V [V] https://dev.classmethod.jp/en/articles/lerobot-so-arm101-assembly-teleop/ .
- Relevance to you: if any follower servo is a 7.4 V C001 on your 12.2 V rail it is being overvolted (datasheet over-voltage protection is set around 7.4 V, 4 V min [V]); it would run hot and error out. Likewise a 12 V C018/C047 with a 1/191 or 1/147 gear would be weaker or different in speed. Check all six stickers.
- Supply: 5 V kits ship with 5 V 4-6 A supplies; Pro kit spec sheets list 12 V 1 A on one seller page (Pakronics) which is clearly too low for 6 servos [U, listing]; roboticscenter.ai spec page says 12 V 3 A minimum [V, low-quality source] https://www.roboticscenter.ai/hi/hardware/so-101/specs . A 4th-party kit (SO-ARM102) quotes follower 1.3 A average, 3.3 A peak at 12 V with a 300 g load [V] https://robonine.com .
- Issue #132: daisy-chained 3-pin jumpers on a 5 A 12 V supply: voltage sag/brown-outs, servo resets and position errors during multi-joint motion; stall ~2.7 A x several servos concentrates 8-16 A theoretical through the first connectors rated ~2-3 A, wire AWG 24-26 [V, stated by the issue author, no maintainer fix] https://github.com/TheRobotStudio/SO-ARM100/issues/132 .
- Corrupt state on power glitch: multi-turn position register ballooned and needed Homing_Offset reset plus full power cycle (unplug USB and DC ~5 s) [V] https://dev.classmethod.jp/en/articles/lerobot-so-arm101-assembly-teleop/ . Cold exposure plus overload killed a bus in #2819 [V].

## 3. Mechanical mitigations people use or that follow from the design
- Counterbalance springs/rubber bands: I found no SO-101-specific community build documenting one [U: absence of evidence in search]. General robotics literature places counter-weight springs at shoulder and elbow where torque is largest and reports self-load near zero in the home pose https://researchgate.net/profile/Chang-Kuo_Tseng/publication/264875086_Counter-weight_spring_approach_in_arm_design_of_wheeled_desktop_robot/links/55fb99b308aec948c4afaf7d/Counter-weight-spring-approach-in-arm-design-of-wheeled-desktop-robot.pdf . For SO-101 a spring across shoulder_lift offsetting ~5-6 of the ~8 kg.cm extended load is physically plausible [E].
- Lighter end-effector: the gripper+wrist are ~0.18 kg at the longest lever; each 50 g removed at the tip saves ~1.2 kg.cm at the shoulder [E]. Avoid heavy cameras/handles on the wrist in the follower.
- Acceleration register: raising the Acceleration value (softer ramps) reduced or changed heating in the #134 test [V, anecdotal]; lerobot leaves Acceleration unconfigured by default on SO follower [V].
- Reduce commanded effort: Max_Torque_Limit / Protection_Current / Overload_Torque as lerobot does for the gripper (500/250/25) [V]; apply a similar cap to wrist_flex and others [E, design suggestion].
- Backlash/friction: STS3215 real backlash ~1 deg measured vs <=0.5 deg spec; position error under load 1.8-2.6 deg [V, #134]. Hunting around a setpoint with a high P gain draws continuous current [U].
- Print tolerance: issue #120, "all connection points require excessive force"; fixes were XY compensation, dry filament, gauge prints [V] https://github.com/TheRobotStudio/SO-ARM100/issues/120 . Tight bearings/horn fits translate directly to extra load current. Burrs near screw holes and brute-forcing motors into slots are called out by builders [V] https://note.com/laplust/n/n1ce78dcea58b?hl=en ; motor washers can be installed backwards, mis-meshing gear and shaft [V same page].
- Cable drag: wires routed after assembly are hard; stiff cables bridging wrist/gripper add torque and can pull against rotation [U inference from the classmethod note].
- Heatsinks/fans on servos: no verified SO-101 reports found [U]. Cases are plastic with a metal gearbox; the motor is the heat source, so adhesive heatsinks on the plastic case would help only marginally [E].
- Pre-align leader and follower before starting teleop; otherwise the follower snaps rapidly to the leader pose, straining motors [V per search summary of classmethod/openelab, https://dev.classmethod.jp/en/articles/lerobot-so-arm101-assembly-teleop/].

## 4. Electrical
- Current: 6 servos x 2.7 A stall = 16 A theoretical; realistic teleop peak 3-4 A, average ~1.3 A (SO-ARM102 figures at 12 V, 300 g load, [V] https://robonine.com). Size the 12 V supply at 5 A minimum (official), ideally 8-10 A with low-impedance wiring, and measure at the board input under motion.
- Servo electronic protection under-voltage at <4 V and over-voltage around 7.4 V on the 7.4 V part [V datasheet]; a 12 V part with a sagging supply goes into brownout resets rather than overheating, but low voltage raises current for the same torque (P = IV constant mechanical) so sag does increase I^2R heat [E].
- Daisy-chain: series 3-pin cables carry cumulative current to the first servos (issue #132 [V]). Powering from the controller board side with thick leads, or injecting power at the shoulder, is the fix suggested by the physics [E].
- Waveshare bus board: the lerobot doc requires jumpers on channel B (USB) and warns the power cable can pop off while handling [V] https://huggingface.co/docs/lerobot/so101 .
- USB hubs: motors "disappear" and "Incorrect status packet" appear on comms/power loss; I found no authoritative hub-specific data (roboticscenter.ai brownout thread is an empty prompt) [U]. Use a direct USB port or a powered hub, short cable.
- "No status packet"/missing IDs: lerobot #2819 shows "Failed to sync read 'Present_Position'", "Incorrect status packet", then "Missing motor IDs" after a servo failure plus cold exposure [V]. Seeed wiki advises checking power and loose 3-pin cables first [V].

## 5. Ranked likely causes for your symptoms, with physical checks

1. **End-stop stall at rest pose (shoulder_lift ~-103, elbow ~97) and wrist_flex past its range.** The servo is a P-position controller; if the goal lies past the stop it pushes with up to torque limit until the overload protection (80% for 2 s, then unloads to 20%) fires and re-arms on the next command, so continuous teleop re-triggers it [V datasheet; E on cycling]. Hot wrist_flex fits the wrap-past-range history. Check: with torque off, hand-move each joint to its stop and read present position vs calibrated min/max; command poses 3-5 deg inside the stops; watch Present_Current at rest (should be <0.3 A); recalibrate wrist_flex after unwrapping (also check multi-turn register ballooning, Magnitude exceeds 2047 error, [V classmethod]).
2. **Gripper stalled on a closed/grasped goal.** Teleop from a leader trigger commands full-closed while jaws are blocked; lerobot caps it at 50% but this is still large [V]. Check: read gripper current when closed; clamp commanded closure to the contact point; verify the jaw does not rub the fixed jaw.
3. **Gravity load at shoulder_lift (and elbow) in extended poses plus P-gain hunting/backlash.** ~8 kg.cm is ~27% of a 12 V servo's stall [E] and above the 7.4 V part's rated torque [V]. Check: log shoulder_lift current in an extended hold (expect ~0.7 A at 12 V); try a rubber band/spring offset and see if current and temperature drop; work in poses with shorter lever arm.
4. **Wrong servo variant (7.4 V C001 on 12.2 V, or wrong gear ratio) or mixed batch.** Check: read each sticker (C018/C047 = 12 V 1/345 for follower); compare Present_Voltage register on each servo and any servo that runs much hotter at identical load; swap the hottest servo with a cool one (the #66 swap test).
5. **Mechanical binding from tight prints, over-tight screws, misaligned horns, washers reversed, cable drag.** Check: torque off, disconnect the leader, move each joint by hand through its range; it should feel uniform with no gritty or sticky spots; unscrew one horn screw by a quarter turn to see whether resistance drops; compare backdrive feel of the hot joints with cool ones.
6. **Supply voltage sag or insufficient amps/daisy-chain drop.** Check: multimeter/scope at board input and at the last servo under a fast multi-joint move (should stay >=11.5 V); read Present_Voltage per servo; look for resets or "no status packet".
7. **Ambient/duty and no cooldown, high acceleration/speed, or accel setting.** Check: leave the arm powered but unloaded for 20 min; if the temperature plateaus near 45-48 C like the #134 static test, the plateau is load-related, not a failure.

Quick triage order: (a) log Present_Current/Temperature per joint at rest; the rest pose should show near-zero current: if not, you are stalling on a stop; (b) swap-test the hottest servo; (c) check stickers and Present_Voltage; (d) hand-feel binding with torque off; (e) measure supply under load.

## Sources
- https://github.com/TheRobotStudio/SO-ARM100/issues/66, /132, /134, /120
- https://github.com/huggingface/lerobot/issues/2819
- https://huggingface.co/docs/lerobot/so101
- https://raw.githubusercontent.com/TheRobotStudio/SO-ARM100/main/README.md and Simulation/SO101/so101_new_calib.urdf
- https://raw.githubusercontent.com/huggingface/lerobot/main/src/lerobot/robots/so_follower/so_follower.py
- https://wiki.seeedstudio.com/lerobot_so100m_new/
- https://core-electronics.com.au/attachments/uploads/sts3215-smart-servo-datasheet-translated.pdf
- https://aifitlab-wiki.super.site/feetech-servo-motor-docs/feetech-sts-servo-memory-table-analysis
- https://openelab.io/it/products/feetech-sts3215-c018-servo-12v , https://robotshop.com/products/feetech-12v-30kgcm-magnetic-encoding-servo-sts3215
- https://dev.classmethod.jp/en/articles/lerobot-so-arm101-assembly-teleop/ , https://note.com/laplust/n/n1ce78dcea58b?hl=en
- https://robonine.com , https://thinkrobotics.com/blogs/product-reviews-buying-guides/thinkrobotics-lerobot-so-101-6-axis-robotic-arm-review-ai-ready-open-source-and-built-for-learning
- https://www.roboticscenter.ai/hi/hardware/so-101/specs and forum prompts (low value)
Not retrieved: Reddit threads, YouTube descriptions, Hugging Face forum/Discord posts (searches returned none that fetched); gh issue search hit the API rate limit partway.
