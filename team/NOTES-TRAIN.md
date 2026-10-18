# Notes from Chat A (training) to Chat C (smart pick) and Chat D (data)

Newest first. Facts only, each with the time it was checked.

## Oct 18, 2:20 AM
- Perceptron: `successful_jobs_per_team` 5, 0 jobs, 0 deployments (`python -m arm.train capabilities`, `deployments`). Steps 1000 only, horizon 30, stride 15, deadline 400 ms. Shared GPU budget 64.8 of 1200 h used.
- `.env`: `PERCEPTRON_DEPLOYMENT_ID` is now empty (it held a wrong value); `SO101_PORT=/dev/tty.usbmodem5C821089781` added. Until a deployment exists there is no `--skills model`.
- `~/scrub-dataset` holds 14 `pick the spatula` episodes (station, 1:39 to 2:04 AM). Not training data. Surgical data goes in a new root, `~/scrub-surgical`.
- Cameras at 2:04 AM from the station: side (C920) 29.5 fps, wrist (icspring) 22.2 fps. The wrist is under the 29 fps gate. Probe: `.venv/bin/python explore/camera_fps.py icspring` (needs the camera free).

## Oct 18, 2:40 AM
- Gates are in: `python -m arm.train preflight <root>` (local_check + qa + qa_video) prints `PREFLIGHT PASS` or `PREFLIGHT FAIL` with reasons; `pipeline` runs it before any upload. The station only accepts settings task strings and flags re-record episodes live.
- Wrist camera: 22.6 fps in every OpenCV mode and through ffmpeg (640x480@30 UYVY asked), brightness 147, on a USB 2.0 hub shared with both arm buses and the C920. Not a light problem. Next test: a direct Mac port. If it stays at 22.6, run 1 trains with `SCRUB_ACCEPT_CAMERA_FPS=wrist=22` and we say the wrist stream repeats frames.
- Run 1 data root: `~/scrub-surgical` (empty at 2:40). Chat C: no deployment until run 1 finishes; plan on taught or scripted picks until then.
