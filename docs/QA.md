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

| ID | Issue | Component | Owner | Severity | Status |
| --- | --- | --- | --- | --- | --- |
| QA-01 | Missing Reset / Clear-Stop button locks UI after Stop | `dashboard/` | Evan | Critical | Fixed |
| QA-02 | Camera stream never displays; stuck on fallback text | `dashboard/` | Evan | High | Fixed |
| QA-03 | Camera stream URL hardcoded to `localhost:8001` breaks remote and HTTPS use | `dashboard/` | Evan | Medium | Fixed |
| QA-04 | `vision --fake` synthetic hand has `target: null`, causing handover timeouts | `vision/` | Brandon | High | Fixed |
| QA-05 | `vision --fake` detector only detects hemostat, breaking other 8 items | `vision/` | Brandon | High | Fixed |
| QA-06 | `vision --fake` never marks slot empty after pick, causing false grasp failures | `vision/` | Brandon | Medium | Fixed |
| QA-07 | Ledger `_out()` never clears on Reset or Setting change, polluting public page | `ledger/` | Evan | High | Fixed |
| QA-08 | Dashboard setting state overwritten by polling; server settings never loaded | `dashboard/` | Evan | Medium | Fixed |
| QA-09 | Empty Results tables render blank table headers alongside empty note | `dashboard/`, `ledger/` | Evan | Low | Fixed |
| QA-10 | Dashboard sample mode does not reconnect if opened before controller starts | `dashboard/` | Evan | Low | Fixed |
| QA-11 | Pressing Spacebar while focused on command buttons triggers emergency stop | `dashboard/` | Evan | Low | Fixed |
| QA-12 | Scalpel command response announces "Scalpel coming" instead of safe spot | `controller/` | Caiden | Medium | Fixed |
| QA-13 | `voice` test script uses POSIX environment assignment syntax failing on Windows | `voice/` | Caiden | Medium | Fixed |
| QA-14 | `SimArm.run_skill` fails on hyphenated instrument names (`needle-nose pliers`) | `sim/` | Caiden | High | Fixed |
| QA-15 | Controller setting switch does not notify sim arm, parking bench items under table | `controller/`, `sim/` | Caiden | High | Fixed |
| QA-16 | `FakeDetector` return-spot desync overwrites controller return spot | `vision/` | Brandon | Medium | Fixed |

---

## Detailed Bug Reports

### QA-01: Missing Reset / Clear-Stop button permanently locks dashboard after Stop
- **Status:** Fixed. Browser check Oct 17: Stop shows Reset, Reset calls `POST /reset`, the step returns to Idle, and Reset hides again.
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
- **Status:** Fixed. Browser check Oct 17 with `python -m vision --fake`: the camera card shows the live frame (slot boxes and the palm dot). A snapshot probe turns the stream on, because the MJPEG response never fires `load`.
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
- **Status:** Fixed. The image has no hardcoded host. Opened at `http://127.0.0.1:8000/`, the stream src was `http://127.0.0.1:8001/stream`.
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
- **Status:** Fixed. Browser check Oct 17: after a hemostat handover the public page listed hemostat. Switching trays cleared it to "Nothing out" on both the dashboard and http://127.0.0.1:8080/. The count follows the newest event's `out` list.
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
- **Status:** Fixed. Browser check Oct 17: choosing Dental office loads mouth mirror, explorer, and cotton pliers from `GET /setting`. Switching trays while the arm is waiting for a pull shows "Could not switch trays" and the picker returns to the current tray.
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
- **Status:** Fixed. Browser check Oct 17: with no measured trials, both pages show "No measured trials yet." and the empty tables are `display: none`.
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
- **Status:** Fixed. Browser check Oct 17: the first `/state` request was forced to fail. The page showed "Controller is not running. This is a sample handover." and then returned to live on its own.
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
- **Status:** Fixed. Browser check Oct 17: Space on the hemostat button left the arm idle. Space on the page body stopped it. Reset cleared that stop.
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
- **Status:** Fixed. `controller/core.py` now uses `lines.coming_sharp` for sharp items, so the scalpel is announced as going to the safe spot. A test is in `controller/test_flows.py`.
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
- **Status**: Fixed. `controller/core.py` returns `lines.safe_spot(it["name"])` ("Scalpel to the safe spot.") when `it.get("sharp")` is true. Verified in live voice test.

---

### QA-13: `voice` test script uses POSIX environment assignment syntax failing on Windows
- **Component**: `voice/`
- **Owner**: Caiden
- **Severity**: Medium
- **Status**: Fixed.
- **Steps to reproduce**:
  1. Open a PowerShell terminal in `voice/`.
  2. Run `npm test`.
  3. The command fails with: `'VOICE_NO_KEYS' is not recognized as an internal or external command, operable program or batch file.`
- **Root cause**:
  In `voice/package.json`, `"test": "VOICE_NO_KEYS=1 tsx scripts/test.ts"`. Windows command shells (`cmd.exe`) do not support POSIX prefix environment variable syntax.
- **Expected behavior**:
  `npm test` should execute cross-platform across macOS, Linux, and Windows.
- **Resolution**:
  Set `process.env.VOICE_NO_KEYS = "1"` directly at the top of `voice/scripts/test.ts` and simplified `voice/package.json` test script to `"tsx scripts/test.ts"`. Verified `npm test` runs and passes on Windows.

---

### QA-14: `SimArm.run_skill` fails on hyphenated instrument names (`needle-nose pliers`)
- **Component**: `sim/`
- **Owner**: Caiden
- **Severity**: High
- **Status**: Fixed.
- **Steps to reproduce**:
  1. Start `python -m controller --sim-arm --setting bench`.
  2. Request `needle-nose pliers` via voice or `/command`: `{"action": "handover", "item": "needle_nose_pliers"}`.
  3. The controller instructs `run_skill("pick the needle-nose pliers")`.
  4. The pick attempt immediately returns `False`, causing the controller to announce: "Missed the needle-nose pliers, trying again."
- **Root cause**:
  In `sim/sim_arm.py` line 189:
  `verb, item = m.group(1), m.group(2).replace(" ", "_")`
  Only spaces were replaced with underscores, leaving hyphens intact (`needle-nose_pliers`). Because the item id in `settings/bench.json` and `sim/layout.json` is `needle_nose_pliers`, `slot_position()` returned `None`.
- **Expected behavior**:
  `run_skill()` should normalize hyphens to underscores as well as spaces (`.replace("-", "_").replace(" ", "_")`).
- **Resolution**:
  Added `.replace("-", "_")` to item name parsing in `sim/sim_arm.py`. Handover of `needle_nose_pliers` now picks cleanly on the first attempt in simulation.

---

### QA-15: Controller setting switch does not notify sim arm, parking bench items under table
- **Component**: `controller/`, `sim/`
- **Owner**: Caiden
- **Severity**: High
- **Status**: Fixed.
- **Steps to reproduce**:
  1. Start `python -m controller --sim-arm`.
  2. Switch to bench tray: `POST /setting {"setting": "bench"}`.
  3. Request any bench instrument (`needle_nose_pliers`, `wire_cutters`, `hex_key`).
  4. The arm cannot locate or pick the instrument.
- **Root cause**:
  `controller/core.py:set_setting()` only updated the controller's internal setting structure; it never notified the connected `arm` instance of the setting change. In `sim/layout.json`, `setting` remained `"surgical"`, which kept all non-surgical items parked below the table (`PARK = (0.0, 0.0, -1.0)`).
- **Expected behavior**:
  Switching settings should inform the arm of the new setting so relevant mocap bodies and slot positions are loaded into the active scene.
- **Resolution**:
  Added `SimArm.set_setting(setting_id)` to update `layout["setting"]` and reload the scene. Updated `controller/core.py:set_setting()` to invoke `self.arm.set_setting(setting_id)` if supported. Also made `sim/scene.py:slot_position()` fall back across all configured setting item lists.

---

### QA-16: `FakeDetector` return-spot desync overwrites controller return spot
- **Component**: `vision/`
- **Owner**: Brandon
- **Severity**: Medium
- **Status**: Fixed.
- **Steps to reproduce**:
  1. Start `python -m controller --sim-arm` and `python -m vision --fake`.
  2. Place an item into the return spot (e.g. `POST /sim/return_spot {"item": "hemostat"}`).
  3. Wait 2 seconds for auto-return.
  4. Auto-return never triggers because the return spot is repeatedly wiped out.
- **Root cause**:
  `SimVision` (in the controller process) detected the return spot and posted `return_spot: {"item": "hemostat"}`. However, `FakeDetector` (in `vision --fake`) polled `/state`, did not track the return spot, and posted `return_spot: {"item": null}` every 1 second, resetting the controller's `_spot_since` timer. Additionally, returned items were still reported as present in their tray slots.
- **Expected behavior**:
  `FakeDetector` should synchronize return spot occupancy with the controller's `/vision` feed and exclude items currently in the return spot from tray slot detections.
- **Resolution**:
  Updated `FakeDetector._sync_with_controller()` in `vision/tray.py` to check `/vision` for existing return spot items when not overridden locally, and excluded return-spot items from tray slot detections. Auto-return now triggers reliably in 2 seconds.
