# dashboard

Owner: Evan. Tasks E2, E6 in `docs/TASKS.md`.

One static page (plain HTML and JS, no build step), served by the controller at `/`. Live camera from `http://<this host>:8001/stream`, the current step, the current lighting, what's out, the event log, setting and lighting pickers, a stop button, a reset button after a stop, spacebar as stop, handoff times, success tables from `GET /stats`. If vision's tray is `stale` or older than 3 seconds, a "Vision stale" line shows.

Files: `index.html`, `app.js`, `style.css`.

The page calls the controller on the same origin: `GET /state`, `GET /setting`, `WS /events`, `POST /command`, `POST /stop`, `POST /reset`, `POST /setting`, `POST /lighting`, `GET /stats`. It reads `GET /vision` for the stale warning (the tray's `stale` flag, or a reading older than 3 seconds), and falls back to `http://<this host>:8001/vision/tray`. `/snapshot` on that port says whether the camera is up. If `/state` does not answer, it shows a sample hemostat handover and keeps trying until the controller is up.

Run with the controller:

```
python -m controller --fake-arm
```

Then open http://localhost:8000/. A handover command (a button on the page, or `POST /command`) moves the step, the event log, what's out, and the handoff time. The results tables load from `GET /stats`, which should return `ledger.stats()` unchanged.

Done when: a fake-arm handover shows live, and a judge can follow a whole request on it.
