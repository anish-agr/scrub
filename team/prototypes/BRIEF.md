# Prototype brief (all prototype agents read this)

Context: DubHacks 2026 (UW Seattle, Oct 17-18), theme "Let's Get Cookin'". Team of 4 builds on an SO-101 robot arm The theme is loose: projects do not need to be about cooking or kitchens.
(Perceptron Robotics track: pre-trained checkpoint + fine-tuning via demos; Perceptron Perception API for
object localization / OCR / captioning / video event detection). The hardware task is still being chosen by the team;
software must work against a MOCK arm. Existing concept "Reach" (../reach/) = assistive arm: user speaks/taps a
request, camera detects items, arm fetches to lap tray, risky tasks (pills) text a caregiver via Photon (iMessage/SMS)
for approval, big latched STOP on every screen.

Judging rubric: Functionality 30, Track fit 30, Design 20 (UI clarity, professional look), Creativity 20.
A robot arm with no interface scores poorly on Design, so UI matters a lot.
Side tracks we can stack: Perceptron Robotics, Perceptron Perception, Photon (messaging agent), Gemini API,
Tiger Data (time-series Postgres), Backboard (AI memory/RAG), MongoDB Atlas, Vultr (cloud GPU), Solana, GoDaddy domain.

Winner lessons (LeRobot hackathon): make the learned component observable (camera inputs, chosen target, policy state,
action replay, post-action verification); show failure honestly; one robust motion + perception + verification;
a nonvisual signal (EMG, load, contact, caregiver approval) makes it distinctive; data tooling (Data Surgeon) can win.

## Rules for every prototype
- ONE self-contained .html file in /Users/caide_1/Documents/dubhacks/prototypes/ (inline CSS + JS). External scripts only
  from cdnjs.cloudflare.com / cdn.jsdelivr.net/npm / unpkg.com; fonts only from Google Fonts. Must open by double-click.
- Fully clickable with realistic, animated MOCK data (fake camera feed via canvas/SVG, fake telemetry, fake messages).
  It should feel alive within 2 seconds of opening.
- Polished, distinct visual identity per prototype (do not all look the same). Responsive down to 390px width.
- Include `<title>` (2-4 words) and `<meta name="description" content="one sentence">` and an HTML comment at top:
  `<!-- FEATURES: bullet list --> <!-- SPONSORS: which tracks it serves --> <!-- BACKEND HOOKS: which REST/WS endpoints it would call -->`
- If it would talk to Reach, use the contract in docs/CONTRACTS.md (older prototypes used a local reach/ contract) (REST /api/state, /api/detect, /api/request,
  WebSocket /ws events) but default to mock mode so it works with no server.
- A visible STOP control on anything that moves the arm. No em dashes in UI copy. 44px tap targets.
- Keep each file under ~1200 lines. Do not edit files outside prototypes/ except your own outputs.
- Final report: filename(s), 3-line summary each, and 3 follow-up build tasks each (for the 24h backlog).
