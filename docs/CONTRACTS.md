# Contracts

Every part codes against these. Build against fake inputs that match them, and things connect on the first try.

**Changing a contract:** say it in the group chat first, then edit this file. Caiden owns this file because the controller is where everything meets. Adding an optional field is fine without asking. Renaming or removing a field needs everyone's OK.

## Conventions

- JSON everywhere. Times are Unix seconds as floats (`time.time()` in Python, `Date.now() / 1000` in TypeScript), field name `t`.
- Item ids are lowercase with underscores: `scalpel`, `hemostat`, `mayo_scissors`, `mouth_mirror`, `explorer`, `cotton_pliers`, `needle_nose_pliers`, `wire_cutters`, `hex_key`.
- Setting ids: `surgical`, `dental`, `bench`. Shown to users: `surgical` (first) and `bench`; `dental` is hidden but still loads.
- Pixel boxes are `[x1, y1, x2, y2]` in the vision camera's image.
- Arm points are meters in the arm's base frame: x forward, y left, z up. Anish confirms the axes against the SO-101 URDF.

## Ports

| Process | Port | Owner |
| --- | --- | --- |
| controller (also serves the dashboard at `/`) | 8000 | Caiden |
| vision (camera stream and debug) | 8001 | Brandon |
| voice server | 3000 | Caiden |
| ledger public page (`python -m ledger`, `/api/*`) | 8080 | Evan |
| sim viewer (`--sim-arm --sim-port`, optional) | 8002 | Caiden |

## Controller endpoints (port 8000)

| Endpoint | Body | Returns |
| --- | --- | --- |
| `POST /command` | a Command | `{"accepted": bool, "reason": str or null, "say": str or null}` |
| `POST /stop` | nothing | `{"accepted": true}`. Always accepted, skips the queue, freezes the arm |
| `GET /state` | | a State. `out` and `case_id` survive a controller restart on the same port and setting within 6 h (`SCRUB_STATE_FILE`, default `data/controller-state-<port>.json`; empty turns it off) |
| `POST /setting` | `{"setting": "surgical"}` | the loaded setting file. 409 if the arm is busy (idle or stopped only), 404 for an unknown id. Keeps `out`: an item still out of the last tray stays counted until it comes back or `POST /reset {"clear_count": true}`. Never clears a stop or error; only a reset rearms |
| `POST /lighting` | `{"lighting": "bright" or "normal" or "dim", "lux": number or null}` | `{"ok": true}`. Tags later events for the tables |
| `POST /vision/tray` | a TrayState | `{"ok": true}` |
| `POST /vision/hand` | a Hand | `{"ok": true}` |
| `GET /stats` | | the success tables, from the ledger |
| `WS /events` | | a stream of Events |
| `GET /` | | the dashboard (static files from `dashboard/`) |
| `GET /setting` | | the current setting file (optional, added Sat 2 PM) |
| `POST /reset` | nothing, or `{"clear_count": true}` | `{"ok": true}`: clears a stop or error and rearms the arm (`resume()`). Homes; if it still holds an item it sets it at the safe spot, else opens the gripper. Keeps `out`, so a stop mid-case never makes the count say everything is back; `{"clear_count": true}` empties it (demo reset between runs). An item the arm held when it stopped counts as out. 409 if busy. After `stop` or `error`, `handover` and `return` are refused (`reason` "stopped: reset first") until a reset |
| `GET /events/recent?n=50` | | the last n Events, oldest first (optional) |
| `GET /vision` | | `{"tray": TrayState or null, "tray_age_s": number or null, "hand": Hand or null, "hand_age_s": number or null}`: the last posts as received (optional) |
| `GET /nurse` | | the nurse console page (optional) |
| `GET /ops` | | the ops page, `controller/ops.html` (optional) |
| `GET /design/*` | | the shared `design/` folder, e.g. `/design/scrub.css` (optional) |
| `GET /arm/pose` | | `{"available": bool, "joints_deg": [5] or null, "gripper": 0..1 or null, "tip_m": [x, y, z] or null, "tip_px": [x, y] or null, "calibrated": bool, "reason": str or null, "t": float}` (optional, read-only). Real arm only, optional: `"counters": {"accepted", "late", "holds", "ticks", "overruns", "api_errors"}` and `"last_reason": str` for first-contact checks |
| `GET /arm/camera/{side,wrist}`, `GET /arm/stream/{side,wrist}` | | a JPEG, or MJPEG; 404 until the arm has `camera_jpeg(name)` (optional) |
| `GET /camera/overhead` | | vision's `/snapshot` proxied, 502 if vision is down (optional) |
| `GET /calibration` | | `vision/calibration.json`, 404 if missing (optional) |
| `POST /alias` | `{"item": "hemostat", "alias": "clamp"}` | Always 200: `{"ok": bool, "say": str, "reason": str or null}` (X6 clinic words). `ok: false` for an unknown item, a bad word, a word another item already has, or judge mode (`reason` "judge mode"). Saved in `settings/<id>.local.json` (optional) |
| `POST /restock` | `{"type": "restock", "item", "qty", "setting", "from", "heard", "case_id", "t"}` (voice texts) | `{"ok": bool}`: `false` when the ledger isn't loaded (voice then appends to `voice/restocks.jsonl`). Goes to `ledger.log` as a record with `type: "restock"`, not an Event (optional) |
| `GET /tray_check` | | X3: vision's `GET /tray_check` for the current setting, plus `say`, `available` (vision answered), `label` and `items` (the setting's item names). Vision down or a timeout (3 s): falls back to the controller's own TrayState when it is under `TRAY_STALE_S` (default 8 s) old and not stale (reports missing items only). Otherwise `ok: false`, `say` "I can't check the tray right now." (optional) |
| `POST /fake/force` | `{"miss_grasp", "out_of_region", "skill_fail", "no_pull", "no_load", "collapse", "hot", "api_error"}` (ints, all optional) | the fake arm's pending forced failures. 400 unless `--fake-arm` (testing only, optional) |
| `POST /fake/pull` | nothing | sim arm: a simulated tug; otherwise the same as a `got_it` command from the dashboard (testing only, optional) |
| `GET /demo` | | the demo console page (optional) |
| `POST /judge` | `{"on": true or false}` | `{"ok": true, "judge": bool}` (optional). Judge mode: `/command` accepts only `handover`, `count`, `stop` and `got_it`; anything else gets `accepted: false`, `reason` "judge mode" and a spoken `say`. `POST /alias` answers `ok: false`, `reason` "judge mode". `/setting`, `/reset`, `/lighting`, `/stop` and the operator endpoints still work. Also `python -m controller --judge` |

## Command (voice, keyboard or dashboard to the controller)

```json
{
  "id": "3f1c...",
  "action": "handover",
  "item": "hemostat",
  "heard": "grab me the kelly",
  "source": "voice",
  "t": 1760731200.12
}
```

- `action` is one of `handover`, `return`, `count`, `stop`, `got_it`, `unknown`.
- Optional actions (reading, from the OCR pass): `read_sheet` (read the count sheet in view), `read_tray` (read the tray tag and switch to that setting when idle), `read_pack` (read sterile pack labels and warn on an expired date). `item` is `null`. A controller that doesn't know them rejects them as `unknown`.
- `item` is an item id from the current setting, or `null` for `count`, `stop`, `got_it` and `unknown`. For `return` it is the item id when one was named ("put the hemostat back"; auto returns always name it), or `null`: the controller then takes the item in the return spot from a fresh TrayState, else the last item out. Events of a return flow carry the item id either way.
- `source` is one of `voice`, `keyboard`, `dashboard`, or `auto` (the controller's own return when an item sits in the return spot, F1; it appears only on `command` events, never in a POST).
- `got_it` means release now (the voice fallback for release on pull).
- `method` (optional, `handover` and `return`): `"model"`, `"taught_adjusted"`, `"ik"` or `"taught"` forces the first grasp method under `--skills smart` (`controller/trials.py` uses it for N tries per method). Ignored in judge mode and in other `--skills` modes. A method the item can't use now (no deployment, no taught skill) gets `accepted: false`, `reason` "method unavailable". The `command` event repeats it.
- `instance` (optional, `handover`): a selection hint, for example `{"variant": "phillips"}`, `{"side": "left"}`, `{"side": "right"}`, `{"side": "closest"}` or `{"slot": 2}`. Slots are one-based. A variant selects a configured item, while side or slot selects a physical instance. The selected hint is passed to the picker and locate step. Left and right mean the surgeon's view of the tray. The controller's overhead view assumes the surgeon is at image-bottom: image-left is their left, and larger image y is closer. The station's side-camera convention is separate (`explore/station/README.md`). Confirm mounting and surgeon position before a live side selection.
- `question_id` (optional): echo the controller-issued question id when answering its pending question. A superseded or expired id cannot authorize a pick. Voice-only name questions do not send their local question id as a controller answer.
- The voice server never sends an item that isn't in the current setting. Gemini's schema only allows those ids.

If more than one candidate matches, no pick is authorized. The controller may return
an optional `clarify` object in the `/command` reply and emits a `clarify` event.
An offer of a single remaining instrument may include `confirm: true`, accepting
yes or no before any movement.
Voice keeps the pending question per call or text thread, not across callers.
The next answer sends a handover with the chosen item and instance. A question
expires after 15 seconds: "I'll wait for you to ask again." Cancel drops the
question. Stop uses `/stop` immediately, even while a question is pending.

`POST /clarify` (optional) logs voice questions and answers through the normal
controller event stream. It does not move the arm. Body fields are `type`
(`clarify` or `clarify_answer`), and optional `say`, `item`, `candidates`,
`question_id`, `answer`, `answer_ms` and `context`.

## State (`GET /state`)

```json
{
  "step": "idle",
  "item": null,
  "queue": [],
  "out": ["hemostat"],
  "setting": "surgical",
  "lighting": "normal",
  "fake_arm": true,
  "hand_seen": true,
  "out_camera": ["hemostat"],
  "case_id": "surgical-1760731200",
  "t": 1760731200.12
}
```

- `out_camera` (optional): what the camera says is out, from the latest fresh TrayState: items whose slot is empty, minus anything sitting in the return spot. `null` when there's no fresh TrayState. `count` compares it with `out` and says if they disagree.
- `out_instances` (optional): outstanding physical identities alongside the existing `out` item list. Multiple handed instances of the same item must remain counted separately; returning one must not remove another person's instrument. Pick, handover and return events may carry `instance` to identify which copy changed hands.
- `sheet` (optional): the last count sheet read this case, `{"tray", "items": {"<item id>": {"expected", "initial", "closing"}}, "method", "t"}`, or `null`. Counts are integers or `null` when the box is empty or unreadable.
- `packs` (optional): pack labels read this case, `[{"item", "lot", "expires", "expired"}]`. `expires` is `YYYY-MM-DD` or `null`.
- `case_id` (optional): the current case, `<setting>-<unix start seconds>`. A new case starts when the controller starts, when the setting changes and on `POST /reset` with `clear_count`.
- `judge` (optional): `true` in judge mode (`POST /judge`).
- `arm` (optional): which arm the controller runs, `"fake"`, `"sim"` or `"real"`. `sim` (optional, bool): `true` on the sim arm. `fake_arm` stays `true` on the fake arm and the sim (anything but the real arm), so pages that only read `fake_arm` keep sim runs out of real numbers; read `arm` to tell the sim from the fake arm. Events carry the same two fields, and `test: true` when written by a test run (`SCRUB_TEST`).
- `skills` (optional): `{"mode": "model" | "taught" | "auto" | "smart", "items": {"<item id>": "model" | "taught" | "taught_adjusted" | "ik" | null}}`. `mode` is the controller's `--skills`; each item has the source its next pick would use (`null`: `--skills taught` and no taught skill for that item, so a handover is refused). With `--skills smart` also `policy`: `{"<item id>": {"method", "confidence" (0..1, the Wilson lower bound; 0 with too few real tries), "why", "order": [methods, first is tried first, the next on a miss]}}` from `controller/picker.py` (`data/skill_policy.json`).
- `safe_zone` (optional): `{"center": [x, y, z] or null, "size": [sx, sy] or null, "problems": [str]}` in meters, arm base frame, from the arm's `safe_zone()`. `problems` (real arm only; `[]` for fake and sim) is why a sharp can't be picked: not taught, closer than 15 cm to the handoff box, or overlapping it.
- `last_zone_check` (optional): `{"zone_check", "zone_confirm", "t"}` of the last sharp set-down (see Event), or `null`.
- `latency_ms` (optional): `{"skill": ms, "skill_p50": ms, "skill_n": int, "hand_age": ms, "tray_age": ms}`. `skill` is the last `run_skill` call, `skill_p50` the median of the last 50; `hand_age` and `tray_age` are how long ago vision last posted a Hand and a TrayState. Each can be `null` (nothing yet).
- `arm_telemetry` (optional, only when the arm has `telemetry()`): the last `{"temps": {motor: C}, "loads": {motor: raw}, "hottest": C, "cooling": bool, "t": unix}`, read about once a second off the event loop, or `null` when the last read failed.

`step` is one of `idle`, `finding`, `picking`, `checking`, `moving_to_hand`, `setting_down`, `waiting_for_pull`, `releasing`, `homing`, `returning`, `stopped`, `error`.

## Stats (`GET /stats`, also the ledger's `GET /api/stats`)

```json
{
  "by_item": [{"item": "hemostat", "attempts": 10, "successes": 9, "success_rate": 0.9,
               "wilson_low": 0.6, "wilson_high": 0.98, "median_request_to_hand_s": 6.1}],
  "by_lighting": [{"lighting": "normal", "attempts": 10, "successes": 9, "success_rate": 0.9,
                   "wilson_low": 0.6, "wilson_high": 0.98, "median_request_to_hand_s": 6.1}],
  "median_request_to_hand_s": 6.1,
  "out": ["hemostat"],
  "next_likely": {"item": "mayo_scissors", "after": "hemostat", "share": 0.6, "n": 5, "setting": "surgical"},
  "t": 1760731200.12
}
```

- Rates come from `log_test` rows; medians from `handed` events (else the test rows' `seconds`). Rows with `fake_arm` or `sim` true are left out unless `GET /api/stats?sim=1`. `next_likely` and `out` may be `null` / `[]`.
- Without the ledger the controller answers the same shape with `"source": "controller memory (ledger not loaded)"`, `wilson_low`/`wilson_high` null and `by_lighting` empty.

## TrayState (vision to the controller, about once a second)

```json
{
  "setting": "surgical",
  "slots": [
    {"item": "hemostat", "present": true, "confidence": 0.91, "box": [120, 80, 260, 140]},
    {"item": "scalpel", "present": false, "confidence": 0.88, "box": [120, 160, 260, 210]}
  ],
  "return_spot": {"item": null, "confidence": 0.0, "box": null},
  "stale": false,
  "t": 1760731200.12
}
```

- `stale` (optional): `true` when the Perceptron call failed or timed out and the local slot check could not answer; the body is the last good read with a new `t`. The controller treats a stale TrayState, or one older than `TRAY_STALE_S` (default 8 s, set in `.env`), as no camera reading (the count and the grasp check fall back to the gripper and `out`).
- `detector` (optional): `perceptron` when `/v1/detect` answered within its timeout (6 s unless `VISION_DETECT_TIMEOUT_S` is set), `local` when that call was slow, failed, or out of credits and each slot was judged full or empty from the image, `none` when neither answered and `stale` is true.
- Perceptron gives no confidence, so a fresh read uses `1.0`.
- Multiple physical instances may be supplied as separate present slot rows for the same `item`. Optional per-row `slot` (one-based), `variant`, `side` or instance metadata identify them. Never collapse two detections into one before asking which one.

## Hand (vision to the controller, about 10 times a second)

```json
{
  "seen": true,
  "open": true,
  "palm_px": [412, 300],
  "target": [0.22, -0.10, 0.18],
  "path_clear": true,
  "t": 1760731200.12
}
```

- `target` is the arm point a few cm short of the palm, already converted with the calibration. `null` if there's no hand or no calibration.
- `target_px` (optional): the pixel of `target` (the palm pixel without calibration), for the preview overlay. Only when `seen` is true.
- The controller treats a Hand older than 0.5 s as `seen: false`.

## Event (controller to the dashboard, the voice server and the ledger)

```json
{
  "type": "handed",
  "item": "hemostat",
  "step": "waiting_for_pull",
  "say": "hemostat coming",
  "request_to_hand_s": 6.4,
  "retries": 0,
  "setting": "surgical",
  "lighting": "normal",
  "command_id": "3f1c...",
  "t": 1760731206.52
}
```

- `type` is one of `command`, `step`, `picked`, `handed`, `set_down`, `released`, `returned`, `missed`, `count`, `stopped`, `error`.
- Optional types `clarify` and `clarify_answer` record each question and answer. A question carries `say`, `item`, `candidates` and `question_id`. Each candidate can carry `item` (item id), `label`, `variant`, `side`, `slot` and `instance` (the handover hint). Answers carry `question_id`, `answer` and `answer_ms` (elapsed milliseconds). Cancellation and timeout are answers too, with no handover. `context` optionally identifies the call or text thread. These events use the same WebSocket and ledger path as all other events.
- Optional `type` `read`: the result of a reading command, with a `read` object `{"kind": "count_sheet" | "tray_tag" | "pack_label", "ok", "method": "qr" | "perceptron" | "gemini" | null, "latency_ms", ...}` plus the reader's fields (vision `POST /read/*`). Its `say` is the spoken answer. Optional extras: for a count sheet `compare` (`"closing"`, `"initial"` or `null`) and `mismatch` (closing mode `[{"item", "sheet", "scrub"}]`, initial mode `[{"item", "sheet", "expected"}]`); for a tray tag `switched` (bool); `error` when vision can't be reached.
- `read.source` (optional) is `"photo"` when the result came from a texted photo through `POST /read_result`.
- `sheet_mismatch` (optional) on `count` events, when a count sheet was read this case: `[{"item", "sheet", "scrub"}]`, where the sheet's count and Scrub's count of that item on the tray differ.
- `say` is the line the voice server speaks, or `null`. Only the controller writes these lines, so wording lives in one place.
- Every field except `type` and `t` can be `null`.
- `case_id` (optional): the case this event belongs to, same value as in State.
- `fake_arm` (optional, bool): `true` on fake-arm and sim runs. `sim` (optional, bool) has the same effect. The controller also sends `arm` (`"fake"`, `"sim"` or `"real"`) and `sim` on every event, as in State. The ledger leaves these rows out of the `/stats` rates and medians; `GET /api/stats?sim=1` includes them.
- `out_camera` (optional) on `count` events: the same value as in State at that moment. The voice server uses it to group the end-of-case text.
- The voice server speaks Event `say` lines only. The `say` in the `/command` reply repeats the same line, for keyboard and curl use.
- Optional extra fields on `command` events: `action`, `heard`, `source`, `accepted`, `reason`. Every event carries `out` (the State's list at that moment), so pages don't need to re-read `/state`. On `error` events: `error`, and for the robot model's API errors (Perceptron) `code` (the HTTP status as an int, or `null` when it didn't answer) and `reason` (a short message with no keys, e.g. "Perceptron HTTP 503"). An `error` event from pre-opening sessions after a setting change has `command_id: null` and leaves `step` as it was (the arm is not held); one from a skill run holds the arm (`step: "error"`) like any error. Every event also carries `judge` (bool). On `stopped` events from the hand watcher: `reason` (`hand_lost`, `hand_blocked`, or `hand_closed` when the hand stayed closed on the fast leg of the approach); the arm holds the item until a reset.
- `skill_source` (optional): `"model"`, `"taught"`, `"taught_adjusted"` (taught waypoints shifted by the located offset) or `"ik"` (top-down grasp from the located pose) on every event of a pick or return flow (its `step` events, `picked`, `missed`, `handed`, `released`, `set_down`, `returned`, and a `stopped` or `error` that lands during it). Never on `command` or `count` events. Taught skills are a labeled backup; pages and voice show the source.
- `arm` (optional, every event): `"real"`, `"sim"` or `"fake"`. `test` (optional): `true` on events from a test run (`SCRUB_TEST`). The picker counts only `arm: "real"` rows without `test`.
- Smart pick fields (optional, on `picked`, `missed`, `handed`, `set_down`, `returned` of a `--skills smart` handover): `locate_method` (`"local"`, `"perceptron"`, `"gemini"`, `"slot"`, `"none"` or `null` when vision didn't answer), `locate_confidence` (0..1 or `null`), `grasp_check` (`"gripper"`, `"gripper+wrist"`, `"wrist"` or `"none"`: what judged the grip), `retry` (0 for the first method, 1 for the next one after a miss), `wrist_disagrees` (`true` when the jaw says held and the wrist camera says no; still a pick). The first miss is a `missed` with `retries: 1` and the retry line; two misses end with the "couldn't pick" `missed`.
- Sharps (`sharp: true` items) never go to a hand in any mode. `set_down` of a sharp carries `zone_check` (`"clear"`, `"cleared_after_wait"` after "Clear the safe spot.", or `"no_camera"`) and `zone_confirm` (`true`/`false`: the overhead camera sees it in the zone; `null`: no camera). A zone that stays blocked puts it back in its slot: a `missed` with `zone_check: "timeout_to_slot"`. On the real arm a sharp with no valid safe zone is refused before moving: a `missed` with `reason` "safe zone: ...". A hand inside 20 cm of the tip or the zone while a sharp is held: "Hand back, I'm holding a sharp.", then a `stopped` with `reason` `hand_keepout` if it stays during a move.
- `release` (optional) on `released` events: why the gripper opened: `"pull"` (load change over `PULL_LOAD_DELTA`), `"collapse"` (grip load fell toward zero) or `"got_it"`.
- An `error` event from an arm thermal stop (`ArmFault`, below) has the arm's message as `say`, e.g. "Too hot: shoulder_lift 71 C. Cooling down.", and holds the arm like any error.

## Vision endpoints (port 8001)

Read by the controller (`/tray_check`, `/snapshot`) and the dashboard (`/stream`, `/snapshot`, `/vision/tray`). All optional.

| Endpoint | Returns |
| --- | --- |
| `GET /health` | `{"ok": true, "camera": bool, "exposure_locked": bool, "controls": {...}}` |
| `GET /snapshot`, `GET /stream` | the annotated overhead frame as a JPEG, or MJPEG |
| `GET /vision/hand`, `GET /vision/tray` | the last Hand and TrayState it posted |
| `GET /lighting` | `{"lighting", "lux", "brightness", "t"}` |
| `GET /tray_check` | `{"ok", "ready", "setting", "missing": [ids], "wrong_slot": [{"item", "in_slot_of": id or null, "found_in"}], "extra": [], "correct", "slots", "return_spot", "stale", "summary", "t"}`. Reads the last tray read, never calls Perceptron. `stale` is true with no read yet, a failed read, or one older than `VISION_TRAY_STALE_S` (default 8 s) |
| `POST /clinician` | `{"name", "hand_height_m"}` -> `{"ok", "clinician", "hand_height_m"}` |
| `POST /gripper` | `{"px": [x, y] or null}` -> `{"ok", "px"}` |
| `GET /clips?case_id=`, `POST /clips/record`, `POST /clips/label`, `GET /clips/{case_id}/{file}` | X4 event clips (`docs/PERCEPTRON-ROBOTICS.md`) |
| `GET /locate?item=<id>` | `{"item", "found", "center_px", "slot_center_px", "offset_px", "offset_mm", "yaw_deg", "arm_xy", "arm_offset", "confidence", "method": "local" \| "perceptron" \| "gemini" \| "slot" \| "none", "agree", "tray", "setting_ok", "t"}` (`vision/locate.py`). Never an error: unknown or missing is `found: false`, `method: "none"`. The controller waits at most 2.5 s; `found: false` with confidence 0.6 or more from local, perceptron or gemini is "not on the tray" |
| `GET /safe_zone` | `{"clear": bool or null, "blocked_by": ["hand" or item id], "item_in_zone": id or null, "method", "confidence", "t"}`. `clear: null` with no zone pixels (no calibration and no `safe_zone_px` in the setting) |

Vision reads the controller's `GET /state`, `GET /setting` and `GET /events/recent?n=20`, and posts `/vision/hand`, `/vision/tray` and `/lighting` (only when the tag changes, with `lux`).

## Ledger public page (port 8080)

`GET /api/stats` (Stats, `?sim=1` includes fake and sim rows), `GET /api/cases`, `GET /api/case?id=<case_id>` (400 for a bad id, 404 for none), `GET /api/public` (`{"url"}`), `GET /qr.png`. The `/api/*` routes send CORS headers (GET from any origin).

## Setting file (`settings/<id>.json`)

```json
{
  "id": "surgical",
  "label": "Operating room",
  "items": [
    {
      "id": "hemostat",
      "name": "hemostat",
      "aliases": ["kelly", "clamp", "hemo"],
      "sharp": false,
      "slot": [120, 80, 260, 140],
      "pick_instruction": "pick the hemostat",
      "return_instruction": "return the hemostat"
    }
  ],
  "return_spot": [400, 300, 520, 380]
}
```

Slot and return-spot boxes start as `null` and get filled once the camera is mounted (Brandon marks them; Evan commits the numbers).

Optional overlay `settings/<id>.local.json`: `{"aliases": {"<item id>": ["word", ...]}}`, clinic-taught words, written only by the controller (`POST /alias`). The controller merges it into the setting it loads (added lowercase, deduped, unknown ids ignored), so `GET /setting` and `POST /setting` return the merged file. Code never writes `<id>.json`.

Optional item fields: `group` is a shared request word, and `variant` is the short
distinguishing word. For example, the bench items `flathead_screwdriver` and
`phillips_screwdriver` share `"group": "screwdriver"` and have variants `flathead`
and `Phillips`. "Screwdriver" asks a question; "Phillips" selects one. Existing
names, aliases and exact pick/return instructions stay unchanged. The surgical
training tray has no added example items.

## Arm interface (Python, the controller imports it)

`arm/real_arm.py` (Anish) and `controller/fake_arm.py` (Caiden) both implement this. The controller picks one with `--fake-arm`.

```python
class Arm:
    def connect(self) -> None: ...
    def run_skill(self, instruction: str, max_s: float = 20.0, source: str = "model") -> bool: ...   # "pick the hemostat"; source "taught" plays arm/skills/
    def go_home(self) -> None: ...
    def go_carry(self) -> None: ...
    def move_to(self, x: float, y: float, z: float, speed: float = 0.3) -> bool: ...  # False if outside the handoff region
    def set_down_safe_spot(self) -> bool: ...
    def open_gripper(self) -> None: ...
    def gripper_position(self) -> float: ...   # 0 open, 1 closed
    def gripper_load(self) -> float: ...       # raw load, used for release on pull
    def freeze(self) -> None: ...              # hold position now; must work from any thread
    def disconnect(self) -> None: ...
    # optional:
    def resume(self) -> None: ...              # rearm after a freeze; the controller calls it only on reset
    def prepare(self, instructions: list[str]) -> list: ...  # pre-open robot model sessions; blocking, raises APIError
    def telemetry(self) -> dict | None: ...    # {"temps", "loads", "hottest", "cooling", "t"}; the controller polls it on its own thread
    # optional, smart pick and sharps (arm/grasp.py):
    #   run_skill(..., source="model" | "taught" | "taught_adjusted" | "ik", located=<GET /locate answer or None>)
    def sharp_mode(self, on: bool) -> None: ...      # speed scale grasp.SHARP_SPEED while a sharp is in the flow
    def hover_safe_spot(self) -> bool: ...           # hold above the safe zone
    def wrist_jpeg(self) -> bytes | None: ...        # latest wrist camera frame
    def safe_zone(self) -> dict | None: ...          # rig.json safe_zone {"center", "size", "yaw_deg"}
    def tip(self) -> list | None: ...                # gripper tip [x, y, z], arm base frame
```

A thermal trip during a skill or move raises `arm.hardware.ArmFault` (a `RuntimeError`) after the arm goes safe; the controller turns it into an `error` event with the message as `say` and holds until a reset.

The controller calls `prepare` with every item's `pick_instruction` and `return_instruction` at start, on each setting change and after a reset if the last one didn't finish, on its own thread (never the event loop, never under its lock). `run_skill` retries on its own first (503/504/429 or a timeout: hold and retry; 409/422: reset the session; 401/404/410: a fresh grant and session once) and raises `APIError` after 5 failures in a row. A `return` skill succeeds only after the jaw closed on the item and opened again. `connect()` refuses while another process holds the serial port. `SO101_SIDE_CAMERA` and `SO101_WRIST_CAMERA` may be an index, a /dev path or part of the camera's name. Perceptron failures raise `APIError` (`arm/perceptron.py`, message "Perceptron HTTP <status>"); the controller turns them into `error` events with `code`.

The fake arm sleeps about 1 second per motion and returns `True`. `freeze()` interrupts a running call.

The handoff region (a box in arm coordinates the arm may enter for a handoff), the home pose, the carry pose and the safe-spot pose live in `arm/rig.json` (Anish).

## Ledger interface (Python, the controller imports it)

`ledger/` (Evan):

```python
def log(event: dict) -> None: ...                  # never raises; buffers to a local file if MongoDB is down
def log_test(item: str, setting: str, lighting: str, success: bool,
             seconds: float | None, retries: int) -> None: ...
def stats() -> dict: ...                           # success rate by item and lighting, median request-to-hand time
```

The controller calls `log` on every event. If `ledger` fails to import, the controller runs without it.

## Known mismatches (Oct 17 comb)

- Judge mode: this file says `/setting` still works in judge mode, and the controller allows it (`controller/core.py` `set_setting`). Voice is stricter on purpose: by call or text it never posts `/setting`, `/alias` or `/restock` in judge mode (`voice/src/turn.ts`, `voice/src/texts.ts`). Voice also handles a 403 from `/setting` and `/alias`, which the controller never sends (`/alias` answers 200 `ok: false`). Harmless.

## Keys

Every key comes from environment variables loaded from `.env` at the repo root. `.env` is git-ignored. `.env.example` lists the names.
