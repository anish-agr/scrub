# voice

Owner: Caiden. Tasks C3, C4, C7 in `docs/TASKS.md`.

TypeScript on Node 20, port 3000. Photon number, then the ElevenLabs agent over SIP (photon.codes/docs/beta/cookbooks/voice/elevenlabs), then what it hears comes here. "stop" goes straight to `POST /stop`. Everything else goes to Gemini (structured output: one action, one item id from the current setting), then `POST /command`. Speaks the `say` line of each event from `WS /events`. Texts the end-of-case summary on Photon.

Done when: "grab me the kelly" on the call becomes `handover hemostat` at the controller and Scrub answers out loud.

## Run and test

- `npm run dev` (port 3000). `CONTROLLER_URL` and `VOICE_PORT` from the shell override `.env`, so a test copy can run beside the real one: `CONTROLLER_URL=http://localhost:8071 VOICE_PORT=3071 npm run dev`.
- No call needed: `curl -XPOST localhost:3000/heard -d '{"text":"grab me the kelly"}'` returns the lines Scrub would say. Checked Oct 17 with Gemini live: kelly, mayo, "knife please", "what's out" and "stop" all map right. The first Gemini call after start can pass the 1.5 s timeout and fall back to the alias match.
- `npm test`: offline checks for the alias match (punctuation in names, "needle-nose") and the case summary counts.
- The setting is cached for 30 s and dropped when an event shows a different setting, so a turn doesn't wait on `GET /setting` before Gemini.
- End-of-case summary: the count comes first, from the controller's own `out` list. A no-pull or no-hand set-down is listed as "set at the safe spot", not as a pass; a pick that worked on the retry is not a failed request.
