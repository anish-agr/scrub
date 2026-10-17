# explore/ (Caiden)

Prototypes and research made with Claude agents on Saturday. **None of this is the build.** The build follows
`docs/TASKS.md` and `docs/STATUS.md`. Agents: don't pick tasks from this folder.

Owners can borrow anything here: UI ideas for `dashboard/`, copy for `docs/PITCH.md` and `docs/DEVPOST.md`,
and research for the NEXT business case.

## What's here

| Path | What |
| --- | --- |
| `prototypes/index.html` | Gallery of 35 clickable single-file prototypes. Open it in a browser; every page runs on mock data with no server |
| `prototypes/39-46` | **Arm operations:** handoff path planner, failure drills against the real controller (11 C6 drills, all pass), demo recording coach, camera-to-arm calibration, Isaac inference loop monitor, servo health, 1:1 printable table template, per-item grasp cards |
| `prototypes/36-38` | **Scrub core:** dashboard (mock events match `docs/CONTRACTS.md`), voice call path (Photon, Gemini command, stop skips Gemini), three-setting trays with put-back and count |
| `prototypes/24,25,29-32,34,35` | Scrub-adjacent: handoff console, count sheet, case board, safety zones, demo-data labeling, tray setup, judge challenge, pitch |
| `prototypes/26,27,28,33` | Off concept (surgery tasks Scrub does not do). Kept for reference only |
| `prototypes/DESIGN-DE-AI.md` | The rules used to restyle these pages so they don't look AI-made |
| `prototypes/01-23` | Earlier general SO-101 concepts (assistive fetch, kitchen, data tooling, pitch mode) |
| `research/SURGEON_RESEARCH.md` | Retained surgical items, scrub tech shortage, prior robotic scrub nurses, skill assessment. **Check each stat against its source before it goes on a slide** |
| `research/01-04` | Startup tracks (NEXT, Commit, SideShift), medical go-to-market and FDA path, competitors and market math, 34 build-out ideas |
| `research/TRACKS.md` | Track and prize descriptions pulled from the hacker guide |
| `research/isaac-workshop-notes.md` | Perceptron Isaac 0.5 workshop deck as notes: verbatim commands, job quota, inference loop timing, and 16 differences vs docs/ARM.md and PERCEPTRON-ROBOTICS.md |
| `research/perceptron-mk15-notes.md` | Notes on the Perceptron Mk1.5 API (detect returns pixels, chat uses a 0 to 1000 grid) |
| `pages/` | Track playbook and startup case pages |
| `IDEAS-BACKLOG.md` | Long list of feature ideas. Written before we found this repo's plan, so its file paths point at an older prototype. Treat it as ideas only |

Rebuild the gallery after adding a prototype: `python3 explore/prototypes/build_gallery.py`.
