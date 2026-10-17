# voice

Owner: Caiden. Tasks C3, C4, C7 in `docs/TASKS.md`.

TypeScript on Node 20, port 3000. Photon number, then the ElevenLabs agent over SIP (photon.codes/docs/beta/cookbooks/voice/elevenlabs), then what it hears comes here. "stop" goes straight to `POST /stop`. Everything else goes to Gemini (structured output: one action, one item id from the current setting), then `POST /command`. Speaks the `say` line of each event from `WS /events`. Texts the end-of-case summary on Photon.

Done when: "grab me the kelly" on the call becomes `handover hemostat` at the controller and Scrub answers out loud.
