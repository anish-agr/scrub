# What's left (Sun Oct 18, 07:30)

People only. Agents handle the rest. What works is in `team/STATE.md`. Delete an item when it's done.

Deadlines: video uploaded unlisted by 9:00, Devpost submitted by 9:30 (locks 10:00), everyone in the HUB Ballroom by 10:20, judging from 10:30.

## Filming (everyone, now until about 8:30)

Shot list is in `team/HANDOFF-7AM.md`. Each shot 20 to 40 s without stopping (start before the ask, stop a few seconds after the arm is home), 3 takes, phone landscape, 1080p 30 fps, exposure locked, a second phone recording audio by the speaker. Lab coat and gloves, no faces.

Name each file `V<slot>-take<n>.mp4` and drop it in `/Users/caide_1/Documents/dubhacks/dubhacks-2026/data/video/kit/real/` (make the folder if it's missing) or send it to Caiden.

- [ ] V1 hemostat: ask, pick, carry, handoff into the gloved hand, release on pull, arm home. Wide and close.
- [ ] V2 Mayo scissors, same.
- [ ] V3 stop mid-move, red STOPPED banner, reset, finish the pass.
- [ ] V4 manual return (a tool put back by hand or jogged).
- [ ] V5 lighting: bright, normal, dim tries, each logged.
- [ ] V6 thermal: screen recording of the temperature graph during a hold, then the arm resting with torque off.
- [ ] V7 dashboard count and the count-sheet OCR read, latency on screen.
- [ ] V8 tray check: one overhead frame through Perceptron detect, result and latency on screen.
- [ ] V9 only if a Perceptron model gets deployed: unedited roll of model picks.
- [ ] V10 sim inserts (agents render these).
- [ ] V11 narration memos from Anish, Caiden, Evan and Brandon: one line per file, quiet room.

## Other people-only items

- [ ] **Brandon:** redeploy the Vultr page from your laptop (this Mac's SSH key is refused): `powershell -File deploy/push_public.ps1 -Target root@144.202.95.111`. Check `curl -s http://144.202.95.111/` no longer says bench tray, fine-tuned, safe spot, Tiger or Backboard (all five were still there at 07:30).
- [ ] **Caiden:** the four Gemini lines are in `.env` on this Mac (checked 07:30). Add them on any other machine that runs voice: `GEMINI_MODEL=gemini-3.8-flash`, `GEMINI_TIMEOUT_MS=8000`, `GEMINI_THINKING_LEVEL=low`, `GEMINI_MAX_OUTPUT_TOKENS=1024`.
- [ ] **Caiden:** upload the video to YouTube, unlisted, by 9:00. Send the link to Evan.
- [ ] **Anish, at 9:00:** run `team/HIDE.md` and make the repo public. Agents don't run it.
- [ ] **Whoever ran the arm 06:32 to 06:59 (voice, dim light, hemostat and scalpel):** say in the chat whether it was the real SO-101. Those 66 events have no `fake_arm` tag, so `docs/DATA.md` keeps them apart as "possibly the real arm, unproven" and the pitch has no real handoff numbers. Confirmed real gives the first real rows.
- [ ] **Evan, before the Devpost:** every `[measured]` number comes from the Pitch and Devpost table in `docs/DATA.md` (read 08:17). Where it says "no real data yet" (real handoff rate and time), don't write a number.
- [ ] **Evan, by 9:30:** submit the final Devpost (text in `team/DEVPOST.md`, video link, public repo link).
