# Audit (comb pass, Sat Oct 17 night)

Every finding from the fine-toothed comb (`team/COMB-PROMPT.md` Phase 2), by severity, with where it was and what happened to it. FIXED items are on `main` with tests. NOT FIXED items say why and who decides.

Tests after the comb: `controller.test_flows` 66/66, `controller.test_run_all` 30, `controller.trials --self-test` 19, arm 94 (9 suites plus the new `arm/test_safety.py`), `vision.test_vision` 41, `ledger.test_ledger` 14, `deploy.test_check_env` 6, `sim/test_sim.py` 16/16, `cd voice && npm test` passes, `npx tsc --noEmit` clean.

## Critical

| # | Where | Problem | Status |
| --- | --- | --- | --- |
| C1 | `arm/real_arm.py` `_playback` | Hold, freeze and the end of every move sent the **measured** joints back as the goal. The STS3215s run P 16, I 0, so a loaded arm sagged more every tick and a jaw closed on a tool went slack (the tool could drop while frozen or waiting for the pull). | FIXED: hold resends the last command. `arm/test_safety.py` HoldTests |
| C2 | `arm/real_arm.py` `_pose`, `move_to`, `_open_gripper` | Moves started from the measured jaw, so carry and home let go of a held tool. | FIXED: `_commanded_start` keeps the commanded grip. GripTests |
| C3 | `arm/streaming.py` `command` | With no chunk covering a tick (first 400 ms of a skill, any late reply), the target drifted toward the measured state. | FIXED: holds the previous command. TimelineTests |
| C4 | `controller/core.py` `stop()` | The generation was bumped before the queue was cleared, outside the lock: a queued handover could run after a stop (reproduced). | FIXED: both under the lock, same in `_hold`. `stop_never_lets_a_queued_job_run` |

## High

| # | Where | Problem | Status |
| --- | --- | --- | --- |
| H1 | `controller/core.py` `set_setting` | A tray switch while stopped or in error set the step to idle: the next handover ran with no reset. | FIXED: a switch never clears a stop. Test |
| H2 | `controller/core.py` `_reset` | A stop landing as a reset started was undone by `resume()`. | FIXED: checks before and after, freezes again. Test |
| H3 | `arm/real_arm.py` `run_skill` | One 503, timeout or expired session froze the arm, and the APIError was swallowed. | FIXED: retry, reset or re-grant, then raise `APIError` after 5 failures. 5 tests |
| H4 | `arm/perceptron.py` | Every inference call had a 0.4 s timeout, including opening a session (cold container). | FIXED: predict 0.4 s, create/contract 15 s, reset/delete 3 s |
| H5 | `arm/real_arm.py` `_settled` | A move only ended within 1 deg of every goal; loaded P-only joints stop short, so home and carry would time out and freeze. | FIXED: within 5 deg and still for 0.3 s also counts |
| H6 | `arm/real_arm.py` | The policy commands "closed" past the contact point, so the jaw sat stalled at 50% torque (the Oct 17 overheating). | FIXED: claw guard (hold at contact + 1.5) and a jaw range clamp. 2 tests |
| H7 | `arm/backends.py`, `arm/teach.py`, `arm/record.py` | macOS doesn't lock serial ports: teach (torque off) could drop an arm the controller holds. | FIXED: refuse a port another process holds (`lsof`). Tests. `explore/arm_session.py` still lacks it (below) |
| H8 | `arm/real_arm.py` | A return skill ended when the jaw closed on the item, so the arm homed holding it. | FIXED: succeeds only after release. Test |
| H9 | `voice/src/summary.ts` | The end-of-case text could say "everything is back on the tray" with items still out (second summary, or after a voice restart). | FIXED: count from controller `GET /state`. Test |
| H10 | `voice/src/cases.ts` | "go grab the kelly off the surgical tray" switched trays (and cleared the count). | FIXED: the switch word must lead into the tray word. Tests |
| H11 | `voice/src/config.ts` | Blanking Photon keys in the shell did nothing: a test voice opened a second listener on the live line. | FIXED: an empty shell value blanks the key. Use `VOICE_NO_KEYS=1` for test copies |
| H12 | `vision/service.py` | Event clips were deduped by `command_id` alone, so no handover clip was ever saved live. | FIXED. Test |
| H13 | `deploy/`, `ledger/` | Two installers fought over the server (port 80 vs 8080); the push copied the whole `.env` and `buffer.jsonl`. | FIXED: one path (`deploy/setup_public.sh`), server gets only `MONGODB_URI` and `SCRUB_PUBLIC_URL` |
| H14 | `ledger/__init__.py` | Fake-arm runs counted in `/stats` rates and medians. | FIXED: `fake_arm`/`sim` rows left out (`?sim=1` includes them); the controller tags every event and restock. Tests |
| H15 | `team/NEXT-PASS-PROMPT.md` (section "Earlier next-steps notes") | The ROI table showed $560 to $800 saved minus $750 as a gain, from unsourced savings. | FIXED: one sourced number ($36 per OR minute, JAMA Surgery 2018), break-even 22 OR minutes a month per room |
| H17 | `voice/src/turn.ts` | Lines spoken while no turn was open piled up and were all read at the next turn (20 lines from 15 minutes before "Mayo scissors coming"). | FIXED: lines over 10 s old dropped, at most 2 read. Test |
| H18 | `controller/core.py` | A controller restart mid-case forgot `out`: "what's out" said everything was on the tray. | FIXED: count and case saved per port and restored within 6 h on the same tray. Test |
| H19 | `controller/__main__.py`, `server.py` | With a WebSocket client connected, SIGTERM or Ctrl-C never exited, so `arm.disconnect()` never ran and the real arm's serial port stayed held. | FIXED: graceful timeout, SIGTERM acts like Ctrl-C, the arm always disconnects. Checked by hand on fake and sim |
| H16 | `sim/scene.py` | A cross-tray fallback (commit c4fffd9) gave another tray's item the slot at the same index, so on the surgical tray "wire cutters" picked whatever sat there. | FIXED: active tray only. `sim/test_sim.py` 16/16 |

## Medium

- FIXED:
  - **Controller:** the stats fallback has the ledger's shape, so the dashboard tables fill without the ledger. A closed page can't kill the worker thread. A NaN hand target is refused. A tray switch keeps the count (voice names what's still out).
  - **Voice:**
    - `say.ts` no longer redirects the next real summary to a fake caller.
    - Timeouts: Photon 15 s, Gemini summary 8 s, text reply 30 s.
    - The events websocket has a heartbeat.
    - A repeated refusal is no longer muted, and "got it" no longer holds 8 s.
    - `/heard` and `/summary` need the LLM secret through the tunnel when it's set.
  - **Vision:**
    - `/tray_check` reports stale with no read or a hung detect.
    - `in_slot_of` is never a fake item.
    - Clip routes are safe from path traversal, and the clip buffer is bounded (it was about 400 MB).
    - Hand posts no longer wait on the tray loop.
  - **Ledger and deploy:** CORS on the read-only `/api/*`, and the server binds 127.0.0.1 behind nginx. `python -m deploy` reads the Spectrum key names and passes a vision key on HTTP 400. 3 s timeouts on every polling fetch. Phone table spacing on the judge page.
  - **Presented docs:** dental removed everywhere a judge looks, and the speaker roles are the same in every doc. DEMO used `run_all check` without `--url` (it never checked the live stack). The table card showed "[the number goes here]". QNA claimed a gripper guard that only the recorder had (now true for the real arm too, H6).
  - **From the full-stack sim test:**
    - Voice hold raised to 14 s (the scalpel set-down took 8.2 s).
    - "check the tray" works on the sim and backup stacks (falls back to the controller's TrayState).
    - "thanks got it" and "take back the X" parse without Gemini.
    - Voice starts the Photon listener only after it owns its port.
    - The nurse console fits 390 px and lost its dev wording.
    - A moved `run_all` stack prints its own dashboard URL.
    - `run_all reset` no longer makes an empty case.
    - A blocked path says "Something's in the way".
    - `ledger.shots` and `ledger.qr` take `--help`.
    - `npm test` no longer reads the real keys or the live controller.
- FIXED later on Oct 18 (NEXT-PASS combs):
  - `controller.trials --practice --tries 2` scored 1/2 on the fake arm. The cause was a race between reading state and events; trials and smoke now read events first.
  - MongoDB reconnect: `/stats` answers from a cached Atlas copy plus the local buffer and never waits on MongoDB; the reconnect uploads in batches outside the lock.
  - `explore/arm_session.py` passes `--robot.use_degrees=true` and `--teleop.use_degrees=true` and refuses a port another process holds.
- NOT FIXED (measure on hardware):
  - M6 `arm/real_arm.py`: the 400 ms deadline is measured after the frame is grabbed and encoded, so image age at execution can reach about 580 ms. Decide after measuring `counters.late` on the real arm.
  - M7: about 1 MB of PNG per predict twice a second on venue Wi-Fi. Measure `counters.late`; use a hotspot or wired link if most replies are late.
  - M8: prepare opens 6 sessions at once; the deployment may cap them (three `HTTP 409` lines at start mean it does).

## Low

- FIXED:
  - Hidden-tray replies no longer say "dental", and a dental restock is refused.
  - "End of case" only promises a text when one can be sent. Stop retries once.
  - `say.ts` no longer crashes on a split SSE chunk.
  - Request body limits in voice.
  - Tray warnings once per outage.
  - One persistent Perceptron client in vision.
  - Calibration mm z fix.
  - `/favicon.ico` 204 on the public page.
  - `.gitignore` covers logs, buffers, parquet, avi.
  - The demo console speaker cues match the pitch.
  - `/arm/pose` has `counters` and `last_reason` for first contact.
- FIXED later on Oct 18 (NEXT-PASS combs):
  - The hand watcher freezes after `HAND_CLOSED_READS` (3) closed reads in a row on the fast leg. One closed read between open ones is ignored.
  - A failed return still holding the item sets it at the safe spot.
  - Vision binds 127.0.0.1 by default (`VISION_HOST=0.0.0.0` to show the stream on a phone or tablet).
  - Voice backfills missed events from `/events/recent` on reconnect, so the summary counts every pass.
- NOT FIXED:
  - With vision down for 5 s, the arm uses the saved spot with no hand check. **Team decision** before the real arm demo.

## Facts the comb checked that matter on stage

- **Statistics:** every number in the pitch, slides, Devpost and QNA was opened at its source (list in `team/PITCH.md`). Dropped as unconfirmed: 42.9% turnover, $200 to $400 per shift, $35 to $50 an hour agency, Class II at $2 to 6M, the lux values (computed, not measured), "under $500".
- **Don't say on stage:** "Instrument handoffs take 7.7% of OR time." That line in `explore/research/SURGEON_RESEARCH.md` section 2 misreads a study of scrub nurse shift handoffs.
- **Repo going public:** history scanned for keys (no hits), no file over 300 KB in history, `.env` never committed.

## Safety checklist (verified in code, with tests)

| Rule | Where |
| --- | --- |
| Stop works from every state and thread | `controller/core.py` `stop()` (lock held briefly, never across an arm call), `_hold`, `_fail`; `/stop` skips the queue; `real_arm.freeze()` only sets events |
| Freeze holds the arm | `arm/real_arm.py` hold resends the last command until `resume` (C1) |
| A late or stale chunk never runs | `arm/streaming.py` drops arrivals at or past capture + 400 ms; no accept after freeze |
| Handoff only inside the region, only to an open hand | `arm/motion.py` region check on every interpolated point; `_hand_ready` needs a fresh, open, finite target with a clear path. Caveats in Low |
| Sharps never go hand to hand | `controller/core.py` sends `sharp` items to `_set_down`; a reset with a held item goes to the safe spot |
| Reset after a stop needs a person | only `POST /reset` rearms; a tray switch no longer clears a stop (H1); a stop during rearm wins (H2) |
| The gripper never squeezes past its limit | servo torque cap (LeRobot), claw guard and range clamp (H6) |
| Nothing moves the arm except the controller | busy-port refusal (H7); only `controller/__main__.py` imports `arm.real_arm` |
