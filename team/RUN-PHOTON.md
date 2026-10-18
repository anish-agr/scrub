# Chat B: the phone call, finished and proven (MUST FINISH)

Say to a new Claude Code chat on the arm Mac: "Pull, then follow team/RUN-PHOTON.md exactly."

---

I'm Caiden on team Scrub at DubHacks '26: an SO-101 arm that passes surgical instruments by voice over a phone call. **We're on a hard time crunch**: it's about 2 AM Sunday, the Devpost locks at 10:00 AM (submit by 9:30), judging at 10:30. **This is flagged: the phone call must work before 6 AM.** It's the core of the demo and the Photon track ($700 / $300, plus $400 for the best voice agent). Right now `docs/INTEGRATION.md` shows the call path as FAIL.

## How to work (read twice)

- **Use subagents in parallel and keep them busy:** one on the ElevenLabs agent, one on Photon and SIP, one on the public URL or tunnel, one on `voice/` tests and the end-to-end check, one writing the exact clicks for Anish. You orchestrate and review. Opus for `voice/` logic, Sonnet for scripts and docs.
- Finish it. Don't ask me questions. Anything only Anish can do in an account (a click, a purchase, a verification code) goes to him as numbered clicks with what he should see after each, and you keep working on the rest.
- Other Claude chats run on this Mac. Before editing a file run `git log -1 --format=%ar -- <file>`; skip it if someone changed it in the last 10 minutes. Commit small, `git pull --rebase` before every push. Never print or commit keys; they're in `.env`.
- You own `voice/`, `deploy/` phone scripts, the voice and phone parts of `controller/run_all.py`, `voice/README.md`, and the Photon, ElevenLabs and voice rows of `docs/INTEGRATION.md`. My main chat already pushed `ed7a529` (an ElevenLabs agent script with the Custom LLM pointed at `voice/`, a Photon voice and SIP setup script, `run_all --real` starting the tunnel). Start from that; read `git log -5 -- voice deploy controller/run_all.py` first.

## Read first

`voice/README.md`, `voice/src/*.ts`, `voice/scripts/`, `docs/INTEGRATION.md`, `docs/CONTRACTS.md`, the Photon docs (https://photon.codes/docs and https://photon.codes/docs/beta/cookbooks/voice/elevenlabs), ElevenLabs agents docs (https://elevenlabs.io/docs), and the Photon rules in `team/research/` if present.

## Done means all of this, tested for real

1. Anish calls the Scrub number from his phone. The ElevenLabs agent answers in under 3 s.
2. He says "hemostat". The agent's Custom LLM call reaches `voice/`, Gemini turns it into one command from the tray's fixed list, the controller runs it on the arm (the sim if the real arm is busy), and the spoken reply comes back ("Hemostat coming").
3. "Stop" freezes the arm at once without waiting on Gemini.
4. "Count", "read the count sheet", "what tray is this" and "take back the hemostat" work on the call.
5. "End of case" sends the case summary as a text (iMessage or SMS) in the same Photon thread, with a replay link that opens on a phone (the Vultr IP if there's no domain).
6. A text to the number ("add a second hemostat to the surgical tray") gets a reply.
7. `python -m controller.run_all --real` starts voice, the tunnel or public URL, and prints the phone number. The URL stays the same across restarts, or the agent config is updated automatically on start.
8. A judge can call too: no allowlist blocks an unknown number, and nothing breaks if two calls overlap (the second hears "Scrub is busy").

## Also

- Measure and log per turn: speech-to-command time, Gemini latency, controller time, total time to the spoken reply. Put the median on the ops page (`/state` or voice `/health`) and in `docs/INTEGRATION.md`.
- A fallback that needs no phone network: a page or CLI that speaks to `voice/` the same way the agent does, for when the venue's signal fails. Label it on the dashboard.
- Run the voice test suite and add tests for anything new. Record a 30-second screen and audio capture of a real call into `data/video/raw/` for the demo video.

## Before you stop

Everything pushed (`git status` clean, nothing ahead of `origin/main`). The Photon, ElevenLabs and voice rows in `docs/INTEGRATION.md` are PASS with the proof command, or say exactly what's missing and who does it. Add what's left to `team/LEFT.md`. Report the number, the median turn time, and every step Anish still has to do.
