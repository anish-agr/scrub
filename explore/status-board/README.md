# Scrub Status Board (live)

Ready-to-drop-in version of Evan's dashboard (task E2, and the E6 stats/handoff-time parts). Plain HTML + JS, no build step. Swiss nurse-station look from `prototypes/36-scrub-dashboard.html`, restyled per `DESIGN-DE-AI.md`.

Files: `index.html`, `app.js`, `style.css`. Nothing else.

## Run

Against the controller (default `http://localhost:8000`, start it with `python -m controller --fake-arm` from the repo root):

```
python3 -m http.server 8098        # from the repo root
open "http://localhost:8098/explore/status-board/index.html?api=http://localhost:8000"
```

Without the controller (scripted fake events, same shapes; STOP only stops the fake run):

```
open "http://localhost:8098/explore/status-board/index.html?mock=1"
```

URL options: `?api=<controller url>` (default: same origin, so it works unchanged when served by the controller), `?mock=1`, `?cam=<stream url>` (replaces the vision stream URL).

## Drop into dashboard/ (Evan)

```
cp explore/status-board/{index.html,app.js,style.css} dashboard/
```

The controller mounts `dashboard/` at `/`, so `http://localhost:8000/` then uses the same origin automatically. The controller already sends CORS `*`, so the separate-origin run above works too.

## What it does

- Connection: `GET /state` (+ `/setting`, `/stats`, `/events/recent?n=50`) on load and on every reconnect; `WS /events` live; auto-reconnect (1 s, backing off to 5 s). Big LIVE / DISCONNECTED / MOCK STREAM label plus a full-width banner when not live.
- STOP: red button and spacebar (works even when a button has focus). `POST /stop`. If the controller cannot be reached it says "STOP NOT SENT ... Cut arm power." in red instead of failing silently.
- Now: big current step, plain-words subtext, heard text, item, queue, request-to-hand clock, retries, last spoken line, step rail.
- What is out: running count and names (from `GET /state` `out`, refreshed on every event and every 2 s).
- Handoff times: last, median, count, bar per recent handoff (from `handed` / `set_down` events and `/events/recent`; median prefers `/stats`).
- Event log: newest first, deduplicated across reconnects.
- Pickers: setting (`POST /setting`, shows the 409 "busy" message) and lighting (`POST /lighting`).
- Command buttons for the current tray's items, Return, Count, Got it (`POST /command`, `source: "dashboard"`).
- Success tables: `GET /stats`, by item and by lighting (the by-lighting table shows "not reported" until the ledger returns it).
- Camera: `http://localhost:8001/stream`; "CAMERA OFFLINE" panel with a 5 s retry when it is down; button to switch to the sim stream `http://localhost:8002/stream` (choice remembered).

## Tested (controller on :8000 with --fake-arm, Chrome via Playwright)

Live: connect, handover of hemostat and Mayo scissors by curl (step, log, out count, request-to-hand and "said" line updated live), `got_it` release, Space and button both call `POST /stop`, lighting picker, sim stream loads, camera-offline panel (vision on :8001 was down), STOP when the controller is unreachable, no page errors, no horizontal scroll at 1440 and 390. Mock mode: runs the scripted loop, no errors, no horizontal scroll at 390.

Mock-only: the scripted event loop and the fake `/stats` in `?mock=1`. Not verified: the real vision stream (it was not running), real arm, voice, MongoDB ledger stats.

## CONTRACTS vs the controller (the board follows the controller)

1. `GET /stats`: CONTRACTS gives no shape. Without the ledger the controller returns `{source, by_item: {id: {ok, missed}}, median_request_to_hand_s}`: no `by_lighting`, no per-item median. The board accepts several shapes (`ok/missed`, `n/tries/ok`, `median_s`, object or array) and shows "not reported" for by-lighting. Evan's `ledger.stats()` shape needs agreeing with this.
2. `State.out` can hold duplicates (the same item handed twice is listed twice; nothing ever removes it except `return`). Count is the list length.
3. Only `count` events carry `out`; a `handed`/`released` event does not, so the board re-reads `/state` after every event.
4. Sharp items emit `set_down` (not `handed`) with `request_to_hand_s`; the board counts both as a handoff time.
5. `handed` has `say: null` (the arm arriving is silent), so "said" shows the earlier "coming" line.
6. `stopped` step stays until the next command; there is no "clear stop" endpoint. New requests are accepted from `stopped`.
7. `POST /setting` returns 409 when not idle/stopped (not in CONTRACTS) and 404 for unknown ids.
8. `command` events carry `step` (the current step) and extra `accepted`, `reason`, `action`, `source`, `heard` fields, as CONTRACTS allows; a rejected `got_it` has `say: null`.
9. Lighting changes emit no event; the board learns of them from `/state` (within 2 s) or its own click.
10. CONTRACTS says the controller serves `dashboard/` at `/`; it does, with a placeholder until `dashboard/index.html` exists.

No change needed in `controller/`: CORS is already open (`allow_origins=["*"]`).

## What is left

- Confirm the real `ledger.stats()` shape (by-lighting, per-item median) and adjust `normStats()` in `app.js` if needed.
- Check the vision stream URL on the real camera (and that it works as an `<img>`); no tray/hand box overlay is drawn (the stream is shown as is).
- Test on the real arm and at the venue screen; adjust sizes for the room.
- Optional: a "clear stop" button once the controller has such an endpoint.


## Update: Clear stop
The board shows a **Clear stop** button when the step is `stopped` or `error`. It calls `POST /reset` (added to the controller in ca2c7f1): the controller opens the gripper, goes home, clears `out` and says "Reset. Ready.". A 409 means the arm is busy. Checked against the real controller: STOP, then Clear stop, returns to `idle`.
