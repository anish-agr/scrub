# Batch 47-54 brief (follows ARM_BRIEF.md)

Same rules as prototypes/ARM_BRIEF.md and BRIEF.md (read both, plus DESIGN-DE-AI.md strictly). This batch targets
tasks still OPEN in dubhacks-2026/docs/STATUS.md as of Sat Oct 17 evening. Each page must make one open task faster
or safer for the named person, using the real endpoints in controller/server.py and the shapes in docs/CONTRACTS.md.
Do not duplicate 39-46 (handoff path, failure drills, demo coach, calibration, inference monitor, servo health,
table template, grasp cards); link to them where relevant instead. Pick a different named style than your neighbours.
Smoke: cd /private/tmp/claude-502/-Users-caide-1-Documents-dubhacks/535a9f5f-9616-49bb-9ec5-876e04b8c64d/scratchpad
&& node smoke.mjs NN   (must print OK twice, no HSCROLL). Read shots/NN-*-d.png and -m.png once and fix what looks off.
Optional live check: from dubhacks-2026/, `.venv/bin/python -m controller --fake-arm` on :8000 (kill it after).
