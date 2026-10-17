# dashboard

Owner: Evan. Tasks E2, E6 in `docs/TASKS.md`.

One static page (plain HTML and JS, no build step), served by the controller at `/`. Live camera from `http://localhost:8001/stream`, the current step, what's out, the event log, setting and lighting pickers, a stop button, spacebar as stop, handoff times, success tables from `GET /stats`.

Files: `index.html`, `app.js`, `style.css`.

The page calls the controller on the same origin: `GET /state`, `WS /events`, `POST /command`, `POST /stop`, `POST /setting`, `POST /lighting`. If `/state` does not answer, it shows a sample hemostat handover and plays commands locally.

Run with the controller:

```
python -m controller --fake-arm
```

Then open http://localhost:8000/. A handover command (a button on the page, or `POST /command`) moves the step, the event log, what's out, and the handoff time.

Done when: a fake-arm handover shows live, and a judge can follow a whole request on it.
