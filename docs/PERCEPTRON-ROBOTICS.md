# Perceptron Robotics API (training and inference)

Owner: Anish. Source: https://robotics.perceptron.inc/docs (read Sat Oct 17, 12:55 PM). The full schema is saved in `docs/perceptron-openapi.json`, so agents can read it offline. If the live docs change, they win.

Base URL: `https://robotics.perceptron.inc`. Control calls use `Authorization: Bearer $PERCEPTRON_TEAM_API_KEY`. Inference calls use the two session tokens instead, never the team key.

## What this means for our recording

The model only accepts data in this shape, so `lerobot-record` has to match it exactly:

| Thing | Required |
| --- | --- |
| Frame rate | 30 FPS |
| Cameras | two RGB cameras at 640x480, named `side` and `wrist` (`observation.images.side`, `observation.images.wrist`) |
| State and action | six values in this order: `shoulder_pan.pos`, `shoulder_lift.pos`, `elbow_flex.pos`, `wrist_flex.pos`, `wrist_roll.pos`, `gripper.pos`. Arm joints in degrees, gripper 0 to 100 |
| Format | LeRobot dataset v2.0, v2.1 or v3.0, with `meta/info.json`, episode metadata, data chunks, both videos, original timestamps and episode boundaries |
| Split | at least one training and one validation episode |

Recording command shape (fill the ports and camera indexes at the arm):

```
lerobot-record \
  --robot.type=so101_follower --robot.port=<follower port> --robot.id=scrub_follower \
  --robot.cameras="{ side: {type: opencv, index_or_path: <i>, width: 640, height: 480, fps: 30}, wrist: {type: opencv, index_or_path: <j>, width: 640, height: 480, fps: 30} }" \
  --teleop.type=so101_leader --teleop.port=<leader port> --teleop.id=scrub_leader \
  --dataset.repo_id=<hf user>/scrub-surgical \
  --dataset.single_task="pick the hemostat" \
  --dataset.num_episodes=15 \
  --dataset.fps=30
```

Each instruction ("pick the hemostat", "return the hemostat") is recorded as its own batch with its own `single_task`. Ask Perceptron whether one dataset can mix tasks (LeRobot's `--resume=true` appends to an existing dataset). If not, train one model per setting.

## Two ways to send a dataset

1. **Public Hugging Face repo (easiest).** Record with push to the Hub on and the repo public, then `POST /v1/datasets` with `{"name": ..., "source_kind": "huggingface", "repo_id": "<user>/scrub-surgical", "revision": "main"}`. Needs `HF_TOKEN`.
2. **Direct upload.** `POST /v1/datasets` with `source_kind: "upload"`, then `POST /v1/datasets/{id}/uploads` with each file's path, size and lowercase SHA-256 (up to 500 per batch, `meta/info.json` required). PUT each file's bytes to its signed URL with the returned headers (URLs expire in 15 minutes, no team key on the PUT). Then `POST /v1/datasets/{id}/finalize`. `arm/upload_dataset.py` does this.

Both return a dataset id. Then poll `GET /v1/datasets/{id}` until ready and read `GET /v1/datasets/{id}/validation` before training. Keep each `Idempotency-Key` the same when retrying the same request.

## Training

1. `GET /v1/capabilities` for the allowed backends, modes, horizons and limits.
2. `POST /v1/jobs` with, for example, `{"dataset_id": ..., "backend": "standard", "mode": "expert_only", "action_horizon": 30, "rtc_enabled": true, "steps": 1000}`.
3. Follow `GET /v1/jobs/{id}`, `/logs` and `/metrics` (pass the returned cursor to continue).
4. When it succeeds: `GET /v1/checkpoints/{id}`, then `GET /v1/deployments` and wait for one in `ready` state. `GET /v1/deployments/{id}/contract` gives the `contract_id` and the exact observation and action format.

`arm/train.py` wraps these: register, wait, validate, train, wait, print the deployment id.

## Inference (what `arm/real_arm.py` does in `run_skill`)

1. **Grant:** `POST /v1/deployments/{id}/sessions` with the team key and `{"session_id": "scrub-01", "ttl_seconds": 21600}`. It returns `endpoint_url`, `application_session_token`, `modal_session_token`, `session_id`.
2. **Robot session:** `POST {endpoint_url}/deployments/{id}/sessions` with headers `Authorization: Bearer <application_session_token>` and `Modal-Authorization: Bearer <modal_session_token>`, body `{"instruction": "pick the hemostat", "rtc_enabled": true, "contract_id": ...}`. **The instruction is set per session**, so each skill opens (or reuses a cached) session for its instruction.
3. **Loop:** `POST {endpoint_url}/sessions/{session_id}/predict`, multipart: a `metadata` JSON field (`contract_id`, `observation_id`, `sequence` counting up, `timestamp_seconds`, the six-value `state`, `image_encoding`) plus `side` and `wrist` image files. It returns an action chunk. Send the actions to the arm on the contract's timing. Optional `rtc` object for real-time chunking (`prior_chunk_id`, `prior_start_index`, `delay`, `committed_actions`).
4. **Between episodes:** `POST {endpoint_url}/sessions/{session_id}/reset`. **When done:** `DELETE {endpoint_url}/sessions/{session_id}`.
5. Sessions expire after inactivity. On an expired session, get a fresh grant and a new session.

The API doesn't say when a skill is finished, so `run_skill` stops on whichever comes first: `max_s`, the gripper closed on something and the arm still for about 1 second, or `freeze()`. The controller then checks the grasp.

## Cameras and our vision process

The model uses the `side` and `wrist` cameras, and LeRobot opens them. Brandon's `vision/` needs its own overhead camera (a third USB webcam). If there's no third camera, `vision/` reads the side camera instead and the arm gets its frames from `vision/`. Decide this at the arm; it changes `arm/` and `vision/`, so tell Caiden too.

## Questions still open

- Can one dataset hold several instructions, and does the model follow the instruction?
- How long does a 1,000-step run take, and what step count do they suggest for about 75 to 225 episodes?
- How many deployments can a team have at once?
- Typical predict latency per chunk.
