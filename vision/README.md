# vision

Owner: Brandon. Tasks B1 to B8 in `docs/TASKS.md`.

One process owns the overhead camera (locked exposure and white balance). It runs the MediaPipe hand tracker (POST a Hand to the controller about 10 times a second) and the Perceptron tray perception (POST a TrayState about once a second). It serves an MJPEG stream with boxes and the palm dot at `http://localhost:8001/stream`. `calibrate.py` fits the camera-to-arm mapping into `calibration.json`.

It binds 127.0.0.1, so the camera stream is not reachable from the venue network. The dashboard and nurse page on the same laptop work as is. To open the stream to another device (a dashboard opened at `http://<laptop LAN IP>:8000/` reads the camera at `<that IP>:8001`), run with `--host 0.0.0.0` or set `VISION_HOST=0.0.0.0` in `.env`.

Run from the repo root:

```
python -m vision              # camera CAMERA_INDEX from .env, preview at http://localhost:8001/
python -m vision --fake      # no camera: synthetic tray, open palm, locked-exposure stand-in (30 fps)
python -m vision --fake --port 8011 --host 0.0.0.0   # another port, open to the LAN
python -m vision.test_vision # fake-input checks for B1 to B7, plus the slot, calibration, and lighting tools
.venv/bin/python -m pytest -q vision/test_vision.py  # the same tests under pytest
```

The controller does not have to be running. The first failed POST to `/vision/hand` or `/vision/tray` is logged once.

## What each file does

| File | Task |
| --- | --- |
| `__main__.py` | `python -m vision`: picks the real camera or `--fake`, starts the loops, serves on `--port` and `--host` |
| `service.py` | The hand (10 Hz), tray (1 Hz), lighting (1 Hz) and clip-event (2 Hz) loops, and the posts to the controller |
| `camera.py` | Opens the camera, turns off auto exposure and auto white balance, one grabber thread, `FakeCapture` |
| `hand.py` | MediaPipe Tasks hand landmarker, palm center, open-palm check |
| `tray.py` | `POST https://api.perceptron.inc/v1/detect`, maps boxes onto slots, `FakeDetector` for `--fake`. See `docs/PERCEPTRON.md` |
| `tray_check.py` | Missing and wrong-slot items for `GET /tray_check` |
| `clips.py` | Rolling frame buffer, one .mp4 and thumbnail per event under `vision/clips/<case_id>/` (git-ignored), labels |
| `app.py` | HTTP routes (below) |
| `draw.py` | Slot boxes, detections, palm dot and target on the preview frame |
| `geometry.py` | Box math and the gripper-to-target path check |
| `heights.py` | Load and save `hand_heights.json` |
| `mark_slots.py` | Click slot corners, or `--fake` to write the surgical and bench trays in the settings shape |
| `calibrate.py` | Homography from guided gripper points or `--pairs` (explore page 42). Prints the max error in cm. Target is 4 cm short of the palm |
| `lighting.py` | Mean brightness, and `--test` to append hand / detect / stale rates to a CSV |
| `hand_heights.json` | Default hand height 0.18 m, plus one height per clinician |
| `test_vision.py` | All the fake-input tests |
| `reading.py` | Reading (OCR): count sheet, tray tag, pack label. QR, then Perceptron, then Gemini |
| `test_reading.py` | Reading tests with fake HTTP, and the OpenCV renders of a sheet, a tag and a label |

Routes on port 8001: `GET /` preview page, `/stream` (MJPEG, `?frames=N` stops after N), `/snapshot`, `/health` (camera, exposure lock, `fps.overhead`, `detect_ms` and `detect_p50_ms` over the last 50 detects), `/vision/hand`, `/vision/tray`, `/lighting`, `/tray_check`, `/clips`, `/clips/{case_id}/{file}`, `/read/last`; `POST /clinician`, `/gripper`, `/clips/record`, `/clips/label`, `/read/count_sheet`, `/read/tray_tag`, `/read/pack_label`.

## Reading (OCR)

`vision/reading.py` reads three things from a photo or the overhead frame:

| Route | Returns (plus `method`, `latency_ms`, `ok`, `error`, `attempts`) |
| --- | --- |
| `POST /read/count_sheet` | `tray`, `tray_text`, `items: [{item, name, printed_name, expected, initial, closing}]`, `dropped`, `setting` |
| `POST /read/tray_tag` | `tray` (a setting id or null), `text`, `qr` (payloads found) |
| `POST /read/pack_label` | `labels: [{item, item_text, lot, sterilized, expires, sterilized_text, expires_text, indicator_text, expired}]`, `expired` (any), `today`, `setting` |
| `GET /read/last` | the last result of each reader |

The body is a JPEG (`Content-Type: image/jpeg`), a multipart file, or `{"source": "overhead"}` for the current camera frame. `setting` (form field, JSON field or query) picks the item list; without it vision uses the setting it already tracks. `today` (YYYY-MM-DD) sets the date for `expired`. The OCR call runs in a worker thread: `/vision/hand` answered in at most 5.2 ms during a read.

```
curl -X POST -H "Content-Type: image/jpeg" --data-binary @sheet.jpg http://localhost:8001/read/count_sheet
curl -X POST -F file=@label.jpg -F setting=surgical http://localhost:8001/read/pack_label
curl -X POST -H "Content-Type: application/json" -d '{"source":"overhead"}' http://localhost:8001/read/tray_tag
python -m vision.reading count_sheet sheet.jpg --setting surgical   # same thing from the command line
```

Order: the tray tag tries QR first (OpenCV, payload `scrub:tray:<id>`). Then Perceptron OCR, then Gemini. A backend that errors, times out, or returns JSON that does not validate hands over to the next one. `method` says which one answered; `latency_ms` is the whole read.

Fixed list, never invent: the schemas only allow the setting's item ids and the known setting ids (`settings/*.json`, not `*.local.json`), plus `other`. Then each printed name is matched again to an id, name or alias (also a close spelling, difflib 0.85). A row whose printed name matches nothing is dropped and listed in `dropped`. A count sheet with no matching row, or a pack label with no printed item name, counts as no answer.

Dates come back as YYYY-MM-DD. Numeric dates are read US style (10/17/2026) unless the first number is over 12. A month-only expiry (2026-11) means the last day of that month. `expired` is true when the expiry is before today.

Perceptron OCR is `POST https://api.perceptron.inc/v1/chat/completions` on `perceptron-mk1.5` with `response_format: {"type": "json_schema", "json_schema": {"name", "strict": true, "schema"}}` and the image as an `image_url` data URL. There is no separate OCR endpoint. Gemini uses `responseSchema` with the same enums.

Live check, Oct 18, on OpenCV renders (a count sheet with 4 rows and handwritten-style counts, a text-only tray tag, a pack label), each clean and with a perspective warp:

| Reader | Perceptron, reasoning `low` | Perceptron, reasoning `none` | Gemini 3.5 Flash Lite |
| --- | --- | --- | --- |
| Count sheet | 2/2 correct, 1.9 to 2.2 s | 2/2, 1.0 to 1.1 s | 2/2, 2.4 to 2.9 s |
| Tray tag (text) | 2/2, 1.0 to 1.1 s | 2/2, 0.5 to 0.7 s | 2/2, 1.7 to 2.1 s |
| Pack label | 2/2, 1.2 to 2.2 s | 2/2, 0.6 to 0.8 s | 2/2, 1.7 to 12.1 s |
| Tray tag (QR) | 2/2 by QR, 15 to 30 ms, no API call | | |

Every reader dropped the invented "Army-Navy retractor" row. On the fake camera frame (no label in it) Perceptron once made up a pack label (item_text "null", lot 123456789); the empty-label rule above now drops that, and the same request then answered `ok: false`. These are renders, not photos of the real props; rerun on photos before quoting accuracy.

Settings in `.env`:

```
READ_PERCEPTRON_TIMEOUT_S=8      # worst measured 2.2 s
READ_GEMINI_TIMEOUT_S=15         # one call took 12.1 s
READ_PERCEPTRON_REASONING=low    # none was 2x faster and as correct on renders; low is kept for handwriting
READ_MAX_SIDE=1600               # long side of the uploaded JPEG
PERCEPTRON_OCR_MODEL=perceptron-mk1.5
GEMINI_MODEL=gemini-3.5-flash-lite
```

A backend whose key is not set is skipped. With neither key the result is `ok: false`, `error` "no OCR backend (no API key set)"; QR tags still read.

## Detect timing

`docs/RECOGNITION.md` measured `/v1/detect` at 3.8 to 4.7 s on 640x480 trays. A live `--check-api` call on a flat 640x480 frame took 1.6 s on Oct 18. So the detector shrinks any frame wider than 640 px before upload (the 1280x720 camera frame goes up as 640x360) and scales the boxes back to the full frame. Its timeout is 6 s. `GET /tray_check` calls a read stale once it is older than that timeout plus 2 s (8 s). Watch `detect_p50_ms` on `/health`. Override in `.env`:

```
VISION_DETECT_TIMEOUT_S=6
VISION_DETECT_WIDTH=640      # 0 sends the full frame
VISION_TRAY_STALE_S=8        # default: detect timeout + 2 s
```

The controller has its own 3 s cutoff (`TRAY_STALE_S` in `controller/core.py`), so with a 4 s detect it sees the tray as stale between reads.
`GET /tray_check` reports `stale: true` with no tray read yet, after a failed read, or when the last read is older than the cutoff above (a hung detect), so the controller says it can't check instead of "missing everything". `wrong_slot[].in_slot_of` is another item's id or null. Event clips: vision polls the controller's `/events/recent` every 0.5 s and saves a clip for each picked, handed, set_down, released, returned, stopped and missed event once its 1.5 s after-window has passed. Events from before vision started are skipped. The clip buffer keeps frames at 640 px wide. `target` stays null until `vision/calibration.json` exists, except `python -m vision --fake`, which posts a stand-in target so the fake arm can finish a handover. The API returns no confidence, so a fresh TrayState uses `1.0`. A failed call keeps the last good state and sets `stale` true (optional field).

## Clip captions

`POST /clips/label {"case_id": ...}` captions every clip of a case. Each clip sends one `/v1/chat/completions` call (perceptron-mk1.5, `reasoning_effort: "low"`) with 5 frames spread over the 3 s clip as a `video_frames` part (each frame a JPEG data URL with `timestamp_ms`). The prompt does not name the controller's event. It lists the tray's item names (the event's `setting`, or every tray in `settings/`; the clip's own item is sorted in if no tray has it) and asks for JSON: `caption` (one neutral line on what the arm and hands do), `item_seen` (an item name or `none`) and `action` (`picked`, `handed`, `set_down`, `released`, `returned`, `none_or_unclear`).

Each clip in `GET /clips` then has:
- `label`: the caption, plus `, 6.4 s` when the event has `request_to_hand_s`. Without a key, on an HTTP error, an exception or an empty reply, the fallback (`hemostat presented to clinician, 14:02`).
- `label_source`: `perceptron` or `fallback`.
- `caption_item`, `caption_action`: from the reply (null on fallback, or when the reply had no JSON).
- `agrees`: true when `caption_action` and `caption_item` match the event (`waiting_for_pull` counts as `handed`); null for events a clip can't show (`stopped`, `missed`, `error`) and on fallback.
- `caption_latency_ms` (null when no call was made), `caption_frames`, `caption_error` (why the fallback was used), `labeled_at`.

Notes:
- `max_completion_tokens` is 1024 because reasoning tokens count against it. At 256 one call came back with empty content.
- An earlier prompt that named the event echoed it: a clip where the arm never moved, labeled `handed`, came back `hemostat held by robot arm at hand-off spot`. That is why the event is left out now.
- Live, Oct 18, 2026, `python -m vision --fake --port 8072`, 3 clips cut from real recorded side-camera frames, one `POST /clips/label`:

| Clip (controller event) | label | item, action | agrees | ms |
| --- | --- | --- | --- | --- |
| episode 5 grasp (picked spatula) | Robot arm hands scalpel to person's hand | scalpel, handed | false | 2129 |
| episode 5 end (handed spatula, 6.4 s) | human hand reaches in and takes the scalpel from the tray, 6.4 s | scalpel, handed | false | 1552 |
| episode 0, arm never moves (handed hemostat, 5.2 s) | robot arm holds blue tool over tray, 5.2 s | none, none_or_unclear | false | 2176 |

  The still-arm clip now disagrees, as it should. The first two disagree on the item: the recording's task says "spatula" but the tool on the tray looks like a scalpel. A person's hand is in frame during the grasp, which is likely why the model called it `handed`.
- Tests: `python -m vision.test_clips` (fake HTTP, synthetic frames).

## Lamp check (B1)

Open `http://localhost:8001/` and turn a lamp on. The picture should brighten and stay there. It should not flash and settle back, which is what auto exposure does. Optional numbers: `python -m vision.lighting --label bright` (and `normal`, `dim`).

On the Acer FHD laptop camera, `CAP_PROP_AUTO_EXPOSURE` reads back `-1` for every setting. Setting `CAP_PROP_EXPOSURE` does hold: exposure `-8` stayed near mean brightness 13, and `-1` stayed near 148, with no pull back toward the middle. The default exposure is `-6`. Override it with `CAMERA_EXPOSURE` and `CAMERA_WB` in `.env` if the overhead camera is too dark or too bright.

## Lighting test (B8 tooling)

One row per lighting tag. It counts frames, how often a hand is seen, how often `/v1/detect` returns, and how often that call fails (the stale rate):

```
python -m vision.lighting --test --label bright --seconds 10 --csv vision/lighting_tests.csv
python -m vision.lighting --test --label normal --seconds 10
python -m vision.lighting --test --label dim --seconds 10
```

`--fake` runs the same row without a camera or an API key. `--all-conditions` writes bright, then normal, then dim. On a real camera it waits for Enter between lamps. In a script, run one `--label` at a time. `python -m vision.lighting --check-api` makes one live `/v1/detect` call and prints the status and the latency, not the key. The CSV is a local log. Do not commit it.

## Marking slots (B5)

With the camera mounted, save one frame (`/snapshot`) and click two corners per item, then the return spot:

```
python -m vision.mark_slots --setting surgical --image tray.jpg
python -m vision.mark_slots --setting surgical --live
```

`--live` grabs one frame from `CAMERA_INDEX`, saves it, and opens the click window. Or pass corners without a window: `--clicks x,y,x,y,...`. The JSON it writes is a full settings file with `slot` and `return_spot` filled. Evan copies those numbers into `settings/<id>.json`. Do surgical, then bench. Dental is dropped. Until those boxes are filled, a detection anywhere counts as in the right slot.

`python -m vision.mark_slots --fake --out /tmp/marked` writes the surgical and bench files (and a .jpg of each synthetic frame), with no camera and no window. It does not change `settings/`.

## Calibration (B6)

At the arm, record 6 to 8 gripper positions as pixel and arm meters:

```
python -m vision.calibrate
python -m vision.calibrate --pairs pairs.json
```

Guided mode asks for one point at a time: `pixel_x pixel_y arm_x arm_y arm_z`, meters, 6 to 8 points, blank line to finish. `--pairs` reads the file from explore page 42 (`image_points`, `arm_points`, `hand_height_m`; extra fields are ignored). Either way it writes `vision/calibration.json` and prints the max error in centimeters. It should be under 2 cm. Once that file exists, the Hand posted to the controller includes `target` (4 cm closer to the arm base than the palm, at the saved hand height). `python -m vision --fake` uses a stand-in target when the file is missing, so a fake-arm handover can still move to a hand.

## Path and hand height (B7)

`path_clear` is false when a robot-arm detection, or a second hand, crosses the segment from the gripper to the target. The gripper pixel comes from a Perceptron "gripper" detection or from `POST /gripper` with `{"px": [x, y]}`.

Save a clinician's hand height:

```
curl -X POST http://localhost:8001/clinician -H "Content-Type: application/json" -d "{\"name\":\"brandon\",\"hand_height_m\":0.16}"
```

That writes `vision/hand_heights.json`, which is in git. `CLINICIAN` in `.env` picks the active one at start.

## Keys

`PERCEPTRON_API_KEY` and `CAMERA_INDEX` live in `.env`. Optional: `CAMERA_EXPOSURE`, `CAMERA_WB`, `CONTROLLER_URL` (default `http://localhost:8000`), `CLINICIAN`, `VISION_PORT` (8001), `VISION_HOST` (127.0.0.1), `VISION_FAKE=1` (same as `--fake`), `VISION_SETTING` (surgical, used when the controller is down), `VISION_EXTRA_CATEGORIES=0` (stop asking for "robot arm" and "gripper"), and the three detect settings above. The hand model downloads into `vision/models/` (git-ignored) on first real run.

## Tested

Comb on Oct 18, 2026: `.venv/bin/python -m pytest -q vision/test_vision.py` 47 passed (added: detect downscale and box scaling, detect env settings, the 8 s tray-check cutoff, tray check with the controller's aliases, the 127.0.0.1 default bind, fake camera at 30 fps). `python -m vision --fake --port 8150` answered `/health` (29.9 fps, 4 % CPU; before the fix the fake camera spun at 38000 reads/s and a full core), `/vision/hand`, `/tray_check`, `/snapshot`, `/stream?frames=3`, `/lighting`, `/clinician`, `/gripper`, `/clips`, listening on 127.0.0.1 only. `python -m vision.lighting --check-api`: status 200, 1.58 s, 0 detections on a flat gray frame.

Comb on Oct 17, 2026. `python -m vision.test_vision`: 41 tests OK (second comb pass added clip events, tray check `in_slot_of`, tray check staleness, clip paths, clip buffer size).

What passed:

- Fake mode (`python -m vision --fake --port 8011`): `/health` camera true and exposure locked. `/vision/hand` saw an open palm. `GET /tray_check` returned 200 with scalpel, hemostat, and mayo scissors correct. That "ready" result is because the slot boxes are still null, so a detection anywhere counts. `POST /clips/record` wrote `vision/clips/comb-fake/handed_hemostat_1792297259.mp4` and `GET /clips?case_id=comb-fake` listed it. Those files stay local.
- Stream soak, 10 minutes, against the vision process already bound to port 8001: 9577 frames, 0 stream errors, `/health` 200 every 30 seconds. Working set started near 235 MB, dropped to 155 MB by 90 seconds, and stayed between 155.0 and 155.1 MB through 570 seconds.
- Slow detect: a detector that sleeps 1.5 seconds then raises does not block `/vision/hand` or `GET /tray_check`. After it fails, `/vision/tray` and `/tray_check` come back with `stale` true. `GET /tray_check` reads the last tray state. It does not call Perceptron itself.
- Camera read failure: after `read()` starts failing, the grabber thread stays up, the last frame is kept, and `/health` reports `camera` false.
- `--fake --test --all-conditions` writes three CSV rows (bright, normal, dim).

What failed or still needs a person:

- Oct 17: `python -m vision.lighting --check-api` exited 1 (`PERCEPTRON_API_KEY` was empty then; it passed on Oct 18, above). On the port 8001 process the tray state was already `stale: true` while `/health` and `/vision/hand` kept answering.
- That port 8001 process is an older `python -m vision`. `GET /tray_check` and `GET /clips` returned 404 there. Restart it (`python -m vision`) to load this build. The camera was not unplugged for real; the unplug case above is the fake capture.
- Gloves: not a controlled test. MediaPipe's hand landmarker has no glove model. During the soak `/vision/hand` answered, including one `seen: true` read, but nobody held a gloved hand up for it.
- B5 is not done. Slot boxes in the settings files are still null. With the overhead camera mounted, run `python -m vision.mark_slots --setting surgical --live`, then the same for `bench`. Click two corners per item, then the return spot. It writes `vision/marked/<id>.json` for Evan. Do not pass `--write-settings`.
- B8 is not done. The three lamp rows are not in `docs/STATUS.md`. Run `python -m vision.lighting --test --label bright --seconds 10 --csv vision/lighting_tests.csv`, then `normal`, then `dim`, changing the lamp between them. Do not commit the CSV.
