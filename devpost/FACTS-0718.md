# Facts at 07:20, Sun Oct 18

Checked read-only by the H7 facts agent between 07:15 and 07:25. Each line names its source. If a claim in the video, Devpost or page isn't backed here (or by another log), drop it.

## Short table

| Question | Answer | Source |
| --- | --- | --- |
| Photon call on +1 785 867 1047 moved the real arm, logged | **Not confirmed.** A voice turn moved the real arm at 07:02:14 (scalpel), but no log says it came over the phone line | voice log, station log, ElevenLabs API (below) |
| Gemini lines in `.env` | All 4 present. `GEMINI_MODEL=gemini-3.8-flash` | `grep -c '^NAME=.\+' .env` |
| Perceptron training | 0 jobs, 0 deployments | `Perceptron().jobs()`, `python -m arm.train deployments` |
| Real tries in the ledger | 0 trustworthy. The 30 `fake_arm:false` handed rows are test data | MongoDB via `ledger._read_mongo()`, `controller/test_flows.py` |
| Real station runs today | 35 runs (7 calibrate). Real handoffs taken by a hand: scalpel 06:39 and 07:02 | `~/scrub-logs/thermal/*.jsonl` run_end, station logs |
| Dataset | 29 episodes, 24 usable | git `828b958` "data: refresh 06:49", `docs/DATA.md` |
| Lighting per try | Not logged on the real arm (no lighting field in run_end or episodes) | run_end rows, `docs/DATA.md` "Per task" |

## a. Photon call

- Voice server (pid 80652, started 07:00:56) logs to a scratchpad file, `.../535a9f5f-.../scratchpad/voice-server.out`. Its lines have no timestamps and no conversation id, so a phone call, a `/talk` turn and an ElevenLabs simulated call look the same.
- That log shows conversational turns ("hello there", "what do you mean", "can you get me the scalpel", "let go", "okay go home") routed to the station: `[command] handover scalpel (local, station)`, then `[station] handover scalpel: RUN autopick {"mode": "average", "task": "pick the scalpel"}`, then `let go: letting go`.
- The station log `~/scrub-logs/station-20261018-065728.log` matches it: 07:01:03 "let go: nothing is being held out", 07:02:14 autopick replays the scalpel demo average (19, 22), 07:02:34 offers the handle, 07:02:35 "letting go" and "gripper guard: pulled out by hand", 07:02:37 "it's gone from the jaw; going home". So a voice command moved the real arm at 07:02:14 and it handed over a scalpel.
- Whether that voice came over +1 785 867 1047 is **not found**. `GET /v1/convai/conversations` with the current ElevenLabs key returns 0 conversations for the agent in `.env` and 0 overall (the key may not see call history). The voice log's `[texts] stream error ... validation ... projectId` repeats all through, so the Photon text listener is failing.
- `/health` on :3000: keys gemini/photon/llm_secret true, 10 turns, `active_call: false`.
- Controller :8000 `/events/recent` has `source: "voice"` commands at 02:21, 06:32-06:34 and 06:59, but :8000 runs `fake_arm: true` (its `/state`), so those moved the sim, not the arm.
- Person step: Photon dashboard "Recent calls" or ElevenLabs "Call history" for the 07:00-07:03 window. If it's there, the claim stands with timestamp 07:02:14.

## b. Gemini lines in `/Users/caide_1/Documents/dubhacks/dubhacks-2026/.env`

GEMINI_MODEL 1, GEMINI_TIMEOUT_MS 1, GEMINI_THINKING_LEVEL 1, GEMINI_MAX_OUTPUT_TOKENS 1. `GEMINI_MODEL=gemini-3.8-flash`. Nothing to add.

## c. Perceptron training

- `GET /v1/jobs`: 0 jobs. `python -m arm.train deployments`: `{"items": []}`.
- `arm.train capabilities`: `successful_jobs_per_team` 5; shared GPU budget 90.6 h used (it was about 65 h at 02:05; that budget is shared, not ours).
- So: no fine-tuned model. Real picks are recorded demo replays (taught skills).

## d. Real tries

Ledger (MongoDB Atlas, read via `ledger._read_mongo()`; local buffer `ledger/buffer.jsonl`):
- 70975 events, 0 trial rows. By tag: `fake_arm:true` 51864, untagged 17561, sim 971, fake 157, `fake_arm:false` 422.
- The 422 `fake_arm:false` rows (30 picked, 30 handed, 30 released, all hemostat, all lighting normal, 22:03 to 02:29) are `controller/test_flows.py` writing to Atlas (all 0.41-0.43 s, no misses). Not real.
- The local buffer's 66 rows (06:32-06:59) come from the :8000 fake-arm controller, which runs older code that doesn't tag `fake_arm`, so `ledger.stats()` would wrongly count them as real if the buffer flushes. Don't quote ledger rates.
- Real-arm ledger tries: **0**.

Station runs (`~/scrub-logs/thermal/*.jsonl`, `event: run_end`; all on Oct 18). Note: `result` is how the run ended, not whether the pick worked. "aborted: home" also follows a good handoff (07:02).

| Driver / mode | Item | Runs | Results |
| --- | --- | --- | --- |
| autopick handoff (03:00-04:18, handle finder) | scalpel handle (args carry no item; autopick was scalpel-only then, commit `5e6d9fb`) | 17 | done 15 (5 of them 0.0 s, nothing ran), aborted: kill 2 |
| autopick calibrate | none | 7 | done 7 |
| replay episode 17 | not in args | 1 | aborted: home |
| replay episode 22 | scalpel (station log: "pick the scalpel demo avg of 19,22") | 2 | stopped 1, done 1 |
| replay episodes 24, 25 | hemostat | 2 | stopped 2 |
| autopick replay_demo | scalpel (demo 22) 06:08, hemostat 06:12 | 2 | aborted: home 2 |
| autopick average | hemostat 06:22 | 1 | stopped |
| autopick average | scalpel 06:39, 07:02, 07:17 | 3 | done 1, aborted: home 2 |

- Handoffs where a hand took the instrument and the jaw checked empty (station logs): scalpel 06:39:20 (`station-20261018-061828.log`), scalpel 07:02:37 (`station-20261018-065728.log`). Hemostat was offered at 06:12:06 and 06:22:36; no "gone from the jaw" line for those.
- Mayo scissors: 0 real runs in run_end.
- No Grabbed/Missed marks in the thermal logs. Lighting is not logged per try.

## e. Dataset

- Latest `data: refresh` commit: `828b958` 06:49 "29 episodes, 24 usable; no new events". `1fb6672` 04:49: "70909 events, 4511 simulated tries; still no real handoffs".
- `docs/DATA.md` (06:49): 29 episodes, 0.15 h (9.0 min) recorded, 24 usable, 7 with a handoff outcome. Per task: scalpel handle 11, scalpel 5, hemostat 6, tweezers 4, spatula 3. No Mayo scissors episodes.

## f. Failsafes in code

Two code paths. The real arm on video runs through the **station** (`explore/station`, `explore/arm_session.py`). The **controller** (`controller/core.py`, `arm/real_arm.py`) runs the sim and the fake arm.

| Claim | Status | Where |
| --- | --- | --- |
| Stop freezes the arm until reset | True in the controller: `controller/core.py:727-733` (`stop` freezes), `:701` ("stopped: reset first", stays frozen until reset). Station: "stop" freezes in place, motors on, and goes on with "continue", "return to home" or "kill" (`explore/station/autopick.py:740-759`). Reword for the real arm: "stop freezes it where it is" |
| Thermal guard reads temps twice a second | **False as written.** Station and recorder read every 2 s (`explore/station/station.py:1078-1081`, `explore/arm_session.py:319-322`); controller every 1 s (`arm/real_arm.py:43`). Say "checks motor temperatures every couple of seconds" |
| ... and rests with torque off | True. Trip at 60 C, resume at 50 C (`arm/thermal.py:11`, `explore/station/station.py:44`); trip goes home, motors off (`explore/station/station.py:1099-1108`); controller stops the skill (`arm/real_arm.py:404-412`) |
| Speed limits | True. Station: acceleration 40 and speed cap 1200 steps/s (about 105 deg/s) on every motor (`explore/arm_session.py:222-223, 484-491`); per-step move clamp `max_relative_target=15` (`explore/station/station.py:234`); autopick peak 45 deg/s, 1.6x slower above 52 C (`explore/station/autopick.py:42, 44`). Controller: `SPEED_NORMAL, SPEED_NEAR = 0.3, 0.1` (`controller/core.py:42`) |
| Joint limits | True in the controller: URDF limits tightened by calibration, every row clamped (`arm/real_arm.py:105-107, 192`). Station relies on the per-step clamp above and joint-stall hold (`explore/arm_session.py:228`) |
| Grasp check before carrying | True in the controller (`controller/core.py:1620-1637`, jaw plus wrist camera). Station autopick in handoff mode offers it anyway when the jaw reads nearly shut (`explore/station/autopick.py:797-804`); the replay/average path has no check. Say it only for the controller/sim |
| Release only on a pull | **Not only.** Controller releases on a load change or collapse (`controller/core.py:1810-1831`) and also on a "let go" command (`:779-783`). Station releases on a tug, jaw or joint movement (`explore/station/autopick.py:49-52`, gripper guard `explore/arm_session.py:599-613`) or on "let go" (`autopick.py:1107-1109`). Say "lets go when you pull it or say let go" |
| Slows near the handoff point | True in the controller: last leg at `SPEED_NEAR` 0.1 vs 0.3 (`controller/core.py:42, 1513-1546`). The station replay has no separate slow zone (it follows the demo, capped at 45 deg/s). True for the sim; for the real arm say only the speed cap |

## Update 09:08: fine-tuning job

Section c above was true at 07:20. Since then (checked read-only at 09:08 Sun Oct 18):

- `python -m arm.train pipeline` (run log `~/scrub-logs/train-run-1.log`) built a 14-episode dataset, all task "pick the scalpel", 6,478 frames at 30 fps (wrist camera measured 29.83 to 29.99 fps). It registered as `ds_67632415a672136454b58605` and passed Perceptron's dataset validator at 08:49.
- The same log's local QA on those 14 episodes: pass 0, 10, 13; warn 3; fail the other 10 (episodes 1, 2, 4, 5, 6, 7, 9, 11: gripper never closes; 1, 5, 6, 7, 8, 12: action/state divergence 25.1 to 32.5 deg RMS).
- Job `job_629682f9575271b687e2c734` was created at 08:49:26 PDT: backend standard, mode expert_only, action horizon 30, RTC on, 1000 steps (`arm/train.py` defaults). It fine-tunes Perceptron's service base checkpoint, step 50,000 of an SO-100/SO-101 fine-tune (`explore/research/isaac-workshop-notes.md`).
- `python -m arm.train status job job_629682f9575271b687e2c734` at 09:08: status `training`, step 411 of 1000, 1.50 s/step. (At about 09:05 it was step 339 at 1.13 s/step.)
- `python -m arm.train deployments` at 09:08: `{"items": []}`.
- So: a fine-tuning job exists and is training. There is no deployment, and the arm has not run the fine-tuned model. Real picks on video are still recorded demo replays (autopick average mode).
