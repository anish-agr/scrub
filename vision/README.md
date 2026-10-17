# vision

Owner: Brandon. Tasks B1 to B8 in `docs/TASKS.md`.

One process owns the overhead camera (locked exposure and white balance). It runs the MediaPipe hand tracker (POST a Hand to the controller about 10 times a second) and the Perceptron tray perception (POST a TrayState about once a second). It serves an MJPEG stream with boxes and the palm dot at `http://localhost:8001/stream`. `calibrate.py` fits the camera-to-arm mapping into `calibration.json`.

Run from the repo root:

```
python -m vision              # camera CAMERA_INDEX from .env, preview at http://localhost:8001/
python -m vision --fake      # no camera: synthetic tray, open palm, locked-exposure stand-in
python -m vision.test_vision # fake-input checks for B1 to B7
```

The controller does not have to be running. The first failed POST to `/vision/hand` or `/vision/tray` is logged once.

## What each file does

| File | Task |
| --- | --- |
| `camera.py` | Opens the camera, turns off auto exposure and auto white balance, one grabber thread |
| `hand.py` | MediaPipe Tasks hand landmarker, palm center, open-palm check |
| `tray.py` | `POST https://api.perceptron.inc/v1/detect`, maps boxes onto slots. See `docs/PERCEPTRON.md` |
| `app.py` | Preview page, `/stream`, `/snapshot` |
| `mark_slots.py` | Click slot corners, print boxes for Evan |
| `calibrate.py` | Homography from pixel points to arm x,y. Target is 4 cm short of the palm |
| `lighting.py` | Mean brightness for the bright / normal / dim check |
| `hand_heights.json` | Default hand height 0.18 m, plus one height per clinician |

`target` stays null until `vision/calibration.json` exists. The API returns no confidence, so a fresh TrayState uses `1.0`. A failed call keeps the last good state and sets `stale` true (optional field).

## Lamp check (B1)

Open `http://localhost:8001/` and turn a lamp on. The picture should brighten and stay there. It should not flash and settle back, which is what auto exposure does. Optional numbers: `python -m vision.lighting --label bright` (and `normal`, `dim`).

On the Acer FHD laptop camera, `CAP_PROP_AUTO_EXPOSURE` reads back `-1` for every setting. Setting `CAP_PROP_EXPOSURE` does hold: exposure `-8` stayed near mean brightness 13, and `-1` stayed near 148, with no pull back toward the middle. The default exposure is `-6`. Override it with `CAMERA_EXPOSURE` and `CAMERA_WB` in `.env` if the overhead camera is too dark or too bright.

## Marking slots (B5)

With the camera mounted, save one frame (`/snapshot`) and click two corners per item, then the return spot:

```
python -m vision.mark_slots --setting surgical --image tray.jpg
```

Or pass corners without a window: `--clicks x,y,x,y,...`. The command prints the boxes. Send that printout to Evan for `settings/<id>.json`. Repeat for `dental` and `bench`.

## Calibration (B6)

At the arm, record 6 to 8 gripper positions as pixel and arm meters:

```
python -m vision.calibrate
```

Each line is `pixel_x pixel_y arm_x arm_y arm_z`. A blank line writes `vision/calibration.json` and prints the max error. It should be under 2 cm. The handoff target is 4 cm closer to the arm base than the palm, at the saved hand height.

## Path and hand height (B7)

`path_clear` is false when a robot-arm detection, or a second hand, crosses the segment from the gripper to the target. The gripper pixel comes from a Perceptron "gripper" detection or from `POST /gripper` with `{"px": [x, y]}`.

Save a clinician's hand height:

```
curl -X POST http://localhost:8001/clinician -H "Content-Type: application/json" -d "{\"name\":\"brandon\",\"hand_height_m\":0.16}"
```

## Keys

`PERCEPTRON_API_KEY` and `CAMERA_INDEX` live in `.env`. Optional: `CAMERA_EXPOSURE`, `CAMERA_WB`, `CONTROLLER_URL`, `CLINICIAN`. The hand model downloads into `vision/models/` (git-ignored) on first real run.
