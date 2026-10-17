# Arm-first prototype brief (39 and up). Read this, then the files it names.

The user's feedback: earlier prototypes felt like generic apps that "don't really fit the robot arm situation".
Every prototype from 39 on must be about the PHYSICAL SO-101 arm doing Scrub's one job (pick an item from its tray
slot, bring it handle first to an open hand, let go on a pull or "got it"; scalpel to the safe spot; put-back; count),
and must help a real person on the team do a real task listed in dubhacks-2026/docs/TASKS.md.

Ground truth to read: /Users/caide_1/Documents/dubhacks/dubhacks-2026/README.md, docs/CONTRACTS.md, docs/TASKS.md,
docs/ARM.md, docs/PERCEPTRON-ROBOTICS.md, explore/research/isaac-workshop-notes.md, sim/README.md, sim/layout.json,
controller/README.md and controller/server.py (real endpoints, including POST /fake/force and POST /fake/pull),
/Users/caide_1/Documents/dubhacks/prototypes/DESIGN-DE-AI.md (visual rules, strictly), and BRIEF.md (file rules).

Rules:
- One self-contained HTML file in /Users/caide_1/Documents/dubhacks/prototypes/NN-name.html, header comments
  FEATURES / SPONSORS / BACKEND HOOKS / STYLE, <title> and meta description, STOP where the arm moves, no em dashes.
- Real numbers from the sources: SO-101 joint names and limits, ~0.4 m reach, 30 Hz playback of 30x6 action chunks,
  400 ms deadline, 2 training jobs, STS3215 servos, 3 settings x 3 items, layout.json positions. Units always shown.
- Talk to real services when they're up (controller :8000, vision :8001, sim :8002, with ?api= style overrides),
  fall back to a clearly labeled mock. Never pretend mock data is live.
- Draw the arm and the table as they are: side and top views in mm, the actual tray and zones. No decorative charts.
- Verify: from /private/tmp/claude-502/-Users-caide-1-Documents-dubhacks/535a9f5f-9616-49bb-9ec5-876e04b8c64d/scratchpad
  run `node smoke.mjs NN` (OK, no HSCROLL), view shots/NN-*-d.png once with Read, fix what looks off.
- Don't edit anything in dubhacks-2026/. Report 4 lines per file: what it does, who it helps (task id), live vs mock,
  anything unsure.
