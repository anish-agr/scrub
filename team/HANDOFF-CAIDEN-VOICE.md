# Caiden: Which one handoff and live voice API

Written Oct 18 after `e69bdca` landed on main. This is the handoff for the next agent on Caiden's Mac, not proof of a real phone call or a hardware acceptance run. Read current code and history before acting. Submit Devpost by 9:30 AM Sunday; judging starts at 10:30.

## Goal

Finish and prove the existing voice API path: Photon phone/text transport, ElevenLabs speech and Custom LLM, Scrub's TypeScript voice server, and the actual working arm path. Keep the new Which one behavior. Do not replace the speech provider, parser or arm driver merely to make a new implementation.

Read these first:

1. This handoff, then [voice/README.md](../voice/README.md), especially Which one and Call setup.
2. `voice/src/server.ts`, `turn.ts`, `dialogue.ts`, `text-queue.ts`, `parse.ts`, `controller.ts`, `texts.ts` and `choice.ts`.
3. `voice/scripts/agent.ts`, `photon.ts`, and the relevant parts of `controller/run_all.py`.
4. [Contracts](../docs/CONTRACTS.md), [station README](../explore/station/README.md), `explore/station/autopick.py`, and `controller/core.py`.
5. Recent commit history, [integration evidence](../docs/INTEGRATION.md), and [remaining work](LEFT.md). Older status paragraphs can be stale.

## Already on main: preserve this

- Deterministic name/alias/group matching before Gemini. Optional settings `group` and `variant`; bench has flathead and Phillips screwdrivers. Surgical training settings are unchanged. Curved/straight hemostats are test fixtures only.
- Questions belong to a call or text thread. Variant, full-name, ordinal, position, either/any/you-pick, cancel and stop answers are handled. Either prefers real measured success, then available distance/position evidence; fake/sim rates are not real measurements.
- Another one, same again, the other one, put it back, and take it back use that conversation's history. Low-confidence model interpretations require confirmation. Already-out instruments get a spoken response or an offer of a separately detected copy.
- Real 15-second timers clear pending state and log terminal outcomes. Streaming call replies remain open so the question is spoken immediately and the timeout can be spoken at expiry. Interruption closes that reply, not the pending question. Closed replies cannot receive unsolicited audio; the existing scoped stale-line queue is the fallback. Local `/heard` and texts return promptly.
- Stop bypasses parsing and ordinary text work. Text queues are per thread, with receipt-time generations: an old queued request must not execute after stop and reset.
- Controller replies/events can carry `clarify`, `candidates`, `question_id`, and `confirm`. Answers to controller-issued questions must echo that question id. Do not send a local voice-only telemetry id as a controller answer. `instance` carries variant, side or one-based slot.
- Physical detections live in TrayState `candidates`, separately from configured `slots`. Stable identities and known multiplicity survive stale/local reads and locator timeouts. No selecting the first box on uncertainty. Real physical selections require verified calibrated coordinates before wake and use a targeting method, not a model/plain taught pick that ignores the selected copy.
- `out` remains the unique item-type list. `out_instances` is the physical-unit count. Returning one copy cannot erase another person's instrument. Preserve instance identity in handover/return events and conversation memory.
- `clarify` and `clarify_answer` events include question ids and answer times. Timeouts/cancellations must not count as human answers. Dashboard and ops show waiting questions and physical counts using the existing design system.
- The station has left/right choices, closest selection, timeout holds, and explicit retry without accidentally resuming leader-following. Preserve the latest reach mask, relative-darkness detector, calibrated midpoint, wrist alignment, magnetic grip behavior and recording guards.

Two timing details matter: `POST /command` has a bounded 7-second client budget to cover locator preflight; stop stays on its independent 3-second transport budget and never waits for that command request. Do not restore a 3-second command timeout that says the controller is unreachable while its accepted pick runs afterward.

## Critical integration gap: choose the actual motor owner

The tested voice route is `voice/ -> controller/ -> arm/`. The current real-arm demo can instead be the recording station's Run mode, where AutoPick drives the follower. These are separate runtime paths. The station's Which one buttons do not by themselves connect phone answers to it.

Before wiring the live demo, inspect which process owns the arm and cameras:

- While the station or recorder owns them, test the voice API against an isolated fake/sim controller. Do not launch another real-arm controller or camera process.
- If the demo stays on station AutoPick, finish the smallest tested bridge through the existing gateway and station HTTP API. Forward the selected instance, originating context, question id, answers, progress and spoken replies. Do not import motor control into `voice/` or create a second hardware owner.
- Station questions appear at `/status -> run.driver_status.question` with `id`. The station answer is `POST /control {"action":"clarify_answer","question_id":"...","side":"left|right|closest"}`. A run uses `args.instance`. Translate these into the existing controller/voice clarification contract rather than creating another conversation engine.
- **Stop semantics are not interchangeable.** The station's current `stop` homes the arm; KILL cuts torque and a raised arm drops. Neither is automatically the controller's immediate, latched hold. Do not map spoken stop blindly to either. A station bridge needs a tested same-owner hold/abort path and explicit rearm, or the demo must use the controller path that already provides it.
- Do not silently claim that a successful sim call drove AutoPick. State which backend actually ran. Caiden must supervise any physical acceptance test; agents must not move the arm on their own.

Position conventions also differ: controller overhead view assumes the surgeon at image-bottom, so image-left is their left and larger image y is closer. The station side view assumes the surgeon opposite the camera, so surgeon-left is image-right and closest is image-top. Verify mounting and surgeon position before live side selection. Never forward camera-left as surgeon-left without translation.

## Work order for the voice API

### 1. Sync and establish the current state

Use a clean branch/worktree from fresh `origin/main`; do not discard someone else's dirty work. Before editing an existing file, check `git log -1 --format=%ar -- <file>`. If another agent changed it recently, rebase and reread it. Keep changes small. Never force-push, print keys, or commit `.env`.

Check running services without opening hardware. Inspect key presence only, the voice `/health`, current controller target and backend, the agent's configured URL, Photon plan/number capability, and SIP assignment. Use existing `npm run agent -- status` and `npm run photon -- status`. Do not assume the old 2:40 AM account status is still true.

### 2. Prove the local path without hardware

Use the existing isolated proof from the repo root on the Mac:

```bash
.venv/bin/python -m sim.which_one_smoke --base-port 8300
```

It starts an offline bench sim plus voice on private ports, refuses occupied ports, asks screwdriver, answers Phillips, checks that nothing moved before the answer and only Phillips was handed, then exercises the streaming call timeout. It stops its own processes. `--offline` deliberately disables provider keys, so this does not prove Photon, speech recognition or speech synthesis.

### 3. Finish provider configuration and the public endpoint

- Retain Photon -> ElevenLabs -> Custom LLM. Verify current provider documentation and account capability rather than assuming a shared text line can accept calls. The earlier account check found that shared lines could not; a callable number or account change may need a person.
- ElevenLabs must use Scrub's OpenAI-compatible streaming Custom LLM endpoint, not a separate general-purpose assistant that invents robot actions. Existing `agent.ts` config uses a base URL ending in `/v1`; `server.ts` serves `/v1/chat/completions`.
- Keep both `Caller: {{system__caller_id}}` and `Conversation: {{system__conversation_id}}` in the agent context. A stable conversation id is necessary across the question and answer. Keep interruptions enabled and the `interruption` event; do not shorten provider timeouts below the 15-second clarification window.
- Preserve `VOICE_LLM_SECRET` authentication for the public endpoint and forwarded `/heard` requests. Check missing/bad credentials fail without issuing a command. Redact provider error bodies that might echo secrets.
- Use the current tunnel/public URL tooling and automatic agent repointing. Test URL rotation/restart and the public health/self-check. Do not create a second Photon listener against the same line during testing.
- Keep the controller target on a fake/sim backend while the real arm is owned by the recorder/station. A public URL or `npm run agent -- test` can issue real handovers if pointed at a live backend. The provider's simulated-conversation endpoint is not a substitute for a real call and has previously returned errors despite reaching Scrub.
- Do not purchase a number or subscription, enter a payment flow, or handle verification on someone's behalf. Give Anish/Caiden exact numbered clicks and expected screens, including any displayed cost, and keep working on unblocked software tasks.

### 4. Prove the real call and texts

First run the real provider path against fake/sim, with one intended voice/Photon listener. Then Caiden can supervise the selected hardware path when the arm is free. Record evidence for each row; HTTP/SSE success alone is not a real phone-call result.

| Check | Required observation |
| --- | --- |
| Call connects | A real phone reaches Scrub and hears the reply; log which backend was attached |
| Name ambiguity | Screwdriver asks flathead or Phillips; no command before the answer; Phillips selects only Phillips |
| By-sight ambiguity | Two fake/verified instances ask left/right; the reply carries the current question id and selected instance |
| Context | Call and text-thread questions stay separate; another/other/put-it-back refer to that person's history |
| Uncertainty | An uncertain single interpretation asks for yes/no and does not move before yes |
| Timeout/cancel | About 15 s clears the question and speaks the wait line while the stream is open; cancel issues no new movement |
| Stop | Voice or text stop bypasses a pending question, model parse, slow photo/summary and queued text; reset cannot revive an old queued request |
| Normal commands | Hemostat, got it, count and named return work; preserve optional read commands and sharp safe-zone behavior |
| Text transport | A real restock text replies; end of case reaches the intended thread with a working replay link |
| Restart/fallback | Current public URL still works after restart/repointing; `/talk` remains a labeled no-phone fallback |

Measure actual caller-to-reply timing separately from server parse/first-line timing. Save a short real-call recording with the participant's knowledge if needed for the demo. Mark simulation shots and never present synthetic success rates as real-arm evidence.

## Regression commands and known evidence

Run from the repo root, except the npm commands in `voice/`:

```bash
.venv/bin/python -m pytest -q controller voice
(cd voice && npm test && npm run typecheck)
.venv/bin/python -m pytest -q explore/station
.venv/bin/python -m pytest -q sim/test_sim.py sim/test_web_layout.py sim/test_which_one_smoke.py
.venv/bin/python -m pytest -q vision dashboard/test_clarify.py design/test_ui.py
```

Windows handoff evidence: controller/voice Python 202 passed; npm tests and typecheck passed; sim plus helpers 23 passed; vision plus UI/helpers 142 passed; latest launcher subset 47 passed. After rebasing onto the newest station code, station had 58 passed and five existing dataset tests failing only because LeRobot was absent. Run those on the Mac's existing LeRobot environment; do not hide or skip them to claim green. The isolated sim proved the Phillips pick and the actual streaming endpoint's 15-second timeout. No arm ports, physical cameras, provider calls or servo settings were exercised by that proof.

Before each push: fetch, rebase on current main, preserve other agents' changes, and rerun affected tests. Do not revert the current calibration, wrist alignment, named-return fix or safety guards to make tests pass. Commit and push small pieces, leave a clean worktree, and do not include unrelated local commits.

## Finish with evidence, not another plan

Update the voice/Photon/ElevenLabs rows of `docs/INTEGRATION.md`, the relevant README and `team/STATE.md`. Keep only actual remaining human actions in `team/LEFT.md`. Report the running backend, non-secret URLs/number, real-call and real-text results, measured timings, passing tests, commits on main, and exact human steps still needed. Claim PASS for the live voice API only after a real call and spoken reply are observed; claim the real-arm path only after Caiden's supervised acceptance. Keep Devpost and track claims consistent with that evidence.
