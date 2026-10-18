# Browser & System QA Report

Generated: Saturday, October 17, 2026  
Test Environment: Windows 11, Python 3.10.11, Chromium / Chrome, Node.js v24.18.0  
Stack under test:
- Controller: `python -m controller` (port 8000, fake arm)
- Vision: `python -m vision --fake` (port 8001)
- Ledger Public Page: `python -m ledger serve` (port 8080)
- Dashboard UI: `http://localhost:8000/`

---

## Summary of Findings

| ID | Issue | Component | Owner | Severity |
| --- | --- | --- | --- | --- |
| QA-01 | Missing Reset / Clear-Stop button locks UI after Stop | `dashboard/` | Evan | Critical |
| QA-02 | Camera stream never displays; stuck on fallback text | `dashboard/` | Evan | High |
| QA-03 | Camera stream URL hardcoded to `localhost:8001` breaks remote and HTTPS use | `dashboard/` | Evan | Medium |
| QA-04 | `vision --fake` synthetic hand has `target: null`, causing handover timeouts | `vision/` | Brandon (Fixed) | High |
| QA-05 | `vision --fake` detector only detects hemostat, breaking other 8 items | `vision/` | Brandon (Fixed) | High |
| QA-06 | `vision --fake` never marks slot empty after pick, causing false grasp failures | `vision/` | Brandon (Fixed) | Medium |
| QA-07 | Ledger `_out()` never clears on Reset or Setting change, polluting public page | `ledger/` | Evan | High |
| QA-08 | Dashboard setting state overwritten by polling; server settings never loaded | `dashboard/` | Evan | Medium |
| QA-09 | Empty Results tables render blank table headers alongside empty note | `dashboard/`, `ledger/` | Evan | Low |
| QA-10 | Dashboard sample mode does not reconnect if opened before controller starts | `dashboard/` | Evan | Low |
| QA-11 | Pressing Spacebar while focused on command buttons triggers emergency stop | `dashboard/` | Evan | Low |
| QA-12 | Scalpel command response announces "Scalpel coming" instead of safe spot | `controller/` | Caiden | Medium |

---

## Detailed Bug Reports

### QA-01: Missing Reset / Clear-Stop button permanently locks dashboard after Stop
- **Component**: `dashboard/`
- **Owner**: Evan
- **Severity**: Critical
- **Steps to reproduce**:
  1. Start `python -m controller` and open `http://localhost:8000/`.
  2. Click the red "STOP" button or press the spacebar.
  3. Observe that the step indicator updates to "Stopped".
  4. Attempt to request an instrument (e.g. click "hemostat") or click "Return".
  5. The controller rejects the command with reason `"stopped: reset first"` ("I'm stopped. Reset me first.").
  6. Look for a way to resume or clear the stop on the dashboard.
- **Observed behavior**:
  There is no reset or clear-stop button anywhere in `dashboard/index.html`. Furthermore, `dashboard/app.js` has no logic to call `POST /reset`. The user is permanently locked in the `stopped` state until a manual `curl -XPOST localhost:8000/reset` is run from a terminal.
- **Expected behavior**:
  Per `controller/README.md` ("until POST /reset (the dashboard's clear-stop button)") and `docs/CONTRACTS.md` (`POST /reset`), the dashboard should display a "Reset" / "Clear Stop" button when the arm is in `stopped` or `error` state.

---

### QA-02: Camera stream never displays; placeholder text shown permanently
- **Component**: `dashboard/`
- **Owner**: Evan
- **Severity**: High
- **Steps to reproduce**:
  1. Run `python -m vision --fake` on port 8001 and `python -m controller` on port 8000.
  2. Verify that `http://localhost:8001/stream` is actively serving valid JPEG frames.
  3. Open `http://localhost:8000/` in Chrome or Edge.
  4. Look at the "Camera" card.
- **Observed behavior**:
  The image element remains hidden (`display: none`), and the placeholder message "Camera stream is not up yet." is shown permanently.
- **Root cause**:
  In `dashboard/app.js`, `onCamera()` attaches a listener: `image.addEventListener("load", show)`. In Chromium and WebKit browsers, MJPEG `multipart/x-mixed-replace` streams do not fire the standard `load` event because the HTTP response does not terminate. Because `.camera-frame img` defaults to `display: none` in `dashboard/style.css`, and `.has-stream` is only added on `load`, the live stream is never made visible.
- **Expected behavior**:
  The dashboard should display the live camera stream when frames arrive, or use an image check that detects streaming data.

---

### QA-03: Hardcoded `localhost:8001` in camera image src breaks external access and HTTPS
- **Component**: `dashboard/`
- **Owner**: Evan
- **Severity**: Medium
- **Steps to reproduce**:
  1. Inspect `dashboard/index.html` line 54: `<img id="camera" alt="Tray camera" src="http://localhost:8001/stream">`.
  2. Access the dashboard from a phone, a teammate laptop, or the Vultr deployment IP/domain.
  3. The browser attempts to load `http://localhost:8001/stream` from the client's own device rather than the host running vision.
  4. If the page is served over HTTPS, the browser blocks the HTTP stream as mixed content.
- **Expected behavior**:
  The image `src` should be dynamically set using `location.hostname` (e.g. `http://${location.hostname}:8001/stream`) or proxied through the controller.

---

### QA-04: `vision --fake` synthetic hand has `target: null`, causing handovers to time out and dump items at the safe spot
- **Component**: `vision/`
- **Owner**: Brandon
- **Severity**: High
- **Steps to reproduce**:
  1. Start `python -m controller` and `python -m vision --fake`.
  2. Send a handover command for "hemostat" (via dashboard button or curl).
  3. The arm picks the hemostat, lifts to carry, and enters `moving_to_hand`.
  4. The controller announces: "Hand open, please."
  5. The controller waits for 10 seconds.
  6. The controller announces: "No hand. Hemostat is at the safe spot." and sets the hemostat at the safe spot.
- **Root cause**:
  In `vision/service.py`, `publish_hand()` computes `target = palm_target(runtime.calibration, palm, height_m)`. In `vision/calibrate.py`, `palm_target()` returns `None` if `calibration` or `calibration.homography` is missing. Because `vision/calibration.json` does not exist in the repo, the `Hand` message always has `target: null`.
  In `controller/core.py`, `_tracking()` sees Hand packets arriving and waits for `_hand_ready()`, which rejects any Hand where `target` is not a 3-element list of floats. It times out after 10 seconds and diverts to the safe spot.
- **Expected behavior**:
  In `--fake` mode, `vision` should supply synthetic calibration points or default hand target coordinates (e.g. `[0.22, -0.10, 0.18]`) so simulated end-to-end handovers can complete without physical calibration.
- **Status**: Fixed. Added `synthetic_calibration()` to `vision/calibrate.py` and enabled `fake_calibration=True` in `--fake` mode, providing `[0.22, -0.10, 0.18]` handoff target.

---

### QA-05: `vision --fake` scripted detector only detects "hemostat", breaking other 8 instruments
- **Component**: `vision/`
- **Owner**: Brandon
- **Severity**: High
- **Steps to reproduce**:
  1. Start `python -m controller` and `python -m vision --fake`.
  2. Switch the dashboard setting to "Dental office" or "Robotics bench", or select "scalpel" or "mayo scissors" on the Operating room tray.
  3. Click any instrument other than hemostat (e.g. "scalpel", "mouth mirror", "wire cutters").
  4. The controller immediately rejects the request: "I don't see the <item> on the tray."
- **Root cause**:
  In `vision/__main__.py` lines 27-40, `_ScriptedDetector.detect()` hardcodes a single detection:
  `[{"mention": "hemostat", "point_box": ...}]`.
  All other items across all three settings are reported as `present: false`.
- **Expected behavior**:
  In `--fake` mode, `_ScriptedDetector` should return detections for the items belonging to the currently active setting, allowing full testing of all 9 instruments.
- **Status**: Fixed. Implemented `FakeDetector` in `vision/tray.py` which emits detections for all active items across all three settings (surgical, dental, and bench).

---

### QA-06: `vision --fake` never marks slot empty after a pick, triggering false grasp check retries
- **Component**: `vision/` (and `controller/`)
- **Owner**: Brandon (vision), Caiden (controller)
- **Severity**: Medium
- **Steps to reproduce**:
  1. Start `python -m controller` and `python -m vision --fake`.
  2. Trigger a handover of "hemostat".
  3. Observe the event log after the first pick attempt.
  4. The controller announces: "Missed the hemostat, trying again." and executes a second pick attempt.
- **Root cause**:
  `_ScriptedDetector` always reports `hemostat` present in its slot. After picking, `controller/core.py` checks `_lifted()`, which looks at whether the slot is empty in fresh TrayState messages. Because fake vision still reports the hemostat in the slot, `_lifted()` returns `False`, causing the controller to assume the grasp failed and trigger a retry.
- **Expected behavior**:
  Fake vision should simulate slot depletion when an item is picked, or the fake detector should accept simulated scene state.
- **Status**: Fixed. `FakeDetector` checks controller state (`GET /state`) during picks and marks picked items as depleted from their slots, allowing `_lifted()` checks to pass cleanly on the first attempt. Also supports `empty_slot()`, `fill_slot()`, and `set_return_spot()`.

---

### QA-07: Ledger `_out()` never clears items on Reset or Setting change, showing stale items on the Public Page
- **Component**: `ledger/`
- **Owner**: Evan
- **Severity**: High
- **Steps to reproduce**:
  1. Start `python -m ledger serve` and open `http://localhost:8080/`.
  2. Check the "Out" instruments list.
  3. Observe that items from past runs (`scalpel`, `mayo scissors`, `hemostat`) are listed as currently out.
  4. In the controller, call `POST /reset` or `POST /setting` (which resets active out items to `[]`).
  5. Refresh `http://localhost:8080/`. The public page still displays all three items as out.
- **Root cause**:
  In `ledger/__init__.py`, `_out(events)` aggregates all historical events from `buffer.jsonl` (and MongoDB). It only removes an item when a `returned` event occurs for that specific item. It ignores `reset` events and setting transitions, so any item ever taken out in past runs remains permanently marked as out.
- **Expected behavior**:
  `_out()` should reset its list when a `reset` event or setting change occurs, or synchronize with the latest state `out` array.

---

### QA-08: Dashboard setting selection is overwritten by state polling; server settings never loaded
- **Component**: `dashboard/`
- **Owner**: Evan
- **Severity**: Medium
- **Steps to reproduce**:
  1. Open `http://localhost:8000/`.
  2. Check `dashboard/app.js` lines 174-187 (`applyState`) and 552-568 (`connect`).
  3. `connect()` never fetches `GET /setting`. It populates item buttons using the static hardcoded `SETTINGS` object.
  4. Every 400 ms, `pollState()` fetches `/state` and calls `applyState()`, which executes `model.catalog = SETTINGS[state.setting]`.
  5. If `changeSetting()` receives updated aliases or item names from the server, they are wiped out on the next 400 ms poll.
  6. If a setting change fails (e.g. arm is busy returning 409), the dropdown quietly reverts back to the old setting on the next poll without displaying an error to the user.
- **Expected behavior**:
  `GET /setting` should be fetched on startup and setting changes to display server-provided names, and setting switch errors should be communicated clearly in the UI.

---

### QA-09: Empty Results tables render blank headers and borders alongside "No measured trials yet" note
- **Component**: `dashboard/`, `ledger/`
- **Owner**: Evan
- **Severity**: Low / Cosmetic
- **Steps to reproduce**:
  1. Open `http://localhost:8000/` or `http://localhost:8080/` when no trial runs have been logged (`report.by_item` and `report.by_lighting` are empty).
  2. Scroll to the "Results" section.
  3. Notice that table captions ("By item", "By lighting") and the column headers ("Item \| Trials \| Success \| Median") are displayed with empty bodies and horizontal borders, with "No measured trials yet." rendered underneath.
- **Root cause**:
  In both `dashboard/style.css` and `ledger/public/style.css`, `.tables.has-rows .empty-note` hides the note when rows exist, but there is no CSS rule hiding `.table-wrap` when `.has-rows` is absent.
- **Expected behavior**:
  When there are no rows, `.table-wrap` should be hidden so only the "No measured trials yet." note is displayed.

---

### QA-10: Dashboard sample fallback never retries connecting if opened before controller starts
- **Component**: `dashboard/`
- **Owner**: Evan
- **Severity**: Low
- **Steps to reproduce**:
  1. Open `http://localhost:8000/` in a browser before launching `python -m controller`.
  2. The dashboard displays the sample handover banner: "Controller is not running. This is a sample handover...".
  3. Now start `python -m controller`.
  4. Wait several seconds.
- **Observed behavior**:
  The dashboard stays in sample mode indefinitely. It never retries `fetch("/state")` or attempts to establish a WebSocket connection.
- **Expected behavior**:
  When offline / sample mode is active, the dashboard should poll `/state` periodically (e.g. every 2 seconds) and transition to live mode once the controller responds.

---

### QA-11: Pressing Spacebar while focused on command buttons triggers emergency stop
- **Component**: `dashboard/`
- **Owner**: Evan
- **Severity**: Low / Usability
- **Steps to reproduce**:
  1. Open `http://localhost:8000/`.
  2. Use the Tab key to navigate focus to any command button (e.g. "hemostat" or "got_it").
  3. Press Spacebar (the standard keyboard key to activate HTML buttons).
  4. The arm triggers an emergency stop (`stopArm()`) instead of clicking the focused button.
- **Root cause**:
  In `dashboard/app.js` line 546:
  `if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;`
  The check omits `BUTTON`.
- **Expected behavior**:
  If the active element is a `BUTTON`, Spacebar should activate the button rather than triggering `stopArm()`.

---

### QA-12: Scalpel handover announces "Scalpel coming" instead of sharps announcement
- **Component**: `controller/`
- **Owner**: Caiden
- **Severity**: Medium
- **Steps to reproduce**:
  1. On the dashboard or via curl, send `{"action": "handover", "item": "scalpel"}`.
  2. The controller's HTTP response is `{"accepted": true, "say": "Scalpel coming."}`.
  3. In an operating room, scalpels are sharps and must never be announced as "coming" to a clinician's hand.
- **Root cause**:
  In `controller/core.py` line 169, `_check()` returns `lines.coming(it["name"])` without checking `it.get("sharp")`. It should return a line reflecting safe spot delivery (e.g. "Scalpel to safe spot.").
- **Expected behavior**:
  The initial command response should reflect the sharp status of the instrument.
