# Recognition bench

Compares ways to recognize the surgical tray items (scalpel, hemostat, mayo scissors) on saved images. Code is `explore/recognition/bench.py`, scoring tests are `explore/recognition/test_bench.py`.

```
.venv/bin/python -m explore.recognition.bench --repeat 2
.venv/bin/python -m unittest explore.recognition.test_bench
```

It reads keys from `.env` and never prints them. It writes `explore/recognition/out/bench.json` and `bench.md`. Use `--images DIR` for other photos: `DIR/<item_id>/*.jpg` for single-item crops, and `DIR/labels.json` for whole-tray photos (`{"tray.jpg": {"items": [...], "boxes": {"scalpel": [x1, y1, x2, y2]}}}`, plus `label` and `light` as `capture.py` writes them).

## Methods

Pick with `--methods` (comma list, default all six).

| Method | What it does |
| --- | --- |
| `perceptron` | The `/v1/detect` call `vision/tray.py` makes, frame shrunk to 640 px wide |
| `perceptron_small` | The same on a 416 px wide frame |
| `perceptron_crop` | The same on the tray region only (union of the slot boxes in `settings/<tray>.json`, else the central 70%) |
| `gemini_tray` | Gemini `gemini-3.5-flash-lite` checks the tray against an enum of item names |
| `gemini_ref` | The same, with one reference image of each item in the prompt before the tray image |
| `mediapipe_glove` | MediaPipe hand landmarker (settings from `vision/hand.py`, local, no API) on `glove_*` images |

`--max-calls N` caps the API calls over all API methods (default 120, split evenly between them). Gemini waits 3 s between calls and retries once after 20 s on an HTTP 429. Other flags: `--repeat` (default 3), `--setting`, `--perceptron-timeout` (default 15 s; `vision/tray.py` uses 6 s), `--hand-model`, `--out`, `--model`.

`bench.md` has three tables: per method, per light level (bright, normal, dim, unknown) and per item (images, found rate, box IoU), then the first errors and notes.

## Smoke test (Oct 17, synthetic, not evidence)

The numbers in this section come from the first version of the bench, before the new methods. They are a smoke test only.

### What data exists

The repo holds three real crops, one per item, in `explore/bench/refs/` (80x23, 172x121 and 96x35 px, from the real tray). The six images under `vision/clips/` are 640x480 and completely black (fake-camera clips). There is no whole-tray photo, no image with printed text and no image of a gloved hand. So the numbers below come from 3 real crops plus 2 synthetic trays composed from those crops on a dark 640x480 background (boxes known by construction). The crops are loose: the hemostat crop also shows a scalpel-like rod, so a "scalpel" hit on it is not clearly wrong. Treat every number as a smoke test, not accuracy on a real tray.

### Methods and results (this run: 5 images, 2 repeats each)

| Method | Calls | Found rate | Accuracy | Median latency |
| --- | --- | --- | --- | --- |
| Perceptron `/v1/detect`, the same call `vision/tray.py` makes | 10 | 0.4 | 0.2 | 2.5 s |
| Gemini `gemini-3.5-flash-lite`, name the instruments in a crop | 6 | 0.33 | 0.0 | 0.97 s |
| Gemini `gemini-3.5-flash-lite`, check a tray against the expected list | 4 | 0.5 | 0.5 | 1.56 s |

No call failed in the final run. An earlier run hit HTTP 429 from Gemini when calls came back to back, so the bench now waits 3 s between Gemini calls and retries once after 20 s. About 80 API calls were made across three runs in total while fixing the synthetic tray layout.

Perceptron detect, per image (found = all expected items returned a box):

- Crops: scalpel found, hemostat found, mayo scissors not found in either repeat. Scalpel was also returned for the hemostat and mayo crops.
- Synthetic tray with all three: scalpel and hemostat found, mayo scissors not found. The scalpel box had IoU 0.0 against the pasted crop and the hemostat box IoU 0.34, so those boxes landed on the wrong part of the image (probably on the scalpel-like rod inside the hemostat crop).
- Synthetic tray without the scalpel: hemostat found with IoU 0.996, mayo scissors not found, and a scalpel was still returned (the rod in the hemostat crop).
- Latency per call: 1.8 to 2.5 s on crops, 3.8 to 4.7 s on the 640x480 trays. These runs used the old limits (a 4.0 s timeout and a 3 s stale cutoff), so the larger frames sat on both. `vision/` now uses a 6 s timeout, uploads frames 640 px wide and treats a read as stale after 8 s. The first call in an earlier run took 9.6 s (cold connection).

Gemini naming a crop (open names matched to item ids with the same alias list as vision): scalpel crop named `retractor` once and nothing once. Hemostat crop named `scalpel handle`, `hemostat` and `forceps`. Mayo crop named `surgical retractor` and `surgical blade`. It never produced "mayo scissors" and used generic names (forceps, retractor). Open naming needs a constrained list.

Gemini checking a tray (the prompt lists the three names, structured JSON with an enum): all-three tray correct 2 of 2. Tray without the scalpel wrong 2 of 2: it said the scalpel was present and the mayo scissors missing. The mayo crop was 52 px tall at 1.5x, so this case is as much about image quality as about Gemini.

### Skipped

- OCR: no photo with printed text at the time of this run. Rendered props were read later, see "Reading (OCR) on the printed props". The tray items carry no printed text, so OCR adds nothing for instruments.
- MediaPipe hand landmarker on gloved hands: no such image exists, so there is no measurement. `vision/README.md` already says the landmarker has no glove model. Photos needed: overhead camera, a blue or white nitrile glove, an open palm held 15 to 25 cm above the tray, in bright, normal and dim light, 10 frames each, saved as `DIR/glove_*.jpg`. A person also needs to say where the palm is in each, or the bench can only count whether a hand was found.

## Real tray (pending photos)

The numbers for the real tray come from `data/recognition/tray1` once the photos below are taken. Then run:

```
.venv/bin/python -m explore.recognition.bench --images data/recognition/tray1 --repeat 2 --max-calls 120
```

Fill in the per method, per light and per item tables from `explore/recognition/out/bench.md` here. Until then, nothing in this file is evidence about the real tray.

## Reading (OCR) on the printed props

These are rendered images from `explore/recognition/props/` (count sheet, tray tag, pack labels), not photos yet. The code is `vision/reading.py`; the API facts are in `docs/PERCEPTRON-ROBOTICS.md` Part 2.

Results (Oct 18, measured):

| Prop | Result | Method | Time |
| --- | --- | --- | --- |
| Count sheet, blank, surgical and bench | correct | Perceptron | 1.8 to 2.3 s |
| Count sheet, filled, surgical and bench | correct | Perceptron | 1.8 to 2.3 s |
| Count sheet, filled surgical, at 20 degrees | correct | Perceptron | 1.8 to 2.3 s |
| Tray tag, surgical and bench | correct | QR decode, no API call | 0.05 s |
| Pack labels, flat and at an angle | 4 of 4 labels correct (item, lot, expiry); the expired mayo scissors label flagged | Perceptron | 2.4 to 2.5 s |

Earlier renders by the vision agent:

- Perceptron with `reasoning_effort` `none` was about twice as fast as `low` with the same results (count sheet 1.0 s against 2.0 s).
- Gemini 3.5 Flash Lite was correct on all of them, 1.7 to 2.9 s. One warped pack label took 12.1 s.

One live failure was found and fixed. Perceptron invented a pack label on a frame that had no label. The guards now: an empty label list is allowed, the strings "null" and "none" count as empty, and a label needs a printed item name.

A second live failure, also fixed (Oct 18, through voice, controller and vision): on a camera frame with instruments and no tray tag, "what tray is this" came back "This is the operating room tray". With the tray names in the prompt, Perceptron returned the text "Surgical", then "Surgical Tray", neither of which is in the frame. The OCR fallback is now a plain transcription with no tray names in the prompt, and the tray is matched locally from text that has to contain the word "tray". After the fix the same frame gives "I can't read the tray tag." (2 of 2), and a text-only crop of the printed tag still reads as surgical (Perceptron, 1.0 s).

What still needs real photos: handwriting by a person with a pen (the filled sheets are rendered text), print and paper texture, glare, camera blur, a tray tag and labels under the overhead camera in dim light, and the angled shots in the list below. Rendered images are cleaner than any of these, so treat the times and the 100% correct rate as an upper bound.

### Reading bench, renders and a simulated camera (Oct 18, SYNTHETIC)

`explore/recognition/read_bench.py` runs `vision/reading.py` on every prop PNG and scores it against `explore/recognition/props/truth.json`: count sheet tray, rows and each expected, initial and closing cell; tray tag tray; pack label item, lot, expiry and the expired flag. `render` is the PNG as drawn. `camera` is the same PNG put on a table in a 1280x720 frame, turned 4 degrees, blurred, noisy, dimmed to 75% and saved as JPEG 70. Both are synthetic; neither is a photo.

```
.venv/bin/python -m explore.recognition.read_bench                       # 40 calls at most, about 2 min
.venv/bin/python -m explore.recognition.read_bench --only tray_tag,pack_labels --no-qr --name read_bench_noqr
.venv/bin/python -m unittest explore.recognition.test_read_bench          # scoring, no API
```

| Prop (images) | Variant | Perceptron exact, cells, median / max | Gemini exact, cells, median / max |
| --- | --- | --- | --- |
| Count sheet (5) | render | 5/5, 45/45, 1.6 / 2.5 s | 5/5, 45/45, 2.4 / 6.8 s |
| Count sheet (5) | camera | 5/5, 45/45, 1.6 / 2.0 s | 5/5, 45/45, 1.7 / 2.2 s |
| Pack labels, 4 per sheet (2) | render | 2/2, 32/32, 2.7 / 4.7 s | 2/2, 32/32, 1.7 / 1.7 s |
| Pack labels, 4 per sheet (2) | camera | 2/2, 32/32, 2.7 / 3.5 s | 2/2, 32/32, 1.6 / 1.8 s |
| Tray tag (2), QR | render and camera | 4/4 by QR, 30 to 52 ms, no API call | same |
| Tray tag (2), OCR (`--no-qr`) | render and camera | 4/4, 0.7 to 1.2 s | 4/4, 1.3 to 1.8 s |

Pack rows are from the second run, after the lot fix (the first run: Perceptron 1.9 to 2.3 s, Gemini 2.0 to 2.7 s). One real bug came out of it: on the camera-simulated angled pack sheet Perceptron returned the lot as `LOT SC-24-0917` (it copied the printed prefix), so 0 of 16 fields matched. `vision/reading.py` now strips a `LOT`, `Lot no.:` or `lot#` prefix; the rerun scored 16 of 16. Every count sheet read dropped nothing and invented no row. The expired mayo scissors label was flagged on every read.

The same camera-simulated JPEGs posted to a vision on port 8601 (`POST /read/<kind>`, then worded by a controller layer on a fake arm): the filled surgical sheet in 1.6 s, the bench tray tag in 47 ms by QR (the controller switched to the bench tray), the angled pack sheet in 2.3 s with the expired mayo scissors flagged. The controller's own read path (`controller/reads.py`, `read_sheet` / `read_tray` / `read_pack`) reads the overhead frame instead; on the fake camera `read_tray` was accepted ("Reading the tray tag.").

Run the same bench on photos: capture them with the `count_sheet_*`, `tray_tag` and `pack_label*` keys, write a `truth.json` in the props format beside them, and pass `--images data/recognition/tray1`.

### Trying the capture tool without a camera

`--frames DIR` loops the saved images in a folder as the camera, with the same window and keys, and opens no camera: `.venv/bin/python -m explore.recognition.capture --set try --frames explore/recognition/props --data /tmp/rec`. The tests drive the same loop with scripted keys (`explore/recognition/test_capture.py`).

## Photos to take

About 15 minutes, one person, about 140 frames. Run every command from the repo root. Use one set name (`tray1` below) so everything lands in one folder.

Setup: overhead camera on its mount, tray in place, the surgical setting items on the tray (scalpel, hemostat, mayo scissors). Print the props first: `print explore/recognition/props/*.html` (count sheet, tray tag, pack label). Find camera indexes with `.venv/bin/python -m arm.check_setup --side C920 --wrist icspring` if the defaults are wrong. Defaults: overhead is `CAMERA_INDEX` if it is set in your shell (else 0), side is `CAPTURE_SIDE_INDEX` (1), wrist is `CAPTURE_WRIST_INDEX` (2). `--camera 3` also works.

Keys (the same list prints when the tool starts and is drawn on the preview):

| Key | Label | Items stored |
| --- | --- | --- |
| 1 | full | all three |
| 2 | no_scalpel | hemostat, mayo_scissors |
| 3 | no_hemostat | scalpel, mayo_scissors |
| 4 | no_mayo_scissors | scalpel, hemostat |
| 5 | alone_scalpel | scalpel |
| 6 | alone_hemostat | hemostat |
| 7 | alone_mayo_scissors | mayo_scissors |
| 8 | grip_scalpel | scalpel |
| 9 | grip_hemostat | hemostat |
| 0 | grip_mayo_scissors | mayo_scissors |
| a | glove_blue | all three, under the hand |
| b | glove_white | all three, under the hand |
| c | count_sheet_clean | none |
| d | count_sheet_written | none |
| e | count_sheet_angle | none |
| f | tray_tag (flat or at an angle) | none |
| g | pack_label | none |
| h | pack_label_angle | none |

A label key selects that label and saves one frame. SPACE saves another with the current label. `[` and `]` change label. `l` cycles the light tag (bright, normal, dim). `q` or Esc quits. Each frame is tagged with the light shown on the preview, so set the real light first. Pass `--light` at start to set the first tag.

### 1. Full tray and one instrument removed (overhead, 39 frames)

Do this three times, once per light. Bright: all lights on. Normal: usual room light. Dim: lights down to about a quarter.

```
.venv/bin/python -m explore.recognition.capture --set tray1 --camera overhead --light bright
```

- [ ] Bright: key `1` x 4 (full tray), then remove the scalpel and press `2` x 3, put it back and remove the hemostat, `3` x 3, put it back and remove the mayo scissors, `4` x 3, put it back.
- [ ] Normal: same 13 frames. Rerun with `--light normal` (or press `l` once).
- [ ] Dim: same 13 frames. Rerun with `--light dim` (or press `l` again).

Move each frame a little between presses (nudge the tray or an instrument by a finger width).

### 2. Each instrument alone (normal light, 9 overhead and 15 wrist frames)

Clear the tray, then put one instrument in its slot.

```
.venv/bin/python -m explore.recognition.capture --set tray1 --camera overhead --light normal
```

- [ ] Overhead: key `5` x 3 (scalpel alone), `6` x 3 (hemostat alone), `7` x 3 (mayo scissors alone).

Then the same instruments in the gripper. Close the gripper on each one, lift it 10 cm above the tray, and shoot from the wrist camera.

```
.venv/bin/python -m explore.recognition.capture --set tray1 --camera wrist --light normal
```

- [ ] Wrist: key `8` x 5 (scalpel in gripper), `9` x 5 (hemostat), `0` x 5 (mayo scissors).

### 3. Gloved open hand (overhead, 60 frames)

Full tray in place. Open palm facing down, 15 to 25 cm above the tray, fingers spread. Tilt and move the hand a little between frames. Blue nitrile first, then white, three lights each.

```
.venv/bin/python -m explore.recognition.capture --set tray1 --camera overhead --light bright
```

- [ ] Bright: key `a` x 10 (blue), then swap gloves, `b` x 10 (white).
- [ ] Normal: same 20 frames (rerun with `--light normal`).
- [ ] Dim: same 20 frames (rerun with `--light dim`).

### 4. Printed props (overhead, 21 frames, normal light)

Print `explore/recognition/props/*.html`. Fill the count sheet by hand for the "written" shots (initial and closing counts, pen). Lay each prop flat on the table where the tray sits, filling most of the frame. For "angle", tilt it about 30 degrees and turn it a little off square.

```
.venv/bin/python -m explore.recognition.capture --set tray1 --camera overhead --light normal
```

- [ ] Count sheet, blank, flat: key `c` x 3.
- [ ] Count sheet, handwritten, flat: key `d` x 3.
- [ ] Count sheet, handwritten, at an angle: key `e` x 3.
- [ ] Tray tag on the tray, flat: key `f` x 3.
- [ ] Tray tag on the tray, at an angle: key `f` x 3.
- [ ] Pack label, flat: key `g` x 3.
- [ ] Pack label, at an angle: key `h` x 3. Repeat `g` and `h` with a written lot or date if the label has a blank for it.

A phone is fine for any prop, see below.

### Phone photos instead

Name each file `<label>[_anything].jpg`, for example `count_sheet_written_a.jpg` or `no_hemostat_2.jpg`. Put them in one folder (jpg, jpeg or png; HEIC is skipped, export as jpg first), then:

```
.venv/bin/python -m explore.recognition.capture --set tray1 --import ~/Downloads/phone --light normal
```

Files whose name does not start with a label are skipped and listed. Imported frames are tagged camera `phone` and the light you pass.

### Where the files go and what to run next

- Photos: `data/recognition/tray1/<label>_<n>.jpg`.
- Labels: `data/recognition/tray1/labels.json`. Each entry has `items` (what is on the tray), `boxes` (empty), `label`, `camera`, `light` and `t`. `bench.py` reads `items` and `boxes`. Capturing again with the same set name adds files and never overwrites.
- Check counts: `ls data/recognition/tray1 | sed 's/_[0-9]*\.jpg//' | sort | uniq -c`.
- Run the bench: `.venv/bin/python -m explore.recognition.bench --images data/recognition/tray1 --repeat 2`
- Results land in `explore/recognition/out/bench.json` and `bench.md`.

## Recommendation

Keep `vision/` as it is. Nothing here beats the current Perceptron path on evidence strong enough to change it, and the data is too thin to judge either way. Two things to check on the real overhead frames before the demo:

1. Latency against the limits. On 640x480 tray images, detect took 3.8 to 4.7 s here, over the old 4.0 s timeout and 3 s stale cutoff. The limits are now 6 s and 8 s, set by `VISION_DETECT_TIMEOUT_S` and `VISION_TRAY_STALE_S`. Check `detect_p50_ms` on vision `/health` with the live camera.
2. Missing instruments. Perceptron did not return mayo scissors in any tray image. Take one real overhead photo of the full tray and one with each instrument removed, put them in a folder with `labels.json`, and rerun the bench. If Perceptron still misses, Gemini tray check (about 1.1 to 2 s, structured output, enum of item names) is the candidate second opinion for `controller/traycheck.py`. In this run it got the full tray right and the missing-scalpel case wrong, so it is not ready to replace anything.
