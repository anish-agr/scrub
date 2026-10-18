# controller

Owner: Caiden. Tasks C1, C2, C5, C6, C8 in `team/LEFT.md`.

FastAPI on port 8000. Owns the arm and every safety rule. Endpoints and messages are in `docs/CONTRACTS.md`. Serves `dashboard/` at `/` (a placeholder page with item buttons until `dashboard/index.html` exists).

## Run

```
python3.10 -m venv .venv && .venv/bin/pip install -r controller/requirements.txt   # once, from the repo root
.venv/bin/python -m controller                # fake arm (default), port 8000, surgical tray
.venv/bin/python -m controller --real-arm     # imports arm/real_arm.py (class Arm or RealArm)
.venv/bin/python -m controller --sim-arm      # MuJoCo SO-101 from sim/, see "Testing in the sim" below
```

Options: `--port`, `--setting surgical|bench` (surgical first, bench second; `dental` is hidden but still loads with `--setting dental` or `POST /setting`), `--judge` (start in judge mode), `--motion-s 0.2` (fake arm seconds per motion), `--pull-s 2` (fake arm: simulated pull this long after reaching the hand; `0` = wait for `got_it`), `--skills model|taught|auto` (see Skills below; default `model`).

Try it:

```
curl -XPOST localhost:8000/command -H 'content-type: application/json' -d '{"action":"handover","item":"hemostat","source":"keyboard"}'
curl -XPOST localhost:8000/stop
curl localhost:8000/state
websocat ws://localhost:8000/events      # or open http://localhost:8000/
```

## Files

| File | What |
| --- | --- |
| `__main__.py` | `python -m controller`: picks the arm (fake, sim or real), starts the server |
| `server.py` | the endpoints |
| `core.py` | state, events, the step machine (one worker thread runs arm calls; `stop` never waits on it) |
| `lines.py` | every line Scrub says (`say`). Change wording here only |
| `fake_arm.py` | the arm interface with sleeps, plus forced failures |
| `traycheck.py` | `GET /tray_check`: asks vision's `/tray_check`, words the answer with `lines.py` |
| `reads.py` | `read_sheet`, `read_tray`, `read_pack`: asks vision's `/read/<kind>`, and the count sheet comparison |
| `settings.py` | loads `settings/<id>.json` (built-in defaults until those files exist) with the clinic overlay `settings/<id>.local.json` merged in |
| `armview.py` | read-only `/arm/pose`, arm camera frames, `/camera/overhead`, `/calibration` |
| `sim_vision.py` | stands in for `vision/` with `--sim-arm` (TrayState and Hand from the sim) |
| `demo.html`, `nurse.html`, `ops.html` | the judging console (`/demo`), the nurse console (`/nurse`), the ops page (`/ops`) |
| `run_all.py` | the whole stack in one command, the between-judges reset, the sim backup and the full-stack check |
| `smoke.py` | full runs against a live controller (C5, C8) |
| `trials.py` | operator-gated trial matrix over HTTP, written to the ledger |
| `doctor.py` | one-command health check of every service, key, log and the arm port |
| `test_flows.py`, `test_doctor.py`, `test_run_all.py`, `test_backup.py` | tests (see Tests); `test_backup.py` runs the sim backup end to end on free ports (about 40 s). `conftest.py` keeps every test off the shared ledger |

## Behaviour other parts should know

- Every spoken line arrives as an Event `say`. The `say` in the `/command` reply repeats it; the voice server should speak events only, so lines aren't said twice.
- A `command` event goes out for every command, with extra fields `action`, `heard`, `source`, `accepted`, `reason`.
- Handover: `finding` (skipped with "I don't see the X" if a fresh TrayState says the slot is empty) → `picking` → `checking` (gripper ≥ 0.95 means it closed on nothing; a fresh TrayState still showing the item also fails) → one retry → `moving_to_hand` (carry pose, then to 8 cm short of the target at speed 0.3, then in at 0.1) → `waiting_for_pull` (load jump over `PULL_LOAD_DELTA`, default 80, a grip-load collapse, or `got_it`; 30 s) → `releasing` → `homing`.
- Sharp items (`"sharp": true`) go `setting_down` to the safe spot instead: "Scalpel down, on the safe spot. Careful, it's sharp." A handed item says "Here's the hemostat. Ready to grab." as the arm reaches the hand.
- **Stop latches.** The real arm stays frozen after `freeze()` until `resume()` (`arm/real_arm.py`), and so does the fake arm. After `stop` or an `error`, handover and return are refused with "I'm stopped. Reset me first." until `POST /reset` (the dashboard's clear-stop button). Reset rearms, homes, and if the gripper still holds an item, sets it at the safe spot instead of opening where it froze. Reset keeps the count (an item held at the stop counts as out); `POST /reset {"clear_count": true}` clears it for a fresh demo run.
- Hand tracking counts as running if a Hand arrived in the last 5 s. Then the arm waits up to 10 s for an open, seen hand with a valid `target` and `path_clear` (else it sets the item down: "No hand." or, when the hand is seen but the path is blocked, "Something's in the way. Hemostat is at the safe spot."). While moving it freezes if the hand is lost (older than 0.5 s) or the path blocks, and holds like a stop: "Lost your hand. Holding." or "Something's in the way. Holding." On the first, faster leg (to 8 cm short of the hand) it also freezes when `HAND_CLOSED_READS` (3) Hand posts in a row say `open: false`: "Your hand closed. Holding." One closed read between open ones is flicker and is ignored. On the slow last 8 cm a closing hand is the clinician taking the instrument, so it never stops there. No automatic retry; a reset carries the item to the safe spot.
- An arm exception, or `set_down_safe_spot()` returning False ("Couldn't set it down. Holding."), freezes the arm and goes to `error`. A thermal stop (`ArmFault` from `arm/real_arm.py`) says the arm's own message ("Too hot: shoulder_lift 71 C. Cooling down.") and holds the same way; reset once it has cooled.
- Skills (`--skills`): `model` (default) runs every pick and return on the robot model. `taught` plays the recorded skill from `arm/skills/<setting>/<item>-<pick|return>.json` (`arm/taught.py`) and refuses a handover or return with no recording: "I have no taught skill for the hemostat." `auto` uses the model for an item when a deployment exists (real arm: `PERCEPTRON_DEPLOYMENT_ID` set; fake and sim always count) and the model passed that item's last 3 real tries, else the taught skill if one is recorded, else the model. Real tries are written by the controller after each real-arm pick or return to `~/scrub-logs/skill-tries.json` (`SCRUB_TRIES_FILE` moves it; fake and sim runs never write it), so run `--skills model` trials to earn an item its model slot. Every event of a pick or return flow carries `skill_source` (`model` or `taught`), and `GET /state` has `skills` (`mode` and each item's source).
- `GET /state` also has `latency_ms` (`skill`: last `run_skill` ms, `skill_p50` over the last 50, `hand_age` and `tray_age`: ms since vision last posted) and, when the arm has `telemetry()`, `arm_telemetry` (temperatures, loads, hottest, cooling), polled once a second on its own thread so `/state` never touches the bus.
- Pull: a load change of more than `PULL_LOAD_DELTA` either way (the bus value is signed; measure it on the real arm), or `got_it`. If `gripper_load()` has no reading, Scrub says "Say got it when you have it." and waits for `got_it`.
- Release on pull (collapse): at the hand, if the grip load falls to `PULL_COLLAPSE_FRAC` (default 0.3) of the load it held on arrival or less, for two reads running (0.1 s), the gripper opens. This catches a clinician taking the weight without a sharp tug. It only applies when the held load was at least the pull delta, so noise near zero never drops an item. `PULL_COLLAPSE_FRAC=0` turns it off. The `released` event has `release`: `pull`, `collapse` or `got_it`.
- Grasp check: gripper at or above `GRIPPER_CLOSED` (0.95) means it closed on nothing. The tray check runs after the lift to carry, using only a non-stale TrayState from at least 1 s after the pick. A TrayState older than `TRAY_STALE_S` (8 s) counts as no camera reading: a handover never waits on it, the checks fall back to the gripper and `out`. A return counts only if a later TrayState shows the item back in its slot (when tray vision is running).
- Tracking stays "running" for 5 s after the last Hand post. Fake-hand drills need about a 6 s gap between them, or the next handover waits for a hand instead of using the saved spot.
- Out of region: if the point 8 cm short of the hand is refused (and the hand watcher didn't freeze it), the arm goes straight to the hand slowly. Only if the hand point itself is refused does it say "That's out of my reach" and set the item down (`/fake/force {"out_of_region": 2}` forces that). With no Hand posts at all it goes to the saved spot (`handoff_spot` in `arm/rig.json`, else `[0.22, -0.10, 0.18]`).
- `return` with no item takes the return-spot item from a fresh TrayState, else the last item out. A failed return (the skill fails twice, or the tray still shows the slot empty) says "I couldn't put the hemostat back." If the gripper still holds the item, the arm carries it home and sets it at the safe spot ("Setting the hemostat down."), then homes; it stays in the count.
- Auto return (F1): if TrayStates show the same item in the return spot for `AUTO_RETURN_S` (2 s) with the arm idle and nothing queued, Scrub says "Returning the X." and runs the normal return; its `command` event has `source: "auto"`, `action: "return"`. Once per visit (the item must leave the spot first), never while stopped or busy, and `stop` interrupts it like any return.
- Count from the camera (F2): `GET /state` and `count` events carry `out_camera` (empty slots minus the return-spot item, from a fresh TrayState; `null` without one). If it disagrees with `out`, the count line adds "Camera also sees the X gone." and/or "Camera sees the X back."; otherwise the line is unchanged.
- Reading (OCR, `reads.py`). `/command` actions `read_sheet`, `read_tray` and `read_pack` (item null) call vision's `POST {VISION_URL}/read/count_sheet`, `/read/tray_tag` or `/read/pack_label` with `{"source": "overhead", "setting": <current id>}` on their own thread (`READ_TIMEOUT_S`, default 20 s). They never touch the arm worker, so `stop` never waits on one. The reply says "Reading the count sheet." (or "the tray tag.", "the pack label."); a second read of the same kind while one runs is refused with "Still reading.". The answer comes as a `read` event with `read: {"kind", "ok", "method", "latency_ms", ...vision's fields}` and `say`, and goes to the ledger like every event. Vision down, an HTTP error or `ok: false`: "I can't read the count sheet." / "I can't read the tray tag." / "I can't read the pack label." Judge mode refuses all three.
  - `read_sheet` sets `GET /state` `sheet` (`{"tray", "items": {"<id>": {"expected", "initial", "closing"}}, "method", "t"}`). With closing counts written, each one is compared with Scrub's on-tray count (the sheet's expected, 1 when blank, minus that item in `out`): "Sheet says 0 hemostats back, I count 1." Without closing counts, the initial count is compared with the expected: "Sheet says 1 hemostat at the start, 2 expected." All equal: "Sheet matches my count."; no counts written: "No counts are written on the sheet yet." A sheet for another tray adds "This sheet is for the robotics bench tray, not the operating room tray." `read.compare` is `closing`, `initial` or null and `read.mismatch` lists `{"item", "sheet", "scrub"}` (closing) or `{"item", "sheet", "expected"}` (initial).
  - After a sheet with closing counts, `count` events carry `sheet_mismatch: [{"item", "sheet", "scrub"}]` and the line adds "Sheet disagrees on the hemostat." Without one, no field.
  - `read_tray`: a known tray other than the current one switches the setting the same way `POST /setting` does, when idle or stopped: "This is the robotics bench tray. Switched." Same tray: "This is the operating room tray." Busy: "This is the robotics bench tray. I can't switch while I'm busy." `read.switched` says which.
  - `read_pack` adds each label to `GET /state` `packs` (`[{"item", "lot", "expires", "expired"}]`) and says "Hemostat pack, expires 2027-04-30." or, when expired, "Expired: mayo scissors pack, 2026-09-30. Don't open it." A new case (start, `POST /setting`, reset with `clear_count`) clears `sheet` and `packs`.
  - `POST /read_result` with `{"kind": "count_sheet" | "pack_label" | "tray_tag", "result": <vision's /read JSON>, "source": "photo", "heard": str or null}`: a texted photo (voice) that vision already read. Same rules as the camera reads minus the vision call: it sets `sheet` or `packs`, switches trays from a tag when idle, emits a `read` event (`command_id` null, `read.source` "photo", `heard` on the event) and returns `{"ok", "say", "read"}`. Runs off the event loop, so `stop` never waits on it. Judge mode: `{"ok": false, "say": <judge line>, "read": null, "reason": "judge mode"}` and no event. Unknown kind: 400.
- `count` answers at once, even mid-handover. Up to 3 handovers queue; `stop` clears the queue.
- Switching trays (`POST /setting`) only works when idle or stopped. It keeps `out`: an instrument still out from the last tray stays in the count until it comes back or `POST /reset {"clear_count": true}`. A switch never clears a stop or an error; only a reset rearms the arm. A `return` with no item only picks from what's out of the current tray.
- Stop takes the lock for an instant to bump the run generation and clear the queue together, so a queued handover can never start after a stop. Every event carries `fake_arm` (true for the fake and the sim arm), and so does a restock row.
- `GET /stats` without the ledger answers in the ledger's shape (`by_item` rows with `attempts`, `successes`, `success_rate`), so the dashboard tables still fill.
- `GET /state` and every event carry `arm` (`fake`, `sim` or `real`) and `sim` (bool). `fake_arm` stays `true` for anything but the real arm (the sim too), so the ledger and trials keep sim runs out of real numbers. With no hand tracked, the sim arm hands over at its layout hand zone (`SimArm.handoff_spot`), the spot the viewer and the overhead render draw.
- `run_all backup` refuses when its controller port is already taken (it names the pid) instead of running the script on someone else's controller: use `--base-port 8200`, or `--url` to use that controller on purpose.
- `case_id` (`<setting>-<unix start seconds>`) is in `GET /state` and on every event. A new case starts at controller start, on `POST /setting`, and on `POST /reset {"clear_count": true}`; a plain reset keeps it.
- `ledger` is used if `ledger.log` exists; otherwise `/stats` comes from memory.
- Robot model sessions (L2): if the arm has `prepare(instructions)` (`arm/real_arm.py` does), the controller pre-opens a Perceptron session for every item's pick and return instruction at start, on each `POST /setting`, and after a reset when the last prepare didn't finish (a stop cancels it inside the arm). It runs on its own daemon thread, never under the lock, so stop and the setting change never wait on it. An API error is retried up to `PREPARE_TRIES` (3) times, `PREPARE_RETRY_S` (5 s) apart (not for 401/403), and spoken once per setting change as an `error` event with `code`, `reason` and `command_id: null`; the step is unchanged. Other prepare failures (frozen, no deployment id) are only printed. Skills open sessions on demand anyway.
- Perceptron errors (L2): the arm raises `APIError("Perceptron HTTP 503")` (`arm/perceptron.py`; no status field, the code is read from the message). From a skill run it holds like any error (`step: "error"`, frozen until reset) and says why: 401/403 "The robot model key was refused. Check the team key.", 409/429 "The robot model is busy with another session. Try again in a moment.", 5xx "The robot model is down right now.", no status "I can't reach the robot model right now.", each plus " Holding." The `error` event carries `code` (int or null) and `reason`.
- Judge mode (L3): `POST /judge {"on": true}` or `--judge`. `/command` then accepts only `handover`, `count`, `stop` and `got_it` (got_it finishes a handover when there's no load reading); anything else is refused with `reason` "judge mode" and "In judge mode I can hand you an instrument, read the count, or stop." `POST /alias` is refused the same way. `/setting`, `/reset`, `/lighting`, `/stop` and the operator endpoints stay open. `GET /state` and every event carry `judge`; toggling emits a `step` event. Auto return (F1) still runs, since it isn't a command.

## Tuning (`.env`, measure on the real arm first)

### Which one (optional instance selection)

`POST /command` accepts `instance: {variant?: string, side?: "left" | "right" | "closest", slot?: integer}`
and an optional `question_id`. Fresh repeated tray slots (or `/locate` detecting multiple instances) do not
enqueue a pick or wake the arm. The reply is `accepted: false`, `reason: "clarification needed"`, plus
`clarify: {say, item, candidates, question_id}`; the same payload is emitted as a `clarify` event. Candidates
include `item`, `label`, optional `variant`, `side`, 1-based `slot`, `box`, and an `instance` to echo back.
Send a new handover with that item's `instance` and the issued `question_id` to answer. The id is required
when answering a pending controller question; superseded, missing, or expired ids cannot move the arm. Hints must match
exactly one validated candidate; contradictory, overlapping, or unverified candidates never select the first.

The question expires after 15 seconds (`clarify_timeout` event); there is no waiting motion job to resume.
A late answer is refused; ask for the instrument again without a hint to start over. Stop clears the question
and remains latched. `/state.clarify` exposes the live question. The mounted overhead image has the surgeon
at its bottom: image-left is their left; larger image y is closer. Generated slots sort left-to-right,
then top-to-bottom; supplied stable slot numbers take precedence. With more than two objects, only the
unique bottommost one is called `closest`; other choices use slot numbers. Keep that camera orientation.

Side/slot (or same-id variant) choices use IK with the selected located pose: model/plain taught skills ignore
instance positions. On the real arm, no calibrated finite `arm_xy` or confidence below 0.6 means refusal
**before wake**. A named settings variant with a distinct item id (Phillips vs flathead) uses that item's normal
skill instead. An already-out item answers "The hemostat is with you."; a separately detected instance is
offered as a question rather than silently picked (`confirm: true` for a single remaining candidate, so voice
accepts yes/no). Only that selected physical candidate is used for the grasp check. Production TrayStates keep
configured occupancy in `slots` and physical detections in `candidates`; one configured slot never overrides a
by-sight candidate's identity. Known duplicates remain blocked through stale/local reads or a locate timeout.

`out` stays a unique item-id list. Optional `out_instances: [{item, id, instance}]` on state/events and in the saved
state records each physical item separately; count says "Out: 2 hemostats." A return removes only its selected
instance, and `returned.instance` identifies it. An unspecified return with multiple same-item instances asks
which one before enqueue/wake (auto return does too); it cannot silently erase the physical count.

`POST /clarify` accepts `{type: "clarify" | "clarify_answer", say?, item?, candidates?, question_id?, answer?,
answer_ms?, context?, confirm?}` (`context` string or object) and broadcasts/logs it through the normal event machinery.
It is telemetry only: it never changes a motion job or resolves a controller question. Tests:
`python -m pytest -q controller/test_instances.py vision/test_locate.py`.

| Name | Default | What |
| --- | --- | --- |
| `PULL_LOAD_DELTA` | 80 | raw load change, either sign, that counts as a pull |
| `PULL_COLLAPSE_FRAC` | 0.3 | let go when the grip load falls to this share of the held load (0 = off) |
| `GRIPPER_CLOSED` | 0.95 | gripper fraction at or above which a pick closed on nothing |
| `SCRUB_TRIES_FILE` | `~/scrub-logs/skill-tries.json` | real-arm tries per item for `--skills auto` |
| `TRAY_STALE_S` | 8 | seconds before a TrayState counts as no camera reading. Vision posts after each Perceptron detect (3.8 to 4.7 s on 640x480 trays), so keep it above that; it also sets the nurse console's stale label and the `/tray_check` fallback |
| `HAND_CLOSED_READS` | 3 | Hand posts in a row with `open: false` that freeze the arm on the fast leg (0 = off) |
| `SCRUB_STATE_FILE` | `data/controller-state-<port>.json` | where the count is saved across a restart (empty = off) |
| `VISION_URL` | `http://localhost:8001` | vision, for `/tray_check`, `/read/<kind>` and `/camera/overhead` |
| `READ_TIMEOUT_S` | 20 | longest wait for one vision read (Perceptron OCR, then Gemini) |

## Extra endpoints (not needed by other parts)

- `GET /setting`: the current setting file (the voice server can read item ids and aliases here).
- `GET /events/recent?n=50`: the last events, for a page that loads mid-run.
- `POST /alias` with `{"item": "hemostat", "alias": "clamp"}` (X6 clinic words): teaches a word for an item on the current tray. Always 200 with `{"ok", "say", "reason"}`: "Got it: clamp means the hemostat.", or `ok: false` with "Crile already means the X." (the word names another item on this tray), "That's not on this tray." or "I didn't catch the word." The word is lowercased, articles dropped ("The Clamp" -> "clamp"). Saved to `settings/<id>.local.json` (temp file + rename), then the current setting is reloaded in memory, so `GET /setting` (voice's Gemini list and alias match) has it at once. Works mid-handover; never touches the arm, `out` or the case.
- `POST /restock` with `{"item", "qty", "setting", "from", "heard"}`: a restock texted to the Photon thread (voice F3), logged to the ledger with the `case_id`. Returns `{"ok": false}` when the ledger isn't loaded (voice then keeps it in `voice/restocks.jsonl`).
- `POST /vision/caption` with a clip caption `{"case_id", "event_type", "item", "t", "label", "label_source", "agrees", "caption_item", "caption_action", "caption_latency_ms", "filename"}` (vision's auto-caption, `vision/clips.py`): logged to the ledger as `{"type": "caption", ...}` with `setting` and `fake_arm`, not broadcast as an Event. Returns `{"ok": false}` when the ledger isn't loaded.
- `POST /fake/pull`: simulate the clinician tugging the item (sim arm), otherwise the same as `got_it`.
- `GET /demo`: the judging console (P4). Keys 1/2 load the surgical and bench trays (dental is not offered), J toggles judge mode (amber "judge mode" badge in the header), R resets and clears the count, Space or Esc stops (latched), C sends the current cue's request, G is got it. A 3:00 clock with the PITCH.md beats and who does what, and a rehearsal log for P5. `demo.html` is a copy of `team/prototypes/48-judge-run.html`.
- `GET /ops`: the ops page (`controller/ops.html`, on `/design/scrub.css`): step and events, skill source per item, arm temperatures and loads, latencies. A placeholder until that file exists. `/design/*` serves the shared `design/` folder.
- `GET /nurse`: the nurse console, a live port of `team/prototypes/24-scrub-nurse.html`. Tray slots (on tray, out, held, plus the camera's view from TrayState), item chips and typed or browser-mic requests matched against the setting's aliases, the step track for the running request, request-to-hand time per request (`?target=10` sets the line), the queue, hand lamps (seen, open, path), stop that turns into reset, got it, count, return per item, fake-arm pull and forced failures, and the event log. Space or Esc stops (Esc also from the text box), G is got it, / types.
- `controller/armview.py` (read-only, nothing moves): `GET /arm/pose` gives `joints_deg`, `gripper` (0 open, 1 closed), `tip_m` from `arm/rig.json` forward kinematics and `tip_px`, the tip projected into the overhead image with `vision/calibration.json` (table-plane homography, so approximate above the table). `available: false` with a `reason` on the fake arm. On the real arm it also has `counters` (`accepted` and `late` model chunks, `holds`, `ticks`, `overruns` of the 30 Hz loop, `api_errors`) and `last_reason` (why the last skill or move ended): watch `late` and `overruns` on first contact. `GET /arm/camera/side|wrist` (one JPEG) and `GET /arm/stream/side|wrist` (MJPEG, about 10 fps) need `Arm.camera_jpeg(name)` in `arm/real_arm.py` (Anish), else 404 with the reason. `GET /camera/overhead` proxies vision's `/snapshot` (`VISION_URL`, default `http://localhost:8001`) so pages on :8000 get it same-origin. `GET /calibration` returns `vision/calibration.json` or 404.
- `GET /vision`: the last TrayState and Hand as posted, with `tray_age_s` and `hand_age_s` (for the nurse console).
- `GET /tray_check` (X3): "check the tray". Calls vision's `GET {VISION_URL}/tray_check` (default `http://localhost:8001`, 3 s timeout, in a thread so `stop` never waits) and returns vision's fields plus `say`, `available`, `label` (the setting's label) and `items` (its item names). Always 200. Vision must answer, for the controller's current setting (item ids from `settings/<id>.json`):
  `{"ok": bool, "setting": "surgical", "missing": ["scalpel"], "wrong_slot": [{"item": "hemostat", "in_slot_of": "mayo_scissors"}], "extra": [], "stale": false, "t": 1760731200.1}`.
  Missing fields are fine (`ok` defaults to "nothing missing or in the wrong slot"; a non-empty `missing` or `wrong_slot` always means not ok), extra fields are passed through. `say` is "Tray's ready: scalpel, hemostat, Mayo scissors." / "Missing the scalpel." / "The hemostat is in the Mayo scissors' slot." (plus "Extra on the tray: ..." when `extra` is set). Vision down, 404, timeout, not JSON or `stale: true`: `ok` false, "I can't check the tray right now." (`available` false unless it was just stale). A different `setting` from vision: `ok` false, "The camera is checking the bench tray, not the surgical tray." With no vision answering (the sim and backup stacks), a TrayState the controller got in the last `TRAY_STALE_S` (8 s) answers instead (only missing items; it can't see a wrong slot).
- `POST /fake/force` with `{"miss_grasp": 1, "out_of_region": 1, "skill_fail": 1, "no_pull": 1, "no_load": 1}`: the next fake-arm calls fail that way (testing C6). `{"collapse": 1}` makes the next pick's grip load fall toward zero at the hand (release on collapse); `{"hot": 1}` makes the next skill raise `ArmFault` (thermal stop). `{"api_error": 503}` (any status) makes the next `prepare` or `run_skill` raise the robot model's `APIError`; force it, then `POST /setting` to test the prepare path, or send a handover for the skill path.

## Clinic words overlay (X6)

`settings/<id>.local.json` is `{"aliases": {"hemostat": ["clamp", "snap"]}}`: words a clinic taught through `POST /alias` ("call the hemostat a clamp" on the call or by text). `settings.load()` merges it over Evan's `settings/<id>.json` (or the built-in default): aliases are added to the matching item lowercased and deduped, unknown item ids are ignored, a missing overlay is fine and a broken one is ignored (logged once). The merged setting has `_overlay` set to the file it used. The controller never writes `settings/<id>.json`. The overlay files are clinic config and stay tracked in git. An unknown command now answers "Which instrument? You can say: call the hemostat a crile." (the first non-sharp item and the first of `lines.HINT_WORDS` this tray doesn't have yet, so the hint never names a word that already works).

## Tests

`.venv/bin/python -m controller.test_flows` forces every failure case on the fake arm (grasp miss and retry, tray grasp check, stale tray, empty slot, no pull, no load reading, load drop, `got_it`, no hand, hand lost and path blocked holding until reset, failed set-down, arm exception, out of region, stop mid-pick, mid-move and while holding out, sharp set-down, return checked against the tray, count, auto return, count against the camera, case_id, rejects, the tray check against a fake vision, the clinic-words overlay and `POST /alias` on a temp settings folder, prepare at start and on setting change, Perceptron 401/409/503 on prepare and on a skill, prepare never blocking stop, judge mode and `--judge`, release on collapse, skill source in model, taught and auto modes, the tries record, telemetry and latency in `/state`, a thermal fault, `/ops` and `/design`, a closed hand on the fast leg against flicker and a grab at the hand, a failed return still holding the item, `TRAY_STALE_S` from the environment and a slow tray feed, and `ops.html` with a null skill source, a wake that raises, each read action against a fake vision: sheet initial and closing mismatch math, `sheet_mismatch` on count, another tray's sheet, tray switch idle, stopped, busy, same and unknown, the expired pack line, vision down, stop during a read, one read at a time, judge mode, read and caption records in the ledger, a photo through `POST /read_result` setting the sheet, packs and tray, and stop during one). Prints `98/98 passed`.

`.venv/bin/python -m controller.test_doctor` checks the doctor with no network (prints `doctor ok`). `.venv/bin/python -m controller.trials --self-test` runs the trials runner's 20 offline tests, including two practice handovers in a row on the fake arm.

## Whole stack (`run_all.py`)

```
.venv/bin/python -m controller.run_all                    # fake stack: fake arm, vision --fake, voice, opens the dashboard
.venv/bin/python -m controller.run_all --real              # judging (tunnel, agent update and phone number included)
.venv/bin/python -m controller.run_all reset               # between judges: clear the count, surgical tray, normal light
.venv/bin/python -m controller.run_all backup [--offline] [--loop] [--pause 2]   # the arm failed: sim arm plus a scripted demo
.venv/bin/python -m controller.run_all check               # full-stack check on its own fake stack
```

`--real` is `--arm real --vision real --ledger --judge --skills auto`; each can still be overridden. `--skills model|taught|auto` is passed to the controller, and `--real-arm` is the same as `--arm real`. At start it prints the dashboard, judge console, nurse console, ops page (`/ops`), tablet, `/state`, vision preview and stream, voice health, ledger page and tunnel URLs. Ctrl-C stops every child. `--base-port N` moves every port together for a test stack beside the live one; `--help` lists the rest.

Phone call: `--real` also starts a tunnel (cloudflared when `voice/.bin/cloudflared` exists, else Pinggy; `--no-tunnel` skips it), points the ElevenLabs agent's Custom LLM at each new tunnel URL (`cd voice && npm run agent -- <url>`; `--no-agent` skips it), restarts a tunnel that dies after running a while, and prints `phone (call it)` from `PHOTON_LINE` in `.env` (else the agent's phone numbers). If the real arm can't be used (`SO101_PORT` empty, the device missing, or the port held by another program, from `arm.backends.port_holders`), it runs the sim arm instead (vision `none` unless `--vision` was given) and the table title says so in a `**` line.

## Trials (`trials.py`)

```
.venv/bin/python -m controller.trials --plan-only                     # print the trial matrix, no HTTP
.venv/bin/python -m controller.trials --settings surgical --items hemostat --lighting normal --actions handover --tries 2
.venv/bin/python -m controller.trials --practice --yes --items hemostat --actions handover --tries 2   # fake or sim controller
```

Real trials ask the operator before each try and to confirm each outcome (`s`/`f`), then call `ledger.log_test`. `--practice` refuses a real controller and never writes to the ledger. Each run writes a JSONL journal (`--journal`, default `.env.trials-<id>.jsonl` at the repo root, git-ignored).

## Doctor

```
.venv/bin/python -m controller.doctor [--no-ai] [--json]
```

Checks the controller, vision, voice, ledger, sim, recorder and thermal pages (2 s timeout each), lists which .env keys are set or missing and what each missing one turns off, shows the newest ~/scrub-logs files and recent controller error events, and reports whether SO101_PORT exists and who holds it. It does not open serial ports or cameras. Without --no-ai it sends only the findings text to Gemini and prints at most 8 lines of fixes; with no key or on failure it prints the raw findings. Exit code is 0 when the controller is up, 1 otherwise. Test: `.venv/bin/python -m controller.test_doctor`

## Full runs (Checkpoint 1, C8)

`.venv/bin/python -m controller.smoke` runs a full pass against a live controller: every item handed over (simulated pull on fake/sim arms), then the count. `--return` adds put-backs, `--runs 10 --human` is the C8 ten-in-a-row check on the real arm (a person takes each item and resets the tray), `--url` points elsewhere. It prints each line Scrub said, request-to-hand times, and the clean streak.

## Testing in the sim

`.venv/bin/python -m controller --sim-arm` runs the controller on the MuJoCo arm and, in the same process, the sim server on `--sim-port` (8002): watch it at `http://localhost:8002/web/viewer.html` (Live mode) and use `http://localhost:8002/stream` as a fake camera. Needs `sim/requirements.txt`. Run it in a normal terminal so Ctrl-C works.

Shutdown: Ctrl-C or SIGTERM exits within about 2 s even with voice or a dashboard connected (`timeout_graceful_shutdown=2`), and always runs `arm.disconnect()`, so the real arm's serial port is free for a restart.

Restart mid-case: the count (`out`) and `case_id` are saved to `data/controller-state-<port>.json` (git-ignored) whenever they change, off the request and worker threads. A controller started on the same port and setting within 6 h picks them up, so "what's out" still names the hemostat after a restart. `SCRUB_STATE_FILE=<path>` moves the file; `SCRUB_STATE_FILE=` (empty) turns it off. `run_all check` stacks run with it off. `POST /reset {"clear_count": true}` empties it.

`controller/sim_vision.py` stands in for `vision/`: a TrayState every second from where the sim's instruments really are, and a Hand at 10 Hz when switched on. Knobs:

```
curl -XPOST localhost:8000/sim/hand -H 'content-type: application/json' -d '{"on": true}'        # hand tracking on (default off = saved spot)
curl -XPOST localhost:8000/sim/hand -H 'content-type: application/json' -d '{"seen": false}'     # lose the hand (try it mid-move)
curl -XPOST localhost:8000/sim/hand -H 'content-type: application/json' -d '{"path_clear": false}'
curl -XPOST localhost:8000/sim/hand -H 'content-type: application/json' -d '{"target": [0.25, -0.1, 0.15]}'
curl -XPOST localhost:8000/sim/return_spot -H 'content-type: application/json' -d '{"item": "hemostat"}'  # clinician sets it down
curl -XPOST localhost:8000/fake/pull                                                              # clinician tugs
curl -XPOST localhost:8000/sim/scene_reset                                                        # every item back in its slot, then a reset
```

`python -m controller.smoke --runs 3 --return` runs full passes in the sim, putting items in the return spot itself and resetting the scene between runs. The sim's pick is scripted, so it tests the controller, timing, reach and region limits, not the Isaac policy.
