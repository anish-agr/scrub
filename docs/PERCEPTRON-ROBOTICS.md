# Perceptron APIs: Robotics (training and inference) and Vision (detect, captions)

This file has two parts. Part 1 is the Robotics API (Anish). Part 2 is the Vision API that `vision/` calls (Brandon).

## Part 1: Robotics API (training and inference)

Owner: Anish. Source: https://robotics.perceptron.inc/docs (read Sat Oct 17, 12:55 PM). The full schema is saved in `docs/perceptron-openapi.json`, so agents can read it offline. If the live docs change, they win.

Base URL: `https://robotics.perceptron.inc`.

## Workshop facts that override this file

Caiden's notes from the workshop deck are in `explore/research/isaac-workshop-notes.md` (sections 2 and 5). Where they differ from below, the notes win. The ones that change our plan:

- **Only 2 successful training jobs per team.** Run 1 (operating room set, a probe) and run 2 (everything). No third run. Validate every dataset before training (`lerobot-replay --dataset.episode=0`, the cadence line, `GET /validation`).
- **One dataset for everything:** one Hugging Face repo (`<user>/scrub`), one calibration, cameras never moved. Later slots append with `--resume=true --dataset.root=...`. Each job starts from the base model, so run 2 needs all episodes in that one dataset.
- Record with `--robot.use_degrees=true`, `--dataset.fps=30`, `--dataset.episode_time_s=25`, `--dataset.reset_time_s=10`. Keys: `n` ends an episode, `r` re-records, `q` stops. Check the cadence report after each episode (it must be about 30 Hz).
- Training: `standard`, `expert_only`, horizon 30, RTC on, 1000 steps, about 45 min plus export. Run `GET /v1/capabilities` first and write the result in `docs/ARM.md`.
- Inference: two threads on one clock. A 30 Hz thread plays the chunk row by row and holds if nothing covers now. A predict every 15 rows with `rtc: {prior_chunk_id, prior_start_index, delay: 12}` (none on the first call), a 400 ms deadline, late replies dropped, one request in flight, PNG images, a descriptive User-Agent. p95 latency is about 283 ms. Check in the OpenAPI schema whether inference is under `/v1/inference/...` or a returned `endpoint_url`.
- After `DELETE` a session, a new grant is needed. Use `reset` between runs of the same instruction.
- No gripper load from the model (positions only). Read load from the Feetech bus directly, with "got it" as the fallback.
- The workshop deck documents no vision API. The vision API is a separate product with its own key; see Part 2. Control calls use `Authorization: Bearer $PERCEPTRON_TEAM_API_KEY`. Inference calls use the two session tokens instead, never the team key.

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

## Part 2: Vision API (detect and captions)

Owner: Brandon. Docs: https://docs.perceptron.inc/capabilities/detect (checked Oct 17, 2026). Training and inference for the arm are Part 1.

### Detect: endpoint and auth

- `POST https://api.perceptron.inc/v1/detect`
- Header `Authorization: Bearer $PERCEPTRON_API_KEY` (not the team key from Part 1)
- Header `Content-Type: application/json`

The vision process calls this about once a second (`tray_period` 1.0 s in `vision/service.py`) from `vision/tray.py`. `reasoning_effort` is `none` so the call stays on the fast path. Frames are scaled to 640 px wide. Categories are the current setting's item names (underscores written as spaces), plus `robot arm` and `gripper` for the blocked-path check.

Check a live call with `python -m vision.lighting --check-api`. It prints HTTP status, latency, and how many detections came back. It does not print the key.

### Detect: request

Image bytes go in a data URL. Coordinates in the response are pixels, not the 0 to 1000 chat grid.

```json
{
  "media": {"type": "image", "image_url": "data:image/jpeg;base64,<jpeg of the overhead frame>"},
  "categories": ["scalpel", "hemostat", "mayo scissors", "robot arm", "gripper"],
  "config": {"output": "box", "reasoning_effort": "none"}
}
```

- `config.output` is `"box"` (not `"bbox"`). `"point"` returns a center instead of `point_box`.
- Category strings must be non-empty and must not contain commas. Up to 256.
- `config.enable_thinking` is an old alias: `true` means `high`. Do not send it. We want `reasoning_effort: "none"`.
- `finish_reason` `"max_tokens"` means the model stopped early. Treat a failed HTTP call, an `error` object, or an empty body the same way: keep the last good TrayState and set `stale` true.

### Detect: response

There is no confidence field. `vision/tray.py` writes `confidence: 1.0` on a fresh response.

```json
{
  "detections": [
    {
      "mention": "hemostat",
      "point_box": {
        "top_left": {"x": 130.0, "y": 90.0},
        "bottom_right": {"x": 240.0, "y": 130.0}
      }
    }
  ],
  "finish_reason": "complete"
}
```

`mention` is one of the categories we sent. We match it to an item id by lowercasing and treating spaces, underscores, and hyphens as the same, and we also accept that item's aliases (`kelly` matches hemostat when the setting file lists it).

A slot is present when the detection center lies inside the slot box, or the intersection-over-union with the slot is at least 0.15. The TrayState `box` is the slot box from `settings/<id>.json`, not the detection box. Until those boxes exist, a matching detection anywhere marks the item present and `box` stays null. The return spot uses the same overlap test against `return_spot`.

### Detect: latency and limits

| Limit | Value |
| --- | --- |
| Measured latency | 3.11 seconds, one live call on a 640x480 frame (Oct 17). `docs/RECOGNITION.md` measured a median of 2.5 s in its bench, and `vision/tray.py` notes 3.8 to 4.7 s per call on 640x480 trays |
| Request timeout we use | 6.0 seconds (`vision/tray.py`) |
| Body size | 20 MiB (docs) |
| Categories | 256 |
| Our tray period | 1 second, so a lift shows up on the next successful call |
| Confidence | not returned |

When a call fails or exceeds the timeout, the last good TrayState is posted again with `"stale": true`. That field is optional and extra; the rest of the body still matches `docs/CONTRACTS.md`. Live testing confirmed that the endpoint accepts the data URL payload and respects `reasoning_effort: "none"`. Recognition accuracy per item is in `docs/RECOGNITION.md`.

### Chat completions: captions and video

Perceptron has an OpenAI-compatible Chat Completions API for image captions, video understanding and temporal clipping (checked from `docs.perceptron.inc` Oct 17, 2026).

- `POST https://api.perceptron.inc/v1/chat/completions`, same headers and key as detect.
- Model: `perceptron-mk1.5` (or `perceptron-mk1`). `vision/clips.py` uses `perceptron-mk1.5`.
- Concise caption, SDK helper `caption(style="concise")`, prompt `"Provide a concise, human-friendly caption for the upcoming image."` We use it for short event lines in the case log, like `"scalpel set at the safe spot, 14:02"`.
- Detailed caption, `caption(style="detailed")`, prompt `"Provide a detailed caption describing key objects, relationships, and context in the upcoming image."`
- Video input (`video/mp4`, `video/webm`) goes in as a hosted `video_url`, the SDK `video()` helper, or sampled frames as `image_url` data URLs. A request with clipping and thinking:

```json
{
  "model": "perceptron-mk1.5",
  "messages": [
    {
      "role": "user",
      "content": [
        {"type": "video_url", "video_url": {"url": "https://example.com/clip.mp4"}},
        {"type": "text", "text": "Identify and label the key action in this clip (e.g. 'scalpel set at the safe spot')."}
      ]
    }
  ],
  "vision_config": {"annotation_format": "clip", "enable_thinking": true}
}
```

- `vision_config.annotation_format` `"clip"` asks the model to localize moments and return clip annotations in seconds.
- `vision_config.enable_thinking` `true` turns on reasoning traces (`<think>` blocks).
- Without public video hosting, send key frames as `{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}`.

### Case replay clips (X4)

1. `vision/clips.py` keeps an in-memory ring buffer of recent overhead frames at 640 px wide.
2. For each controller event of type `picked`, `handed`, `set_down`, `released`, `returned`, `stopped` or `missed`, `vision/service.py` saves a 3 second `.mp4` (`pre_s=1.5`, `post_s=1.5`) under `vision/clips/<case_id>/`.
3. `POST /clips/label` asks the chat completions endpoint to describe each clip's key frame. With no key, or when the call fails, it writes a fallback label (`"<item> <action>, HH:MM"`).
4. Endpoints on port 8001:
   - `GET /clips?case_id=<case_id>`: clips and labels for a case.
   - `POST /clips/record`: capture a clip around an event by hand.
   - `POST /clips/label` with `{"case_id": ...}`: label all clips for a case.
   - `GET /clips/{case_id}/{filename}`: stream a clip (`.mp4`) or thumbnail (`.jpg`).
