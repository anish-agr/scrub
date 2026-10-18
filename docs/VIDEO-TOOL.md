# Video tool spec (`video/`)

A command-line pipeline that turns our real footage, photos and logs into the demo video and the Perceptron arm video: a virtual **top-down view** of the table, **cleanup** (stabilize, denoise, even out lighting, blur bystanders, trim dead time), **overlays** from the ledger, and a scripted **edit** to a finished 1080p file. Shot list and timings come from `docs/VIDEO.md` and the "Video edit plan" in `docs/DEVPOST.md`. Visual style for overlays and cards comes from `docs/DESIGN-SYSTEM.md`.

## Honesty rule (non-negotiable)

Judges watch this video to decide whether the robot works. The tool may change how real footage **looks** (crop, reframe, stabilize, color, denoise, speed up idle time with a "2x" tag). It must never invent what the robot **did**. Concretely:
- No generative video that creates or alters arm motion, instruments or outcomes.
- Every reconstructed or simulated shot carries an on-screen label: `SIMULATION` or `RECONSTRUCTED FROM ARM JOINT DATA`.
- Every number on screen (times, success rates, counts) comes from the ledger or the dataset, never typed in by hand.
- A speed change is always labeled ("2x").

## Inputs

| Input | Where it comes from |
| --- | --- |
| Clips | Phone videos, screen recordings, `arm/video.py` per-try clips, LeRobot `side`/`wrist` episode videos. Dropped into `data/video/raw/` (git-ignored) |
| Photos | 20 to 40 stills of the table and tray from above and at angles, 60% overlap. `data/video/photos/` |
| Events | The ledger (MongoDB or `ledger/buffer.jsonl`): every step, item, request-to-hand time, with timestamps |
| Joint angles | The LeRobot dataset (`~/scrub-dataset`) and `/arm/pose` logs, for the reconstruction |
| Layout | `settings/*.json` slots, `sim/layout.json`, `vision/calibration.json` |

## Commands (`python -m video <command>`)

1. **`corners`**: no markers needed (we don't have any). For each camera or clip, find the tray's four corners automatically (the tray is a light rectangle on a blue towel: color segmentation plus the largest four-sided contour), show the result, and let me drag any corner to fix it. Save per camera in `data/video/corners.json`. One click-through per camera, then everything after it is automatic.
2. **`ingest`**: indexes every clip and photo (duration, fps, resolution, start time), makes a contact sheet per clip, and lines clips up in time using the ledger timestamps or a clap in the audio. Writes `data/video/manifest.json`.
3. **`topdown`**: the virtual overhead camera, three ways, each usable alone:
    - **Plane warp:** take the 4 tray corners from `corners` (tracked frame to frame with optical flow if the camera moves a little), compute the homography to the table plane, and warp every frame to a true top-down view at a fixed scale (2 px per mm). Shows the tray and the hand clearly. Tall things (the arm) look stretched; that's expected.
    - **Photo plate:** take one reference photo from straight above, match every other photo to it with SIFT features and RANSAC (no markers), warp them to the same plane and blend them (median) into one clean, high-resolution top-down image of the tray with no people or arm in it. Used as the background for diagrams, title shots and the reconstruction.
    - **Reconstruction:** replay the recorded joint angles through the MuJoCo SO-101 (`sim/`, see `explore/dataset/replay.py`) with an orthographic camera straight down, composite it over the photo plate with the instruments at their slots, and sync it to the real clip. Labeled `RECONSTRUCTED FROM ARM JOINT DATA`.
4. **`clean`**: a chain where each step is optional, logged, and previewable before/after:
    - stabilize (ffmpeg `vidstab` two-pass, or OpenCV feature tracking)
    - match exposure and white balance across clips to one reference frame, and deflicker
    - denoise (ffmpeg `hqdn3d` or `nlmeans`); optional neural upscale only if a GPU is present
    - blur faces of anyone who isn't on the team (MediaPipe face detection; team faces kept by a click list)
    - find idle stretches (no motion in the frame) and speed them up 2 to 4x with a "2x" tag, or cut them
    - audio: noise reduction (`afftdn`), loudness to -16 LUFS, keep the speakerphone voice clear
5. **`find`**: rank the best takes. Use ledger events (a handover that reached `handed` and `released` with no retry) to cut each try out of the long recordings; optionally ask Gemini (video input) to score framing and whether the handoff is visible. Writes a ranked list with timestamps.
6. **`overlay`**: burn in, in the design-system style (Archivo + IBM Plex Mono, square, no shadows): the spoken request as a caption, a lower third ("HEMOSTAT · request to hand 6.4 s"), the step strip, the lighting tag, the `SIMULATION` label where needed, and a small live count.
7. **`cards`**: renders title cards, section cards and the end card (success table, team, tracks) from HTML with the design system, through a headless browser, to 1920x1080 PNGs.
8. **`render`**: reads an edit decision list and produces the final file: 1920x1080, 30 fps, H.264 + AAC, -16 LUFS. Two lists ship with the tool:
    - `video/edl/demo.yaml`: the 2-minute demo, following the timings in `docs/DEVPOST.md`, with slots for each shot (A1 to A8, N1 to N8) and treatment per shot (clean, topdown, side-by-side, picture-in-picture with the dashboard)
    - `video/edl/perceptron-arm.yaml`: the unedited arm roll for the Perceptron track, cleaned only, with the success table end card
9. **`preview`**: a low-resolution fast render of any EDL so the team can check the cut in seconds.

## Tech

Python 3.10, OpenCV (already installed), NumPy, `imageio-ffmpeg` (bundles an ffmpeg binary, so it works on Windows without a system install), MediaPipe (already used in `vision/`), MuJoCo (already used in `sim/`), PyYAML, Playwright for cards, `google-genai` optional for `find`. Nothing paid is required. Heavy optional steps (neural upscale) are skipped cleanly when the hardware isn't there.

## Testing before real footage exists

`python -m video demo-assets` generates synthetic inputs: a rendered table with a tray on a blue towel and instruments, a short clip from the sim arm, a set of "photos" from different angles, and matching ledger events. Every command must run end to end on these, and `video/test_video.py` checks the tray-corner finder and the homography error (under 2 mm on the synthetic plate, with no markers in the scene), that labels appear on simulated shots, and that the render matches the EDL timings.

## Capture guide (what the team does)

- No markers needed. Keep the whole tray in frame with all four corners visible, and keep the blue towel under it (the tray finder uses the contrast).
- Take one photo from straight above the tray first: it's the reference for everything.
- Phone: landscape, 1080p, 30 fps, focus and exposure locked, propped or on a tripod.
- Photos for the plate: 20 to 40, from above and around, overlapping, nobody in the frame.
- Keep the speakerphone close to a second phone recording audio.
- Drop everything into `data/video/raw/` and `data/video/photos/` (or the shared Drive folder, then copy in).
