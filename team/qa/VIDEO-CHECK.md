# Video check

Checked from the detached worktree at `origin/main` (`457c47f`) on this Mac. The PowerShell paths in the task were mapped here: repo `/Users/evan/Documents/GitHub/dubhacks-2026-cur2`, Python `/Users/evan/Documents/GitHub/dubhacks-2026/.venv/bin/python` (3.10). `../dubhacks-2026.env` does not exist and this tree has no `.env`. Nothing was printed from an env file. `--offline` does not need keys.

No tracked file was edited except this one. Clips, logs, and the render stay under `data/` (git-ignored).

## Rehearsal (`python -m video`, synthetic fixtures)

Workspace `data/video/rehearsal-qa`. Log `data/video/qa-rehearsal.log`.

| Command | Exit |
| --- | --- |
| `demo-assets --seconds 3` | 0 |
| `ingest` | 0 |
| `corners` on `raw/demo.mp4` and `photos/demo-00.png` (`--headless --accept-auto`) | 0 |
| `topdown` warp, plate, and reconstruction | 0 |
| `clean --stabilize --deflicker --denoise --audio` | 0 |
| `find --events demo/events.jsonl --cut` | 0 |
| `overlay --allow-synthetic` | 0 |
| `cards --events demo/events.jsonl --allow-synthetic` | 1 |
| `preview` of `video/edl/demo.yaml` with `--demo` | 0 |
| `render` of `video/edl/demo.yaml` with `--demo` | 0 |
| `render` of `video/edl/perceptron-arm.yaml` with `--demo` | 1 |

`python -m unittest video.test_video -v`: 25 tests, OK, 24.674s. Log `data/video/qa-unittest.log` ends `UNIT_EXIT:0`.

## Sim backup video

Stack: `python -m controller.run_all backup --offline --loop --pause 2 --base-port 8100 --no-open`

Voice did not start (`voice/node_modules` missing). Vision was off. Controller on port 8100 with `--sim-arm`, sim viewer on port 8102. Events went to `ledger/buffer.jsonl` (offline clears `MONGODB_URI`). The backup script kept reporting CLEAN (hemostat, scalpel to the safe spot, mayo scissors, return hemostat, count).

Capture (not the synthetic demo assets): 75 seconds of `http://127.0.0.1:8102/stream?cam=overhead` (MJPEG) and headless Chromium screenshots of `http://127.0.0.1:8100/`. There is no `/snapshot`. Frames were encoded at `frame count / elapsed` so playback is 1x. Capture clock in `data/video/sim-capture/started.txt`: start `1792310953.35086`, end `1792311028.4318001`.

The edit uses one complete case from that window, `surgical-1792310972` (42 events in `ledger/buffer.jsonl`). Overhead and dashboard clips were ingested as `kind: simulation` (not synthetic). Overlay burned that case only (`--case-id`, `--allow-synthetic` because the controller sets `fake_arm` on sim events). The overlay sidecar stays `kind: simulation` with `synthetic` unset, so the production render accepts it. Render was **without** `--demo`. `real_only` is false only on the git-ignored copy `data/video/sim-run/sim-backup.yaml`. `video/edl/demo.yaml` was not changed.

Demo order where this run actually had the shot: N7 tray, A1 hemostat, A2 scalpel safe spot, then mayo scissors (the backup script does this between scalpel and the return; slot `MAYO`), A3 return, A6 count, A7 dashboard. Lighting never left `normal`, the tray stayed surgical, and there is no team shot, so A4, A5, and A8 are not in this file.

| | |
| --- | --- |
| Output | `data/video/out/sim-backup.mp4` |
| Also | `data/video/sim-run/out/sim-backup.mp4` (same bytes) |
| Length | 68.8 s (2064 frames, 30 fps) |
| Picture | 1920×1080 |
| Size | 2,690,623 bytes |
| Provenance | `synthetic: false`. Every shot `kind: simulation`. Silent audio kept (no LUFS to hit). |

Checked frames at 3s, 13s, 25s, 35s, 52s, and 62s:

- Each frame has the `SIMULATION` bar. None say `SYNTHETIC FIXTURE` or `SPEED`.
- 13s: `HEMOSTAT | request to hand 6.2 s` from ledger `request_to_hand_s` 6.21.
- 25s: `SCALPEL | request to hand 8.0 s` from 7.96, `OUT 2: hemostat, scalpel`.
- 35s: `MAYO SCISSORS | request to hand 6.1 s` from 6.1, `OUT 3: hemostat, scalpel, mayo scissors`.
- 52s: `OUT 2: scalpel, mayo scissors` after the hemostat return. No speed tag. Source `time_map` is null, so nothing was sped up.
- 62s: the live dashboard from this run (arm `fake`, operating room, normal), with `SIMULATION` on top.

Clip epoch is the capture-loop end minus each file's encoded duration (`overhead` start `1792310953.7667263`, `dashboard` start `1792310954.8108037`). The dashboard page's own "last handoff" can still show the previous pass until this pass completes. The burned overlay numbers come only from case `surgical-1792310972`.

## Bugs (not patched; this task cannot edit those files)

1. `video/cards.py` line 104. `page.screenshot(path=str(png))` uses Playwright's 30s default. After "fonts loaded" it raises `playwright._impl._errors.TimeoutError: Page.screenshot: Timeout 30000ms exceeded.` `video/__main__.py` lines 146-149 do not catch `TimeoutError`, so the command prints a traceback instead of `video: TimeoutError`. Fix line 104 to `page.screenshot(path=str(png), timeout=120000, animations="disabled")`. Then rerun `cards`.

2. `video/edit.py` line 72. `render` of `video/edl/perceptron-arm.yaml` reads `cards/index.json`. That file was never written because cards failed, so the render exits `FileNotFoundError` on `data/video/rehearsal-qa/cards/index.json`. Fix is bug 1, then rerun cards, then rerun that render. No separate change on line 72.

3. `video/overlay.py` line 29. The caption is `command.get('heard')`. Backup commands store the phrase in `say` (`Hemostat coming.`, `Scalpel to the safe spot.`, …) and leave `heard` null, so the spoken line is missing while the item, the request-to-hand time, and the out-list still render. Fix: `'caption': (command.get('heard') or command.get('say')) if command else None`.

## Redo

From `/Users/evan/Documents/GitHub/dubhacks-2026-cur2`, with the venv Python above. Ports stay at 8100 so they do not collide with a stack on 8000.

```bash
python -m controller.run_all backup --offline --loop --pause 2 --base-port 8100 --no-open
```

In another shell, while that loop is CLEAN (Ctrl-C that process when the capture finishes):

```bash
PLAYWRIGHT_BROWSERS_PATH="$PWD/data/video/browser" python -m playwright install chromium
PLAYWRIGHT_BROWSERS_PATH="$PWD/data/video/browser" python data/video/capture_run.py
python data/video/build_sim_backup.py
```

`capture_run.py` records 75s from `http://127.0.0.1:8102/stream?cam=overhead` and `http://127.0.0.1:8100/` into `data/video/sim-capture/{overhead,dashboard}.mp4`. `build_sim_backup.py` keeps case `surgical-1792310972` only if that id is still the case inside the new capture window; on a new run, point `CASE` at the case id whose `t` falls inside `started.txt`. It ingests both clips as simulation, overlays the overhead from `ledger/buffer.jsonl`, and renders without `--demo` to `data/video/out/sim-backup.mp4`.

Rehearsal, from the same directory:

```bash
Demo=data/video/rehearsal-qa
python -m video --root $Demo demo-assets --seconds 3
python -m video --root $Demo ingest
python -m video --root $Demo corners --input raw/demo.mp4 --camera side --width-mm 300 --height-mm 180 --headless --accept-auto
python -m video --root $Demo corners --input photos/demo-00.png --camera photo --width-mm 300 --height-mm 180 --headless --accept-auto
python -m video --root $Demo topdown --mode warp --input raw/demo.mp4 --camera side --output topdown/plane.mp4
python -m video --root $Demo topdown --mode plate --reference photos/demo-00.png --camera photo --empty-scene --output topdown/plate.png
python -m video --root $Demo topdown --mode reconstruction --input demo/joints.json --plate topdown/plate.png --plate-alignment demo/plate-alignment.json --output topdown/reconstruction.mp4
python -m video --root $Demo clean --input raw/demo.mp4 --output clean/demo.mp4 --stabilize --deflicker --denoise --audio
python -m video --root $Demo find --events demo/events.jsonl --cut
python -m video --root $Demo overlay --input clean/demo.mp4 --events demo/events.jsonl --output overlays/demo.mp4 --allow-synthetic
python -m video --root $Demo cards --events demo/events.jsonl --allow-synthetic
python -m video --root $Demo preview --edl video/edl/demo.yaml --bindings demo/edit.json --output renders/preview.mp4 --demo
python -m video --root $Demo render --edl video/edl/demo.yaml --bindings demo/edit.json --output renders/demo.mp4 --demo
python -m video --root $Demo render --edl video/edl/perceptron-arm.yaml --bindings demo/edit.json --output renders/arm.mp4 --demo
python -m unittest video.test_video -v
```

`demo-assets` refuses to overwrite an existing fixture. Use a new `--root` for a second rehearsal. Cards and the Perceptron render stay red until bug 1 is fixed.
