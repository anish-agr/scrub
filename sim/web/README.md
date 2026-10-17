# sim/web

Two plain HTML + JS pages (no build step) for the simulation track. Style: printed shop layout sheet, dimensions in mm.

## Open them

- With the sim: `python -m sim`, then `http://localhost:8002/web/viewer.html` and `http://localhost:8002/web/layout.html`.
- Without it: `python3 -m http.server 8099` from the repo root, then `http://localhost:8099/sim/web/viewer.html`. The pages then look for the sim API on port 8002 and models under `/sim/models/`. Override with `?api=URL`, `?models=URL`, `?controller=URL`.
- As `file://`: `layout.html` works (reach is an estimate, export is copy or download). `viewer.html` cannot load the STL meshes over `file://` and says so in the page.

## viewer.html

3D SO-101 from `so101_new_calib.urdf` (urdf-loader 0.12.3 and three.js 0.164.1 via importmap), table, tray, slots, return spot, safe spot, hand zone and reach ring from the layout. Modes: sliders; live (polls `GET /state` every 0.5 s); events (`WS ws://localhost:8000/events`, with a mock handover when the controller is absent). Scripted handover: pick, carry, hand zone, release; scalpel goes to the safe spot; Put back returns an item via the return spot. Camera presets: iso, top, front, side, hand view. Space = stop. Poses come from `/reach` when the sim answers, otherwise a numeric IK on the loaded model.

## layout.html

Top-down designer. Drag the tray (moves its slots), each slot, return spot, safe spot, hand zone, overhead camera. Reach check for every element (pick and approach height) through `POST /reach/batch`, otherwise a local 2-link-plus-wrist estimate with link lengths read from the URDF, labeled "estimate". Kit builder: setting and procedure (basic dissection, suture removal, laceration repair, dental cleaning, filling, exam, solder a header, servo swap, frame assembly) list tray items, missing items, instruments without an arm skill yet, and spares and consumables; add and remove items and slots. Suggestions are **rule-based for now**, each with a reason and an Apply button. "Ask for suggestions" is a stub that only shows the request it would POST to the controller. Usage counts come from `GET /stats` on the controller when readable, else mock counts.

Export: `layout.json` in the sim's own format (tray center/size, slots as `[x,y]`, `setting_items` in slot order, etc.; other keys of the sim file are kept untouched), PUT to `/layout` when the sim is up, else copy or download. Also `settings/<id>.json` per `docs/CONTRACTS.md` (slot and return_spot are `null` until the camera is mounted; item ids and order are filled). The layout autosaves to browser localStorage (`scrub.layout`) and the viewer picks it up.

## Endpoints used

Sim (8002): `GET /state`, `GET /reach`, `POST /reach/batch`, `GET/PUT /layout`, static `/web/*`, `/models/*`. Controller (8000): `WS /events`, `GET /stats`. All are optional; each page falls back when one is missing.

## Notes and unknowns

- Axes: base frame, x forward, y left, z up, URDF base_link. Positive shoulder_pan swings toward negative y (to the arm's right) in this URDF.
- Sharp flags in the item catalog (scalpel, Mayo scissors, explorer, wire cutters) are my guess; settings files are Evan's.
- Custom kit items are not sent to the sim (it has no skill for them).
