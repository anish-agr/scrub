# Scrub design system (one look for every page)

Caiden's pages already look right: `team/status-board/`, `team/status-board/mockups/*`, `controller/demo.html`, `controller/nurse.html`. The rest (`dashboard/`, `dashboard/tablet.*`, `ledger/public/*`, `sim/web/*`) were built separately and don't match. This doc turns Caiden's look into one shared system so every page a judge sees looks like the same product.

Read first: `team/prototypes/DESIGN-DE-AI.md` (the rules and the banned "AI look"), then open `team/status-board/index.html`, `team/status-board/mockups/wall-display.html`, `scrub-tablet.html` and `controller/demo.html` in a browser.

## 1. The idea

Scrub's pages look like things that already exist in an operating room: a **nurse-station status board** printed on paper (Swiss grid, black rules, small caps labels) and a **medical device monitor** (near-black screen, fixed numeric readouts, alarm colors). Nothing looks like a startup landing page.

Two themes, one set of tokens:

| Theme | Feel | Used by |
| --- | --- | --- |
| `paper` (default) | Swiss status board on warm paper | dashboard, judge page, case list and replay, series, memory, table card, sim viewer, nurse console |
| `monitor` | Medical device HMI, near-black | demo console, tablet view, wall display, fullscreen mode of the dashboard |

## 2. Tokens (copy from `team/status-board/style.css`)

```css
:root, [data-theme="paper"] {
  --paper:#ece8dd; --paper2:#e3dfd2; --ink:#14130f; --mute:#625f55; --hair:#b9b4a4;
  --red:#c8201a;   /* high priority alarm, STOP, sharps */
  --amber:#9a5b00; /* medium: waiting, stale, retry */
  --green:#1d6a38; /* ok: handed, returned, live */
  --cyan:#0e6f86;  /* info only */
}
[data-theme="monitor"] {
  --paper:#0f1110; --paper2:#181b19; --ink:#e8e6df; --mute:#8d8a80; --hair:#2c302d;
  --red:#ff4b3e; --amber:#ffb02e; --green:#3ad17a; --cyan:#4cc9e8;
}
--f: 'Archivo', Arial, sans-serif;          /* labels, headings */
--m: 'IBM Plex Mono', ui-monospace, monospace; /* numbers, times, codes, logs */
```

Alarm colors follow IEC 60601-1-8 meaning (red high, amber medium, cyan info). Color only ever carries meaning. One accent at most beyond that.

## 3. Components (build once in `design/scrub.css`, reuse everywhere)

| Component | Spec |
| --- | --- |
| Masthead | 4px ink rule under it; brand "SCRUB" 900 weight; small-caps subtitle ("OR 4 · Surgical tray"); right side: live/down/mock connection word in its color, case clock `T+00:12:40` in mono |
| Section | 2px ink rule on top, small-caps label (12px, .14em tracking, mute color), no boxes, no shadows |
| Readout | Big number in mono with its unit printed ("6.4 s", "3 / 3"), label above in small caps |
| Step strip | The handoff steps in a row (FIND, PICK, CHECK, HAND, WAIT, RELEASE, HOME), current one filled ink, failed one red |
| Item row | Instrument name, slot, status word (ON TRAY / OUT / SAFE SPOT / RETURNING), item code style ("HEM-01") |
| Event log | Mono, one line per event, time first, status color only on the status word |
| Buttons | Square, 1px ink border, uppercase 15px, 44px min height; pressed = inverted. STOP is solid red, full width on its panel, and always visible |
| Tables | 1px hair rules, tabular numbers, rate with tries and range ("83%  10/12  [55–95]") |
| Banner | Full-width red bar for STOPPED / ARM FROZEN / VISION STALE (amber) |
| Empty state | A plain sentence in mute ("No real-arm tries yet. Tables fill as tests run."), never a spinner |
| Camera panel | The stream edge to edge, labels burned in mono at the corners (CAM OVERHEAD · 30 FPS · BRIGHT) |
| Footer | One mute line: team, DubHacks '26, "Terms · Privacy" placeholders |

Rules: corners 0 to 2px; separate with rules and space, never shadows; motion only on state change (a count updating, an alarm); tabular numerals everywhere; real units; copy in the voice of the room ("Count 2 of 3", "Mayo scissors, curved"). No emojis, gradients, glass, cards-with-shadows, bento grids, Inter/Geist, or em dashes in copy.

## 4. How to apply it

- Create `design/scrub.css` (tokens, both themes, components) and `design/README.md` with a screenshot of each component.
- Each page links `../design/scrub.css` (or the controller serves `/design/`) and keeps only page-specific layout in its own CSS.
- **Keep every behavior**: element ids the JS uses, keyboard shortcuts (space = stop), WebSocket and polling code, data fields. This is a restyle.
- Phone width: everything readable at 375px with no sideways scroll. The judge page is the most important on a phone (the QR code goes there).
- After each page: screenshot it at 1440px and 390px into `docs/media/ui/` and compare with Caiden's mockups.
