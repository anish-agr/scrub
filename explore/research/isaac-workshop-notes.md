# Isaac 0.5 DubHacks robotics workshop: notes

Source: Perceptron "Isaac 0.5 · DubHacks Robotics Workshop" deck (final.html), text and the "Commands" drawers (press C in the deck) extracted. "(inferred)" marks my own reasoning, not deck text. The deck itself says: if a slide disagrees with the live docs (`/docs`, `/openapi.json` on the base URL) or `GET /v1/capabilities`, trust those.

## 1. What Isaac 0.5 is

- Perceptron's open embodied foundation model: one sparse model covering video understanding, embodied reasoning and robot control (a vision-language-action model, VLA).
- Architecture: 35B-parameter mixture-of-experts VLM backbone (256 experts, top-8 routing, about 3B active per token), plus an action expert (diffusion transformer, about 0.58B params) that does flow matching (10 Euler steps per sample, 8 samples averaged at serving, BF16, no quantization).
- Inputs per call: side image, wrist image (RGB, up to 1920x1080; server resizes to 448x448, 16 px patches merged 2x2, 196 tokens per camera), a text instruction, and 6 raw joint readings (server normalizes with q01/q99 stats from your training episodes; never normalize client-side).
- Output: an action chunk, 30 rows x 6 absolute joint targets, already in robot units (degrees for 5 arm joints, gripper 0-100), in contract order: `shoulder_pan.pos, shoulder_lift.pos, elbow_flex.pos, wrist_flex.pos, wrist_roll.pos, gripper.pos`. Row 0 = the moment of capture.
- Control rate: 30 Hz control loop (33 ms ticks). A chunk spans 30 rows = about 1 s. Client asks for a new chunk every 15 rows (2 requests/s).
- Real-time chunking (RTC): the rows that will run while the model is thinking are committed (up to 12 rows = 400 ms) and the model plans the rest to continue from them. The reply is only usable if it lands before capture + 400 ms; otherwise it is rejected, the old chunk has 3 reserve rows, then the robot holds. Trained on delays of 1-12 rows (Poisson, mean 5); delay over 12 is rejected.
- Latency: 283 ms at p95 for one robot on Perceptron's private cluster path; "over the internet it will be more". Budget about 8 Mbit/s uplink per robot (about 0.5 MB per request with two PNGs, 2 Hz).
- Camera requirements: exactly two RGB streams named `side` (fixed, sees the whole task) and `wrist` (on the gripper), 640x480, 30 fps. Rule of thumb from the deck: "If you couldn't do the task looking only at these two images, the model can't either."
- Base: your fine-tune starts from service base checkpoint step 50,000 of an SO100/SO101 fine-tune (36,961 trajectories from 1,205 LeRobot repos). Calibration must make your degrees mean what theirs meant.
- Hardware: SO-100/SO-101, leader + follower, six Feetech STS3215 servos. State = follower joints, action = leader joints.
- Example dataset: `PerceptronAI/so101-tictactoe-dubhacks`, 349 episodes, 215,598 frames, 2.0 h (so about 618 frames = about 21 s per episode, derived).

## 2. The exact workflow

Stages: Setup, Record, Dataset, Ingest, Fine-tune, Monitor, Deploy, Infer. You hold: base URL `https://robotics.perceptron.inc`, one team API key, a terminal. No SDK, no cloud credentials. All steps from "register dataset" on are plain HTTPS (curl).

Key facts by stage (details in the verbatim commands below):

- **Setup.** Team key goes in `team.key`, build `control.headers` from it (private files, chmod 600). Team key is for the control API only; never send it to signed upload URLs or `/v1/inference`. Call `GET /v1/capabilities` first (modes, horizons, control profiles, quotas, budgets; "anything not listed fails explicitly"). `GET /openapi.json`, `/docs`, `/healthz` (also under `/v1/`).
- **Arms.** Install LeRobot from source; `lerobot-find-port`; `lerobot-setup-motors` only if motors are not already id'd (once per arm; new motors ship as id 1; gripper = 6 down to shoulder pan = 1); `lerobot-calibrate` follower and leader. Calibration: all joints to mid-range, Enter, then sweep each joint through full range. The `--robot.id` / `--teleop.id` name the calibration file; reuse the same ids for teleoperate, record and policy run. "Once per dataset: recalibrating shifts what every number means. Keep one calibration for all episodes of a dataset." Waveshare boards: both jumpers on channel B (USB).
- **Cameras.** `lerobot-find-cameras opencv`; ids can change after reboot or re-plug, re-run every session. `lerobot-teleoperate ... --display_data=true` opens Rerun with both feeds.
- **Recording.** `lerobot-record` with `--robot.use_degrees=true`, cameras named `side`/`wrist` 640x480@30, `--dataset.fps=30`, `--dataset.single_task="<instruction>"`. Keys: right arrow or `n` ends the episode early / skips the rest of reset; left arrow or `r` discards and re-records; Esc or `q` stops, encodes videos, finishes. Defaults: `--dataset.episode_time_s` 60 s, `--dataset.reset_time_s` 60 s (reset is not recorded), `--dataset.num_episodes` 50. Resume an interrupted session with `--resume=true` (then `num_episodes` counts additional episodes and `--dataset.root` is required). Read the cadence report after each episode (e.g. 29.88 Hz vs 30 Hz; "8/599 ticks over the 33.3 ms budget"): timestamps come from frame indices, so a laptop that only managed 25 Hz still claims 30 fps and the data plays back too fast; the validator cannot catch it.
- **Dataset contract (validator).** LeRobot v2.0 / v2.1 / v3.0 at exactly 30 fps; complete episodes; video and timestamps agree; exactly two RGB streams `side` and `wrist`, each 640x480; six float32 values for state and action in order; `meta/info.json`; at least 1 train and 1 validation episode (split is about 90/10 by whole episodes, stratified by task). The validator can't check that calibration is sane.
- **Demo guidance.** "50+ episodes" is the LeRobot guide's starting point, "about 10 per object location" (five locations x 10). Consistent behavior across episodes (contradictory demos "blur the policy"); fixed cameras (don't bump them mid-dataset); object always visible; vary slowly (make one setup reliable, then add locations, grasps, camera changes); record with the exact task text you will send as the instruction (one phrasing); spot-check with `lerobot-replay --dataset.episode=0` before spending a training run. "Data quality beats data quantity."
- **Upload.** Two ways, both `POST /v1/datasets` with required `Idempotency-Key` (same key + same JSON = same dataset; same key + different JSON = 409). Recommended: public Hugging Face repo (`source_kind: "huggingface"`, `repo_id`, `revision`), service fetches it, ingestion queued automatically, no upload/finalize. Alternative: direct upload (`source_kind: "upload"`, then reserve, PUT, finalize). Upload limits: allowed types `.json .jsonl .parquet .mp4 .png .jpg .jpeg`, nonzero size, relative paths up to 512 chars, no symlinks, `meta/info.json` required, 1-500 files per reservation, 4 GiB per file, 20 GiB per dataset, request body under 512 KiB (else 413), signed URLs last 900 s (re-reserve the same unchanged files for fresh ones while state is `uploading`), PUT can return 303 (follow `Location` exactly, no auth, don't resend body). Finalize pins sizes/hashes; never upload after.
- **Ingest.** States `uploading, queued, ingesting, validating, ready` (any can go to `failed`). Worker re-hashes, validates, converts to MDS shards, splits about 90/10 by episode stratified by task, computes q01/q99 from train episodes only, loads real samples. Reference run: 50 episodes = 16 files, 609 MB, 41 train / 9 val, 22 MDS objects. Train only on `ready`; `/validation` says which stage failed. Poll every few seconds.
- **Fine-tune.** `POST /v1/jobs` body: `dataset_id`, `backend` (`standard` or `shared`), `mode` (`expert_only`, `backbone_lora`, `full`; `shared` allows only `expert_only`), `action_horizon: 30`, `rtc_enabled: true`, `steps: 1000` ("the workshop setting"; "30 and true is the advertised preset. Don't assume H20 or RTC-off; check capabilities"). Projected times on 8xH100 (extrapolated from 100-update runs, no 1,000-update run measured, excludes export/queueing/retries): `expert_only` about 45 min (hackathon default), `backbone_lora` about 54 min, `full` about 4.4 h, `shared` backend about 4.9 h (17.6 s/update). Measured on a 100-update expert_only run: 9.4 min startup, 1.7 s/update steady state, 3.3 min final checkpoint, then export and verification. Recipe LR schedule: 200-update warmup, 10,000-update cycle, your job stops at 1,000.
- **Quotas (default; live values from the API).** 2 successful jobs per team, 2 queued jobs per team, 6-hour timeout per job, 120 API requests/min. Cancel is a request; quota stays held until GPUs exit.
- **Monitor.** `GET /v1/jobs/{id}`, `/logs?cursor=0`, `/metrics?cursor=0` (then `next_cursor`), `POST /v1/jobs/{id}/cancel`.
- **Deploy.** Training complete != export complete != inference ready. After export: load artifact, check contract, numerical equivalence; checkpoint becomes `inference_ready`, then a deployment appears in `GET /v1/deployments`; use only one in `ready`. `GET /v1/deployments/{id}/contract` pins joint order/units, cameras, horizon 30 at 30 Hz, RTC limits, image limits and `contract_id` (old contract_id is refused).
- **Infer.** Exchange team key for two session credentials (grant, `ttl_seconds` 21600 = default and max), write `inference.headers` (`Authorization: Bearer <application_session_token>`, `Modal-Authorization: Bearer <modal_session_token>`), send both on every `/v1/inference/*` call, never the team key. Create robot session with `instruction`, `rtc_enabled`, `contract_id`; the robot session is bound to the grant's `session_id`. **One instruction per session** (set when the session opens; use the recorded phrasing). Predict: multipart `metadata` JSON + `side` + `wrist` binary images (PNG lossless, no base64). `sequence` strictly increasing, `timestamp_seconds` increasing on the robot's own clock and consistent with rows elapsed (15 rows later = +0.5 s). Keep exactly one request in flight per session. First request has no `rtc`; later ones carry `rtc: {prior_chunk_id, prior_start_index, delay}` (`delay` 1-12; `deadline_ms = delay/30 s = 400`). Reply echoes the committed rows (`prefix_length` 12, `rtc_applied` true); start executing at `execute_from_index` (12), switching at the boundary rather than when the reply lands. If you executed something different from the stored chunk, send `rtc.committed_actions` (one six-value row per delayed step; see `/docs`). Reset between episodes with `POST .../reset` (clears sequence, timestamps, RTC history); `DELETE` ends the robot session (to continue: fresh grant, new session id, new robot session). Idle robot sessions expire earlier than the grant; sessions do not survive an inference redeploy. Health: `GET /v1/inference/health` (model assignment) and `/healthz` (inference process) need only the Modal token. Own client: set a descriptive User-Agent (edge rules reject Python urllib's default).
- **Control loop (deck sketch).** Two threads, one clock. 30 Hz control thread plays the active chunk row by row, holds position if no accepted chunk covers now. 2 Hz inference thread, every 15 rows: capture side, wrist and joints on one clock, send with RTC block, accept the reply only if `now < capture + 12/30`.

### 2.1 Verbatim commands (from the deck's Commands drawers, in slide order)

Identifiers like `team/pick-place`, `ds_REPLACE`, `place the blue block in the tray` are the deck's placeholders.

**Save the key and build the header file (both private: only you can read them)**

```bash
umask 077
CONTROL_URL=https://robotics.perceptron.inc   # the base URL
chmod 600 ./team.key
{
  printf 'Authorization: Bearer '
  tr -d '\r\n' < ./team.key
  printf '\n'
} > control.headers
chmod 600 control.headers
```

**Ask what this service allows, and save the live schema**

```bash
# What this service allows, and the live schema
curl --fail-with-body --silent --show-error --header @control.headers \
  "$CONTROL_URL/v1/capabilities"
curl --fail-with-body --silent --show-error \
  "$CONTROL_URL/openapi.json" > participant-openapi.json
```

**Check the service is up (also at /v1/healthz)**

```bash
curl --fail-with-body --silent --show-error "$CONTROL_URL/healthz"
```

**Install LeRobot with the core scripts and Feetech motor support**

```bash
# huggingface.co/docs/lerobot/so100 · SO-101: same commands
conda create -y -n lerobot python=3.12
conda activate lerobot
conda install ffmpeg -c conda-forge
git clone https://github.com/huggingface/lerobot.git && cd lerobot
pip install -e ".[core_scripts]"
pip install -e ".[feetech]"
```

**Find each arm's port**

```bash
lerobot-find-port # unplug that arm's USB cable when asked
ARM=so100 # or so101
FOLLOWER=/dev/ttyACM0 # macOS: /dev/tty.usbmodem…
LEADER=/dev/ttyACM1
sudo chmod 666 $FOLLOWER $LEADER # Linux only
```

**Write the motor ids, once per arm**

```bash
# Once per arm: one motor plugged in at a time, gripper first
lerobot-setup-motors --robot.type=${ARM}_follower --robot.port=$FOLLOWER
lerobot-setup-motors --teleop.type=${ARM}_leader --teleop.port=$LEADER
```

**Calibrate the follower, then the leader**

```bash
lerobot-calibrate \
  --robot.type=${ARM}_follower --robot.port=$FOLLOWER --robot.id=follower
lerobot-calibrate \
  --teleop.type=${ARM}_leader --teleop.port=$LEADER --teleop.id=leader
```

**Find your cameras (ids can change after a reboot or re-plug)**

```bash
lerobot-find-cameras opencv # note each camera's Id
```

**Name them side and wrist, then teleoperate with both feeds in Rerun**

```bash
SIDE='{type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30}'
WRIST='{type: opencv, index_or_path: 1, width: 640, height: 480, fps: 30}'
lerobot-teleoperate \
  --robot.type=${ARM}_follower --robot.port=$FOLLOWER \
  --robot.id=follower --robot.cameras="{side: $SIDE, wrist: $WRIST}" \
  --teleop.type=${ARM}_leader --teleop.port=$LEADER --teleop.id=leader \
  --display_data=true
```

**Record locally into ./lerobot-export (set ARM, FOLLOWER and LEADER as in setup)**

```bash
# Same ARM, ports, ids and cameras as setup; record locally
# --dataset.push_to_hub=true publishes a public Hugging Face repo (recommended: register its repo_id on slide 24)
# push_to_hub=true needs a Hugging Face login with a write token (hf auth login) and a repo in your own account: --dataset.repo_id=<your-hf-user>/pick-place
# --dataset.push_to_hub=false keeps the local folder for direct upload (the alternative, as written below)
SIDE='{type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30}'
WRIST='{type: opencv, index_or_path: 1, width: 640, height: 480, fps: 30}'
lerobot-record \
  --robot.type=${ARM}_follower --robot.port=$FOLLOWER \
  --robot.id=follower --robot.use_degrees=true \
  --robot.cameras="{side: $SIDE, wrist: $WRIST}" \
  --teleop.type=${ARM}_leader --teleop.port=$LEADER \
  --teleop.id=leader \
  --dataset.repo_id=team/pick-place \
  --dataset.root=./lerobot-export \
  --dataset.fps=30 --dataset.num_episodes=50 \
  --dataset.single_task="place the blue block in the tray" \
  --dataset.push_to_hub=false
```

**Spot-check before uploading: replay episode 0 on the follower**

```bash
# Spot-check before uploading: replay episode 0 on the follower
lerobot-replay --robot.type=${ARM}_follower --robot.port=$FOLLOWER \
  --robot.id=follower --dataset.repo_id=team/pick-place \
  --dataset.root=./lerobot-export --dataset.episode=0
```

**Recommended: register a public Hugging Face dataset (publish it with --dataset.push_to_hub=true first)**

```bash
cat > hf-dataset.json <<'EOF'
{"name":"team-pick-place","source_kind":"huggingface","repo_id":"<your-hf-user>/pick-place","revision":"main"}
EOF
curl --fail-with-body --silent --show-error --header @control.headers \
  --header 'Content-Type: application/json' \
  --header 'Idempotency-Key: team-hf-v1' \
  --data-binary @hf-dataset.json \
  "$CONTROL_URL/v1/datasets"
DATASET_ID=ds_REPLACE # the dataset id in the response
# No upload and no finalize: ingestion is queued automatically. Next: ingest.
```

**Alternative, direct upload: register an empty upload dataset, then copy its id**

```bash
cat > upload-dataset.json <<'EOF'
{"source_kind":"upload","name":"team-pick-place"}
EOF
curl --fail-with-body --silent --show-error --header @control.headers \
  --header 'Content-Type: application/json' \
  --header 'Idempotency-Key: team-upload-v1' \
  --data-binary @upload-dataset.json \
  "$CONTROL_URL/v1/datasets"
DATASET_ID=ds_REPLACE # the dataset id in the response
```

**Alternative, direct upload: describe every regular file into uploads.json (on macOS use stat -f %z and shasum -a 256 in place of stat -c %s and sha256sum)**

```bash
# One descriptor per regular file: relative path, size, SHA256
cd lerobot-export
find . -type f -print0 | sort -z | while IFS= read -r -d '' f; do
  jq -nc --arg p "${f#./}" --argjson s "$(stat -c %s "$f")" \
    --arg h "$(sha256sum "$f" | cut -d' ' -f1)" \
    '{path: $p, size_bytes: $s, sha256: $h}'
done | jq -sc '{files: .}' > ../uploads.json
cd ..
```

**Reserve: send uploads.json, get one signed URL per file**

```bash
curl --fail-with-body --silent --show-error --header @control.headers \
  --header 'Content-Type: application/json' --data-binary @uploads.json \
  "$CONTROL_URL/v1/datasets/$DATASET_ID/uploads" > upload-reservation.json
```

**PUT /v1/uploads/{signed_grant}: each file to its returned URL with its headers, no team key (prints index and status; for an index that printed 303, set i and follow its Location)**

```bash
# PUT every reserved file to its own signed URL
n=$(jq '.files | length' upload-reservation.json)
for i in $(seq 0 $((n - 1))); do
  f=$(jq -c ".files[$i]" upload-reservation.json)
  jq -r '.headers | to_entries[] | "\(.key): \(.value)"' \
    <<<"$f" > upload.headers
  curl --fail-with-body --silent --show-error --header @upload.headers \
    --upload-file "lerobot-export/$(jq -r .path <<<"$f")" \
    --dump-header "put-$i.headers" --output "put-$i.json" \
    --write-out "$i %{http_code}\n" "$(jq -r .url <<<"$f")"
done

# A 303 means the operation is still running: follow its Location exactly, with no extra auth, and don't resend the body
loc=$(awk 'tolower($1)=="location:" {print $2}' "put-$i.headers" | tr -d '\r')
curl --fail-with-body --silent --show-error "$loc"
```

**Finalize, only after every upload has completed**

```bash
# Only after every upload has completed (each PUT returned 2xx, or its 303 poll finished)
curl --fail-with-body --silent --show-error --header @control.headers \
  --request POST "$CONTROL_URL/v1/datasets/$DATASET_ID/finalize"
```

**Watch the dataset until it is ready**

```bash
curl --fail-with-body --silent --show-error --header @control.headers \
  "$CONTROL_URL/v1/datasets/$DATASET_ID" # state: train only on ready
curl --fail-with-body --silent --show-error --header @control.headers \
  "$CONTROL_URL/v1/datasets/$DATASET_ID/validation" # stage, evidence and errors
```

**Submit the fine-tune**

```bash
cat > job.json <<EOF
{"dataset_id":"$DATASET_ID","backend":"standard","mode":"expert_only",
 "action_horizon":30,"rtc_enabled":true,"steps":1000}
EOF
curl --fail-with-body --silent --show-error --header @control.headers \
  --header 'Content-Type: application/json' \
  --header 'Idempotency-Key: team-job-v1' \
  --data-binary @job.json \
  "$CONTROL_URL/v1/jobs"
JOB_ID=job_REPLACE # the job id in the response
```

**Watch the job (read-only)**

```bash
curl --fail-with-body --silent --show-error --header @control.headers \
  "$CONTROL_URL/v1/jobs/$JOB_ID"
curl --fail-with-body --silent --show-error --header @control.headers \
  "$CONTROL_URL/v1/jobs/$JOB_ID/logs?cursor=0"
curl --fail-with-body --silent --show-error --header @control.headers \
  "$CONTROL_URL/v1/jobs/$JOB_ID/metrics?cursor=0"
# then repeat with ?cursor=<next_cursor from the response>
curl --fail-with-body --silent --show-error --header @control.headers \
  "$CONTROL_URL/v1/jobs" # list jobs
```

**Cancel, only if you mean it**

```bash
# Only when you really want this job to stop:
curl --fail-with-body --silent --show-error --header @control.headers \
  --request POST "$CONTROL_URL/v1/jobs/$JOB_ID/cancel"
```

**Find the checkpoint, the deployment and its contract**

```bash
CHECKPOINT_ID=artifact_REPLACE # the id your job record points to
curl --fail-with-body --silent --show-error --header @control.headers \
  "$CONTROL_URL/v1/checkpoints/$CHECKPOINT_ID"

# Appears only once the checkpoint passed its checks
curl --fail-with-body --silent --show-error --header @control.headers \
  "$CONTROL_URL/v1/deployments"
DEPLOYMENT=deployment_REPLACE # one whose status is ready
curl --fail-with-body --silent --show-error --header @control.headers \
  "$CONTROL_URL/v1/deployments/$DEPLOYMENT" # status and details
curl --fail-with-body --silent --show-error --header @control.headers \
  "$CONTROL_URL/v1/deployments/$DEPLOYMENT/contract"
```

**Exchange the team key for the two inference credentials**

```bash
INFER_URL="$CONTROL_URL/v1/inference"          # the inference API, same base URL

SESSION=robot-01 # choose a unique id: letters, digits, _ or -
# after expiry, grant again with a new id, e.g. robot-02
curl --fail-with-body --silent --show-error --header @control.headers \
  --header 'Content-Type: application/json' \
  --data "{\"session_id\":\"$SESSION\",\"ttl_seconds\":21600}" \
  "$CONTROL_URL/v1/deployments/$DEPLOYMENT/sessions" > grant.json
# the grant echoes your session_id back with the two credentials
jq -r '"Authorization: Bearer " + .application_session_token,
       "Modal-Authorization: Bearer " + .modal_session_token' grant.json > inference.headers
chmod 600 inference.headers
# From here on: inference.headers only. Never send control.headers to $INFER_URL.
```

**Fetch the serving contract, then create the robot session**

```bash
curl --fail-with-body --silent --show-error --header @inference.headers \
  "$INFER_URL/deployments/$DEPLOYMENT/contract" > contract.json
CONTRACT_ID=$(jq -r '.contract_id' contract.json)
jq -n --arg c "$CONTRACT_ID" --arg t 'place the blue block in the tray' \
  '{instruction: $t, rtc_enabled: true, contract_id: $c}' > session-req.json
curl --fail-with-body --silent --show-error --header @inference.headers \
  --header 'Content-Type: application/json' --data-binary @session-req.json \
  "$INFER_URL/deployments/$DEPLOYMENT/sessions" > session.json
```

**Optional: inference health (send only Modal-Authorization)**

```bash
curl --fail-with-body --silent --show-error --header "$(grep '^Modal-Authorization:' inference.headers)" \
  "$INFER_URL/health" # model assignment health
curl --fail-with-body --silent --show-error --header "$(grep '^Modal-Authorization:' inference.headers)" \
  "$INFER_URL/healthz" # inference process health
```

**Send one frame (first request, no RTC yet), with both session credentials from inference.headers**

```bash
SESSION=$(jq -r '.session_id' grant.json)  # the id you chose in the grant (slide 30); the grant echoes it back
cat > metadata.json <<EOF
{"contract_id":"$CONTRACT_ID","observation_id":"obs_000001","sequence":0,
 "timestamp_seconds":1000.0,"state":[0.0,0.0,0.0,0.0,0.0,0.0],
 "image_encoding":"png","capture_age_ms":0.0,"deadline_ms":400.0}
EOF
curl --fail-with-body --silent --show-error --header @inference.headers \
  --form-string "metadata=$(<metadata.json)" \
  --form 'side=@side.png;type=image/png' \
  --form 'wrist=@wrist.png;type=image/png' \
  "$INFER_URL/sessions/$SESSION/predict" > chunk-0.json
```

**A quick look at what came back**

```bash
# A quick look at what came back
jq '{chunk_id, execute_from_index, rows: (.actions | length), timings}' \
  chunk-0.json
```

**Second request: name the chunk in motion with an rtc block**

```bash
SESSION=$(jq -r '.session_id' grant.json)  # the id you chose in the grant (slide 30); the grant echoes it back
PRIOR_CHUNK=$(jq -r '.chunk_id' chunk-0.json)
cat > metadata.json <<EOF
{"contract_id":"$CONTRACT_ID","observation_id":"obs_000002","sequence":1,
 "timestamp_seconds":1000.5,"state":[0.0,0.0,0.0,0.0,0.0,0.0],
 "image_encoding":"png","capture_age_ms":0.0,"deadline_ms":400.0,
 "rtc":{"prior_chunk_id":"$PRIOR_CHUNK","prior_start_index":15,"delay":12}}
EOF
curl --fail-with-body --silent --show-error --header @inference.headers \
  --form-string "metadata=$(<metadata.json)" \
  --form 'side=@side.png;type=image/png' \
  --form 'wrist=@wrist.png;type=image/png' \
  "$INFER_URL/sessions/$SESSION/predict" > chunk-1.json
```

**Response, abbreviated**

```json
{"sequence":1,"chunk_id":"chk_…","rtc_applied":true,
 "prefix_length":12,"execute_from_index":12,
 "actions":[[…6 values…], … 30 rows],"timings":{"model_ms":300.0, …}}
```

**Sketch, not a library: the two threads**

```bash
# Sketch, not a library. 30 Hz control thread:
every 1/30 s:
    row = active.row_at(now) # None if no chunk covers now
    send_joint_targets(row) if row else hold_position()
# 2 Hz inference thread, one request in flight per session:
every 15 rows:
    obs = capture(side, wrist, joints) # one clock for all three
    rtc = {"prior_chunk_id": active.id, "prior_start_index": active.index,
           "delay": 12}
    reply = predict(obs, rtc) # None on error or timeout
    if reply and now() < obs.time + 12 / 30:
        active = Chunk(reply, start=reply["execute_from_index"])
    # else: drop it, play out the reserve rows, then hold
```

**Reset between episodes, delete when you are done (both session credentials, from inference.headers)**

```bash
SESSION=$(jq -r '.session_id' grant.json)  # the id you chose in the grant (slide 30); the grant echoes it back
curl --fail-with-body --silent --show-error --header @inference.headers --request POST \
  "$INFER_URL/sessions/$SESSION/reset" # between episodes
curl --fail-with-body --silent --show-error --header @inference.headers --request DELETE \
  "$INFER_URL/sessions/$SESSION" # when you are done
```

**Inference health checks (the Modal session token is required)**

```bash
curl --fail-with-body --silent --show-error --header "$(grep '^Modal-Authorization:' inference.headers)" \
  "$INFER_URL/health" # model assignment
curl --fail-with-body --silent --show-error --header "$(grep '^Modal-Authorization:' inference.headers)" \
  "$INFER_URL/healthz" # inference process
```

## 3. Limits, gotchas, tips, logistics

Limits and quotas (defaults, check `/v1/capabilities`):
- 2 successful jobs and 2 queued jobs per team; 6 h timeout per job; 120 API requests/min. Quota held until GPUs exit after a cancel.
- Datasets: 20 GiB, 4 GiB per file, 500 files per reservation, 512 KiB request body, 15-minute signed URLs.
- Session grant max TTL 6 h; idle robot sessions expire sooner.
- Steps: 1000 is "the workshop setting"; unsupported step count/mode/horizon gives 422 (429 = back off). Whether other step counts are allowed is only knowable from `/v1/capabilities`.
- Dataset reference size: 50 episodes = 609 MB, so 225 episodes is about 2.7 GB (derived, inferred).

Failure table (deck): 401/404 on control = bad header file, revoked key, wrong/other team's id. 409 on create = idempotency key reused with different JSON. 413 = file list too big. 303 = not an error. Dataset `failed` = fps, camera/joint names, 640x480, timestamps, video frames, missing `meta/info.json`, too few episodes to split: read `/validation`, fix, create a NEW dataset. 422/429 on job submit. No deployment appears = export/attestation still running or job failed (check job, logs, `/v1/checkpoints/{id}`; ask staff). 401 on inference = expired creds or team key sent there. 409/422 on predict = request already in flight, non-increasing sequence/timestamp, old contract, unknown prior chunk, delay over 12. 503/504 = capture a fresh frame, never resend a stale one, hold meanwhile. Replies late = network (budget 8 Mbit/s).

Five rules: (1) never execute a late or stale chunk, hold instead; (2) team key stays in a private file, never in commands/URLs/chat/logs/git; (3) never reorder joints or convert units by guesswork; (4) retry with same Idempotency-Key and same JSON; (5) trust capabilities and the pinned contract over any example.

Other gotchas:
- Joints in degrees only if `--robot.use_degrees=true` at record time. Gripper is 0-100.
- Don't recalibrate mid-dataset; cameras must not move mid-dataset.
- Hugging Face route needs `hf auth login` with a write token and a repo in your own account; `push_to_hub=true` publishes a PUBLIC repo.
- Validator can't detect a slow recording loop or bad calibration; check the cadence line.
- Python urllib default User-Agent can be rejected at the edge.
- Staff: "A leaked key, a stuck job or a missing deployment: come find us."

Not in the deck (no information at all): shared-arm schedule or slot lengths, overnight arm access, where the arm lives, judging criteria for the Perceptron tracks, prizes, whether an arm comes to judging, whether LeRobot end-effector control works for `move_to`, whether the gripper reports load (state is position only), image augmentation in training (deck only says server resizes to 448x448), a Perceptron perception/vision API (nothing about detection endpoints, rate limits or keys beyond the robotics API; it only says Isaac covers "video understanding" and "embodied reasoning"). GPU access: all training/inference runs on Perceptron's service (8xH100 projections); teams get no GPUs or cloud credentials, only the quota above. Ask staff for the rest.

Answers to the `docs/ARM.md` workshop-notes table (lines 9-22):
| Question | Deck answer |
| --- | --- |
| Slots / overnight / location / tray | not in deck |
| Cameras | exactly two, `side` and `wrist`, 640x480@30; deck says nothing about a third USB webcam at the arm |
| Gripper load | not reported; state is 6 positions |
| 1,000-step run time | about 45 min `expert_only` projected (9.4 min startup + about 28 min + 3.3 min checkpoint, plus export, attestation, queue); not measured for 1,000 |
| Several instructions in one dataset | implied yes (split is "stratified by task", `single_task` per episode, `--resume=true` to append), never stated outright (inferred) |
| Demos per item | not per item: "50+ episodes, about 10 per object location"; 349-episode tic-tac-toe set as the big example; "you do not need that much" |
| Augmentation | not mentioned |
| One model, different text per item | yes, that is the design: instruction is text input, set per robot session |
| Predict latency | p95 283 ms private cluster, more over internet; deadline 400 ms |
| Vision API | not covered |
| EE control / judging | not covered |

## 4. Differences vs our repo docs (all paths under `dubhacks-2026/`)

1. **Job quota vs two-run plan.** Deck: 2 successful jobs per team (and 2 queued). `docs/ARM.md:68-72` plans Run 1, Run 2, then "10 more demos before the next run"; `team/LEFT.md` A5 (line 45) and A10 (line 50) are Run 1 and Run 2. That spends the entire quota; a third "fix-up" run is not possible unless capabilities says otherwise. Failed/cancelled jobs probably don't count as "successful" (inferred). Check `GET /v1/capabilities` now.
2. **Demo counts.** `docs/ARM.md:58-64` and TASKS A4/A9 (lines 44, 49): 75 per setting, 25 per item (15 hand-out + 10 put-back), 225 total. Deck recommends 50+ episodes minimum with about 10 per object location, quality over quantity. Our counts are within the deck's guidance, but the unit is different: the deck counts per object location/variation, not per item. Our 15 per instruction is above 10 per location only if we treat each instruction as one location (inferred). Position/angle jitter in `docs/ARM.md:51-54` matches the deck's "vary slowly" rule only if we start with a tight setup; deck advises "make one setup reliable, then add" locations/lighting/camera changes, while ARM.md:50-54 varies position, lighting (thirds) and clutter from episode 1 (conflict, inferred risk).
3. **Conditioning on which item.** `docs/PERCEPTRON-ROBOTICS.md:32` and `:66` ask "can one dataset mix tasks / does the model follow the instruction?". Deck: instruction is a text input to the VLA; set once per robot session (matches `docs/PERCEPTRON-ROBOTICS.md:53`); record with the EXACT task string you will send; split is stratified by task. So one model with 18 instructions (pick/return x 9) is the intended design; the fallback "train one model per setting" is unneeded and impossible under the 2-job quota anyway. Confirm by trying run 1 with several instructions.
4. **Single dataset / single calibration.** Deck: one calibration and one camera placement per dataset, never recalibrate mid-dataset. ARM.md:56-62 records three settings in different slots, possibly hours apart; for run 2 to train on all 225 episodes they need to be in one dataset (each job takes one `dataset_id`, and each starts from the base checkpoint, not from run 1) (inferred). Use one repo and `--resume=true` (with `--dataset.root`) and the same `follower`/`leader` ids and camera mounts across all slots. `docs/PERCEPTRON-ROBOTICS.md:19-30` uses `--robot.id=scrub_follower`; any id works if reused.
5. **Record command missing flags.** `docs/PERCEPTRON-ROBOTICS.md:21-30` and `docs/ARM.md:34-38` omit `--robot.use_degrees=true` (the deck's record and teleoperate commands have it on record; the deck's teleoperate command does not), and `--dataset.root`, `--dataset.push_to_hub`. Add `--robot.use_degrees=true`. `docs/PERCEPTRON-ROBOTICS.md:15` says degrees but the command doesn't ensure it. The cameras string there is the same shape as the deck's.
6. **Episode length / reset time.** Not specified anywhere in our docs (ARM.md:37 only keys). Deck defaults 60 s episode, 60 s reset, 50 episodes. Our `ARM.md:58-64` budget (about 1 min per demo) matches defaults, but defaults waste time if a pick is about 10-20 s. Set `--dataset.episode_time_s` to about 20-30 and `--dataset.reset_time_s` to about 10-15 and use `n` to end early (inferred; example dataset averages about 21 s per episode).
7. **Keys.** `docs/ARM.md:37`: "Escape stops and uploads". Deck: Esc/q stops, encodes videos and finishes; upload to the service is a separate step (Hub push if `push_to_hub=true`, else direct upload). Also `n`/`r` alternates.
8. **Training path.** `docs/ARM.md:39` says "lerobot-train is the LeRobot equivalent"; `:40` uses `lerobot-rollout` with a policy path. Deck has no local training or LeRobot rollout: training and inference go only through the service's HTTP API; the policy runs remotely. `lerobot-rollout` is not mentioned (inferred: not applicable). Drop lines 39-40's alternatives.
9. **Inference endpoints.** `docs/PERCEPTRON-ROBOTICS.md:52-53` says the grant returns `endpoint_url` and the robot session is `POST {endpoint_url}/deployments/{id}/sessions`. Deck: inference lives at `$CONTROL_URL/v1/inference` (same base URL), and the grant is described as echoing `session_id` plus the two tokens (no `endpoint_url` mentioned). Deck routes: `GET /v1/inference/deployments/{id}/contract`, `POST /v1/inference/deployments/{id}/sessions`, `POST /v1/inference/sessions/{session_id}/predict|reset`, `DELETE /v1/inference/sessions/{session_id}`. Check `docs/perceptron-openapi.json` for which is current; if `endpoint_url` is returned, use it.
10. **Predict metadata.** `docs/PERCEPTRON-ROBOTICS.md:54` lists `contract_id, observation_id, sequence, timestamp_seconds, state, image_encoding` and optional `rtc`. Deck adds `capture_age_ms` and `deadline_ms` (400.0) in metadata; the RTC block is required from request 2 (prior_chunk_id, prior_start_index, delay 1-12); first request omits `rtc`. Deck also adds: one request in flight, strictly increasing sequence and timestamps, timestamp must match rows elapsed, late replies (past capture + delay/30 s) must be dropped, chunk switches at `execute_from_index` (12) not on arrival, images binary PNG (up to 1920x1080).
11. **Timing/stop.** `docs/PERCEPTRON-ROBOTICS.md:54` says "send actions on the contract's timing"; deck specifies it: 30 Hz row playback, request every 15 rows, hold if no chunk covers now. `:58` says "the API doesn't say when a skill is finished": confirmed, the deck has no done/stop signal; the only defined "stop" is hold. So `run_skill`'s own stop rule (max_s, gripper closed + still about 1 s, freeze) in `team/LEFT.md` A6 (line 46) stays our design.
12. **Sessions.** `docs/PERCEPTRON-ROBOTICS.md:55` "DELETE when done". Deck: after DELETE you need a fresh grant (new session_id) and new robot session, not just a new robot session; `reset` is the between-episodes call and keeps the instruction. Our plan "each skill opens (or reuses a cached) session for its instruction" (`:53`) needs the one-instruction-per-session rule plus one robot session per grant `session_id` (inferred from "bound to the session_id you chose").
13. **Latency question** (`docs/PERCEPTRON-ROBOTICS.md:69`, ARM.md:19): answered, p95 283 ms private path. Training time question (`:67`, ARM.md:14): about 45 min projected, 1000 steps only. Concurrent deployments (`:68`): not answered.
14. **Cameras.** `docs/PERCEPTRON-ROBOTICS.md:62`: overhead third webcam for `vision/` and fallback to the side camera. Deck: the dataset must have exactly two streams `side` and `wrist`; the fixed side view "sees the whole task". The third webcam is fine as a separate device, not recorded. Camera ids can change on re-plug (`lerobot-find-cameras` every session), which affects `CAMERA_INDEX` in `team/LEFT.md` B1 (line 76). Opening one USB camera from both LeRobot and `vision/` at once usually fails (inferred), so the fallback "vision reads the side camera" means frames must come from one process.
15. **Perception API.** `team/LEFT.md` B4 (line 79) and `docs/PERCEPTRON-ROBOTICS.md` assume a "Perceptron vision API"; the deck documents none (see section 3).
16. **Gripper load.** `team/LEFT.md` A6 (line 46) wants gripper "position and load", C6 `wait_for_pull` uses a "load jump". Deck/contract exposes only `gripper.pos`; load must come from LeRobot's Feetech bus directly (inferred; not via the model).

## 5. What this means for Scrub

Anish (arm and fine-tuning)
- Run `GET /v1/capabilities` before the first slot; record the allowed steps/modes/horizons/quotas in `docs/ARM.md`. Treat the 2-successful-job quota as the hard budget: Run 1 = OR set only is a probe, Run 2 = everything. Do not burn a run on a malformed dataset: validate before submitting (replay episode 0, check cadence, view `/validation`).
- Record into ONE dataset (`<user>/scrub`), one calibration, fixed cameras, all slots; use `--resume=true --dataset.root=...` when continuing. Tape the camera mounts. If run 1 reveals a problem with positions, any new demos must be added to the same dataset for run 2 (training starts from the base each time).
- Use these instruction strings exactly everywhere: `pick the <name>` / `return the <name>` (same as `settings/*.json`), and send the same text to `/sessions`.
- Add `--robot.use_degrees=true`; use `--dataset.fps=30`; shorten `episode_time_s`/`reset_time_s` (see diff 6); end episodes at a clean boundary (arm still at the carry pose) because the model has no stop output.
- `expert_only` / `standard` / 1000 steps first (about 45 min + export + queue; plan about 1 h end to end). For run 2 consider `backbone_lora` (about 54 min) if lighting/object variety is poor (inferred; the deck calls `expert_only` the sensible default). Keep run 2 under the 6 h timeout (it is).
- Use HF public repo route (no upload step). Make sure `hf auth login` has a write token before the first slot.
- Write `arm/real_arm.py` with the deck's two-thread structure: 30 Hz sender, 2 Hz predict every 15 rows, RTC block with delay 12, deadline 400 ms, drop late replies, hold, one request in flight, PNG upload (send 640x480 frames; inferred), User-Agent set, wired/fast network. Measure round trip on the venue network in the first hour; if p95 is over 400 ms you will see hold-stutter.
- Plan for 8 Mbit/s uplink; avoid a weak hotspot.
- Gripper load: pull it from the Feetech bus (not from the policy); the model only returns positions.

Brandon (vision)
- Nothing in the deck about a perception endpoint. Look at `https://robotics.perceptron.inc/docs` and `/openapi.json` for any perception route; otherwise ask staff or fall back per `team/LEFT.md` backups (line 117). Check `docs/PERCEPTRON-ROBOTICS.md` stays unfilled until you confirm.
- Keep the overhead camera a separate USB device from the arm's `side`/`wrist` cameras; never move the arm's side camera during dataset recording; re-check `CAMERA_INDEX` after every re-plug/reboot (`lerobot-find-cameras opencv`). The side camera view must be fixed and show the whole tray, so calibrate your homography against the same fixed mount (B6).
- Don't hold the LeRobot cameras open from `vision/`.

Caiden (controller)
- Controller never talks to Perceptron; `arm/real_arm.py` does. The arm interface contract (`docs/CONTRACTS.md:156`, `run_skill(instruction, max_s)`) is adequate: the policy has no done signal, so the controller owns termination: `max_s`, gripper-closed-and-still, `freeze()`. Pick `max_s` with a margin: each skill is a single ~10-25 s chunk-stream (inferred from 21 s average).
- `freeze()` / stop must make the 30 Hz thread hold position (send current joint state, stop sending policy rows) and stop issuing predicts; then `reset` the session. A late reply must never be applied. Stop latency about 33 ms for the control thread; an in-flight predict can finish and must be discarded.
- Latency budget: skill start includes opening a robot session (grant + contract + session create) and the first predict (the first chunk has no RTC) so first motion is delayed by at least the round trip (about 0.3-0.5 s, inferred). Pre-open sessions for the active setting's instructions at setting change (inferred), not at request time.
- One instruction per session, session ids unique, and one in-flight predict per session. For the 18 instructions use one grant session per instruction or open on demand; after `DELETE` a new grant is needed.
- Failure modes to expose as events: 401 (re-grant), 409/422 (reset session), 503/504 (hold and retry with a fresh frame), session gone (re-grant). Treat repeated late replies as "policy unavailable" and tell the clinician instead of moving.
- Hand-out is not in the demos (`docs/ARM.md:46`): the policy ends at the carry pose; `move_to` (IK) is unrelated to Isaac and the deck says nothing about it.
