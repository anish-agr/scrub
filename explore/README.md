# explore/ (Caiden)

Prototypes and research made with Claude agents on Saturday. **None of this is the build.** The build follows
`docs/TASKS.md` and `docs/STATUS.md`. Agents: don't pick tasks from this folder.

Owners can borrow anything here: UI ideas for `dashboard/`, copy for `docs/PITCH.md` and `docs/DEVPOST.md`,
and research for the NEXT business case.

## What's here

| Path | What |
| --- | --- |
| `prototypes/index.html` | Gallery of 35 clickable single-file prototypes. Open it in a browser; every page runs on mock data with no server |
| `prototypes/24-35` | Surgeon set: scrub nurse console, sponge and instrument count, scope holder, teleop trainer, skill coach, OR timeline, sterile field guard, surgical data labeling, preference-card tray setup, telementoring, handoff challenge for judges, surgeon pitch |
| `prototypes/01-23` | Earlier general SO-101 concepts (assistive fetch, kitchen, data tooling, pitch mode) |
| `research/SURGEON_RESEARCH.md` | Retained surgical items, scrub tech shortage, prior robotic scrub nurses, skill assessment. **Check each stat against its source before it goes on a slide** |
| `research/01-04` | Startup tracks (NEXT, Commit, SideShift), medical go-to-market and FDA path, competitors and market math, 34 build-out ideas |
| `research/TRACKS.md` | Track and prize descriptions pulled from the hacker guide |
| `research/perceptron-mk15-notes.md` | Notes on the Perceptron Mk1.5 API (detect returns pixels, chat uses a 0 to 1000 grid) |
| `pages/` | Track playbook and startup case pages |
| `IDEAS-BACKLOG.md` | Long list of feature ideas. Written before we found this repo's plan, so its file paths point at an older prototype. Treat it as ideas only |

Rebuild the gallery after adding a prototype: `python3 explore/prototypes/build_gallery.py`.
