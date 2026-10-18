# Videos: plan, shots, and what to capture now

Two videos are needed. The **demo video** (2 to 3 min) is required for judging at all. The **Perceptron arm video** is required for the Perceptron Robotics track. A third, the **sim backup**, is for the table if the arm fails.

Owner of the edit: Evan. Script lines come from `docs/PITCH.md`. The cut plan by second is in `docs/DEVPOST.md` ("Video edit plan").

## 1. Capture now (before the arm works)

None of this needs a working model. Grab it tonight so Sunday morning is only the real-arm shots and the edit.

| # | What | How | Who |
| --- | --- | --- | --- |
| N1 | **Sim backup run**: the MuJoCo arm doing a full surgical case with the dashboard beside it | See "Recording the sim backup" below | Anish |
| N2 | **How we trained it**: hands on the leader arm, the follower copying, the recorder page with the episode counter | Phone, landscape, 30 s of a clean recording session. Faces optional | whoever isn't driving |
| N3 | **The training run**: Perceptron job status, the loss going down in `arm.train follow`, the Hugging Face dataset page | Screen record or screenshots | Caiden |
| N4 | **Dashboard, tablet, case replay, judge page on a phone** | Screen record a fake-arm case: `python -m controller.run_all` (fake arm), drive it with `cd voice && npm run say -- "grab me the kelly"` | Evan |
| N5 | **The phone**: the call screen to the Photon number, the end-of-case text arriving, a texted "what's out?" and its reply | Screen recording on the phone | Anish |
| N6 | **System diagram** (`docs/media/`) and title cards (`docs/SLIDES.md`) | Export as 1920x1080 images | Evan |
| N7 | **The tray close-up**: instruments on the blue towel, lamp off, then the lamp on showing glare | Phone, tripod or propped, 10 s each | Brandon |
| N8 | **Room sound**: 20 s of quiet room tone for the edit | Phone voice memo | anyone |

### Recording the sim backup (tested on Anish's Windows laptop, Sat 11:10 PM)

1. `pip install -r sim/requirements.txt -r controller/requirements.txt` (once).
2. `python -m controller.run_all backup --offline --loop --pause 2`. It resets the tray and runs hemostat, scalpel to the safe spot, Mayo scissors, a return and a count, over and over. Each run prints `CLEAN` when every step worked. (If the real-arm controller holds port 8000, add `--base-port 8100` and use 8100 below.)
3. Open two windows side by side:
    - the dashboard: `http://localhost:8000/`
    - the 3D arm: `http://localhost:8002/web/viewer.html?controller=http://localhost:8000`, then click **Live /state** so it follows the sim
4. Screen-record one full run (about 40 s) with Win+Alt+R. Save as `N1-sim.mp4`.
5. Ctrl-C in the terminal to stop.

## 2. Capture after the arm works (Sunday, after run 2)

| # | Shot | Notes |
| --- | --- | --- |
| A1 | "Hemostat" on speaker, the pick, handle into the open hand, the gripper opening on the pull | The money shot. Take it 5 times |
| A2 | "Scalpel" to the safe spot, "scalpel down" | |
| A3 | Return spot, "returning the hemostat", back into its slot | |
| A4 | Lamp on, glare, a handoff still works, cut to the lighting table | |
| A5 | Bench tray, "pliers", same arm | |
| A6 | "Count", the readback, the summary text arriving | |
| A7 | The dashboard tables with real numbers | Hold long enough to read |
| A8 | The team and the arm | |

**Perceptron arm video:** one unedited roll, side camera plus a phone, of several picks and returns across items and lighting, with the success table at the end. `arm/video.py` records each try with the instruction and result overlaid.

## 3. How to record

- **Windows screen:** Win+Alt+R (Xbox Game Bar) or OBS. **Mac:** Cmd+Shift+5.
- **Phone video:** landscape, 1080p, 30 fps, lock focus and exposure (long-press on iPhone).
- **Audio:** the speakerphone must be clearly heard. Put a second phone recording audio right next to it.
- Drop every file into one shared folder (Google Drive or AirDrop to Evan), named `N1-sim.mp4`, `A1-take3.mp4`, and so on.
- No keys, `.env` files or personal notifications on screen.

## 4. The edit

- 2 minutes is the target, 3 the maximum. 16:9, 1080p.
- Order and timings: `docs/DEVPOST.md` "Video edit plan". Narration follows `docs/PITCH.md`.
- The sim and fake-arm footage only goes in the "how we built it" part, labeled as simulation. The demo part is the real arm only.
- Upload to YouTube (unlisted is fine) or Vimeo by **Sun 9:00 AM**, link it on Devpost, submit by 9:30.
