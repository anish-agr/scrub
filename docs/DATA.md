# Data: what MongoDB says

Read 2026-10-18 02:16 from `MongoDB Atlas, database scrub`. Regenerate with `.venv/bin/python -m explore.analysis`. Machine-readable copy: `data/analysis.json` (committed snapshot `docs/media/data/analysis.json`). Read-only: nothing here edits MongoDB.

- 63625 events, 8 episodes (0.06 h recorded), 4341 thermal rows
- Events by arm: fake 45852, pretag 17429, real 344. Tags (`fake_arm`) started 2026-10-17 22:02; earlier rows are test data (`pretag`).

## Pitch and Devpost numbers

| Number | Value | Query | Read |
| --- | --- | --- | --- |
| Episodes recorded (MongoDB) | 8 | `db.episodes.countDocuments({})` | 2026-10-18 02:16 |
| Hours of demonstrations recorded | 0.06 | `db.episodes.aggregate([{$group:{_id:null,s:{$sum:"$duration_s"}}}])` | 2026-10-18 02:16 |
| Episodes usable for training | 3 of 8 | `db.episodes.find({}, {episode_index:1, task:1, duration_s:1, handoff:1})` | 2026-10-18 02:16 |
| Episodes with a handoff outcome | 1 | `db.episodes.countDocuments({handoff: {$ne: null}})` | 2026-10-18 02:16 |
| Real handoff success rate | no real data yet | `db.events.countDocuments({type:"handed", fake_arm:false})` | 2026-10-18 02:16 |
| Real median request-to-hand (s) | no real data yet | `db.events.find({type:"handed", fake_arm:false}, {request_to_hand_s:1})` | 2026-10-18 02:16 |
| Simulated handoff tries | 3947 | `db.events.countDocuments({type:"command", action:"handover", accepted:true, fake_arm:true})` | 2026-10-18 02:16 |
| Hottest motor and peak | gripper 55 C | `db.thermal.aggregate([{$match:{kind:'sample'}},{$project:{m:{$objectToArray:'$motors'}}},{$unwind:'$m'},{$group:{_id:'$m.k',peak:{$max:'$m.v.temp'}}},{$sort:{peak:-1}},{$limit:1}])` | 2026-10-18 02:16 |
| Thermal samples | 3782 | `db.thermal.countDocuments({kind:'sample'})` | 2026-10-18 02:16 |
| Max safe hold time | 291 s | `db.thermal.find({kind:'experiment',phase:'torque_on_hold'},{t:1,session:1,elapsed_s:1,temps:1}).sort({session:1,elapsed_s:1})` | 2026-10-18 02:16 |
| Reads logged | 46 | `db.events.countDocuments({type:"read"})` | 2026-10-18 02:16 |
| count_sheet OCR accuracy | 0/8 correct (0%), 8 unscored, item fields 33% of 24 | `db.events.find({type:"read","read.kind":"count_sheet"})` | 2026-10-18 02:16 |
| tray_tag OCR accuracy | 10/18 correct (56%), 0 unscored | `db.events.find({type:"read","read.kind":"tray_tag"})` | 2026-10-18 02:16 |
| pack_label OCR accuracy | no real data yet | `db.events.find({type:"read","read.kind":"pack_label"})` | 2026-10-18 02:16 |
| Median read latency | 1800 ms | `db.events.find({type:"read"},{"read.latency_ms":1})` | 2026-10-18 02:16 |
| Perceptron vs Gemini | Perceptron 22/26 answered, median 1800 ms; Gemini 2/6 answered, median 890 ms; 0 rescues | `db.events.find({type:"read","read.attempts":{$exists:true}},{"read.attempts":1})` | 2026-10-18 02:16 |

## Training data: episodes

8 episodes in MongoDB (3.4 min recorded), 3 usable as they are.

| Ep | Task | Length (frames) | Duration s | FPS | Idle start s | Idle end s | Gripper opens s | Gripper closes s | Verdict | Why |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | pick the spatula | 450 | 15.0 | 30 | 15.0 | 15.0 | - | - | **drop** | the arm never moves |
| 1 | pick the spatula | 450 | 15.0 | 30 | 0.1 | 0.0 | 10.0 | - | **re-record** | the gripper opens but never closes on the spatula |
| 2 | pick the spatula | 180 | 6.0 | 30 | 0.3 | 0.1 | - | - | **drop** | the gripper never opens, so there is no grasp to learn |
| 3 | pick the scalpel handle | 569 | 19.0 | 30 | 0.1 | 3.1 | 0.4 | 8.3 | **keep** | trim 3.1 s idle at the end |
| 4 | pick the scalpel handle | 3143 | 104.8 | 30 | 3.0 | 0.2 | 6.0 | 8.3 | **re-record** | 105 s long with the arm moving only 19% of the time |
| 5 | pick the scalpel handle | 585 | 19.5 | 30 | 6.2 | 0.0 | 8.4 | 11.2 | **keep** | trim 6.2 s idle at the start |
| 6 | pick the scalpel handle | 233 | 7.8 | 30 | 0.1 | 7.6 | - | - | **drop** | the gripper never opens, so there is no grasp to learn |
| 7 | pick the scalpel handle | 528 | 17.6 | 30 | 3.4 | 0.1 | 7.3 | 11.6 | **keep** | trim 3.4 s idle at the start |

![Episode timeline](media/data/episodes.png)

### Joint motion (deg and deg/s, from `state` and `timestamp`)

| Ep | Joint | Range deg | Peak speed | Mean speed |
| --- | --- | --- | --- | --- |
| 0 | shoulder_pan.pos | 0.0 | 0 | 0.0 |
| 0 | shoulder_lift.pos | 0.0 | 0 | 0.0 |
| 0 | elbow_flex.pos | 0.2 | 3 | 0.0 |
| 0 | wrist_flex.pos | 0.0 | 0 | 0.0 |
| 0 | wrist_roll.pos | 0.0 | 0 | 0.0 |
| 0 | gripper.pos | 0.0 | 0 | 0.0 |
| 1 | shoulder_pan.pos | 34.7 | 69 | 10.3 |
| 1 | shoulder_lift.pos | 119.2 | 66 | 12.4 |
| 1 | elbow_flex.pos | 81.1 | 58 | 5.9 |
| 1 | wrist_flex.pos | 42.6 | 71 | 8.7 |
| 1 | wrist_roll.pos | 97.4 | 71 | 7.1 |
| 1 | gripper.pos | 10.6 | 30 | 0.7 |
| 2 | shoulder_pan.pos | 1.1 | 13 | 1.5 |
| 2 | shoulder_lift.pos | 0.4 | 3 | 0.2 |
| 2 | elbow_flex.pos | 0.1 | 3 | 0.0 |
| 2 | wrist_flex.pos | 0.4 | 8 | 0.1 |
| 2 | wrist_roll.pos | 0.9 | 24 | 0.5 |
| 2 | gripper.pos | 0.2 | 2 | 0.0 |
| 3 | shoulder_pan.pos | 80.4 | 50 | 5.4 |
| 3 | shoulder_lift.pos | 47.8 | 63 | 5.3 |
| 3 | elbow_flex.pos | 51.2 | 50 | 2.8 |
| 3 | wrist_flex.pos | 32.2 | 42 | 3.3 |
| 3 | wrist_roll.pos | 36.4 | 34 | 2.5 |
| 3 | gripper.pos | 31.3 | 63 | 6.1 |
| 4 | shoulder_pan.pos | 83.0 | 71 | 2.1 |
| 4 | shoulder_lift.pos | 121.2 | 69 | 3.1 |
| 4 | elbow_flex.pos | 75.0 | 55 | 1.4 |
| 4 | wrist_flex.pos | 81.1 | 66 | 2.3 |
| 4 | wrist_roll.pos | 80.5 | 87 | 2.3 |
| 4 | gripper.pos | 29.7 | 65 | 0.9 |
| 5 | shoulder_pan.pos | 93.1 | 71 | 8.9 |
| 5 | shoulder_lift.pos | 129.5 | 74 | 14.4 |
| 5 | elbow_flex.pos | 85.0 | 58 | 5.7 |
| 5 | wrist_flex.pos | 61.6 | 74 | 11.6 |
| 5 | wrist_roll.pos | 99.2 | 74 | 12.5 |
| 5 | gripper.pos | 21.5 | 54 | 2.0 |
| 6 | shoulder_pan.pos | 0.0 | 0 | 0.0 |
| 6 | shoulder_lift.pos | 0.0 | 0 | 0.0 |
| 6 | elbow_flex.pos | 0.4 | 8 | 0.1 |
| 6 | wrist_flex.pos | 0.1 | 3 | 0.0 |
| 6 | wrist_roll.pos | 0.0 | 0 | 0.0 |
| 6 | gripper.pos | 0.0 | 0 | 0.0 |
| 7 | shoulder_pan.pos | 72.0 | 63 | 7.0 |
| 7 | shoulder_lift.pos | 160.5 | 84 | 12.2 |
| 7 | elbow_flex.pos | 130.8 | 63 | 7.6 |
| 7 | wrist_flex.pos | 44.8 | 48 | 6.2 |
| 7 | wrist_roll.pos | 102.4 | 71 | 8.6 |
| 7 | gripper.pos | 24.7 | 59 | 2.1 |

### Per task

| Task | Episodes | Start-pose spread (deg) | Lighting |
| --- | --- | --- | --- |
| pick the spatula | 3 | 3.8 | not recorded (no lighting field) |
| pick the scalpel handle | 5 | 19.9 | not recorded (no lighting field) |

Local dataset `~/scrub-dataset`: 14 episodes, 8873 frames. Camera fps: dataset says 30; git history: side and wrist 29-31 fps; wrist 18.7-22.6 fps on the spatula episodes.

### Flags

- Only 8 episodes (3 usable); ACT usually needs 50+ per task. A training job now will overfit.
- Gripper never opens in episodes [0, 2, 6].
- Gripper opens but never closes in episodes [1].
- Idle head or tail over 2 s in episodes [0, 3, 4, 5, 6, 7]; trim before training.
- Episodes [4] run over 60 s; a pick should take well under a minute.
- MongoDB has 8 episodes but the local dataset says 14 (8873 frames); the extra episodes were never uploaded or were recorded after the upload.
- No lighting field on any episode, so lighting variety cannot be checked.
- Wrist camera frame rate is not stored per episode. git history: side and wrist 29-31 fps; wrist 18.7-22.6 fps on the spatula episodes; below 25 fps is a training concern.
- 7 of 8 episodes have no handoff outcome attached.

## Handoffs: what the arm did, per item, lighting and skill source

**Definition.** A try is one accepted handover command (a `command` event with action `handover` and accepted true), keyed by command_id; all later events with that command_id belong to it. A success is a try whose flow emitted `handed` (the arm reached the hand and offered the item) or `set_down` (sharp items such as the scalpel are set on a safe spot by design); the same two events ledger.stats counts. A miss is a `missed` event in the try (retries are the `retries` field on handed/missed). A stop is a `stopped` event in the try. Time is request_to_hand_s on the `handed` event. Lighting and skill_source come from the try's own events (skill_source 'none' when the flow ended before one was chosen). Rate range is the Wilson 95% interval.

**Trusted: NO.** The 24 real-tagged handed rows have median 0.42 s and span 0.41-0.43 s, matching the fake arm's median 0.42 s, with no misses or retries across 24 cases. They are the test real_tries_are_recorded_fake_ones_are_not in controller/test_flows.py (RecordingArm motion_s=0.1, auto_pull_s=0.2, fake_arm=False), which wrote to Atlas whenever the tests ran with MONGODB_URI set; no real SO-101 hands over in 0.4 s.

### Real arm (tagged real, suspect): 344 rows, 24 tries

| item | lighting | skill | tries | ok | rate | 95% range | median s | p90 s | retries | misses | stops |
| --- | --- | --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| hemostat | normal | model | 24 | 24 | 100% | 86-100% | 0.42 | 0.42 | 0 | 0 | 0 |

Do not quote these as real results. The pitch says "no real data yet".

### Miss reasons (real-tagged)

- none

### Simulation (fake and sim arms, never real): 45852 rows, 3947 tries

| item | lighting | skill | tries | ok | rate | 95% range | median s | p90 s | retries | misses | stops |
| --- | --- | --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| hemostat | bright | model | 2 | 2 | 100% | 34-100% | 0.81 | 0.82 | 0 | 0 | 0 |
| hemostat | dim | model | 4 | 4 | 100% | 51-100% | 1.32 | 3.73 | 0 | 0 | 0 |
| hemostat | dim | none | 3 | 3 | 100% | 44-100% | 2.14 | 4.08 | 0 | 0 | 0 |
| hemostat | normal | model | 1709 | 1255 | 73% | 71-75% | 0.42 | 0.66 | 104 | 237 | 249 |
| hemostat | normal | none | 1732 | 1025 | 59% | 57-61% | 0.43 | 0.44 | 128 | 288 | 291 |
| hemostat | normal | taught | 24 | 24 | 100% | 86-100% | 0.41 | 0.42 | 0 | 0 | 0 |
| hex_key | normal | model | 24 | 24 | 100% | 86-100% | 0.41 | 0.42 | 0 | 0 | 0 |
| hex_key | normal | none | 32 | 32 | 100% | 89-100% | 0.42 | 0.44 | 0 | 0 | 0 |
| mayo_scissors | normal | model | 60 | 59 | 98% | 91-100% | 6.10 | 6.29 | 0 | 0 | 1 |
| mayo_scissors | normal | none | 146 | 32 | 22% | 16-29% | 0.42 | 0.44 | 0 | 0 | 0 |
| scalpel | normal | model | 114 | 88 | 77% | 69-84% | 0.31 | 7.89 | 0 | 0 | 0 |
| scalpel | normal | none | 97 | 64 | 66% | 56-75% | 0.32 | 0.33 | 0 | 0 | 0 |

### Simulation miss reasons

- checking: Missed the hemostat, trying again.: 232
- checking: I couldn't pick the hemostat.: 174
- finding: I don't see the hemostat on the tray.: 61
- moving_to_hand: That's out of my reach.: 58

![Simulation handoff success](media/data/handoffs_sim.png)

## Heat

Source: `thermal` collection, real hardware (recording Mac). Temperatures are whole degrees C from the STS3215 `present_temperature` register.

Phase grouping: idle = parked, off, preview, killed and the idle monitor (arm not working a task); moving = recording, teleop, resetting; holding = `torque_on_hold` experiment rows (torque on, goal = present). Guard = 60 C (`COOL_TRIP`, arm/thermal.py; resume at 50 C). Firmware limit = 70 C.

### Per motor

| Motor | Idle C | Moving C | Holding C | Peak C | Hold rise C/min | Min from idle to guard (hold) | Cool C/min |
| --- | --- | --- | --- | --- | --- | --- | --- |
| shoulder_pan | 46.0 | 47.0 | 50.0 | 51 | 1.03 | 13.6 | n/a |
| shoulder_lift | 47.0 | 48.0 | 52.5 | 53 | 1.07 | 12.2 | 0.36 |
| elbow_flex | 46.0 | 47.0 | 50.0 | 53 | 0.84 | 16.6 | 0.42 |
| wrist_flex | 48.0 | 48.0 | 52.0 | 53 | 0.95 | 12.6 | 0.21 |
| wrist_roll | 48.0 | 49.0 | 52.0 | 53 | 0.98 | 12.2 | 0.23 |
| gripper | 49.0 | 51.0 | 54.0 | 55 | 1.13 | 9.7 | 0.43 |

Medians per phase group; the hold rate is a least-squares fit over the hold experiment (stretches of 60 s or more), the cool rate over the first 5 min of idle stretches that began at 49 C or more and fell at least 1 C. `n/a` means no usable stretch.

### Cooling

Median fall 0.36 C/min over 11 motor-stretches; 60 C to 50 C would take about 28 min at that rate (linear extrapolation: the data never went above 55 C, and real cooling slows near the ambient floor).

### Sessions

| Session | Source | Mode | Minutes | Moving min | Start C | Peak C (motor) | Median hottest while moving C |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 20261018-013938-6072 | station | station | 36.4 | 2.5 | 49 | 53 (gripper) | 51.0 |
| 20261018-000148-a7f0 | arm_session |  | 9.3 | 9.2 | 42 | 55 (gripper) | 53.0 |
| 20261018-002624-1606 | arm_session | preview | 4.4 | 0.0 | 48 | 54 (gripper) | n/a |
| 20261018-013235-3fe3 | station | station | 4.2 | 0.1 | 49 | 50 (gripper) | 49.0 |
| 20261018-011748-79aa | station | station | 4.1 | 1.3 | 47 | 50 (gripper) | 48.0 |
| 20261017-231317-0f3d | experiment |  | 3.8 | 0.0 | 50 | 55 (gripper) | n/a |
| 20261018-011343-365d | station | station | 3.6 | 0.1 | 47 | 50 (gripper) | 49.0 |
| 20261018-003730-770f | arm_session | preview | 0.9 | 0.0 | 44 | 50 (gripper) | n/a |

### Settings: what kept it cool or hot

Gripper temperature at grasp start, by gripper `torque_limit`:

| torque_limit | Grasps | Median C | Max C | Median |load| |
| --- | --- | --- | --- | --- |
| 350 | 53 | 50.0 | 52 | 350 |

Session settings that were the same in every session (so they cannot explain any difference): COOL_RESUME=50, COOL_TRIP=60, DEADBAND_DEG=0.4, EASE_DEG_S=45.0, GAP_DEG=25.0, GENTLE_ACCEL=40, GENTLE_SPEED=1200, GRIP_SQUEEZE=1.5, JOINT_LOAD_MAX=250. None of them varied.
Register snapshot: acceleration [40, 254], torque_limit [500, 1000], goal_velocity [0, 1200], max_temperature_limit [70], overload_torque [25, 80].

### Recommendations

- gripper is the hottest motor: peak 55 C against a 60 C guard and a 70 C firmware limit. Nothing in the data reached the guard (hot events: 0).
- With torque on and no motion, gripper warms fastest: 1.13 C/min. Holding is not free; every motor warms with torque on.
- Plan for at most 291 s of continuous hold per pass (half of the 582 s the gripper needs from idle to the 60 C guard); then torque off or park.
- Park or torque off between passes: motors fall about 0.36 C/min (median), so 60 C to 50 C takes about 28 min.
- gripper and wrist_flex idle warmest (49 and 48 C against 46 C for elbow_flex): their idle temperature is not a fault, only their rise is.
- No guard trips were recorded, so the guard values are untested on this data; keep COOL_TRIP at 60.

![heat_timeline](media/data/heat_timeline.png)
![heat_cooling](media/data/heat_cooling.png)
![heat_hold](media/data/heat_hold.png)

## Reading

## Reading (OCR)

46 `read` events (fake 46). Reads do not depend on the arm: the camera and the vision calls are real even on a fake-arm run, so every read here is real camera data.

Scoring: Reads are split into scored and unscored. Scored = tied to a printed prop in truth.json: tray_tag always (a failed read counts as scored-incorrect); count_sheet when it is ok and its tray id and item ids equal a truth sheet's; pack_label when it is ok and at least one label's lot (or item+lot) is in truth. Other ok reads (test-scenario sheets, lots like L-4471) are unscored (not a printed prop); failed count_sheet and pack_label reads are counted as failed, not scored. A scored read is correct when tray_tag: tray id equals a truth tray_id; count_sheet: items (id, expected, initial, closing) equal a truth sheet's; pack_label: every label's (item, lot) matches a truth label. accuracy = correct / scored. Live events carry no filename, so this is content matching, not per-file scoring.

| Kind | Reads | ok | Scored | Unscored (not a printed prop) | Failed | Correct | Accuracy | Item fields right | Median ms | p90 ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| count_sheet | 23 | 16 | 8 | 8 | 7 | 0 | 0% | 33% of 24 | 1800 | 3240 |
| pack_label | 5 | 2 | 0 | 2 | 3 | 0 | no real data yet | n/a | 2100 | 2100 |
| tray_tag | 18 | 12 | 18 | 0 | 6 | 10 | 56% | n/a | 304 | 2578 |

Overall latency: median 1800 ms, p90 2410 ms.

| Method (per attempt) | Attempted | Answered | Failed | Median ms |
| --- | --- | --- | --- | --- |
| gemini | 6 | 2 | 4 | 890 |
| perceptron | 26 | 22 | 4 | 1800 |
| qr | 10 | 6 | 4 | 12 |

Gemini rescued a failed Perceptron read 0 time(s).

Error reasons:

- 6 x vision unreachable
- 2 x no known tray
- 2 x perceptron: timeout
- 2 x no overhead frame yet
- 2 x perceptron: ValueError: no tray tag text
- 1 x perceptron: ValueError: no row matched an item of this setting
- 1 x perceptron: ValueError: no label read

Captions: 3, agree with the label 0, median latency 833 ms.

Offline bench (separate from live reads): docs/RECOGNITION.md (Oct 18, rendered props, not photos): count sheets correct (Perceptron, 1.8-2.3 s); tray tags correct (QR, 0.05 s); pack labels 4 of 4 (Perceptron, 2.4-2.5 s). Upper bound, not live accuracy.

