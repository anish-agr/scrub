# Visual and Functional Page QA Report

Tested on branch `origin/anish/local-main-0050` (detached HEAD) because `design/scrub.css` is not on `main` yet.
Test date: October 18, 2026.
Environment: Windows 11, Google Chrome via Playwright automation, viewports 1440x900 and 390x844.
Stack under test: `python -m controller.run_all backup --offline --loop --pause 2 --ledger --no-open` (controller on port 8000 with sim arm, sim viewer on port 8002, ledger on port 8080, and external Vultr host `144.202.95.111`).
All 26 screenshots saved to `data/qa/agy/` (git-ignored).

---

## Executive Summary

| Page | URL | Viewport 1440px | Viewport 390px | Live Updates | Stop Button | Spacebar Stop | Console Errors | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Dashboard (Paper) | `http://localhost:8000/` | PASS | PASS (no overflow) | PASS | Stops arm, no banner | Stops arm, no banner | 4 (8001 connection refused) | FAIL |
| Dashboard (Monitor) | `http://localhost:8000/?theme=monitor` | PASS | PASS (no overflow) | PASS | Stops arm, no banner | Stops arm, no banner | 3 (8001 connection refused) | FAIL |
| Dashboard Tablet | `http://localhost:8000/tablet.html` | PASS | PASS (no overflow) | PASS | Stops arm, no banner | Stops arm, no banner | Clean (0) | FAIL |
| Nurse Console | `http://localhost:8000/nurse` | FAIL (font / bg bug) | PASS (no overflow) | PASS | Stops arm, no banner | Stops arm, no banner | 6 (8001 stream & 404s) | FAIL |
| Demo / Judge Console | `http://localhost:8000/demo` | FAIL (white bg / font bug) | PASS (no overflow) | PASS | Latches stop, no banner | Latches stop, no banner | Clean (0) | FAIL |
| Sim Viewer | `http://localhost:8002/web/viewer.html` | PASS | PASS (no overflow) | PASS | Red STOP bar present | Stops simulation | Clean (0) | PASS |
| Ledger Judge Page | `http://localhost:8080/` | PASS | PASS (no overflow) | Static report | N/A | N/A | Clean (0) | PASS |
| Ledger Case List | `http://localhost:8080/cases.html` | PASS | PASS (no overflow) | Static register | N/A | N/A | Clean (0) | PASS |
| Ledger Case Replay | `http://localhost:8080/case.html?id=...` | PASS | PASS (no overflow) | Static replay | N/A | N/A | Clean (0) | PASS |
| Ledger Series Page | `http://localhost:8080/series.html` | PASS | PASS (no overflow) | Static minutes | N/A | N/A | Clean (0) | PASS |
| Ledger Memory Page | `http://localhost:8080/memory.html` | PASS | PASS (no overflow) | Static notes | N/A | N/A | Clean (0) | PASS |
| Ledger Table Card | `http://localhost:8080/card.html` | PASS | PASS (no overflow) | Static QR | N/A | N/A | Clean (0) | FAIL (127.0.0.1 in QR) |
| Vultr Public Page | `http://144.202.95.111/` | FAIL (outdated design) | PASS (no overflow) | Live stats API | N/A | N/A | Clean (0) | FAIL (pre-restyle build) |

---

## 1. Dashboard (`http://localhost:8000/`)

### Status: FAIL

### Ranked Problems (Judge Priority)
1. **No red STOP banner shown when arm is stopped**
   - File: `dashboard/app.js`, function `render()` and function `stopArm()`
   - Element: `<p id="banner" class="banner warning" role="status" hidden>` in `dashboard/index.html` (line 52)
   - Problem: When the user clicks the STOP button (`#stop`) or hits the Spacebar, the controller stops and `#step` changes to `Stopped` in red text. But `#banner` remains hidden. `docs/DESIGN-SYSTEM.md` Section 3 mandates: "Banner: Full-width red bar for STOPPED / ARM FROZEN / VISION STALE (amber)". In `dashboard/app.js`, `#banner` is only populated and unhidden during offline demo sample mode.
   - Fix: In `dashboard/app.js`, when `model.step === "stopped"`, remove the `hidden` attribute from `#banner`, set its text to `ARM STOPPED. A PERSON MUST RESET.`, and set class `banner stop`. Hide it when `model.step !== "stopped"`.
2. **Default theme is dark monitor instead of warm paper**
   - File: `dashboard/index.html` (line 3)
   - Element: `<html lang="en" data-theme="monitor">`
   - Problem: Per `docs/DESIGN-SYSTEM.md` Section 1, the default dashboard should use the `paper` theme (`#ece8dd`), reserving `monitor` for fullscreen and tablet modes. `index.html` line 3 hardcodes `data-theme="monitor"`, forcing the page to load with near-black `#0f1110` background by default.
   - Fix: Change line 3 to `<html lang="en" data-theme="paper">`. Let query string `?theme=monitor` or fullscreen toggle switch to monitor.
3. **Console connection refused errors for snapshot**
   - File: `dashboard/app.js` (line 673)
   - Element: `pollSnapshot()` calling `http://localhost:8001/snapshot`
   - Problem: In sim mode (`run_all backup`), vision runs in-process (`sim_vision`). There is no separate HTTP vision server running on port 8001. The dashboard polls `localhost:8001/snapshot` every 3 seconds, logging repeated `net::ERR_CONNECTION_REFUSED` errors in the developer console.
   - Fix: In `dashboard/app.js`, check if vision is disabled or back off polling if the endpoint returns connection errors.

### Detailed Checks
- **Console errors**: 4 connection refused errors for port 8001.
- **Live numbers update**: PASS. The step (`Picking`, `Checking grasp`, `Moving to hand`, `Releasing`, `Homing`, `Idle`), event log, and queue update live via WebSocket during the backup run loop.
- **STOP button**: Button `#stop` calls `POST /stop`. Controller stops. `#reset` unhides. Red banner does not show.
- **Spacebar**: Spacebar keydown calls `POST /stop`. Controller stops. Red banner does not show.
- **Design tokens**: Font is Archivo and IBM Plex Mono. 0 box shadows, 0 gradients, 0-2px border radius. Tabular numbers present.
- **Sideways scroll at 390px**: PASS. `docWidth=390, winWidth=390`. Responsive layout wraps cleanly.
- **Copy and text**: PASS. Voice of the room used throughout. No em dashes, no buzzwords, no false claims.

---

## 2. Dashboard Monitor Mode (`http://localhost:8000/?theme=monitor`)

### Status: FAIL

### Ranked Problems (Judge Priority)
1. **No red STOP banner shown when arm is stopped**
   - File: `dashboard/app.js`, function `render()`
   - Element: `<p id="banner">` in `dashboard/index.html`
   - Problem: Pressing STOP or Spacebar stops the arm, but the required full-width red alarm banner remains hidden.
   - Fix: Show `#banner` with red background and text `ARM STOPPED` when `model.step === "stopped"`.
2. **Console errors from missing port 8001**
   - File: `dashboard/app.js` (line 673)
   - Problem: `net::ERR_CONNECTION_REFUSED` logged on snapshot poll when standalone vision is off.
   - Fix: Catch and silence or skip snapshot polling when running against sim controller.

### Detailed Checks
- **Console errors**: 3 snapshot connection errors.
- **Live numbers update**: PASS. State changes and event timestamps stream in real time.
- **STOP button & Spacebar**: Both trigger stop. `#step` turns red. Red banner missing.
- **Design tokens**: PASS. Dark theme tokens `--paper:#0f1110`, Archivo font, IBM Plex Mono tabular numbers. No shadows, 0-2px border radius.
- **Sideways scroll at 390px**: PASS. `docWidth=390, winWidth=390`. Clean mobile layout.
- **Copy and text**: PASS.

---

## 3. Dashboard Tablet View (`http://localhost:8000/tablet.html`)

### Status: FAIL

### Ranked Problems (Judge Priority)
1. **Missing STOP banner on emergency stop**
   - File: `dashboard/tablet.html` and `dashboard/tablet.js`
   - Element: No banner container in DOM
   - Problem: When STOP is pressed or Spacebar hit, `#step` displays `STOPPED`, but there is no full-width red banner as defined by IEC 60601-1-8 alarm standards in `docs/DESIGN-SYSTEM.md`.
   - Fix: Add a full-width sticky red alarm banner to `dashboard/tablet.html` that reveals on `stopped` state.
2. **RESET button permanently visible in dock**
   - File: `dashboard/tablet.html` (line 34)
   - Element: `<button id="btn-reset" class="btn-reset">RESET</button>`
   - Problem: In `dashboard/index.html`, Reset is hidden during normal operations and only displays after a stop or error. On `tablet.html`, Reset is always visible side-by-side with STOP in the bottom bar, creating potential for accidental resets mid-operation.
   - Fix: Hide `#btn-reset` by default in `dashboard/tablet.css` and unhide only when state is `stopped` or `error`.

### Detailed Checks
- **Console errors**: PASS. 0 console errors, 0 warnings.
- **Live numbers update**: PASS. Giant step text and instruments out update live via WebSocket.
- **STOP button**: `#btn-stop` calls `POST /stop`. Step turns to STOPPED.
- **Spacebar**: Spacebar triggers stop cleanly.
- **Design tokens**: PASS. Archivo font, dark monitor palette, large tactile buttons, 0-2px radius, no shadows.
- **Sideways scroll at 390px**: PASS. `docWidth=390, winWidth=390`.
- **Copy and text**: PASS. Clean, concise, medical monitor copy.

---

## 4. Nurse Console (`http://localhost:8000/nurse`)

### Status: FAIL

### Ranked Problems (Judge Priority)
1. **Critical CSS bug: Body font falls back to Times New Roman and background is white**
   - File: `dashboard/style.css` (lines 137 to 144)
   - Element: `body[data-page="nurse"]`
   - Problem: `dashboard/style.css` declares `@scope (body[data-page="nurse"]) { html,body{margin:0;background:var(--bg);color:var(--text);font-family:var(--head);font-size:16px;...} }`. In CSS `@scope`, `html` is an ancestor and `body` is the scope root; the selector `html, body` fails to match `:scope`. As a result, the body element receives no background color and no font-family from line 144. The page background falls through to default white, and all un-scoped text (including the footer and buttons) renders in browser default serif `"Times New Roman"`.
   - Fix: In `dashboard/style.css` line 144, change `html,body` to `:scope` or move `body[data-page="nurse"]` out of `@scope`.
2. **Theme mismatch: Uses dark theme instead of paper theme**
   - File: `controller/nurse.html` and `dashboard/style.css` (line 138)
   - Problem: `docs/DESIGN-SYSTEM.md` Section 1 specifies that the nurse console should look like a Swiss status board printed on paper (`paper` theme, warm background `#ece8dd`, black rules, small caps labels). Instead, `nurse.html` uses custom dark theme variables (`--bg: #1c1f22`, `--panel: #25292c`).
   - Fix: Align nurse console with shared paper theme tokens from `docs/DESIGN-SYSTEM.md`.
3. **STOP button renders in Times New Roman serif font**
   - File: `controller/nurse.html` (line 19)
   - Element: `<button class="stopbtn" id="stopBtn" aria-label="Stop">STOP</button>`
   - Problem: Due to the font scoping failure, the prominent red STOP button renders in serif Times New Roman instead of Archivo or IBM Plex Mono.
   - Fix: Explicitly declare `font-family: var(--f)` on `.stopbtn`.
4. **Console errors from port 8001 camera stream**
   - File: `controller/nurse.html` (lines 27-30)
   - Element: `<img id="camImg">`
   - Problem: Tries to connect to `http://localhost:8001/stream`, logging `net::ERR_CONNECTION_REFUSED` when sim controller runs without external vision server.
5. **Banned font imported in HTML header**
   - File: `controller/nurse.html` (line 11)
   - Problem: Imports `IBM Plex Sans` instead of `Archivo`. `docs/DESIGN-SYSTEM.md` explicitly lists Archivo for headings and labels.

### Detailed Checks
- **Console errors**: 6 errors (port 8001 stream refusal and 404s).
- **Live numbers update**: PASS. Latency stats, step, and arm position track live.
- **STOP button & Spacebar**: Both trigger stop. Status updates to `stopped`. Red banner missing.
- **Sideways scroll at 390px**: PASS. `docWidth=390, winWidth=390`. Responsive grid collapses to single column.
- **Copy and text**: PASS.

---

## 5. Demo / Judge Console (`http://localhost:8000/demo`)

### Status: FAIL

### Ranked Problems (Judge Priority)
1. **Critical CSS bug: Body background is transparent white with Times New Roman serif font**
   - File: `dashboard/style.css` (lines 256 to 264)
   - Element: `body[data-page="demo"]`
   - Problem: Identical to the nurse console bug. `dashboard/style.css` uses `@scope (body[data-page="demo"]) { html,body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.4 var(--sans)} }`. The selector `html, body` does not match the `:scope` element inside `@scope`. Therefore, `body` does not receive `background: var(--bg)` (`#141518`) or `font: 15px/1.4 var(--sans)`. The page renders against a WHITE browser background with Times New Roman serif text for all judge pitch cue scripts ("Every operation has a scrub tech...", "Ready: The problem").
   - Fix: In `dashboard/style.css` line 263, change `html,body` to `:scope` so the scope root receives background `#141518` and font `var(--sans)`.
2. **Missing red STOP banner across the top**
   - File: `controller/demo.html`
   - Problem: When STOP is clicked or Spacebar pressed, the stop button latches with class `latched`, but there is no full-width alarm banner across the top of the viewport.
   - Fix: Add full-width alarm banner matching design system spec.

### Detailed Checks
- **Console errors**: PASS. 0 console errors, 0 warnings.
- **Live numbers update**: PASS. Run clock, arm state, item status, and rehearsal log update live.
- **STOP button**: Large red STOP button (`#stop`). Space or Esc latches stop.
- **Spacebar**: Spacebar stops and latches.
- **Sideways scroll at 390px**: PASS. `docWidth=390, winWidth=390`. Responsive layout adapts cleanly.
- **Copy and text**: PASS. Script matches `docs/PITCH.md`. Plain words, short sentences, verified numbers (120 days, 10 minutes).

---

## 6. Sim Viewer (`http://localhost:8002/web/viewer.html?controller=http://localhost:8000`)

### Status: PASS

### Evaluation
- **Page load and console**: PASS. Loads immediately with 0 console errors and 0 warnings.
- **Design system compliance**: PASS. Warm paper background (`#ece8dd`), Archivo header (`SCRUB Arm viewer`), Swiss grid layout, sharp borders, tabular joint readouts in IBM Plex Mono.
- **Interactive features**: PASS. Mode buttons (SLIDERS, LIVE /STATE, EVENTS), camera angles (ISO, TOP, FRONT, SIDE, HAND VIEW), joint sliders, and handover script operate properly.
- **Live numbers and state**: PASS. Clicking "LIVE /STATE" connects directly to controller state and updates joint positions in real time.
- **STOP bar**: PASS. Large full-width red STOP bar below canvas with text "Spacebar stops the simulation."
- **Spacebar stop**: PASS. Spacebar freezes the sim arm.
- **Sideways scroll at 390px**: PASS. `docWidth=390, winWidth=390`. 3D canvas and controls scale to mobile width without overflow.
- **Copy and text**: PASS. Technical engineering labels, no buzzwords, no emojis.

---

## 7. Ledger Public Judge Page (`http://localhost:8080/`)

### Status: PASS

### Evaluation
- **Page load and console**: PASS. 0 console errors, 0 warnings.
- **Design system compliance**: PASS. Warm paper background (`#ece8dd`), 4px ink rule under masthead, Archivo wordmark and bold headline ("Scrub is a robot arm that passes instruments when you ask out loud."). Two-column track overview, monospace diagram, cases listing.
- **Numbers and units**: PASS. "Median handoff --", active case links with event counts and items out.
- **Sideways scroll at 390px**: PASS. `docWidth=390, winWidth=390`. Two-column grid collapses to single column on phone.
- **Copy and text**: PASS. Matches `docs/OVERVIEW.md` and `docs/DEVPOST.md`. Short sentences, plain words, no em dashes, no buzzwords. Truthful claim: "A research prototype, not a medical device."

---

## 8. Ledger Case List (`http://localhost:8080/cases.html`)

### Status: PASS

### Evaluation
- **Page load and console**: PASS. 0 console errors, 0 warnings.
- **Design system compliance**: PASS. Swiss register layout, paper theme (`#ece8dd`), Archivo kicker and title ("Case record"), 1px hair rules between case entries.
- **Live data**: PASS. Lists all active cases recorded during the session with case ID, setting, event counts, and items currently out.
- **Sideways scroll at 390px**: PASS. `docWidth=390, winWidth=390`. Clean mobile display.
- **Copy and text**: PASS. Direct, concise copy: "Open a case to read its requests, handoff times and instrument count."

---

## 9. Ledger Case Replay (`http://localhost:8080/case.html?id=...`)

### Status: PASS

### Evaluation
- **Page load and console**: PASS. 0 console errors, 0 warnings.
- **Design system compliance**: PASS. Paper theme (`#ece8dd`), 4px ink masthead rule, Archivo headline, event log with IBM Plex Mono timestamps (`10/18/2026, 00:43:05`).
- **Content accuracy**: PASS. Detailed chronological step-by-step trace of each command, pick, grasp check, handoff, release, and return. Spoken voice feedback quotes recorded accurately.
- **Sideways scroll at 390px**: PASS. `docWidth=390, winWidth=390`. Log table wraps properly.
- **Copy and text**: PASS. Plain words, short sentences.

---

## 10. Ledger Series Page (`http://localhost:8080/series.html`)

### Status: PASS

### Evaluation
- **Page load and console**: PASS. 0 console errors, 0 warnings.
- **Design system compliance**: PASS. Paper theme (`#ece8dd`), Archivo headline ("Handoffs by minute"), IBM Plex Mono tabular counts and bar charts.
- **Truth in labeling**: PASS. Truthful fallback sentence displayed: "Tiger Data is not connected, so these minutes are counted from the local ledger. Set TIGER_DATABASE_URL to store them there." No exaggerated claims.
- **Sideways scroll at 390px**: PASS. `docWidth=390, winWidth=390`.
- **Copy and text**: PASS.

---

## 11. Ledger Memory Page (`http://localhost:8080/memory.html`)

### Status: PASS

### Evaluation
- **Page load and console**: PASS. 0 console errors, 0 warnings.
- **Design system compliance**: PASS. Paper theme (`#ece8dd`), Archivo headline ("Ask about past requests"), clean input box with sharp 1px border and 0px radius, list of historical request notes.
- **Truth in labeling**: PASS. Truthful fallback sentence: "Backboard is not connected. Answers come from the local ledger. Set BACKBOARD_API_KEY and BACKBOARD_ASSISTANT_ID to store the notes there."
- **Interactive query**: Question input and ASK button work.
- **Sideways scroll at 390px**: PASS. `docWidth=390, winWidth=390`.
- **Copy and text**: PASS.

---

## 12. Ledger Table Card (`http://localhost:8080/card.html`)

### Status: FAIL

### Ranked Problems (Judge Priority)
1. **QR code and printed URL point to `http://127.0.0.1:8080`**
   - File: `ledger/public/card.html`
   - Element: `<p id="url">` and `<div id="qr">`
   - Problem: The QR code and printed text encode `http://127.0.0.1:8080`. If a judge or attendee scans this QR code with their mobile phone at the DubHacks table, the phone will attempt to connect to localhost on the phone itself and fail with connection error.
   - Fix: Use `SCRUB_PUBLIC_URL` or the LAN IP address (e.g. `http://10.19.236.213:8080` or `http://144.202.95.111/`) so mobile devices can open the public judge page.

### Detailed Checks
- **Console errors**: PASS. 0 console errors.
- **Design tokens**: PASS. Clean paper theme, Archivo title ("ON THE TABLE / SCRUB / Ask for an instrument out loud. Scrub hands it to you.").
- **Sideways scroll at 390px**: PASS. `docWidth=390, winWidth=390`.
- **Copy and text**: PASS.

---

## 13. Vultr Public Page (`http://144.202.95.111/`)

### Status: FAIL

### Ranked Problems (Judge Priority)
1. **Critical: Vultr host runs outdated pre-restyle build with rounded cards and Avenir Next font**
   - Host: `http://144.202.95.111/` (per `docs/ACCOUNTS-TODO.md` line 88)
   - Elements:
     - `<header class="top">`: `border-radius: 16px`, black container
     - `<section>`: `border-radius: 16px` rounded card containers
     - `<p id="status" class="banner">`: `border-radius: 10px`
     - `<pre class="diagram">`: `border-radius: 10px`
     - Typography: Computed body font is `"Avenir Next", "Segoe UI", sans-serif` instead of `Archivo`
     - Tracks section: Uses HTML unordered list bullets (`<ul><li>`) instead of the two-column Swiss layout
   - Problem: The public server at `144.202.95.111` has not been updated with the design system changes from branch `origin/anish/local-main-0050`. Any judge scanning the QR code or visiting the public server will see the old rounded-card startup landing page style, which contradicts `docs/DESIGN-SYSTEM.md`.
   - Fix: Run `powershell -File deploy/deploy.ps1` (or rsync restyled `ledger/public/` to `root@144.202.95.111:/var/www/scrub/`) so the Vultr server serves the restyled Swiss status board.

### Detailed Checks
- **Console errors**: PASS. 0 console errors.
- **Live numbers update**: PASS. Live Atlas data connects (`GET /api/stats` returns median handoff 0.44s and instruments out).
- **Sideways scroll at 390px**: PASS. `docWidth=390, winWidth=390`.
- **Copy and text**: PASS. Text content is truthful and matches project docs.
