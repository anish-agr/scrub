# Videos

## How to drop a take in

1. Pick the best take, name it by slot: `V1.mp4` ... `V10.mp4` (`.mov` is fine too). Narration memos: `V11-<Speaker>-<n>.m4a` or `.wav`, names listed in `team/VIDEO-SCRIPT.md`.
2. Put it in `/Users/caide_1/Documents/dubhacks/dubhacks-2026/data/video/kit/real/`.
3. From the main checkout `/Users/caide_1/Documents/dubhacks/dubhacks-2026`, run:

   ```
   .venv/bin/python -m video.roughcut
   ```

   It writes `data/video/kit/rough-cut.mp4` (1080p 30 fps H.264, -16 LUFS when there is sound) and prints each slot as REAL, SIM or MISSING with its seconds, plus the total length. Keep it under 3:00.

To use only part of a take, add `data/video/kit/real/trims.json`, e.g. `{"V1": [2.5, 31.0]}` (start and end second). Each real beat runs as long as its narration plus 2 s, so trim to the best window. Sim stand-ins come from `data/video/kit/sim/` (`sim-hemostat.mp4`, `sim-scissors.mp4`, `sim-stop.mp4`, `sim-return.mp4`, `simdemo-final.mp4`, rendered by `video/simdemo.py`). A missing slot shows a plain TO FILM card.

## Slots

| Slot | Shot | In the cut |
| --- | --- | --- |
| V1 | "Hemostat" on the phone, pick, carry, handle into the gloved hand, release on the pull, arm home | real, else sim-hemostat |
| V2 | Same with the Mayo scissors | real, else sim-scissors |
| V3 | "Stop" mid-move, arm freezes, red STOPPED banner, reset, pass finishes | real, else sim-stop |
| V4 | Manual return: a tool put back by hand or the arm jogged | real, labeled "MANUAL RETURN" |
| (return) | Simulated electromagnet return | sim-return, labeled "SIMULATED RETURN (electromagnet)" |
| V5 | Lamp on, glare, a handoff still finishes; bright, normal, dim tries logged | narration only over a real take |
| V6 | Temperature graph during a hold, arm folds to rest, torque off | real |
| V7 | Dashboard count and the count-sheet OCR read with latency | real (screen recording) |
| V8 | Tray check: one overhead frame through Perceptron detect, result and latency | real (screen recording) |
| V9 | Real model picks and the success table, only if a model is deployed | optional, left out until it exists |
| V10 | How it works: two plain cards, then the sim | simdemo-final |
| V11 | Narration memos, one line each | under their lines |

## How to record

- Phone in landscape, 1080p 30 fps, exposure locked, 20 to 40 s per take without stopping, 3 takes each. A second phone records audio near the speaker.
- The person asking wears a lab coat; keep faces out of frame, show the arm and the open gloved hand.
- No music. Real voices.
- Mac screen recording: Cmd+Shift+5. No keys, `.env` files or notifications on screen.
- Sim footage is labeled SIMULATION in the picture. Never call the sim "connected" to the real arm.

## The edit

- 2 to 3 minutes, under 3:00. 1080p 30 fps H.264, about -16 LUFS.
- Captions are burned in by the rough cut for every spoken line (plain white, thin outline).
- Final trims and room tone in CapCut or similar if needed. Upload unlisted by 9:00 and put the link on Devpost.
- The Perceptron Robotics video (only if a model is deployed) is one unedited roll of model picks with the success table at the end.
