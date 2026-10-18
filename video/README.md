# Scrub video tools

Offline Python 3.10 tools for the demo edit and the Perceptron arm roll.
**No robot, camera, account, API key or system ffmpeg is needed.** Inputs are
explicit local recordings, photos, joint data and ledger exports. Never runs
training, connects to the arm or imports the controller.

Modules: `ingest` (index and clock sync), `geometry` (tray corners), `topdown` (plane warp, photo plate), `reconstruction` (joint replay in MuJoCo), `clean` (cleanup, privacy, idle review), `takes` (rank takes from the ledger), `overlay` and `cards` (ledger-backed captions and tables), `edit` (EDL render), `synthetic` (labeled fixtures), `common` and `style` (shared helpers). `edl/` holds `demo.yaml`, `perceptron-arm.yaml` and `bindings.example.json`. Tests: `python -m unittest video.test_video`.

## Install on this Windows laptop

Run in PowerShell from `C:\Users\anish\Documents\GitHub\dubhacks-2026`:

```powershell
python -m pip install -r video/requirements.txt
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\data\video\browser"
python -m playwright install chromium
python -m unittest video.test_video -v
python -m video --help
```

ffmpeg comes from `imageio_ffmpeg.get_ffmpeg_exe()`, never PATH. Chromium is only
for HTML cards. The first overlay/cards run downloads Archivo and IBM Plex Mono from
Google Fonts into `data/video/fonts/`; later runs work offline. To pre-provision
offline, place `Archivo.ttf` and `IBMPlexMono-Regular.ttf` there. Fonts use the SIL
Open Font License (see the corresponding `google/fonts/ofl` family directories).
No remote scripts, trackers or font requests run inside rendered card pages.

Optional face cleanup: `python -m pip install mediapipe`. First `clean --faces`
downloads Google's BlazeFace short-range model to the workspace's `models/`.
Close other Python/OpenCV processes if Windows locks `cv2.pyd`; don't repeatedly
reinstall packages or upgrade the hardware environment to solve a video install.
MuJoCo reconstruction requires the existing SO-101 model; if missing, separately
run `python -m sim.fetch_model`. Generated scenes go in `data/video/`, not `sim/`.

### Install on the Mac (bash)

From the repo root, with `.venv` already holding the repo requirements:

```bash
.venv/bin/python -m pip install -r video/requirements.txt
export PLAYWRIGHT_BROWSERS_PATH="$PWD/data/video/browser"
.venv/bin/python -m playwright install chromium
.venv/bin/python -m unittest video.test_video
.venv/bin/python -m video --help
```

Every `python -m video ...` below runs the same on the Mac as `.venv/bin/python -m video ...`.
Only the shell lines (variables, `Read-Host`, `Test-Path`, `Copy-Item`, `notepad`) differ; each
block is followed by its bash equivalent.

## Where the real inputs come from

| Input | Default | Where it is written |
| --- | --- | --- |
| Ledger events and trials (`--events` for `find`, `overlay`, `cards`) | the ledger | In order: `--events`; else `LEDGER_BUFFER`, or `ledger/buffer.jsonl`, when that file exists and is not empty (the file `ledger/__init__.py` appends to); else, when `MONGODB_URI` is set (`.env`, loaded by `ledger/`), Atlas through `ledger.stored_rows()`, exported to `<root>/events.jsonl`; else an earlier `<root>/events.jsonl` from `export-ledger`. Lines are `{"kind":"event"|"test","doc":...}` |
| LeRobot dataset (`topdown --mode reconstruction`, no `--input`) | `SCRUB_DATASET`, else `~/scrub-dataset` | `python -m arm.record` and `explore/station/station.py` write there by default (`--root` changes it). On Anish's laptop pass `--input` or set `SCRUB_DATASET` |

Every command says what it read: a `video: events from ...` (or `video: dataset ...`) line on stderr and a `sources` key in the printed JSON. An explicit `--events` or `--input` always wins.

`ledger/buffer.jsonl` only holds rows that have not reached Atlas yet: any process with `MONGODB_URI` set flushes it and the file disappears. When the buffer is the source but you want everything, run `export-ledger` and pass `--events events.jsonl`. `export-ledger` overwrites `<root>/events.jsonl` and refuses to write an empty file.

### Which arm a row came from

`video.common.arm_kind` puts every ledger row in one of five kinds, and `find --arm` and `cards --arm` keep one of them:

| Kind | Rows | Video label |
| --- | --- | --- |
| `real` | `fake_arm: false` events; test rows from `controller.trials` (untagged, a person confirmed each) | none |
| `simulation` | the sim arm: `sim_arm: true`, `sim: true` or `arm: "sim"` (the controller's new shape). Old shape, `fake_arm: true` with no sim marker anywhere in the file, counts as simulation only when it captions an ingested `simulation` clip | `SIMULATION`; no `--allow-synthetic` needed |
| `fake` | `fake_arm: true` (the fake arm) | needs `--allow-synthetic`, never on real footage |
| `synthetic` | `demo-assets` fixtures (`synthetic: true`) | `SIMULATION - SYNTHETIC FIXTURE` |
| `unknown` | events with no arm tag (written before the controller tagged them) | never counted as real |

Sim rows never caption real footage. Cards from sim rows carry `SIMULATION - SIM ARM RUN` and kind `simulation`, so a `real_only` EDL (the Perceptron arm video) refuses them.

## Honesty and output boundaries

- No generation/inpainting of robot actions, object motion, grasps or outcomes.
- Every simulated shot says **SIMULATION**. Joint replay says **RECONSTRUCTED FROM
  ARM JOINT DATA**. A photo plate says it is a static background, not action footage.
  Synthetic metrics/cards are explicitly labeled as fixtures, never real results.
- Timing/count/lighting/request overlays are selected from source-time ledger
  events. Unknown values are omitted, not guessed. No free-form numeric captions.
- Success tables use **all supplied measured test rows**, including failures,
  not `find`'s selected successes. They include denominators and Wilson ranges.
  No trial records means no invented rate. Export a complete test ledger.
- Every speed-up gets a persistent `2x` or `4x` tag. Idle classification is only
  a candidate: review the original before approving a time change. The Perceptron
  roll refuses temporal edits, trims, per-try montages and reconstructed substitutes.
- Originals stay unchanged. Derivatives, manifests, hashes, operation histories,
  source-time maps, logs, previews, models and browser assets stay in **data/video/**.
  A `.video.json` sidecar accompanies every derivative. Keep it beside the media
  when copying, especially simulated/reconstructed sources. Do not delete labels.
- Production `render` rejects synthetic sources, missing footage, unverified
  provenance and too-short clips. It never fills missing footage with a sim.
  `--demo` is ONLY for permanently labeled synthetic test exports.

The CLI's global `--root` comes **before** the command. It can select a workspace
inside this repository's `data/video/`, not any arbitrary output directory.
Relative media paths are workspace-relative. An explicit absolute path may select
an external read-only ledger/dataset source. EDL YAML paths are repo/cwd-relative.

## End-to-end rehearsal without footage

Use a fresh workspace; `demo-assets` refuses to overwrite an existing fixture:

```powershell
$Demo = "data/video/rehearsal-" + (Get-Date -Format "yyyyMMdd-HHmmss")
python -m video --root $Demo demo-assets --seconds 3
python -m video --root $Demo ingest
python -m video --root $Demo corners --input raw/demo.mp4 --camera side --width-mm 300 --height-mm 180 --headless --accept-auto
python -m video --root $Demo corners --input photos/demo-00.png --camera photo --width-mm 300 --height-mm 180 --headless --accept-auto
python -m video --root $Demo topdown --mode warp --input raw/demo.mp4 --camera side --output topdown/plane.mp4
python -m video --root $Demo topdown --mode plate --reference photos/demo-00.png --camera photo --empty-scene --output topdown/plate.png
python -m video --root $Demo topdown --mode reconstruction --input demo/joints.json --plate topdown/plate.png --plate-alignment demo/plate-alignment.json --output topdown/reconstruction.mp4
python -m video --root $Demo clean --input raw/demo.mp4 --output clean/demo.mp4 --stabilize --deflicker --denoise --audio
python -m video --root $Demo find --events demo/events.jsonl --cut
python -m video --root $Demo overlay --input clean/demo.mp4 --events demo/events.jsonl --output overlays/demo.mp4 --allow-synthetic
python -m video --root $Demo cards --events demo/events.jsonl --allow-synthetic
python -m video --root $Demo preview --edl video/edl/demo.yaml --bindings demo/edit.json --output renders/preview.mp4 --demo
python -m video --root $Demo render --edl video/edl/demo.yaml --bindings demo/edit.json --output renders/demo.mp4 --demo
python -m video --root $Demo render --edl video/edl/perceptron-arm.yaml --bindings demo/edit.json --output renders/arm.mp4 --demo
```

Bash equivalent (Mac), the same commands with only the first line different:

```bash
D="data/video/rehearsal-$(date +%Y%m%d-%H%M%S)"
V() { .venv/bin/python -m video --root "$D" "$@"; }
V demo-assets --seconds 3     # then run each line above as V <command> ...
```

The fixture has a blue towel/light tray with no markers, one overhead reference
plus perspective photos, a real MuJoCo SO-101 render, six-joint samples, a matching
synthetic event/test ledger, and generated room noise/clap (not fabricated speech).
Fixture looping is permitted ONLY in labeled `--demo` assembly to exercise a long
edit with short test clips. It is never available for real footage.

The shipped demo EDL follows the exact Devpost table: **125 seconds**, not 120.
1080p delivery is **3,750 frames at 30 FPS**; preview keeps the same timing at
640×360/15 FPS. The arm EDL uses the entire roll plus eight seconds per table card.
Actual rendering speed depends on the laptop and enabled treatments.

## Real capture: filenames and synchronization

Put originals in `data/video/raw/`; put only empty-scene plate photos in
`data/video/photos/`. Do not mix fake-arm captures into the real-demo workspace.
Keep the synthetic rehearsals in their own `--root` directories.

The binding template expects these names (or edit the template to actual names):

| File | Minimum usable duration in the shipped demo |
| --- | --- |
| `raw/N7-tray.mp4` | 5 seconds at rest |
| `raw/A1-take3.mp4` | 23 seconds: ask through complete handoff/release |
| `raw/A2-scalpel.mp4` | 14 seconds: entire safe set-down |
| `raw/A3-return.mp4` | 16 seconds |
| `raw/A4-lighting.mp4` | 14 seconds |
| `raw/A5-bench.mp4` | 16 seconds |
| `raw/A6-count-phone.mp4` | 16 seconds |
| `raw/A7-dashboard.mp4` | 12 seconds |
| `raw/A8-team.mp4` | 9 seconds |
| `raw/arm-roll.mp4` | One separate uninterrupted roll of picks/returns |

Record handles before/after each action. These are **edit durations**, not claims
about robot speed. If the complete action does not fit, change the editorial EDL
or capture a better take. Do not cut away a failure and claim an uninterrupted try.
Use constant-frame-rate footage; export variable-frame-rate phone files to CFR
while preserving source duration/audio first. Never use optical-flow frame
interpolation. Verify video/ledger sync visually before publishing any numbers.

Make `data/video/sync.json`, keyed by exact filename. Each video start time is the
real Unix epoch corresponding to media second zero, with the devices' clock offset
resolved. `kind` is `real`, `simulation` or `reconstructed`; it cannot downgrade a
source's existing non-real provenance. Example **schema, not values to copy**:

```text
{
  "A1-take3.mp4": {
    "start_time": ACTUAL_EPOCH_SECONDS_AT_CLIP_START,
    "method": "operator-confirmed clap aligned to ledger timestamp",
    "kind": "real"
  }
}
```

Use numeric epoch seconds, not a timezone-ambiguous local time. File modification
time is indexed for reference but **never** treated as recording-time alignment.
EXIF is retained as unverified capture metadata. Missing synchronization remains
`UNALIGNED`; event overlays and take selection cannot manufacture the offset.

Alternatively align a clip with a known ledger clap time. These prompts are for
non-secret measured timestamps, **not credentials**:

```powershell
$ClapEpoch = [double](Read-Host "Actual ledger epoch of the clap")
$ClapInClip = [double](Read-Host "Clap position in A1-take3.mp4, seconds")
python -m video ingest --kind real --clap-clip raw/A1-take3.mp4 --clap-ledger-time $ClapEpoch --clap-second $ClapInClip
```

Bash:

```bash
read -p "Actual ledger epoch of the clap: " CLAP_EPOCH
read -p "Clap position in A1-take3.mp4, seconds: " CLAP_S
.venv/bin/python -m video ingest --kind real --clap-clip raw/A1-take3.mp4 --clap-ledger-time "$CLAP_EPOCH" --clap-second "$CLAP_S"
```

Omit `--clap-second` to detect the strongest isolated audio peak in the first
minute. Review it: other loud transients can look like claps. Other clips still
need their own mapping. No clock sync is inferred from when a file was copied.

## Exact real-footage workflow

From the repo root, after copying correctly named footage, a reference photo
`photos/reference.jpg`, the other plate photos, and then run
`python -m video export-ledger` (writes `data/video/events.jsonl`; without it the commands read
the ledger buffer or Atlas, see "Where the real inputs come from"):

Run commands individually and stop on any failure. The binding template uses the
generated `overlays/A1.mp4`, so the finished demo actually includes the sourced
handoff overlay. Do not overwrite an existing custom `edit.json` with the template.

```powershell
python -m video export-ledger
python -m video ingest --kind real --sync sync.json
$TrayWidthMm = [double](Read-Host "Measured LEFT-TO-RIGHT tray extent in millimeters")
$TrayHeightMm = [double](Read-Host "Measured TOP-TO-BOTTOM tray extent in millimeters")
python -m video corners --input raw/A1-take3.mp4 --camera side --width-mm $TrayWidthMm --height-mm $TrayHeightMm
python -m video corners --input photos/reference.jpg --camera photo --width-mm $TrayWidthMm --height-mm $TrayHeightMm
python -m video topdown --mode warp --input raw/A1-take3.mp4 --camera side --output topdown/A1.mp4
python -m video topdown --mode plate --reference photos/reference.jpg --camera photo --empty-scene --output topdown/plate.png
python -m video clean --input raw/A1-take3.mp4 --output clean/A1.mp4 --denoise --audio
python -m video find --events events.jsonl --arm real --cut
python -m video overlay --input clean/A1.mp4 --events events.jsonl --output overlays/A1.mp4
python -m video cards --events events.jsonl --arm real
if (-not (Test-Path data/video/edit.json)) { Copy-Item video/edl/bindings.example.json data/video/edit.json }
notepad data/video/edit.json
python -m video preview --edl video/edl/demo.yaml --bindings edit.json --output renders/demo-preview.mp4
python -m video render --edl video/edl/demo.yaml --bindings edit.json --output renders/scrub-demo.mp4
python -m video render --edl video/edl/perceptron-arm.yaml --bindings edit.json --output renders/perceptron-arm.mp4
```

Bash equivalent of the PowerShell-only lines:

```bash
read -p "Measured LEFT-TO-RIGHT tray extent in millimeters: " TRAY_W
read -p "Measured TOP-TO-BOTTOM tray extent in millimeters: " TRAY_H
# then pass --width-mm "$TRAY_W" --height-mm "$TRAY_H" to the two corners commands
[ -f data/video/edit.json ] || cp video/edl/bindings.example.json data/video/edit.json
${EDITOR:-nano} data/video/edit.json
```

Review/edit bindings **before** exporting: actual source names, measured in points,
correct A1 take and one true `ARM_ROLL`. Default demo shots use only appearance/
audio cleanup and the prescribed static captions. `find` is an editorial aid,
not approval of physical success. Watch the handle-first handoff yourself.

Corners opens a native window: drag the red TL/TR/BR/BL points to the physical tray
corners; **Enter saves, Escape cancels**. Calibrate each camera/view separately,
including the exact overhead reference photo. A frame saved from the same fixed
camera is reusable; a different phone angle is not. `--points` accepts a JSON
array of four pixel coordinates. `--headless --accept-auto` is useful for fixtures;
real production should get human review. Rectification uses **2 px/mm** of the
measured tray extent. It is only a table-plane warp: the elevated arm/hand stretches.

Optical flow tracks features within the tray, fits a robust homography and stops
if tracking becomes inconsistent. For an actually locked tripod, `--no-track`
keeps the measured homography. Do not select it to conceal camera movement.

Plate matching uses SIFT, RANSAC and masked median blending. `--empty-scene`
confirms no people/arm and an unchanged instrument arrangement. Unmatched photos,
uncovered pixels or unreliable transforms stop the operation; there is no inpainting.

## Joint reconstruction (separate labeled explanatory footage)

The real-demo and unedited-arm EDLs intentionally do not substitute reconstructions
for actual arm evidence. Use them in a separately labeled explanation/backup edit.

Select the episode (no broad dataset scans). Without `--input` the dataset is
`~/scrub-dataset`, where `arm.record` writes. Pass `--input` for any other root:

```powershell
$Episode = [int](Read-Host "Recorded episode index")
python -m video topdown --mode reconstruction --episode $Episode --output topdown/recorded-joints.mp4
python -m video topdown --mode reconstruction --input "D:\path\to\dataset" --episode $Episode --output topdown/recorded-joints.mp4
```

Bash: `.venv/bin/python -m video topdown --mode reconstruction --episode 0 --output topdown/recorded-joints.mp4`.

This reuses `explore.dataset.replay.Dataset`, `sim.scene` and the SO-101 model.
It does **not** replay the action column, clamp/smooth joint readings, solve new
IK or infer grasp success. Five degrees convert to radians; raw gripper 0..100
maps to the model's jaw range. Instrument slot geometry is a static illustration,
not a reconstruction of object contact or transport. No tool is attached to the
moving robot from a heuristic or ledger success label.

Also accepts a JSON file with `units: "degrees_gripper_0_100"`, `fps`, `states`
(N×6), and optional genuine `start_time`; or JSONL `/arm/pose` records with `t`,
five `joints_deg`, and public `gripper` (0 open / 1 closed) or explicit raw
`gripper_raw`. Pose logs must have regular, complete timestamps. Irregular/missing
samples stop instead of inventing interpolated motion. LeRobot v3 joint feature
names/order must match the contract. V2 readers are not silently guessed.

Photo compositing additionally requires `--plate topdown/plate.png
--plate-alignment alignment.json`. The alignment JSON contains **measured**
`world_corners_m`: four TL/TR/BR/BL tray corners in the calibrated arm-base frame.
The renderer projects those into its actual orthographic camera. A same-size PNG
is not evidence of alignment. Do not use `demo/plate-alignment.json` on real data.
Add `--start-time` only for a measured epoch offset matching the real clip.

## Cleanup options, privacy and time edits

Every option is independent and recorded in the derivative sidecar:

- `--stabilize`: OpenCV background features/robust transforms, smoothed trajectory.
  Missing border pixels remain borders, never generated scene content.
- `--reference photos/reference.jpg`: bounded exposure and white-balance gains.
- `--deflicker`: bounded global temporal exposure correction.
- `--denoise`: bundled ffmpeg `hqdn3d`.
- `--faces`: MediaPipe detection, expanded Gaussian blur on non-team faces.
  Default blurs all detected faces. `--keep-team` opens a click list: click only
  team faces on the first frame, Enter accepts. New/lost/reappearing identities
  are treated conservatively; this is not face recognition. Detection can miss
  people: **review every frame for privacy before publishing**.
- `--audio`: `afftdn` plus loudness target. Final delivery uses measured two-pass
  -16 LUFS normalization and checks the result; silent audio remains silence
  (silence has no finite LUFS). If a clap/large transient makes the peak ceiling
  prevent the target, one logged dynamics-leveling pass is tried and remeasured.
  Listen for changed speech/room-noise balance; another failure stops delivery.
  There is no synthetic speech or music.
- `--upscale`: explicitly reports skipped when no approved non-generative model
  is configured. No silent AI replacement of instruments or arm geometry.

Before/after PNGs are in `previews/`; full source and processed clips remain
available to compare audio and moving details. Operation logs list each filter.

```powershell
python -m video clean --input raw/A1-take3.mp4 --analyze-only
# Review analysis/idle.json against the original, then ONLY for genuinely idle time:
python -m video clean --input raw/A1-take3.mp4 --output clean/idle-review.mp4 --idle-speed 2 --idle-confirmed
# --cut-idle is the alternative; never use either on the required unedited arm roll.
```

Low pixel motion can miss a slow robot movement. Never approve solely from the
JSON. Source-time maps preserve ledger alignment through cuts/speed changes;
measurements remain source values, not faster-looking edited performance.

## EDLs, composites and measurements

`video/edl/demo.yaml` lists all A1–A8 and N1–N8 slots. Only the nine rows from the
actual Devpost timing table are in the real-demo assembly; sim/making-of slots
are catalogued, not silently inserted. Copy an EDL **under data/video/** for an
alternate edit. Do not change `real_only` to smuggle a sim into the real demo.

Supported per-shot `treatment`: `none`, `clean`, `topdown`, `side-by-side`,
`picture-in-picture`. For a composite, a slot binding also supplies `secondary`
and `secondary_in_s`. Real video panels must share a verified clock. A dashboard
still is labeled **DASHBOARD STILL - NOT A LIVE STATE**. A separately labeled
making-of EDL may set `real_only: false`; every non-real panel retains its label.

A binding may supply `events` and `case_id` for an automatic ledger overlay, or
point at an already generated overlay clip. For the real demo, retain the caption
restraint from Devpost; don't cover the handoff with every possible diagnostic.
If the ledger spans multiple cases, `overlay --case-id` is mandatory. Captions,
timings, counts, lighting and active step never borrow a future event's state.

Ledger JSONL supports flat controller events and actual buffer envelopes
`{"kind":"event","doc":...}` / `{"kind":"test","doc":...}`. Export MongoDB
records to that local format rather than giving the tool a database credential.
Unknown test flags/times are rejected; rates do not come from visually guessed
success or a generated text summary. Supply full test results for the success card.
Tables paginate instead of dropping data. The current ledger lacks an action
field, so mixed handover/return rates are not advertised as handover-only rates.

`find` groups by case and command ID, requires ordered `handed` and `released`,
explicit zero retries and no error/miss/stop, then ranks sharpness. Unmatched
and excluded trials are retained in `ranked.json`. Sharpness is not proof of good
framing. Optional `--gemini` currently reports **SKIPPED**; no remote scorer is
configured and no footage is uploaded. Nothing paid is required.

### Camera captions as a second signal

The ledger decides which takes qualify. Captions only reorder them: takes sort by
`caption_score`, then sharpness. A caption never rescues a failed trial.

- Source: `vision/clips/<case_id>/metadata.json` (or `--clips-dir`), `--vision-url $VISION_URL`
  (GET `/clips?case_id=`), and `{"type":"caption"}` rows in the events file. A clip
  belongs to a take when its `command_id` matches, or its `case_id` matches and its
  `timestamp` is within 1 s of the trial window.
- Only `label_source == "perceptron"` counts. Fallback labels are built from the event
  itself, so they are ignored. Missing or unreadable metadata means no captions, not an error.
- +1 for `agrees: true`. -1 for `agrees: false`, for a seen item that differs from the
  ledger's item, and for caption words such as dropped, missed, fell, failed or empty gripper.
- `--qa report.json` adds a `qa_video` report: a take whose ledger rows carry an `episode`
  number gets -1 per `dropped`, `grasp_failed` or `dark` flag on that episode.
- `--no-captions` ranks by sharpness alone, as before.

Each take in `ranked.json` and the CLI output gets `captions`, `caption_score` and
`caption_reasons`, for example:

```
"captions": ["arm holds a scalpel"],
"caption_score": -1,
"caption_reasons": ["camera disagrees: saw scalpel, controller said hemostat"]
```

## How to shoot it

- Landscape 1080p/30, locked focus/exposure, tripod/propped phone; include the
  whole tray and all four corners over the blue towel. No markers required.
- Shoot one straight-overhead empty-scene reference first. Then 20–40 overlapping
  stills (about 60% overlap), no people/arm, same tool placement. Don't move cameras
  during an action. Measure the tray in millimeters; calibration is not a guess.
- Keep a wide view plus a close view proving **handle first**. Capture five complete
  A1 attempts; keep failures in the test ledger. Film scalpel handle safe set-down
  without an attached blade. Film return, glare before success, bench, count and
  actual summary arrival. Hold the real tables long enough to read.
- Put a second recorder next to the speakerphone. Record a clap and its real ledger
  time; retain original audio. Also record quiet room tone. No music or fake replies.
- Capture a separate uninterrupted arm roll across items/lighting. Do not build
  that required roll by joining individually successful per-try clips.
- Hide keys, terminals containing secrets, notifications, phone numbers and
  bystanders. Get team consent; review blurring. Copy media with its provenance.

Before publishing, watch both full outputs, listen to the ask/reply, compare every
displayed measurement against its logged source, check all disclosures, and verify
the arm film is continuous. Tests on synthetic media are **not** physical acceptance.

## Perceptron arm video (`video/edl/perceptron-arm.yaml`)

One unedited real-arm roll (`ARM_ROLL`, cleaned only, never trimmed or sped up) followed by the end cards with the
success table. Inputs: the filmed roll of real tries, and the ledger: real-arm handover events with
`skill_source: "model"` (to find and check the tries) and test rows from `controller.trials` (the only success-rate
denominator). Run from the repo root on the Mac after the tries are filmed:

```bash
A=data/video/arm                                          # workspace; raw/ holds the filmed roll
mkdir -p $A/raw && cp <filmed roll>.mp4 $A/raw/arm-roll.mp4
.venv/bin/python -m video --root $A export-ledger          # every row: Atlas plus the local buffer
.venv/bin/python -m video --root $A ingest --kind real    # add --clap-clip raw/arm-roll.mp4 --clap-ledger-time <epoch> to sync
.venv/bin/python -m video --root $A find --events events.jsonl --arm real --skill-source model --no-captions
#   "trials": the real model handovers (handed + released, zero retries); "ledger_trials" lists them
.venv/bin/python -m video --root $A cards --events events.jsonl --arm real
#   cards/end*.png: the success table from real test rows only; refuses if there are no real rows
echo '{"ARM_ROLL": {"source": "raw/arm-roll.mp4", "clean": {"audio_clean": true}}}' > $A/edit.json
.venv/bin/python -m video --root $A render --check --edl video/edl/perceptron-arm.yaml --bindings edit.json
.venv/bin/python -m video --root $A render --edl video/edl/perceptron-arm.yaml --bindings edit.json --output renders/perceptron-arm.mp4
```

`render --check` runs every gate (real provenance, unedited roll, cards present and not simulated) without encoding.
Without `cards/index.json` the render now says to run `cards --arm real` first instead of a `FileNotFoundError`.
The dataset (`~/scrub-dataset`) holds teleoperated demos, not model tries, so it is not an `ARM_ROLL`; use it only for
`topdown --mode reconstruction` shots, which carry `RECONSTRUCTED FROM ARM JOINT DATA` and are refused by this EDL.

Dry run on Oct 18 01:45: `ledger/buffer.jsonl` had 6 rows, all `fake`. Atlas (`export-ledger`) had 56,933 events and
0 test rows: 39,253 fake, 17,427 untagged (`unknown`), 253 `fake_arm: false`. Of those, `find --arm real
--skill-source model` finds 17 complete hemostat handovers, every one 0.41 to 0.43 s request-to-hand, which is
not a physical arm (likely a test controller writing `fake_arm: false` to Atlas). No genuine real-arm try and no
trial row exists yet, so `cards --arm real` renders an end card with no rate, and the render waits for the roll.

## Sim backup video (`video/sim_backup.py`)

The labeled `SIMULATION` backup from a running sim stack. Give the stack its own ledger file, otherwise any process
with `MONGODB_URI` flushes the rows to Atlas before `build` reads them:

```bash
export LEDGER_BUFFER=$PWD/data/video/sim-run/ledger.jsonl
SCRUB_STATE_FILE= .venv/bin/python -m controller.run_all backup --offline --loop --pause 2 --base-port 8500 --no-open
# in another shell, with the same LEDGER_BUFFER, once it prints "backup run N: CLEAN":
.venv/bin/python -m video.sim_backup capture --root data/video/sim-run/capture-1        # 110 s by default
.venv/bin/python -m video.sim_backup build --root data/video/sim-run/capture-1
```

`capture` records `http://127.0.0.1:8502/stream?cam=overhead` and Chromium screenshots of the dashboard on
`:8500`, resampled to 30 FPS on the capture clock (the clock the controller stamps events with), and writes
`sync.json` with each clip's first-frame epoch and `kind: simulation`. One backup pass is about 52 s, so 110 s
always holds one whole case. `build` ingests both clips, picks the first case fully inside the window that ran the
whole script (three handovers done, a return, an accepted count, no error, missed or stopped event), overlays that
case only, renders without `--demo` (every frame has the `SIMULATION` bar) and copies the result to
`data/video/out/sim-backup.mp4`, with `sim-backup-summary.json` listing the case, its request-to-hand times and
every overlay change by output second. Check those against the frames before showing it.

