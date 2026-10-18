# Scrub recording and training: operator-agent handoff

Give this file (or paste everything below the divider) to the person/agent helping
at the arm. This is an instruction prompt, **not evidence that recording, replay,
calibration or training has happened**. The operator must be at the Windows laptop
connected to the arms. No new Apple Vision, ElevenLabs, Photon or dashboard work
is needed for this task. Those are separate integrations.

Related: [training targets](TRAINING.md), [bring-up](BRINGUP.md),
[workshop facts](PERCEPTRON-ROBOTICS.md), [batch log](DATA-LOG.md).

---

## Your role and how to interact with me

I am Anish on team Scrub. Help me record high-quality SO-101 demonstrations and
train Isaac 0.5 through Perceptron. **Walk me through ONE step at a time.**

At each operator-facing step give me only:

1. **Step and purpose.** Say whether it is read-only, opens cameras, enables/moves
   hardware, publishes a dataset, or can spend a training run.
2. **Exact command for my laptop**, in a PowerShell code block with no unresolved
   placeholder. If a value is unknown, the current step must discover that value,
   not give a guessed recording command. Explain which terminal/environment to use.
3. **What I should see**, with concrete pass criteria.
4. **What makes us stop** and the safe next action if it fails.
5. **What to send back**, such as a sanitized cadence line or confirmation of a
   physical result. Never ask for secrets or an entire `.env` screenshot.

Then **WAIT for my reply**. Do not issue the next physical action because a
process merely exited successfully. Do not dump this whole playbook back at me.
You may inspect code and prepare documentation between replies, but do not launch
motion, open devices, publish media or submit jobs ahead of the current step.

Maintain two clearly separated ledgers: accepted recording progress and the two
training runs. Never count offline tests, re-recorded/discarded takes, incomplete
clips or evaluation trials as accepted demonstrations.

## 1. Read the actual repository, preserve other people's work

The known project checkout on Anish's laptop is:

```powershell
Set-Location "C:\Users\anish\Documents\GitHub\dubhacks-2026"
```

The similarly named `dubhacks-26` sibling is not this project. If using another
laptop, find the actual checkout and confirm it instead of copying this path.

First inspect `git status --short --branch`, then run `git pull --rebase` if clean.
Never stash, discard or commit other agents' work. If pull is blocked by unrelated
changes, report that and use a clean documentation worktree if appropriate. Do not
move the hardware workflow into a temporary worktree: calibration, `.env`, run
state and installed tools may be tied to the original checkout/environment.
Resolve any code-version mismatch before giving physical recording commands.

Read these, in order:

- `AGENTS.md`, `README.md`, `docs/CONTRACTS.md`, Anish's `docs/TASKS.md` and
  `docs/STATUS.md` sections.
- `docs/TRAINING.md` in full; it is the current demonstration target table.
- `docs/BRINGUP.md` sections 6–8; also sections 2–5 for missing hardware setup.
- The **workshop facts at the top** of `docs/PERCEPTRON-ROBOTICS.md`, plus
  `explore/research/isaac-workshop-notes.md` sections 2 and 5 as needed.
- `docs/DATA-LOG.md`, `arm/README.md`, the relevant settings JSON files.
- `arm/train.py`, `arm/pipeline.py`, `arm/dataset_check.py` and their CLI help
  before issuing pipeline commands. Use installed LeRobot help to check its flags.

Do not edit `arm/check_setup.py` or `arm/record.py` (Caiden owns that work), other
people's implementation files, or contracts. Those two scripts may not exist in
this checkout: do not invent a CLI for them. This assignment explicitly authorizes
batch updates to `docs/DATA-LOG.md`; preserve Evan's existing rows. If a code fix
outside Anish's files is necessary, stop and give its owner the exact failure and
needed change rather than rewriting their implementation.

Do not browse datasets or caches broadly. Only inspect the specific dataset root
and episode metadata I explicitly identify for recording/preflight; do not scan
`data/`, `outputs/`, `.venv/`, `node_modules/` or unrelated recordings.

### Resolve known documentation differences

- `TRAINING.md` currently says **20 picks + 10 returns per surgical item**:
  90 surgical episodes, not the older 75 in `BRINGUP.md`/`DATA-LOG.md` prose.
- Bench is **15 picks + 10 returns per item**: 75 bench episodes. Baseline run 2
  therefore contains 165 episodes, plus any documented corrections/additions.
- Dental is not in the current `TRAINING.md` table. Do not silently add another
  75 demos or spend a run for it; ask if the scope has changed.
- `TRAINING.md` calls scalpel picks "to the safe spot"; bring-up describes picks
  ending held and still at carry, and controller code owns sharp set-down. Before
  scalpel recording, get Anish/workshop staff to resolve the intended policy skill
  boundary against the current controller. Do not mix incompatible endings under
  `pick the scalpel` or silently alter that instruction. Record the decision.
- A failed service validation does **not** authorize creating a new local dataset
  repo/calibration or a replacement training job. Keep one cumulative dataset;
  stop, inspect the failure and agree on a repair/registration plan first.
- `arm.train pipeline` does **not** upload local data to Hugging Face. LeRobot/HF
  must finish publishing first; the pipeline registers that existing repo/revision.
- Status syntax is `python -m arm.train status job <job-id>` (or dataset,
  checkpoint, deployment), not bare `python -m arm.train status`.

Live capabilities/API schema govern service limits. Workshop facts override old
examples lower in the Robotics document. Never infer permission for a third run.

## 2. Establish this laptop's real configuration, one discovery at a time

Start with a short question: **Are both arms connected, with a driver and a spotter
present, and which Python/LeRobot environment did workshop staff approve?**

Use the existing environment; do not replace it or upgrade LeRobot casually.
Python 3.10 is used for lightweight repository tests, while workshop hardware
instructions may use a different approved environment. Verify which executable
actually owns `lerobot-record` and that it supports Feetech, OpenCV and encoding.
If an install fails twice, stop and report it; do not keep reinstalling.

Discover the follower and leader with `lerobot-find-port`, one cable at a time as
prompted. These are Windows `COM...` values, not Linux `/dev/tty...` paths. Have me
confirm their labels and saved calibration IDs. Never run motor-ID setup on the
assembled workshop arm without staff explicitly requiring it.

With competing camera processes closed, discover camera identities with
`lerobot-find-cameras opencv`. Ask me to physically identify side versus wrist;
distinct numbers alone are not enough. Do not assume side=0/wrist=1, reuse the
overhead `CAMERA_INDEX`, or open a device owned by another process. IDs can change
after replug/reboot. The overhead camera belongs to Brandon's vision process.

Confirm the Hugging Face account/organization and write access using an installed
HF auth command or a safe API check. GitHub username is not proof of HF username.
Use **one** verified `<owner>/scrub` repo for the entire project, not separate
`scrub-surgical`, `scrub-bench` or run-specific HF repos. Check for an existing
dataset before creating anything. Do not overwrite an unrelated repo or directory.

Build a non-secret session worksheet and repeat it before the first recording:

| Field | Required evidence |
| --- | --- |
| Checkout | Actual project root and code revision |
| Environment | Python executable/version; installed LeRobot command/version |
| Follower / leader | Physically identified COM ports and existing calibration IDs |
| Side / wrist | Operator-identified camera IDs; both RGB 640×480 at 30 FPS |
| Dataset root | Absolute path; new versus resumed; current episode count |
| HF repo | Confirmed owner/repo and permission to publish |
| Cadence file | Absolute path for genuine wall-clock evidence |
| Setup | Fixed camera/tray/base locations; calibration identity |
| People | Driver and resetter/spotter ready; workspace clear |
| Runs | Existing job IDs, states, committed dataset revisions, remaining budget |

The prior guides propose `C:\Users\anish\scrub-dataset` and
`C:\Users\anish\scrub-cadence.json`; these are **proposed paths, not verified
existing datasets**. If that dataset already exists, reconcile it and resume it.
Do not create or delete it merely to make the example work. Store raw cadence
reports outside tracked files and keep the dataset outside Git.

Populate `$Follower`, `$Leader`, `$Side`, `$Wrist`, `$Repo`, `$DatasetRoot` and
`$Cadence` with confirmed values in the operator's PowerShell session. Also set
`$FollowerId`/`$LeaderId` to the actual calibration IDs. Bring-up uses
`scrub_follower`/`scrub_leader`; existing workshop calibration may use different
IDs. Reuse the correct IDs everywhere; never rename/recalibrate mid-dataset.
Do not present worksheet blanks as a ready-to-run recording command.

### Credentials without exposure

Robotics uses `PERCEPTRON_TEAM_API_KEY`; vision's `PERCEPTRON_API_KEY` is different.
HF publication needs `HF_TOKEN`/an approved HF login. Let me enter secrets in local
Notepad or an interactive hidden prompt. Never print their values, dump `.env`,
put tokens in CLI arguments, log auth headers, or commit credentials/session
tokens/signed URLs. Check existence/authentication with booleans or HTTP status.
LeRobot/HF CLI may not load the repo `.env` automatically: verify auth without
echoing it; use approved login or an in-process dotenv loader, not copied tokens
in PowerShell history. Read-only credential checks do not permit training.

## 3. Hardware/data-quality gates before the first accepted batch

- Two people: the driver moves the leader; the resetter restores the tray, changes
  lighting, operates episode keys and can cut power. Software stop is not an E-stop.
- Use blunt practice tools and a scalpel **handle with no blade attached**. Keep
  people outside motion/replay paths. No policy handoff to a person at this stage.
- Only one process owns the follower bus and each camera. Stop teleop before
  recording/replay; do not kill another person's controller without coordination.
- Reuse verified calibration/units. Arm state and action have six float32 values
  in order: `shoulder_pan.pos`, `shoulder_lift.pos`, `elbow_flex.pos`,
  `wrist_flex.pos`, `wrist_roll.pos`, `gripper.pos`. Five joints use degrees;
  recorded gripper uses raw 0 closed / 100 open, not public Arm's reversed 0..1.
- Exactly `observation.images.side` and `observation.images.wrist`, RGB 640×480,
  30 FPS. Side sees the entire task; wrist sees the grasp. Confirm with images,
  not metadata alone. Fix glare/occlusion before collecting quantity.
- Tape base, tray, slots, camera mounts and the separate safe spot. Keep them and
  calibration fixed across all batches/settings/runs. Vary item position slightly
  within a slot; do not introduce big layout changes or camera movement.
- Verify a small, slow teleop motion before recording if setup is unverified.
  Stop on unexpected direction, jerk, collision risk or missing feedback. A trained
  deployment does not verify the rig. Never flip `hardware_verified` to bypass it.

## 4. Recording targets and running progress

Use the current `TRAINING.md` table, not this snapshot if the team updates it.
The lighting allocation below is a proposed balanced schedule, since the guide
requires three lighting conditions but does not prescribe exact per-light counts.
Have me approve it once, then track it consistently.

**Targets, not recorded counts**. Each cell is pick / return episodes:

| Setting | Item ID | Bright target | Normal target | Dim target | Total |
| --- | --- | --- | --- | --- | --- |
| surgical | scalpel | 7 / 4 | 7 / 3 | 6 / 3 | 20 / 10 |
| surgical | hemostat | 7 / 4 | 7 / 3 | 6 / 3 | 20 / 10 |
| surgical | mayo_scissors | 7 / 4 | 7 / 3 | 6 / 3 | 20 / 10 |
| bench | needle_nose_pliers | 5 / 4 | 5 / 3 | 5 / 3 | 15 / 10 |
| bench | wire_cutters | 5 / 4 | 5 / 3 | 5 / 3 | 15 / 10 |
| bench | hex_key | 5 / 4 | 5 / 3 | 5 / 3 | 15 / 10 |

Reconstruct accepted counts from genuine existing batch rows and explicitly
authorized episode metadata. The log was empty when this prompt was written;
that is not proof that the laptop has no recordings. If evidence disagrees, show
the discrepancy and resolve it before accepting new progress. Do not invent a
backfilled batch/date or treat a planned batch size as saved episodes.

After **every batch** show:

| Setting / item / direction | Bright accepted/target | Normal accepted/target | Dim accepted/target | Total accepted/target |
| --- | --- | --- | --- | --- |

Include totals (surgical /90; bench /75; cumulative /165 before corrections),
the batch's actual episode indices, min/max measured Hz, rejected/pending clips,
and remaining episodes. Preserve uncertainty explicitly. Never double-count an
`r` re-record, resumed batch or repeated log command. Extra failure corrections
are separate additions beyond the baseline target; record the reason and task.

### Exact task vocabulary (re-read settings before use)

| Item ID | Pick instruction | Return instruction |
| --- | --- | --- |
| scalpel | `pick the scalpel` | `return the scalpel` |
| hemostat | `pick the hemostat` | `return the hemostat` |
| mayo_scissors | `pick the mayo scissors` | `return the mayo scissors` |
| needle_nose_pliers | `pick the needle-nose pliers` | `return the needle-nose pliers` |
| wire_cutters | `pick the wire cutters` | `return the wire cutters` |
| hex_key | `pick the hex key` | `return the hex key` |

Aliases such as kelly, knife or mayo are for voice parsing, not alternative
recording task strings. Non-sharp picks finish held, still at carry; returns start
from the agreed return location, place into the correct slot and finish home.
Resolve the sharp endpoint as described above before scalpel batches.

## 5. Batch loop: record → verify cadence → log → publish log → wait

Start with a small **normal-light hemostat pick** batch after gates pass. Five
episodes is a useful first batch, not five new episodes if those targets are
already met. One batch has one setting, item, direction, instruction and lighting.
Do not change lighting or task without ending/saving the batch.

Before each batch summarize: actual setup, task, lighting, intended episode count,
existing indices/count, next expected indices and whether `--resume=true` applies.
Get my readiness confirmation before any recording motion. Do not leave a second
motion command queued to run after it.

This is a **command construction reference**, not a command to issue before the
values and LeRobot flags are verified. When helping me, resolve all variables and
quote paths correctly. `$Instruction` and `$BatchCount` are the agreed current
batch, not hard-coded defaults. `$Cameras` is constructed from confirmed IDs:

```powershell
$Cameras = "{side: {type: opencv, index_or_path: $Side, width: 640, height: 480, fps: 30}, wrist: {type: opencv, index_or_path: $Wrist, width: 640, height: 480, fps: 30}}"
lerobot-record --robot.type=so101_follower --robot.port="$Follower" --robot.id="$FollowerId" --robot.use_degrees=true --robot.cameras="$Cameras" --teleop.type=so101_leader --teleop.port="$Leader" --teleop.id="$LeaderId" --dataset.repo_id="$Repo" --dataset.root="$DatasetRoot" --dataset.single_task="$Instruction" --dataset.num_episodes=$BatchCount --dataset.fps=30 --dataset.episode_time_s=25 --dataset.reset_time_s=10 --dataset.push_to_hub=true
```

On **every later batch** append `--resume=true` to that command; keep exactly the
same dataset root/repo/calibration/cameras. `num_episodes` is the **additional**
count, not the lifetime total. Never run the first-batch form on an existing
dataset to overwrite it. Expect two feeds, correct task label and saved episodes.
Most demonstrations finish in about 10–20 seconds; 25 s is the cap, not a reason
to include long idle tails. Reset time is 10 s and is not recorded.

Explain the installed recorder's keys before starting: `n`/right arrow ends cleanly,
`r`/left arrow discards/re-records a bad take, `q`/Esc finishes/saves/encodes. Verify
those bindings against the workshop build, particularly on Windows. Keep filming
outcomes distinct from encoder/upload success. Do not unplug while encoding.

### Cadence is a mandatory per-episode AND per-batch gate

1. Read each episode's genuine wall-clock cadence report. Accept **29–31 Hz**.
   Nominal metadata FPS or `timestamp = frame_index / 30` cannot prove cadence.
2. Record the actual episode-index-to-measured-Hz mapping as soon as the episode
   saves. Retain original sanitized measurement evidence outside Git. Do not
   replace missing reports with 30.0, averages, or a measurement from another take.
3. If the build does not report measurable cadence, stop collecting accepted
   batches. Ask staff for its approved instrumentation/build; do not fabricate
   evidence, change the validator, or re-time/resample slow clips to make them pass.
4. After the batch finishes encoding, reconcile actual saved episode count,
   indices, task and camera continuity against the operator report. Every accepted
   episode needs evidence; verify both streams are present and usable.
5. If an episode is slow, obscured, incomplete or wrong-task, do not count it as
   accepted. Re-record using the supported recorder workflow. If already persisted,
   stop for a supported repair plan; do not delete media/parquet by hand or silently
   renumber indices. Track rejected clips so they cannot reach a training snapshot.
6. Update the cumulative cadence JSON with one entry per current saved episode:
   `{"episodes": [{"episode_index": <actual integer>, "measured_fps": <actual number>}, ...]}`.
   That is a schema, **not literal JSON or sample measurements to copy**. Include
   all episodes in the candidate snapshot, no duplicates/missing indices. Store
   the report outside Git. A pending/rejected dataset is not training-ready.
7. After an accepted batch, run `python -m arm.train pipeline "$DatasetRoot"
   --cadence-report "$Cadence" --check-only` as a separate current step and inspect
   its exit code/report before proceeding. It needs at least two complete episodes.
   If a one-episode diagnostic cannot satisfy that, report the gate as pending;
   never claim it passed or submit training. Do not use `--check-only` failure as
   permission to weaken checks.

Close avoidable heavy apps/processes if cadence is bad, without disrupting other
operators. Retry only after the underlying load/camera problem is fixed.

### Log actual batches, never plans

Once verified, append one row using the existing logger (fill values first):

```powershell
python -m ledger log --setting "$Setting" --item "$Item" --direction "$Direction" --lighting "$Lighting" --demos $AcceptedCount --dataset "$Repo" --notes "$BatchNotes"
```

`$Direction` is `hand-out` for pick or `put-back` for return. Notes must include
batch ID, exact task, actual episode index range/list, accepted count, measured
cadence min/max, check-only outcome and any rejects/repairs. The dataset column
is `local` if publication has not succeeded, not an unverified HF claim. If the
recorder already appended a row, enrich/reconcile it instead of adding it twice.
For a failed/pending batch, record its real status transparently; do not write
"cadence ok" or count it as accepted. Confirm an unfamiliar log format before
changing it. The logger requires `--demos` to be at least 1. For a batch with zero
accepted demos, append a clearly marked rejected/pending row directly using the
existing table columns, Demos `0`, actual time and reason in Notes; do not invent
one demo to satisfy the CLI. If saved clips are pending rather than accepted,
record their number in Notes and leave accepted Demos at zero until verified.
Never log measured values/episodes that the operator has not supplied.

After each batch update, inspect the diff, stage **only** `docs/DATA-LOG.md`, commit
with a concrete batch message, run `git pull --rebase`, then push. Run commands
separately and inspect each result. Do not commit `.env`, datasets, videos, model
weights, raw private logs or someone else's staged work. Check the staged diff
contains only the intended batch row before committing. If a push fails, retain
the local row/commit and retry the Git operation, not the recording/log insertion.
Never force-push. If unrelated dirty files block pulling, use a clean documentation
worktree and transfer only the exact log diff (checking for an already-pushed row),
or coordinate with the owner; never hide their work with a stash/reset.

Show the updated progress table and commit/push result, then wait for me to choose
or confirm the next batch. A git/network issue must not trigger another recording.

## 6. Hard gate before EACH training run

**No training request until all of these have evidence and my explicit approval.**
There are only two planned runs: `scrub-run-1` surgical and `scrub-run-2` cumulative.
Workshop quota is two successful jobs; operationally do not submit replacement
or speculative jobs without staff/operator review, even if a failure might not
consume that successful-job quota. Check existing jobs/state before first use.

1. **Counts and scope:** run 1 meets surgical targets (90); run 2 includes all run
   1 episodes plus bench (165 baseline), corrections, and any explicitly approved
   additions. No missing tasks/light coverage; no rejected/unknown cadence clips.
2. **Stable local snapshot:** finish encoding, recording and evidence updates.
   Stop writes while fingerprinting, publishing and checking. Save run-specific
   evidence/revision/counts. Do not assume a directory copied mid-recording is valid.
3. **Replay:** clear workspace, blunt tool, spotter and same calibration. Tell me
   clearly that this moves the real follower. Issue the verified command for
   episode 0 as one operator step, then wait for physical confirmation:

   ```powershell
   lerobot-replay --robot.type=so101_follower --robot.port="$Follower" --robot.id="$FollowerId" --robot.use_degrees=true --dataset.repo_id="$Repo" --dataset.root="$DatasetRoot" --dataset.episode=0
   ```

   Expect correct trajectory, grip and task endpoint without stutter/collision.
   Before run 2, also inspect/replay representative newly added tasks with a fresh
   safety confirmation; replaying the same old episode alone does not test bench.
   Do not call a fake-joint dry-run physical replay. Any mismatch stops the run.
4. **Offline preflight:** run on that exact candidate root/report:

   ```powershell
   python -m arm.train pipeline "$DatasetRoot" --cadence-report "$Cadence" --check-only
   ```

   Expect success/exit 0, fps 30, correct episode/frame totals, measured min/max
   within 29–31 and a fingerprint. This is offline, does not spend a job and
   does not prove decoded-video quality, calibration or physical success.
5. **Publication:** finish the approved LeRobot/HF upload. Confirm public access
   is acceptable (no keys, private people or sensitive scenes), both videos/data/
   metadata exist, and the HF export matches the checked local snapshot. Resolve
   **the immutable HF commit SHA**, not just `main`. Put it in `$HfCommit` and record
   the URL/revision. The pipeline does not publish missing files for you.
6. **Capabilities/quota:** run `python -m arm.train capabilities` and record
   non-secret settings/quotas in `docs/ARM.md`. Verify `standard`, `expert_only`,
   horizon 30, RTC enabled, 1000 steps are actually allowed. Inspect existing run
   records/jobs and ask staff if remaining budget is unclear. A capabilities
   response alone is not proof no teammate has submitted a concurrent job.
7. **Service validation:** the pipeline waits for a ready ingested dataset and
   a completed successful `/validation` before its job POST. If the operator wants
   to inspect this separately before approving any training-capable command,
   use supported `register-hf`, `status dataset`, `validation` commands with a
   distinct stable registration key and pinned revision. Do not use raw `train`
   to bypass pipeline gates. Unknown/failed/incomplete validation must stop job
   submission; inspect actual response evidence, not merely HTTP 200.
8. **Final approval card:** show run number, exact dataset root/repo/SHA, counts,
   cadence range, replay confirmation, check-only fingerprint, validation status
   (or that pipeline will gate it), settings, stable key/state file, known existing
   job ID and remaining budget. Ask **"Approve submitting run 1 [or 2] on this exact
   snapshot?"** Wait. Never add confirmation flags before the facts are true.

## 7. Submit once, monitor, resume safely

Only after the preceding approval, give the resolved pipeline command. Run 1
construction reference (use actual candidate root/report if a snapshot was made):

```powershell
python -m arm.train pipeline "$DatasetRoot" --cadence-report "$Cadence" --repo-id "$Repo" --revision "$HfCommit" --idempotency-key scrub-run-1 --backend standard --mode expert_only --steps 1000 --confirmed-replay --confirmed-hf-matches-local
```

The pipeline sets horizon 30 and RTC on internally. Do not invent CLI flags for
those. The command can spend a run only after local checks and service validation.
Expect dataset/validation evidence, one job ID, logs/metrics, checkpoint/export,
then a **ready deployment matching that job**, not any arbitrary ready deployment.
Training is roughly 45 minutes plus queue/export; it is not a promised deadline.

Preserve `.env.pipeline-scrub-run-1.json` in the repo root. A timeout or dropped
connection does **not** cancel a remote job. Resume with the **exact same command,
key, parameters, revision, candidate bytes, cadence file and state file**. Do not
delete state, change the key, call raw train, or create another job to "try again".
If status is uncertain, inspect the existing dataset/job/checkpoint/deployment;
do not submit again blindly. HTTP 409/input-fingerprint mismatch is a stop, not a
reason to generate a random key. Failed jobs need operator/staff review.

### Critical: recording bench while run 1 is active

The local fingerprint includes metadata, episode data, **media bytes and cadence
report bytes**. Appending bench episodes to that path/report changes inputs and
can prevent safe resumption of run 1 even though its HF revision is pinned.

Default safe option: keep the run-1 local dataset/report unchanged until the
pipeline finishes deployment. Then append bench to the same cumulative dataset.

If parallel recording is necessary, agree **before submitting run 1** on a complete,
immutable local snapshot plus its own copied cadence file, outside Git. Verify
the copy while all writers are stopped, check/replay that snapshot, pin its matching
HF SHA, and pass its absolute paths to run 1. Resume run 1 against those unchanged
paths; append bench only to the original cumulative recording root in the same
HF repo. Do not silently switch the pipeline root after submission, delete the
snapshot, or imply a later `main` update changes the already-ingested run 1 data.

Monitoring commands are read-only (resolve IDs first):

- `python -m arm.train status dataset <dataset-id>`
- `python -m arm.train validation <dataset-id>`
- `python -m arm.train status job <job-id>`
- `python -m arm.train follow <job-id>`
- `python -m arm.train status checkpoint <checkpoint-id>`
- `python -m arm.train deployments`
- `python -m arm.train status deployment <deployment-id>`
- `python -m arm.train contract <deployment-id>`

These are syntax references, not ready-to-run placeholder commands. A completed
job can still be exporting; wait/inspect instead of starting another. Contract
retrieval is not authority to move the arm or set the rig as verified.

When ready, expect `PERCEPTRON_DEPLOYMENT_ID` updated in ignored `.env`, preserving
other entries. `arm/train.py` also writes public `arm/run_info.json` containing
dataset URL, job/checkpoint/deployment IDs and status; verify it exists and relates
to this run without reading out `.env`. It is not the private resume state or a
complete run history. Preserve a non-secret per-run record (SHA, fingerprint,
counts, IDs, outcome) in the training documentation before a later run replaces it.

Run 2 uses `scrub-run-2`, its own state, a newly pinned cumulative HF revision and
all the same gates/explicit approval. It starts from the service base model,
**not** run 1's checkpoint. Do not train only on bench. If run 1 physical tests
identify weak items, agree on the exact corrective demonstrations (the guide
suggests ten extra per weak item), log them, and include them before run 2.
Real policy tests need the separate rig/contract/physical acceptance gates in
bring-up; no automatic `--real-arm` launch just because training succeeded.

## 8. Hard stops, final report and your FIRST response

Stop on missing credentials (ask for local entry, never the value), unidentified
ports/cameras/calibration, exclusive-device conflicts, camera movement, unsafe
motion, missing/slow cadence, count disagreement, incomplete encode/upload,
failed replay/preflight/validation, unknown quota, wrong HF revision or changed
resume inputs. Explain the failed gate and give **one** safe diagnostic next.
Never solve a blocked training gate by spending an extra job.

At the end report verified per-item/per-light counts, rejected/pending episodes,
dataset/revisions, replay/check/validation evidence, each run's IDs/outcome,
remaining budget, log commits/push results and any physical acceptance still
pending. Keep simulated, software-tested and physically verified claims separate.
Do not mark A3/A5/A6/A7/A8/A10 complete without their actual acceptance evidence.

**Your first response to me must not be a recording or training command.** Read
and pull as safely possible, summarize any unresolved guide conflict in a sentence,
then ask whether both arms and the driver/spotter are ready and which workshop
environment to use. After my answer, discover one unknown at a time. Only when
the session worksheet is confirmed may you give a fully filled-in batch command.
