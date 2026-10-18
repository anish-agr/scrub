# Recording station

One long-running process for recording SO-101 episodes. The arms, cameras and dataset open once and stay open. Teleop is always live, and you start, save or discard an episode whenever you want, with no timers and no episode limit.

Run 1 (hemostat), the recommended command:

```
.venv/bin/python explore/station/station.py --task "pick the hemostat" --root ~/scrub-surgical --port 8090
```

Switch between `pick the hemostat` and `return the hemostat` with the task buttons on the page; keep the same `--root` for the mayo scissors and scalpel later.

## Flags

| Flag | Default | What it does |
| --- | --- | --- |
| `--task` | `pick the hemostat` | Task stored with every frame. Must be an exact pick/return instruction from `settings/*.json` (`arm.record.instructions()`: surgical and bench). Anything else, even a case or space difference, is refused at startup with the valid list. |
| `--any-task` | off | Allows free text for play or demos. The page then shows a permanent **NOT FOR TRAINING** banner (red while the current task is not a settings instruction). Don't record training data with it. |
| `--root` | `~/scrub-dataset` | Dataset folder. Resumed if it has episodes. Writes `<root>-cadence.json` and `<root>-station-qa.json` beside it. |
| `--repo` | `local/scrub` | LeRobot repo id stored in the dataset. |
| `--port` | `8090` | Page and API port. |
| `--side`, `--wrist` | `C920`, `icspring` | Camera name part or OpenCV index. |
| `--follower`, `--leader` | from `arm_session.py` | Serial ports. |
| `--ease-s` | `3.0` | Accepted for `arm_session.py` compatibility; unused (the station starts with motors off). |
| `--no-browser` | off | Don't open the page. |

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
| Task buttons | | One click sets the task for the next episode: pick/return the hemostat, mayo scissors, scalpel first, then the bench items. Refused while recording. |
| Set task | Enter in the box | Only with `--any-task`: free text for the next episode. |
| Noted | shown with a RE-RECORD banner | Hides the RE-RECORD banners already checked (the episodes stay listed as FAIL). |

States: `idle` (teleop) -> `recording` -> save/discard -> `idle`; `homing` -> `parked`; `killed`; `cooling`; `error`.

Cool-down: when any motor reaches 60 C, the open episode is discarded (reason `cooldown`) and the arm goes home with motors off. Start stays locked until the hottest motor is at or below 50 C, or until it has stopped cooling for 3 minutes at or below 55 C. Then the state is parked, and Motors on resumes.

Ctrl-C: discards an open episode (reason `exit`), parks, finalizes the dataset, then disconnects with torque off at home.

## How it differs from arm_session.py

- `arm_session.py` restarts `lerobot-record` for every batch, which reconnects the arms and cameras each time. The station runs its own 30 Hz loop with LeRobot's pieces: `SOFollower`/`SOLeader`, `LeRobotDataset.create`, or resume + `start_image_writer`, then `build_dataset_frame`, `add_frame`, `save_episode`, `clear_episode_buffer` and `finalize`. It uses the same settings `arm_session.py` passes to `lerobot-record`: `use_degrees`, `max_relative_target=15`, `disable_torque_on_disconnect=false`, side and wrist cameras at 640x480/30, `streaming_encoding`, `encoder_threads=2`. The dataset features match `~/scrub-dataset`, checked with LeRobot's DeepDiff rule.
- The safety guards come from `arm_session.py` unchanged: joint and gripper guards, gentle mode, park, temperatures and telemetry. The station sets `arm_ui.S["phase"]` and `park_req`, and replaces `arm_session._start_cooldown` and `arm_ui.note/discard_episode/camera_down/camera_stall` at runtime, so the guards never raise and never end the process. Note: `A.COOL_TRIP = 999` on its own would not stop the guard, because the guard checks `arm.thermal.too_hot`, which reads `arm.thermal.COOL_TRIP`. The `_start_cooldown` replacement is what makes the guard safe.
- After each save, it writes `<root>-cadence.json` entries (loop rate and camera fps) like `arm_ui`, for `arm.train`'s check, plus `"use_degrees"` (true only when both the follower and leader configs say so) and `"task"`.

## Episode QA

Every saved episode is checked, and a failing one shows a big red **RE-RECORD episode N: reason** banner, so it's recorded again while the setup is still there:

- At once (no video): side or wrist camera under 29 fps during the episode, or the episode over 20 s.
- In the background, a few seconds later: `explore/dataset/qa_video.check_episode` (dark, unreadable; local only, no Perceptron call) plus a decode of the episode's whole span for frozen video (one frame for 1 s or more) and repeated frames (over 15% of frames identical to the one before, which means the camera delivered under about 25 fps). It runs in a separate `.venv` python process, one episode at a time, so the 30 Hz loop never waits. The thresholds were set on the 8 Oct 18 episodes in `~/scrub-dataset`: good 30 fps cameras showed 1 to 10% repeats.

`/status` has `last_qa` and `qa` (one row per episode this session: `status` is `checking`, `PASS` or `FAIL`, with `reasons`), and `rerecord` (the banner lines). Results also go to `<root>-station-qa.json` and the `episode_qa` telemetry event. Nothing is deleted from the dataset: drop failed episodes before training.

## Counts and targets

`/status` -> `counts` and the "Episodes per task" card show, per task, episodes already in the dataset's meta at startup plus this session's saves, against the targets:

- Run 1: hemostat, 30 to 40 episodes, about 2/3 pick: `pick the hemostat` about 24, `return the hemostat` about 12.
- Later, same root: mayo scissors 25 to 30, scalpel 25 to 30 (`pick the scalpel`; the scalpel goes to the safe spot).

## Run mode (a driver moves the arm, nothing is recorded)

A driver produces the follower's action instead of the leader. It never writes to the dataset, and the station's guards, `max_relative_target=15`, KILL, Home and the cool-down all still apply. Runs start only from `idle` (motors on, following the leader).

| Control (POST /control) | What it does |
| --- | --- |
| `{"action": "run", "driver": "replay", "args": {"episode": 7, "speed": 0.5}}` | State `running`. Refused unless idle, or if the driver or args are bad (the arm doesn't move). |
| `{"action": "stop"}` | Ends the run, goes home, motors off. |
| `kill` / `home` / `reconnect`, cool-down, bus error, Ctrl-C | Abort the driver first, then do what they always do. |
| `{"action": "mark", "result": "grabbed"}` or `"missed"` | Marks the last finished run. |

`GET /drivers` lists the drivers (and whether each one loads) and the replayable episodes. Every run and mark goes to `<root>-runs.jsonl`, outside the dataset. `/status` has `run` (the current or last run, with `driver_status`) and `runs`.

Drivers are listed in `DRIVERS` in `station.py` (`replay` in `replay.py`, `autopick` in `autopick.py`). The interface:

```python
class Driver:
    def __init__(self, args: dict)       # raise ValueError on bad args
    def start(self, st) -> None          # fast (< 100 ms): runs on the 30 Hz loop; do slow work on your own thread
    def tick(self, st, obs) -> dict | None
        # obs = robot.get_observation(): "<motor>.pos" in degrees, camera arrays "side" / "wrist"
        # return {"shoulder_pan.pos": deg, ..., "gripper.pos": v}; missing joints hold where they are ({} = hold)
        # None or {"done": "home"}: glide home, motors off (parked)
        # {"done": "off"}: torque off where it is, grip kept (state "off"; Motors on resumes, Home is refused)
    def abort(self) -> None              # instant, never raises
    def status(self) -> dict             # {"phase": ..., "detail": ..., "progress": 0..1} for the page
```

From the station, a driver can use `st.joints`, `st.gripper`, `st.temps()` (per motor, C), `st.fps`, `st.jpeg("side")`, `st.note(msg)` and `st.root`. A driver that raises in `tick` ends the run and the arm goes home.

`replay` eases from the current pose to the episode's first frame (at most 30 deg/s, at least 1.5 s), then plays its actions at `speed` (0.1 to 1). It only grabs the object if the object is where it was in that demo. Episodes in the file LeRobot is still writing can't be replayed until the station restarts.

### AutoPick: which one?

AutoPick keeps every reachable matching handle, instead of silently choosing the darkest one. A single
candidate works as before. When two or more remain, it holds the observed joint positions (including the
jaw; never follows the leader), asks **Which one?**, and shows **My left / My right** on the Run page.
For two handles: "I see two scalpel handles: the left one or the right one?"
With more than two, those mean the extreme left/right; **C** chooses the closest (or answer through the
API), described as "the one closest to you". No grasp plan or motion starts until a valid choice. Leave the tray still while
answering; candidates are from that detection frame, not live-tracked objects.

**Orientation is surgeon-relative, not camera-relative.** The station assumes the surgeon stands opposite
the side camera across the tray, looking toward it; the feed is unmirrored. Surgeon-left is image-right
(larger image x), surgeon-right is image-left, and closest is the image-top/far-camera edge (smallest image y).
Slots are **one-based, sorted surgeon-left to right**, not saved tray-slot ids. Confirm this orientation at
the bench before use; moving the camera or standing on its side invalidates these descriptions and the
existing grasp calibration. `closest` is this image-depth convention, not distance from the robot base.

You may skip the question with an optional selector in run args:

```json
{"action":"run","driver":"autopick","args":{"instance":{"side":"left"}}}
```

`instance` accepts `side: "left" | "right" | "closest"`, `slot: <positive integer>` and/or `variant: <string>`.
A variant must be verified by the detector, never inferred from position: the current dark-handle detector
does not classify variants, so unverified variants hold and report an error rather than selecting another
tool. If a selector still leaves multiple candidates, it asks. An absent slot likewise holds; it never picks
a different slot. Bad selector syntax refuses the run before starting.

`GET /status` exposes the active question as `run.driver_status.question` (`null` when cleared), with `id`,
`item`, `say`, `count`, `choices`, `orientation`, and `timeout_s`. Answer with:

```json
{"action":"clarify_answer","question_id":"<question.id>","side":"right"}
```

`side: "closest"` is also accepted by that control. The existing localhost-only control restriction applies.
Stale ids, duplicate answers, invalid sides and answers after **15 seconds** are refused. Timeout clears
the question, says "I'll wait for you to ask again.", and keeps the run holding (`clarify_timeout`).
Run and its argument fields unlock for an **explicit fresh request**: the old driver keeps holding until
the new driver has been constructed and started successfully, then its run ends with `then: "hold"` and
the new driver takes over. Bad args or a failed start leave the old hold intact. There is no automatic
retry, homing, motors-off or return to leader-following. Stop/Home still end the hold deliberately. An
unresolvable selector similarly holds (`clarify_failed`). Stop, Home, KILL, reconnect, cool-down, bus error
and exit abort the worker and clear the question immediately. KILL still cuts torque; a raised arm drops.

Telemetry records `clarify` and `clarify_answer`, linked by `question_id`; the answer includes `answer_ms`,
`answer` and `status`. Actual choices have `status: "answered"`, `answer`/`side` left, right or closest,
and selected `slot`. Timeout and pending-question abort also emit one `clarify_answer`, both with
`answer: "timeout"`, elapsed `answer_ms`, and respectively `status`/`reason` `"timeout"` or `"cancelled"`;
count only `status: "answered"`
in answered-choice metrics. Repeated aborts, stale answers and replacing a timed-out hold do not create
extra answers. A valid local detection makes **no network calls**, even with `detector: "gemini"`;
that option enables cloud fallback only when local finds nothing. Gemini still requires two agreeing votes
out of at most three detection votes per frame, now for each candidate; its existing model fallback,
spend log/cap and Perceptron
fallback are unchanged. Duplicate category boxes for the same physical rod are not counted twice.

## Test (no hardware)

```
.venv/bin/python -m pytest explore/station -q
```

The test uses a fake follower, leader and cameras, writes to a temp dataset, and sends telemetry to a temp folder with MongoDB off. It also checks the task rules (startup `--task` refusal, Set task refusal, `--any-task` warning), the quick and video QA flags on small synthetic videos, the QA banner and `qa_ack`, per-task counts, and `use_degrees`/`task` in the cadence file. It runs the HTTP API on port 8197 and covers start, save, discard, kill, wake, home, park, the cool-down lock, the Enter toggle, a camera going down, a bus loss followed by Reconnect, a refused remote POST and discard-on-exit. It then checks that the saved episodes load back with `LeRobotDataset` and that resuming the dataset appends a third episode.

`test_instances.py` and `test_autopick.py` also run without LeRobot: synthetic handles, fake motors, no
API calls. They cover selectors, orientation, two/three candidates, voting, holds, timeout, stale/double
answers, abort and the real HTTP control route. Run just those two files if LeRobot is not installed.
