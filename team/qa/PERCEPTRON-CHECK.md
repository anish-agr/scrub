# Perceptron preflight (Scrub)

Checked 2026-10-18 against `docs/perceptron-openapi.json` (control plane only), `docs/PERCEPTRON-ROBOTICS.md`, and the workshop notes in `explore/research/isaac-workshop-notes.md` (those notes win where they differ). Worktree base `9af7543`. No dataset was created, uploaded, or trained. No POST, PUT, PATCH, or DELETE was sent to Perceptron.

The service allows **2 successful training jobs** per team. A dataset that fails ingest does not spend one. A job that trains on bad data does. The gaps below are the ones that can spend a job, highest risk first.

## Findings

### 1. Wrist/side camera fps is saved, then ignored

`explore/arm_ui.py` lines 196-218 write `camera_fps` for each camera and only print `slow camera` when a camera is under 29 Hz. `arm/dataset_check.py` lines 87-96 read `measured_fps` (the motor loop) and never read `camera_fps`.

The workshop validator cannot see this. Timestamps are frame index / 30, so a 23 Hz camera still claims 30 fps (`explore/research/isaac-workshop-notes.md` line 28). `team/LEFT.md` line 11 already measured the wrist camera at 22.6 fps. That dataset would pass `python -m arm.train pipeline ... --check-only` and can still be trained.

A temporary synthetic set passed `local_check`: loop `measured_fps` 30.0, `camera_fps.wrist` 22.6, no video files.

**Fix:** in the cadence loop in `arm/dataset_check.py`, require `camera_fps.side` and `camera_fps.wrist` on every episode, each finite and in 29..31. If either key is missing, raise. Do not treat a hand-written report that only has `measured_fps` as evidence.

### 2. The instruction string is never checked

`arm/dataset_check.py` lines 57-63 require an episode index and a length. They do not read `tasks`, `meta/tasks.jsonl`, or `meta/tasks.parquet`. `explore/arm_session.py` lines 1198 and 1247-1248 pass `--task` straight into `--dataset.single_task`.

The same synthetic set used the task `pick up the hemostat` (not a settings string) and `local_check` returned success: 2 episodes, 6 frames. The service checks camera names, fps, and joint names. It does not check our phrasing. The model is later told the exact string from `settings/*.json`. A typo spends a successful job.

`python -m arm.record` does reject inexact strings (`arm/record.py` lines 59-70). Calling `explore/arm_session.py` directly does not.

**Fix:** in `local_check`, load `pick_instruction` and `return_instruction` from `settings/surgical.json` and `settings/bench.json` and require every episode's task to be one of those strings. In `explore/arm_session.py` `main`, call `arm.record.resolve_task` before building the `lerobot-record` command and exit when it is not an exact match.

Allowed strings:

- `pick the scalpel`, `return the scalpel`
- `pick the hemostat`, `return the hemostat`
- `pick the mayo scissors`, `return the mayo scissors`
- `pick the needle-nose pliers`, `return the needle-nose pliers`
- `pick the wire cutters`, `return the wire cutters`
- `pick the hex key`, `return the hex key`

### 3. Pipeline revision defaults to the moving branch `main`

`arm/train.py` line 210: `--revision` defaults to `main`. `arm/pipeline.py` lines 83-84 send that revision on `POST /v1/datasets`. The local fingerprint is the folder on disk. The service fetches whatever `main` is when it ingests. `--confirmed-hf-matches-local` is a flag, not a comparison.

**Fix:** drop the default. Require a 40-character hex commit SHA and reject `main` and `master`. Register that SHA only after the checked folder has been pushed to it.

### 4. Joint units are not checked, and a radians-scale file passes

`arm/dataset_check.py` lines 77-80 require six finite floats and a gripper in 0..100. They do not require degrees. The synthetic state `[0.2, -0.4, 0.1, 0.0, 0.0, 50]` passed. The workshop says the validator cannot judge calibration, and a `use_degrees=false` recording keeps the same joint names.

The recorders do set the flag: `explore/arm_session.py` lines 1229 and 1234, and `arm/record.py` `lerobot_cmd` lines 173-175. `local_check` never sees that flag. LeRobot's normalized range is about -100..100 and looks like degrees, so a magnitude check alone cannot catch that mode.

**Fix:** have `explore/arm_ui.py` `_write_cadence` store `"use_degrees": true` only when the record command passed `--robot.use_degrees=true` and `--teleop.use_degrees=true`. Have `local_check` raise when that field is not true. Also raise when every `shoulder_lift` sample (index 1) stays inside -10..10: this arm rests near -104 deg (`explore/dataset/README.md`).

### 5. Team key is blank, so quota was not read

`PERCEPTRON_TEAM_API_KEY` is present in the worktree `.env` (copied from the repo `.env`) and the value length is 0. No request was sent. `team/LEFT.md` line 23 records an earlier `Perceptron HTTP 401` when a key was set. This run did not repeat that call.

`arm/pipeline.py` lines 109-120 fetch `GET /v1/capabilities` and still `POST /v1/jobs` without reading modes, horizons, or remaining successful jobs.

**Fix:** put the robotics team key in `.env`. Before `api.train`, require the capabilities document to allow `backend=standard`, `mode=expert_only`, `action_horizon=30`, `rtc_enabled=true`, and `steps=1000`, and require at least one successful job remaining. If those fields are absent, do not submit.

### 6. `python -m arm.train train` submits even when validation failed

`arm/train.py` lines 244-252 require the dataset state to be `ready`, print `/validation`, and then call `api.train`. They never call `validation_ok`. `--confirmed-replay-and-cadence` (line 198) does not open a cadence file.

`arm/pipeline.py` lines 116-118 do check validation before the POST. `validation_complete` (lines 59-64) also treats status, state, or stage `ready` as success. A validation body that echoes dataset readiness early would pass that test.

**Fix:** make `train` call `validation_ok` and `validation_complete` and skip `api.train` when either fails. Remove `ready` from the success set. Require `valid`/`passed`/`success` true, or status/state/stage in `passed`, `valid`, `validated`, `succeeded`, `success`, `completed`. Keep the existing rejection of a non-empty `errors` list.

### 7. A 429 or 5xx aborts the waiter instead of backing off

`arm/perceptron.py` lines 30-33 turn every non-success status into `APIError` and drop the body, so `Retry-After` is discarded. The OpenAPI 429 response on `/v1/capabilities`, `/v1/jobs`, and `/v1/deployments` defines that header. `arm/pipeline.py` lines 97-105 let that exception leave `poll`, while the job keeps running. Resuming the same idempotency key is safe. Starting a new key spends the second job.

**Fix:** on 429, sleep `Retry-After` seconds (default 1 if the header is missing) and retry the same request. Retry 502, 503, and 504 a few times inside `poll`. Do not allocate a new idempotency key.

### 8. Direct `arm_session` caps episodes at 600 seconds

`explore/arm_session.py` lines 1201-1202 default `--episode-s` and `--reset-s` to 600. The usage at line 5 does not pass those flags. The workshop cap used by `arm/record.py` line 39 is 25 s episodes and 10 s reset, and `arm_session_cmd` forwards those values. A forgotten Done on a direct `arm_session` run saves a 10-minute episode into the one dataset.

**Fix:** change the `arm_session` defaults to 25 and 10.

### 9. The QA tools only open a v3 parquet dataset

`explore/dataset/qa.py` line 58, `explore/dataset/replay.py` line 37, and `explore/dataset/variety.py` lines 29 and 43 read `meta/episodes/**/*.parquet` and, for variety, `meta/tasks.parquet`. `local_check` accepts v2.0, v2.1, and v3.0. The synthetic v2.1 folder passed with zero video files. `qa.py` on that folder would crash, which is how a FAIL gets skipped.

The arm backend comment pins LeRobot v0.4.4, which usually writes v3. That path can use these tools. A v2 folder cannot.

**Fix:** when `meta/episodes.jsonl` exists and the parquet tree does not, read the jsonl (and `meta/tasks.jsonl`) in qa, replay, and variety.

### 10. The example repo id is `scrub-surgical`

`docs/PERCEPTRON-ROBOTICS.md` lines 38-39 show `<hf user>/scrub-surgical`. The workshop override on line 12, `docs/TRAINING.md`, and `arm/record.py` lines 8-10 use `<HF_USER>/scrub`. Training the example repo leaves later `--resume` batches in a different dataset, and run 2 starts from the base model, so it needs every episode in one repo.

**Fix:** change that example `repo_id` to `<HF_USER>/scrub`.

## Control calls that match the saved OpenAPI

`docs/perceptron-openapi.json` response schemas are empty objects. Path, method, and request bodies below match the schemas. `next_cursor` matches the workshop notes. `items`, `id`, and `status` are what `arm/pipeline.py` assumes and were not confirmed live (finding 5).

| Call | Code | Body / query | Schema |
| --- | --- | --- | --- |
| `GET /v1/capabilities` | `arm/perceptron.py` 63-64 | none | match |
| `POST /v1/datasets` | 66-70, `arm/pipeline.py` 83-84 and 111, `arm/upload_dataset.py` 87 | `name`, `source_kind` `huggingface` or `upload`, optional `repo_id`, `revision`; `Idempotency-Key` required | `DatasetRequest` match |
| `POST /v1/datasets/{id}/uploads` | `perceptron.py` 72-74, `upload_dataset.py` 34 | `files[]` of `path`, `size_bytes` >= 1, lowercase sha256; batches of at most 500 and under 512 KiB | `UploadRequest` match |
| `POST /v1/datasets/{id}/finalize` | `perceptron.py` 76-77 | no body | match |
| `GET /v1/datasets/{id}` | 79-80 | | match |
| `GET /v1/datasets/{id}/validation` | 82-83 | | match |
| `POST /v1/jobs` | 85-89, `pipeline.py` 85-86 and 120, `train.py` 250-252 | `dataset_id`, `backend` `standard`, `mode` `expert_only`, `action_horizon` 30, `rtc_enabled` true, `steps` 1000; `Idempotency-Key` required | `JobRequest` match |
| `GET /v1/jobs`, `GET /v1/jobs/{id}` | 91-95 | | match |
| `POST /v1/jobs/{id}/cancel` | 97-98 | no body | match |
| `GET /v1/jobs/{id}/logs?cursor=`, `.../metrics?cursor=` | 100-104, `pipeline.py` 127-132 | integer `cursor`; client stores `next_cursor` | query match |
| `GET /v1/checkpoints/{id}` | 106-107 | | match |
| `GET /v1/deployments`, `GET /v1/deployments/{id}`, `.../contract` | 109-116 | | match |
| `POST /v1/deployments/{id}/sessions` | 118-120, `arm/sessions.py` 27-28 | `session_id` `scrub-` + 32 hex chars, `ttl_seconds` 21600 | `SessionGrantRequest` match |

There is no `GET /v1/datasets` collection in the schema, and the client does not call one. Signed `PUT` plus the 303 poll `GET` are outside this file; `arm/upload_dataset.py` lines 54-79 match the workshop (HTTPS, returned headers, no team key, no body on the poll).

Inference routes are not in the saved OpenAPI. `arm/test_perceptron.py` lines 46-51 only check control paths, so an inference drift would still pass that test. The client matches the workshop deck: base URL is `grant.endpoint_url` or else `https://robotics.perceptron.inc/v1/inference` (`arm/perceptron.py` lines 126-134), then `POST deployments/{id}/sessions`, `POST sessions/{id}/predict`, `POST .../reset`, `DELETE .../sessions/{id}`.

## Inference behavior

Checked in code and in `arm/test_real_arm.py` / `arm/test_streaming.py`. No defect against the deck.

- One robot session per instruction. `SessionPool` keeps a session for that string. A different instruction closes the previous one (`test_new_instruction_closes_old_session`). `reset` runs at the end of `run_skill`. `DELETE` runs on close, and the next session takes a new grant (`arm/sessions.py` 22-34 and 46-58).
- Playback is 30 Hz (`streaming.py` `HZ`). A predict is scheduled every 15 rows (`STRIDE`). The first metadata object has no `rtc`. Later ones send `prior_chunk_id`, `prior_start_index`, `delay` 12, and `committed_actions` (the rows the rate limiter will actually play).
- Horizon is 30. `accept` requires `actions` shaped `(30, 6)`. Training sends `action_horizon` 30.
- Deadline is 400 ms. `PREDICT_TIMEOUT_S` is 0.4 (`perceptron.py` line 17). `Timeline.accept` (`streaming.py` lines 77-79) drops a reply at or after capture + 12/30 s. `test_late_replies_are_dropped_including_exact_deadline` and `test_late_policy_holds_and_max_s` cover that. Images are PNG, 640x480 (`arm/backends.py` lines 17-24). User-Agent is set on both clients. One predict is in flight (`test_one_predict_in_flight`).
- Timeout and 5xx: `httpx` timeout becomes `APIError` with no status (`_status` is `None`). `None`, 429, 500, 502, 503, and 504 are `TRANSIENT` (`real_arm.py` lines 37-40). The chunk is not applied, the arm holds, sequence increments, and the next loop captures a new frame. Five consecutive transient failures raise and `freeze()` (`PREDICT_TRIES`). 401, 404, and 410 re-grant once. 409 and 422 reset the session and clear the chunk history.
- Stop wins. `freeze` (`real_arm.py` lines 502-504) sets two events and returns. `test_freeze_during_inflight_reply_is_nonblocking_and_latched` measured it under 50 ms, and the in-flight reply was not accepted. The 30 Hz thread holds the last command (on purpose: sending measured joints lets the P-only servos sag).

`arm/rig.json` has `hardware_verified: false` and `verified_contract_id: null`. `Arm.connect` refuses a real arm until the rig is measured. `PolicySession` refuses a contract id that is not pinned. That blocks `--real-arm`. It does not block training.

## Pre-flight checklist

Run this on the Mac, from the repo root, before either training job. Stop when a step fails. Do not start a third job.

1. Set `PERCEPTRON_TEAM_API_KEY` in `.env`. Run `python -m arm.train capabilities` and `python -m arm.train deployments`. Neither may print `Perceptron HTTP 401`. Read how many successful jobs are left. If it is under 1, stop.
2. Train `<HF_USER>/scrub` only. Ignore the `scrub-surgical` example. Do not train `~/scrub-dataset-backup-1820` or `~/scrub-dataset-blackwrist-1820`.
3. Record with `python -m arm.record` so the caps stay 25 s / 10 s and the task is an exact string from the list in finding 2. `pick the kelly` and `pick the allen key` are the wrong strings (`pick the hemostat`, `pick the hex key`).
4. Confirm the printed command contains `--robot.use_degrees=true` and `--teleop.use_degrees=true`. After one episode, `shoulder_lift` in the parquet should sit near the real rest (about -104 deg).
5. Cameras are named `side` and `wrist`, 640x480. Open `<root>-cadence.json`. Every episode needs `measured_fps` in 29..31 and `camera_fps.side` and `camera_fps.wrist` at least 29. A `slow camera` line means re-record. Do not write this file by hand. `arm.record --lerobot` does not write it.
6. Both video files exist under the dataset. `python -m explore.dataset.qa --root ~/scrub-dataset --out ~/qa.html` shows zero FAIL (dark, frozen, or repeated frames included). Replay episode 0 on the follower with `--robot.use_degrees=true` before either run.
7. Count episodes per exact instruction. The service splits about 90/10 by whole episode, stratified by task, and fails a dataset that is too small to split. Give every instruction in this run at least 10 episodes. `local_check` currently accepts 2 episodes total, which is not enough. Run 1 is the operating-room strings. Run 2 appends the bench strings to the same dataset.
8. One calibration (`scrub_follower`, `scrub_leader`) and the cameras stay taped for the whole repo. Append with the recorder's `--resume=true`. Counts to hit before run 2: surgical 20 pick and 10 return per item, bench 15 pick and 10 return per item (`docs/TRAINING.md`). `team/LEFT.md` line 25 is stale; `docs/DATA-LOG.md` already matches TRAINING.md.
9. Push that folder. Pass `--revision` as the new commit SHA. Pass `--confirmed-hf-matches-local` only after that SHA is the folder you checked.
10. Check first: `python -m arm.train pipeline ~/scrub-dataset --cadence-report ~/scrub-dataset-cadence.json --check-only`. Then the real run with `--repo-id <HF_USER>/scrub --revision <SHA> --idempotency-key scrub-run-1 --confirmed-replay --confirmed-hf-matches-local`. Run 2 uses `scrub-run-2` on the same repo. Use `standard`, `expert_only`, horizon 30, RTC on, 1000 steps. Do not use `python -m arm.train train`.
11. If the command dies after the POST, run it again with the same key and the same JSON. A changed body returns 409. A new key can spend the other job. Wait until the dataset state is `ready` and `/validation` has no errors. A failed dataset means a new dataset id, not a training job.
12. After a deployment is `ready`, `python -m arm.train contract <id>`. Pin `contract_id` in `arm/rig.json` only when it shows six joints in the contract order, degrees, gripper 0..100, cameras `side` and `wrist`, horizon 30, 30 Hz, RTC delay 12. Leave `hardware_verified` false until the Mac measurements in `team/LEFT.md` are done.

## GET results

No HTTP call was made.

| Check | Result |
| --- | --- |
| `PERCEPTRON_TEAM_API_KEY` | Name is in `.env`. Value length 0. Treated as missing. |
| `GET /v1/capabilities` | Not sent. Quota unknown. |
| `GET /v1/datasets` | Not sent. The saved OpenAPI has no list route, only `GET /v1/datasets/{id}`. |
| `GET /v1/jobs` | Not sent. Jobs unknown. |
| `GET /v1/deployments` | Not sent. Deployments unknown. |
| 401 | Not observed this run. An earlier note in `team/LEFT.md` line 23 says a previous key was rejected with `Perceptron HTTP 401`. |

## arm/ tests

Interpreter: repo `.venv` Python 3.10.22. `pyarrow` was missing (it is listed in `arm/requirements.txt`); 23.0.1 was installed into that venv, then the suite was rerun. No training job was started.

`python -m unittest discover -s arm -t . -p test_*.py` from the worktree:

- Ran 94, passed 93, failed 1.
- Failure: `arm.test_safety.BackendTests.test_busy_port_is_refused` (`arm/test_safety.py` line 247). `port_holders` returns `[]` when `lsof` is not on PATH (`arm/backends.py` lines 79-80). This PC has no `lsof`, so the mocked `run` never runs. The Mac has `lsof`. The later "port in use" assertions in that test were not reached.

`python -m arm.train self-test` (mocked pipeline, no network): 9 passed, 0 failed.

The 10 tests in `arm/test_pipeline.py` did not run until `pyarrow` was installed. They passed on the rerun, including "validation failure never trains" and "bad metadata never opens a client."

## Cannot be checked without the Mac

- `~/scrub-dataset` is not on this PC. `team/LEFT.md` says it does not exist yet, and the only local sets are the two 4-episode backups, which are not the training set. No real `meta/info.json`, videos, or `<root>-cadence.json` was read.
- Whether the wrist camera still runs at 22.6 fps, whether the C920 is visible, and whether a saved frame is bright.
- Whether the follower calibration from 21:49 still matches the bus, and whether `shoulder_lift` rest is still about -104 deg.
- `lerobot-replay` of episode 0, `explore/dataset/qa.py` on a real folder, and `aim.py` (`ps` is macOS-only).
- Which codebase version LeRobot on the Mac writes (v2.1 jsonl vs v3 parquet).
- The live `endpoint_url` on a session grant. Creating a grant is a POST, so it was not called. The fallback base is `https://robotics.perceptron.inc/v1/inference`.
- Predict latency on the venue network against the 400 ms deadline.
- Gripper `Present_Load` sign change on a real grasp.
- `arm/rig.json` poses are still null. That is a hardware measurement, not a training-schema check.
