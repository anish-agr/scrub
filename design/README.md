# Scrub interface system

Swiss status board on paper. Medical device HMI on monitor. The reference is
Caiden's `explore/status-board/`, especially the ruled masthead, instrument
sheet and wall display. Use semantic colors, square controls, Archivo labels
and IBM Plex Mono readouts. There are no decorative accent colors.

## Use it

```html
<link rel="stylesheet" href="style.css">
<body class="scrub-ui" data-theme="paper">
```

Set `data-theme="monitor"` on the root HTML element for dark pages, so the
canvas and native controls also use the theme. Both dashboard views use it.
Page CSS should contain layout only, with colors and fonts from the tokens.

The dashboard (paper, `?theme=monitor`), tablet (monitor), ops (monitor), demo console (monitor) and nurse console (paper) all use `scrub.css` directly. Page CSS holds layout only. The old `@scope` copies are gone. Stopped state: a full-width red `.stop-banner` on dashboard, tablet, nurse and demo.

`scrub.css` is the only source. The controller mounts `dashboard/` at `/`,
the ledger has a fixed file allowlist, and sim mounts `sim/web/` at `/web`.
None serves the root `design/` directory. To keep backend files untouched,
we publish identical copies as each server's existing `style.css`:

```
python design/sync.py
python design/sync.py --check
```

Regression and integration checks:

```
python design/check.py
python -m unittest design.test_ui -v
python design/check_http.py --controller http://localhost:8400 --ledger http://localhost:8403 --sim http://localhost:8402
```

`migrate_console.py` is the one-time, guarded extraction tool for the two
approved consoles. Do not rerun it after migration. The shared link falls back
to `../dashboard/style.css` when a console is opened from disk or a root static
server. The normal controller route uses `/style.css` directly.

Do not hand-edit those three generated files. Include regenerated copies in
any commit that changes the source. The consoles use the controller's
`/style.css`, with their original rules isolated under `data-page`.

## Components

Open `design/components.html` with a repo-root static server. It contains both
themes and every component. Static example values are labeled as samples.

| Component | Class | Usage |
| --- | --- | --- |
| Masthead | `masthead`, `wordmark`, `subtitle`, `clock` | 4px bottom rule, connection word, mono clock |
| Section | `section`, `kicker` | 2px top rule, tracked label |
| Readout | `readouts`, `readout` | Fixed numeric text with printed units |
| Step strip | `step-strip`, `current`, `failed` | Fill the current step, red failure |
| Item row | `instrument-row`, `code`, `state` | Item, slot, status word, item code |
| Event log | `event-log` | Time first; only status carries color |
| Buttons | `primary`, `stop` | 44px minimum, square, inverted pressed state |
| Tables | `table-wrap` | Rates with tries and ranges, ruled rows |
| Banner | `banner`, `warning` | Red stop or amber stale reading |
| Empty state | `empty-note` | A sentence, no spinner |
| Camera | `camera-frame`, `camera-label` | Edge-to-edge image and mono corner label |
| Footer | `foot` | Team, event, Terms and Privacy placeholders |

## Verification record

Browser review and screenshots are pending: the installed Tabbit launcher
returns routing error 69 without a browser connection. Do not treat planned
screenshot names as captured evidence. Exact page coverage and any remaining
test issues are recorded in `docs/media/ui/README.md`.
