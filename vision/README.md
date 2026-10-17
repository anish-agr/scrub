# vision

Owner: Brandon. Tasks B1 to B8 in `docs/TASKS.md`.

One process owns the overhead camera (locked exposure and white balance). It runs the MediaPipe hand tracker (POST a Hand to the controller about 10 times a second) and the Perceptron tray perception (POST a TrayState about once a second). It serves an MJPEG stream with boxes and the palm dot at `http://localhost:8001/stream`. `calibrate.py` fits the camera-to-arm mapping into `calibration.json`.

Run: `python -m vision`.

Done when: lifting an item off the tray shows on the dashboard within about 2 seconds, and the palm dot's arm target is within about 2 cm.
