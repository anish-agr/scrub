# dashboard

Owner: Evan. Tasks E2, E6 in `team/LEFT.md`.

One static page (plain HTML and JS, no build step), served by the controller at `/`. Live camera from `http://<this host>:8001/stream`, the current step, the current lighting, what's out, the event log, setting and lighting pickers, a stop button, a reset button after a stop, spacebar as stop, handoff times, success tables from `GET /stats`. If vision's tray is `stale` or older than 3 seconds, a "Vision stale" line shows.

Files: `index.html`, `app.js`, `style.css`, and the tablet view `tablet.html`, `tablet.js`, `tablet.css` (big step, what is out, Stop and Reset, at `/tablet.html`).

The step line and event log tag each pick or return as "model" or "taught skill" when the event carries `skill_source`. "Likely next" comes from `next_likely` in `GET /stats`. Links to Cases, Series and Memory point at the ledger page on port 8080 of this host (`?ledger=URL` overrides it).

The page calls the controller on the same origin: `GET /state`, `GET /setting`, `WS /events`, `POST /command`, `POST /stop`, `POST /reset`, `POST /setting`, `POST /lighting`, `GET /stats`. It reads `GET /vision` for the stale warning (the tray's `stale` flag, or a reading older than 3 seconds), and falls back to `http://<this host>:8001/vision/tray`. `/snapshot` on that port says whether the camera is up. If `/state` does not answer, it shows a sample hemostat handover and keeps trying until the controller is up.

Run with the controller:

```
python -m controller --fake-arm
```

Then open http://localhost:8000/. A handover command (a button on the page, or `POST /command`) moves the step, the event log, what's out, and the handoff time. The results tables load from `GET /stats`, which should return `ledger.stats()` unchanged.

Done when: a fake-arm handover shows live, and a judge can follow a whole request on it.

## Tested

Saturday Oct 17, with `python -m controller --fake-arm` and `python -m vision --fake` already up.

- Dashboard at http://127.0.0.1:8000/, desktop and a 390px phone width. No horizontal overflow. The picker listed Operating room and Robotics bench (since Oct 18 it lists only Operating room). Dental stays in `settings/dental.json` and is not in the picker. The page showed Idle, hemostat out, the handoff seconds, and the success table. No console errors.
- Count from the page appended a count line to the log.
- Closing the event socket changed the pill to "reconnecting". About a second later it was "live" again on a new socket.
- A bad `GET /stats` body and an empty body did not throw. The empty body shows "No measured trials yet" and hides the table headers.
- Tablet at http://127.0.0.1:8000/tablet.html on a 390px width. Stop stays on screen. Reset and Stop span the width. No console errors.
- `settings/surgical.json`, `settings/bench.json`, and `settings/dental.json` parse. Only the scalpel is sharp.
