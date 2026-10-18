# State of Scrub (Sun Oct 18, 07:30)

What works today, true only. What's left is in `team/LEFT.md`. Tool-by-tool proof is in `docs/INTEGRATION.md`.

## Works

- Scope: three instruments (scalpel handle, hemostat, Mayo scissors), surgical tray only.
- Real arm: the recording station (`explore/station/`, port 8090) runs the SO-101 and both cameras; at 07:25 it was parked, side camera 30 fps, wrist camera 22.8 fps.
- Real picks: "Pick & hand over" replays an averaged path from our recorded demos per instrument (`explore/station/autopick.py`). This is a skill we taught it, not a model.
- Moves are minimum-jerk with a 45 deg/s peak (1.6x slower above 52 C), so the arm slows as it nears the handoff point.
- The arm holds at the handoff point, lets go on a pull or "let go"/"got it", checks the jaw closed on nothing, and goes home.
- Voice to the real arm: with the station up, voice finds it on localhost:8090 and sends handover, let go, stop, continue, return to home and kill to it (commits 774e2da, 5bd0b37, 380b970).
- Stop: "stop" freezes the arm where it is; "continue" resumes; the controller needs `POST /reset` after a stop.
- Gemini: `gemini-3.8-flash` at thinking low parses a request with no tool name in 2.8 s and asks back when it's unclear; known names skip Gemini. The four Gemini lines are in `.env`.
- Thermal: the station's guard reads motor temperatures every 2 s while it drives the arm (`explore/station/station.py`, `explore/arm_session.py`) and cools it with torque off when hot; `explore/thermal_plot.py` draws the heat graphs.
- Training data: 29 episodes in the station dataset by the 06:49 refresh, 24 usable.
- Perceptron Robotics: the key works; 0 deployments as of 07:10, so no pick on the arm comes from a model.
- Perceptron detect (tray check) and OCR (count sheet, Gemini fallback) answer through `vision/`; detect took about 1.8 s in the integration run.
- Vision on :8001 runs with the real camera and locked exposure (07:25).
- Controller (fake arm), dashboard, ops page and ledger run; the dashboard shows the count.
- Sim: `video/simdemo.py` renders the scripted sim demo, with the return labeled as a simulated electromagnet pickup.
- MongoDB Atlas holds the ledger and thermal samples.
- Vultr page at http://144.202.95.111/ answers, but shows old text until Brandon redeploys.
- Photon line +1 785 867 1047 routes to the ElevenLabs agent and `voice/`; voice health shows the Photon keys loaded.

## Not working or not shown

- No hand detection or tracking. No safe spot. Real return is manual.
- No Perceptron model deployed.
- A real phone call that moves the arm is not confirmed in a log yet.
- No real summary text sent on Photon.
- Lighting tries (bright, normal, dim) not logged yet.
- No domain; the public page is HTTP only.
- Not used: Tiger Data, Backboard, GoDaddy.
