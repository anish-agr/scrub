# Recording station

One long-running process for recording SO-101 episodes. The arms, cameras and dataset open once and stay open. Teleop is always live, and you start, save or discard an episode whenever you want, with no timers and no episode limit.

```
.venv/bin/python explore/station/station.py --task "pick the spatula"
.venv/bin/python explore/station/station.py --task "pick the spatula" --root ~/scrub-dataset --port 8090
```

Page: http://localhost:8090. Teammates can watch on `http://<this Mac>:8090`, but the buttons only work on this Mac. Log: `~/scrub-logs/station-<time>.log`. Telemetry goes to `~/scrub-logs/thermal/*.jsonl` and MongoDB `scrub.thermal`, the same as `arm_session.py`.

## Controls

| Control | Key | What it does |
| --- | --- | --- |
| Start episode | Space, or Enter in the terminal | Starts recording frames with the current task. Only works from idle teleop, when no save is running, both cameras are up and the arm is not parked. |
| Save episode | Space / Enter again | Saves the episode in the background while teleop keeps running. The next Start waits until the save finishes. |
| Discard | Backspace | Throws away the episode being recorded. |
| KILL | Escape (even while typing) | Turns follower torque off immediately, stops sending actions and discards any open episode. **A raised arm drops.** |
| Home + motors off | | Glides home at 30 deg/s, then turns torque off (state parked). Refused while recording. |
| Motors on | | From parked: follows the leader again. From killed: sets Goal = Present, turns torque on, then follows; the guard catches up big gaps slowly. |
| Reconnect arms | shown only in the error state | Reopens both motor buses without restarting the process or the cameras. |
| Set task | Enter in the box | Sets the task for the next episode. Refused while recording. |

States: `idle` (teleop) -> `recording` -> save/discard -> `idle`; `homing` -> `parked`; `killed`; `cooling`; `error`.

Cool-down: when any motor reaches 60 C, the open episode is discarded (reason `cooldown`) and the arm goes home with motors off. Start stays locked until the hottest motor is at or below 50 C, or until it has stopped cooling for 3 minutes at or below 55 C. Then the state is parked, and Motors on resumes.

Ctrl-C: discards an open episode (reason `exit`), parks, finalizes the dataset, then disconnects with torque off at home.

## How it differs from arm_session.py

- `arm_session.py` restarts `lerobot-record` for every batch, which reconnects the arms and cameras each time. The station runs its own 30 Hz loop with LeRobot's pieces: `SOFollower`/`SOLeader`, `LeRobotDataset.create`, or resume + `start_image_writer`, then `build_dataset_frame`, `add_frame`, `save_episode`, `clear_episode_buffer` and `finalize`. It uses the same settings `arm_session.py` passes to `lerobot-record`: `use_degrees`, `max_relative_target=15`, `disable_torque_on_disconnect=false`, side and wrist cameras at 640x480/30, `streaming_encoding`, `encoder_threads=2`. The dataset features match `~/scrub-dataset`, checked with LeRobot's DeepDiff rule.
- The safety guards come from `arm_session.py` unchanged: joint and gripper guards, gentle mode, park, temperatures and telemetry. The station sets `arm_ui.S["phase"]` and `park_req`, and replaces `arm_session._start_cooldown` and `arm_ui.note/discard_episode/camera_down/camera_stall` at runtime, so the guards never raise and never end the process. Note: `A.COOL_TRIP = 999` on its own would not stop the guard, because the guard checks `arm.thermal.too_hot`, which reads `arm.thermal.COOL_TRIP`. The `_start_cooldown` replacement is what makes the guard safe.
- After each save, it writes `<root>-cadence.json` entries (loop rate and camera fps) like `arm_ui`, for `arm.train`'s check.

## Test (no hardware)

```
.venv/bin/python -m pytest explore/station/test_station.py -q
```

The test uses a fake follower, leader and cameras, writes to a temp dataset, and sends telemetry to a temp folder with MongoDB off. It runs the HTTP API on port 8197 and covers start, save, discard, kill, wake, home, park, the cool-down lock, the Enter toggle, a camera going down, a bus loss followed by Reconnect, a refused remote POST and discard-on-exit. It then checks that the saved episodes load back with `LeRobotDataset` and that resuming the dataset appends a third episode.
