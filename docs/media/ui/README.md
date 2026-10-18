# UI verification record

## Status

Code migration complete. **Browser review and screenshots are not complete.**
The installed Tabbit stable launcher returns exit 69 (routing unavailable),
without stdout or stderr, for both `diagnose` and `tabs`. No reference pages
could be opened through that browser, and no screenshot files have been
created. Do not use the planned paths below as evidence of visual acceptance.

## Page coverage

All image paths below are planned, not captured. Each page needs both widths.

| Source page | Planned 1440px image | Planned 390px image |
| --- | --- | --- |
| `dashboard/index.html` | `dashboard-1440.png` | `dashboard-390.png` |
| `dashboard/tablet.html` | `tablet-1440.png` | `tablet-390.png` |
| `ledger/public/index.html` | `judge-1440.png` | `judge-390.png` |
| `ledger/public/cases.html` | `cases-1440.png` | `cases-390.png` |
| `ledger/public/case.html` | `case-1440.png` | `case-390.png` |
| `ledger/public/series.html` | `series-1440.png` | `series-390.png` |
| `ledger/public/memory.html` | `memory-1440.png` | `memory-390.png` |
| `ledger/public/card.html` | `card-1440.png` | `card-390.png` |
| `sim/web/viewer.html` | `sim-viewer-1440.png` | `sim-viewer-390.png` |
| `sim/web/layout.html` | `sim-layout-1440.png` | `sim-layout-390.png` |
| `controller/nurse.html` | `nurse-1440.png` | `nurse-390.png` |
| `controller/demo.html` | `demo-1440.png` | `demo-390.png` |
| `design/components.html` | `components-paper-1440.png`, `components-monitor-1440.png` | `components-paper-390.png`, `components-monitor-390.png` |

Use `docs/media/ui/` as the destination directory. The component sheets cover
the masthead, section, readout, step strip, item row, event log, buttons, table,
banner, empty state, camera panel and footer in both themes.

## Checks completed

- Installed controller and sim requirements once, plus missing ledger dependencies.
- Ran `python -m controller.test_flows` after every page: **66/66 passed**.
- Ran `python -m pytest -q sim/test_sim.py` after every page: **16 passed**.
- Ran `python -m pytest -q ledger/test_ledger.py` after every page: **15 passed**.
- `python -m unittest design.test_ui -v`: seven static checks, including all
  original element IDs, equivalent inline application scripts, external scripts
  unchanged apart from display copy, exact approved console CSS declarations,
  identical published sheets and banned effects.
- `python design/sync.py --check` verifies the three published copies.
- `python design/check_http.py --controller http://localhost:8400 --ledger http://localhost:8403 --sim http://localhost:8402`
  passes for all 12 live pages, shared CSS, page CSS, application JavaScript
  assets and the QR PNG.
- `npm run say -- grab me the kelly` against the isolated fake stack replied
  "Hemostat coming." and "Here's the hemostat. Ready to grab."

These are functional and source-preservation checks, not a claim about pixel
appearance, responsive overflow, WebGL rendering or loaded web fonts.

## Running stack and Windows constraints

The requested `python -m controller.run_all --arm fake` refused to start because
8000 was already occupied. That process was not stopped. An isolated stack used
controller 8400, fake vision 8401, sim 8402, voice 3400 and ledger 8403.

The isolated `run_all` brought up controller and vision, then failed to launch
`npm` with Windows `CreateProcess`. Its cleanup also calls unavailable
`os.killpg`. The started fake controller and vision remained available. Voice,
ledger and sim were started separately; no backend code was changed.
Voice used `VOICE_NO_KEYS=1` and the fake controller, ledger used an empty Mongo
URI. The fake handoff was sent with `VOICE_URL=http://localhost:3400`.

For a later browser review, use dashboard
`http://localhost:8400/?vision=http://localhost:8401&ledger=http://localhost:8403`,
tablet `/tablet.html`, consoles `/nurse` and `/demo`, public pages on 8403 and
sim pages on `http://localhost:8402/web/`. Open the replay with a real `id` from
`/api/cases`; check a missing case as well. Check idle, handed, stopped,
reset, vision-stale, offline and empty-result states, plus both component themes.

The controller's plain `read_text()` also made `/demo` fail with HTTP 500 on
Windows when decoding its original UTF-8 smart quotes. The allowed console
files now use HTML entities and equivalent JavaScript unicode escapes. Their
rendered copy and decoded application scripts are unchanged. `/demo` now
passes the same live HTTP check without editing server code.

Compare against `explore/status-board/index.html`, mockups `wall-display`,
`scrub-tablet`, `item-id`, `bring-up`, and the original nurse/demo appearances.
Console rules use native CSS `@scope`, supported by current Chromium browsers.
