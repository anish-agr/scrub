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

## Texts

Text the Photon number (same iMessage thread as the end-of-case summary). The listener only starts when `PHOTON_PROJECT_ID` and `PHOTON_API_KEY` are in `.env`; otherwise the server logs `[texts] off`. Gemini reads the text (structured output, the current setting's item ids plus `surgical`/`dental`/`bench`); with no key or a Gemini error it falls back to a local match.

| You text | Scrub replies |
| --- | --- |
| "add a second hemostat to the surgical tray", "added 2 kellys" | `Logged: +1 hemostat on the surgical tray.` The restock is appended to `voice/restocks.jsonl` (git-ignored) until the ledger has an HTTP way in |
| "what's out?", "count" | `Out (2): hemostat, scalpel.` from `GET /state` `out`, plus what the camera says (`out_camera`) when the controller has it |
| "summary", "end of case" | the end-of-case summary, and a new case starts |
| anything else | one help line |

Code in `src/texts.ts`; `npm test` runs it against a fake message stream and fake state, no network.

The end-of-case text (saying "end of case" on the call, or `POST /summary`) goes to the number that called (`Caller:` in the agent's system prompt) or else `PHOTON_SUMMARY_TO`, on that same thread. It names the case: count first, then `Scrub case: surgical, started 2:41 PM (23 min)`, the items used, what was passed, set down or failed, and the median request-to-hand time. Events are grouped by the controller's `case_id` (a new `case_id` starts a new case); without it, one case runs until "end of case".
