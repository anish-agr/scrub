# voice

Owner: Caiden. Tasks C3, C4, C7 in `docs/TASKS.md`.

TypeScript on Node 20, port 3000. Code in `src/` (`server.ts` is the entry), `scripts/say.ts` (one fake caller turn), `scripts/test.ts` (`npm test`). Photon number, then the ElevenLabs agent over SIP (photon.codes/docs/beta/cookbooks/voice/elevenlabs), then what it hears comes here. "stop" goes straight to `POST /stop`. Everything else goes to Gemini (structured output: one action, one item id from the current setting), then `POST /command`. Speaks the `say` line of each event from `WS /events`. Texts the end-of-case summary on Photon.

Done when: "grab me the kelly" on the call becomes `handover hemostat` at the controller and Scrub answers out loud.

## How a call reaches us

caller -> Photon number -> Photon Voice profile (SIP, TLS) -> ElevenLabs agent (speech to text, text to speech) -> its LLM is "Custom LLM" = our `POST /v1/chat/completions` through a public tunnel. Each caller turn prints `[heard] ...`. The reply streams back as OpenAI `chat.completion.chunk` SSE lines (`data: {...}\n\n`, then `data: [DONE]\n\n`) and the agent speaks them. The first chunk goes out before the controller answers; the reply stays open up to `VOICE_HOLD_S` (14 s: longer than the 10 s hand wait plus a set-down) to speak follow-up event lines ("Scalpel down."). A line that lands with no turn open (a dashboard or smoke handover) is spoken at the start of the next turn only if it is under 10 s old, and only the last 2.

- We only act when the last message is the caller's. ElevenLabs also asks for a reply after silence; that gets an empty reply instead of a repeated command.
- The system prompt line `Caller: {{system__caller_id}}` gives us the caller's number for the summary text (`[case] caller +1...`). If that line never prints, Photon isn't passing caller id over SIP: set `PHOTON_SUMMARY_TO` in `.env`.
- Optional: `VOICE_LLM_SECRET=<anything>` in `.env` makes the endpoint require `Authorization: Bearer <it>`. ElevenLabs sends its `OPENAI_API_KEY` secret that way, so give that secret the same value. A mismatch prints `[server] 401`. With it set, `POST /heard` and `POST /summary` also need it when they come through the tunnel (a forwarding header, or not loopback); plain local curl still works.
- Any other path prints `[server] 404 POST /...`: the Custom LLM URL is wrong.

## Run and test

- `npm run dev` (port 3000). `CONTROLLER_URL` and `VOICE_PORT` from the shell override `.env`, so a test copy can run beside the real one: `CONTROLLER_URL=http://localhost:8071 VOICE_PORT=3071 npm run dev`. Keys only come from `.env`. For a test copy, use `VOICE_NO_KEYS=1`: it ignores `.env`, so the copy never calls Gemini or Photon and never texts: `VOICE_NO_KEYS=1 CONTROLLER_URL=http://localhost:8071 VOICE_PORT=3071 npm run dev` (it logs `[texts] off`). A key set to empty in the shell (`PHOTON_API_KEY= ...`) also blanks just that key.
- `curl localhost:3000/health`: `{"ok":true,"keys":{"gemini":..,"photon":..,"llm_secret":..},"controller":true,"controller_url":"http://localhost:8000","turns":3,"gemini_ms":412,"gemini_p50_ms":380}`. Booleans only for keys, never values. `gemini_ms` is the last Gemini parse time and `gemini_p50_ms` the median of the last 50 (null before any). GET answers send `access-control-allow-origin: *`. When an event carries `skill_source: "taught"`, the `[say]` log line ends `, taught skill)` and the end-of-case summary adds a line such as `3 handovers: 2 by the model, 1 by a taught skill`. The spoken reply is unchanged.
- No call needed: `npm run say -- "grab me the kelly"` sends what ElevenLabs sends and prints the streamed reply with timings. It sends no caller id, so it never changes where the live server's end-of-case text goes; `SAY_CALLER=+1...` acts as that caller. `VOICE_URL=https://<tunnel> npm run say -- "stop"` does it through the tunnel. `curl -XPOST localhost:3000/heard -d '{"text":"grab me the kelly"}'` returns the lines as JSON.
- Robot-model errors: the controller's `error` events (optional `code` 401, 409 or 503, and a `say` line) are spoken like any event line, during a turn and in the hold window, and end the hold. The end-of-case summary does not count them as failed requests.
- `npm test`: offline. Its fake controller uses ports 3020-3023 and its voice server 3024-3027; in-process code points at 3029, where nothing listens, so it never reaches the live controller on 8000. Alias match, case summary counts, caller id and last-message rules, and the real server against a fake controller: SSE chunk shape, `[DONE]`, "stop" hits only `POST /stop` (no `/setting`, no Gemini, no `/command`), "check the tray" hits only `GET /tray_check`, `/health`, and passes made while the events socket was down still counted after the reconnect. `VOICE_NO_KEYS=1` (set by `scripts/test-env.ts`, imported first by the test) ignores `.env`, so it never calls Gemini or Photon.
- Gemini: checked Oct 17 live, kelly, mayo, "knife please", "what's out" and "stop" all map right. The first Gemini call after start can pass the 1.5 s timeout and fall back to the alias match.
- Nothing waits forever: the `WS /events` socket pings every 5 s and reconnects after a missed pong (a controller that went away without closing). After a reconnect it reads `GET /events/recent?n=500` from the newest event it saw before the drop and adds the missed events to the case summary (`[events] backfill checked N events since the drop`), deduped by event (`t`, `type`, `command_id`, `item`). Missed lines are never spoken. A drop longer than the controller's last 500 events can still undercount. A Photon connect or send fails after 15 s, a text reply after 30 s, and the summary uses the template if Gemini takes over 8 s. "stop" retries `POST /stop` once.
- The setting is cached for 30 s and dropped when an event shows a different setting, so a turn doesn't wait on `GET /setting` before Gemini.
- Clinic words (X6): "call the hemostat a clamp", "clamp means the hemostat", "when I say clamp I mean the hemostat" are caught by a local pattern (`parseAlias` in `src/parse.ts`) before Gemini, on the call and by text (texts also have a Gemini `alias` kind). The item side has to name an item on the tray. They go to the controller's `POST /alias` (saved in `settings/<id>.local.json`), Scrub says its `say`, and the cached setting is dropped so the next turn hears the new word. The Command action enum is unchanged.
- End-of-case summary: the count comes first, from the controller's own `out` list. A no-pull or no-hand set-down is listed as "set at the safe spot", not as a pass; a pick that worked on the retry is not a failed request.

## Texts

Text the Photon number (same iMessage thread as the end-of-case summary). The listener only starts when `PHOTON_PROJECT_ID` and `PHOTON_API_KEY` are in `.env`; otherwise the server logs `[texts] off`. Gemini reads the text (structured output, the current setting's item ids plus `surgical`/`bench`); with no key or a Gemini error it falls back to a local match.

| You text | Scrub replies |
| --- | --- |
| "add a second hemostat to the surgical tray", "added 2 kellys" | `Logged: +1 hemostat on the surgical tray.` Logged to the ledger through the controller's `POST /restock`; if that fails or the ledger isn't loaded, appended to `voice/restocks.jsonl` (git-ignored) |
| "what's out?", "count" | `Out (2): hemostat, scalpel.` from `GET /state` `out`, plus what the camera says (`out_camera`) when the controller has it |
| "check the tray", "is the tray ready?", "tray check" | `Tray ready: Operating room, all 3 instruments in place.` when it passes, else the controller's line ("Missing the scalpel.", "I can't check the tray right now."). From `GET /tray_check`, matched before Gemini |
| "summary", "end of case" | the end-of-case summary, and a new case starts (plus the case link line, below) |
| "start a bench case", "switch to the bench tray", "surgical case", "start a robotics case" | `Bench case started: needle-nose pliers, wire cutters, hex key.` (names from the setting file `POST /setting` returns). The controller starts a new `case_id`; the previous case's summary is not sent. The switch clears the controller's count, so anything still out is added to the reply (`Still out from the last tray: wire cutters.`). 409: `The arm is busy. Stop or wait, then try again.` Saying it on the call does the same (a local phrase match before Gemini, `src/cases.ts`). The switch word has to lead into the tray word ("switch to the bench tray"), because a switch clears the count: "go grab the kelly off the surgical tray" stays a handover. Voice offers surgical, then bench. Dental is hidden: "start a dental case" gets `That tray isn't set up for this demo. I have the surgical and bench trays.` (the reply never names it) and nothing is posted or logged (the controller can still load it from the keyboard or dashboard) |
| "call the hemostat a clamp", "clamp means the hemostat", "when I say clamp I mean the hemostat" | the controller's `POST /alias` line: `Got it: clamp means the hemostat.` (or `Clamp already means the X.`) |
| anything else | one help line (`Text me "add a hemostat to the surgical tray", "what's out?", "switch to the bench tray" or "summary".`) |

Judge mode: when `GET /state` has `judge: true`, the controller only takes handover, count, stop and got_it. Voice then never posts `/setting`, `/alias` or `/restock` (tray switches, clinic words, restocks, by call or text) and answers `In judge mode I can hand you an instrument, read the count, or stop.` On the call the flag comes from `GET /state`, cached `VOICE_JUDGE_TTL_MS` (3000) and only asked on those paths, so stop and handover never wait on it. A 403 from `POST /setting` or `/alias` gets the same line.

Code in `src/texts.ts`; `npm test` runs it against a fake message stream and fake state, no network.

The end-of-case text (saying "end of case" on the call, or `POST /summary`) goes to the number that called (`Caller:` in the agent's system prompt) or else `PHOTON_SUMMARY_TO`, on that same thread. It names the case: count first, then `Scrub case: surgical, started 2:41 PM (23 min)`, the items used, what was passed, set down or failed, and the median request-to-hand time. Events are grouped by the controller's `case_id` (a new `case_id` starts a new case); without it, one case runs until "end of case".

Case link: with `SCRUB_PUBLIC_URL` set (non-secret, `.env` or shell, the ledger public page's URL), a second short text follows the summary: `Case replay: <SCRUB_PUBLIC_URL>/case.html?id=<case_id>` (Evan's replay page on the ledger public site). A "summary" text gets the same line after the summary in its reply. Unset, or no `case_id` from the controller: nothing extra.

## Tunnel

ElevenLabs has to reach port 3000 from the internet. Every tunnel below gives a new URL each start (except ngrok's free static domain), and **the ElevenLabs Custom LLM Server URL must be updated to match every time**.

- `npm run tunnel`: Pinggy over SSH on port 443, no account. Works on the venue Wi-Fi (Oct 17). Prints `https://<x>.run.pinggy-free.link`. Free tunnels end after 60 min: run it again and paste the new URL.
- `npm run tunnel:cf`: cloudflared quick tunnel (`voice/.bin/cloudflared`, gitignored; `--protocol http2`). Needs outbound port 7844, which the venue Wi-Fi blocks (UDP and TCP: "dial tcp ...:7844: i/o timeout"). Use it on a phone hotspot.
- `npm run tunnel:ngrok`: needs a free ngrok account once: `ngrok config add-authtoken <token>` (a human, from dashboard.ngrok.com). Claim the free static domain there and run `ngrok http --url=<name>.ngrok-free.app 3000` so the URL never changes.

Measured Oct 17, fake-arm controller, alias match (no Gemini): request to first streamed byte about 20 ms locally, 0.5 to 0.75 s through Pinggy on a fresh connection (about 0.27 s of that is the TLS handshake). The spoken line follows 0 to 60 ms later; "stop" is the fastest path (no setting fetch, no Gemini). Gemini adds up to the 1.5 s timeout.

## Call setup (Caiden)

Only a human can do these. Order: Photon, ElevenLabs agent, import the number, then run.

1. **Run** (three terminals, repo root):
   1. `.venv/bin/python -m controller --fake-arm` (port 8000; add `--pull-s 0` so "got it" is what releases).
   2. `cd voice && npm run dev`. Expect `[events] connected ws://localhost:8000/events`.
   3. `cd voice && npm run tunnel`. Copy the `https://...` URL. Check: `curl https://<tunnel>/health` shows `"controller":true`.
2. **ElevenLabs agent** (elevenlabs.io, Agents): Create agent, Blank.
   - First message: `Scrub here. What do you need?`
   - System prompt: `You are Scrub, a robot arm that passes surgical instruments. Caller: {{system__caller_id}}`
   - LLM: **Custom LLM**. API type **Chat Completions** (not Responses). Server URL: `https://<tunnel>/v1` (we accept `/v1` or the full `/v1/chat/completions`). Model ID: `scrub`. API key: only if you set `VOICE_LLM_SECRET`: Create new secret, name `OPENAI_API_KEY`, value the same string.
   - Advanced: Interruptions on (so "stop" cuts Scrub off). Turn eagerness: Eager. Soft timeout: off. Take turn after silence: 30 s.
   - Voice/ASR: add keywords `kelly, hemostat, scalpel, mayo, scissors, knife`.
   - Test in **Preview** (say "grab me the kelly", watch `[heard]` in terminal 2), then **Publish**.
3. **Photon** (app.photon.codes): your project, **Voice**. Under **Lines** find the number. **Set up default**, **SIP**, **Create profile** (or open the profile the number already uses). Media encryption: **Auto**. Under **Inbound calls**, **Enable inbound**: SIP address `sips:sip.rtc.elevenlabs.io:5061`, Transport **TLS**, no inbound SIP credentials. Outbound is not needed for answering calls; to also let Scrub call out: **Outbound calls**, Digest algorithm **SHA-256**, **Enable outbound**, save the password (shown once), note the **SIP connection** server and port (e.g. `sip.photon.codes:5061`) and **Username**.
4. **Import the number** (ElevenLabs, Deploy, Phone Numbers, Import number, **From SIP Trunk**):
   - Label `Scrub Photon`. Phone number: the Photon number with `+` and country code.
   - Inbound: Media Encryption **Allowed**, Allowed Numbers empty, Allowed Source IP Addresses `0.0.0.0/0`, Remote Domains empty, SIP Trunk Username and Password empty.
   - Outbound (only if enabled in Photon): Address `sip.photon.codes:5061` (no `sip:` prefix; use the server shown in Photon), Transport **TLS**, Media Encryption **Allowed**, codecs G.722, PCMU, PCMA, no custom headers, SIP Trunk Username and Password from Photon.
   - Import. On the number's page, **Agent**: the Scrub agent. **Branch**: Follow traffic split.
5. **Call** the Photon number from a phone. Scrub says "Scrub here. What do you need?"

| Say | Terminal 2 shows | Scrub says |
| --- | --- | --- |
| "grab me the kelly" | `[heard] grab me the kelly`, `[command] handover hemostat` | "Hemostat coming." |
| "got it" | `[command] got_it` | nothing (released) |
| "knife please" | `[command] handover scalpel` | "Scalpel to the safe spot." then "Scalpel down." (sharps never go hand to hand) |
| "what's out" | `[command] count` | "Out: hemostat, scalpel." |
| "stop" | `[command] stop (POST /stop)` | "Stopped." |
| "check the tray", "is the tray ready", "tray check" | `[tray] ready` (or `not ready`, `can't check`) | the controller's `GET /tray_check` `say`: "Tray's ready: scalpel, hemostat, Mayo scissors." / "Missing the scalpel." / "I can't check the tray right now." A pass also texts `Tray ready: Operating room, all 3 instruments in place.` to the caller's thread |
| "hand me the bovie" | `[command] unknown` | "Which instrument? You can say: call the hemostat a crile." |
| "call the hemostat a crile" | `[alias] crile -> hemostat` | "Got it: crile means the hemostat." Then "crile please" hands the hemostat |

`(local)` or `(gemini)` after each command says which parser ran. After "stop", reset the controller (`curl -XPOST localhost:8000/reset`) before the next request. If the call connects but Scrub is silent, check terminal 2: no `[heard]` means the Custom LLM URL is stale (new tunnel URL) or wrong (`[server] 404`); a phone that doesn't ring means Photon inbound or the agent assignment (Photon's troubleshooting table in the cookbook, and **SIP Messages** on the ElevenLabs number page).
