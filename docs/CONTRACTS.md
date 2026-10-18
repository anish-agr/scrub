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
| `GET /arm/pose` | | `{"available": bool, "joints_deg": [5] or null, "gripper": 0..1 or null, "tip_m": [x, y, z] or null, "tip_px": [x, y] or null, "calibrated": bool, "reason": str or null, "t": float}` (optional, read-only). Real arm only, optional: `"counters": {"accepted", "late", "holds", "ticks", "overruns", "api_errors"}` and `"last_reason": str` for first-contact checks |
| `GET /arm/camera/{side,wrist}`, `GET /arm/stream/{side,wrist}` | | a JPEG, or MJPEG; 404 until the arm has `camera_jpeg(name)` (optional) |
| `GET /camera/overhead` | | vision's `/snapshot` proxied, 502 if vision is down (optional) |
| `GET /calibration` | | `vision/calibration.json`, 404 if missing (optional) |
| `POST /alias` | `{"item": "hemostat", "alias": "clamp"}` | Always 200: `{"ok": bool, "say": str, "reason": str or null}` (X6 clinic words). `ok: false` for an unknown item, a bad word, a word another item already has, or judge mode (`reason` "judge mode"). Saved in `settings/<id>.local.json` (optional) |
| `POST /restock` | `{"type": "restock", "item", "qty", "setting", "from", "heard", "case_id", "t"}` (voice texts) | `{"ok": bool}`: `false` when the ledger isn't loaded (voice then appends to `voice/restocks.jsonl`). Goes to `ledger.log` as a record with `type: "restock"`, not an Event (optional) |
| `GET /tray_check` | | X3: vision's `GET /tray_check` for the current setting, plus `say`, `available` (vision answered), `label` and `items` (the setting's item names). Vision down or a timeout (3 s): falls back to the controller's own TrayState when it is under 3 s old and not stale (reports missing items only). Otherwise `ok: false`, `say` "I can't check the tray right now." (optional) |
| `POST /fake/force` | `{"miss_grasp", "out_of_region", "skill_fail", "no_pull", "no_load", "api_error"}` (ints, all optional) | the fake arm's pending forced failures. 400 unless `--fake-arm` (testing only, optional) |
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
- `item` is an item id from the current setting, or `null` for `return`, `count`, `stop`, `got_it` and `unknown`.
- `source` is one of `voice`, `keyboard`, `dashboard`, or `auto` (the controller's own return when an item sits in the return spot, F1; it appears only on `command` events, never in a POST).
- `got_it` means release now (the voice fallback for release on pull).
- The voice server never sends an item that isn't in the current setting. Gemini's schema only allows those ids.

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
- `case_id` (optional): the current case, `<setting>-<unix start seconds>`. A new case starts when the controller starts, when the setting changes and on `POST /reset` with `clear_count`.
- `judge` (optional): `true` in judge mode (`POST /judge`).

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

- `stale` (optional): `true` when the Perceptron call failed or timed out; the body is the last good read with a new `t`. The controller treats a stale TrayState, or one older than 3 s, as no camera reading (the count and the grasp check fall back to the gripper and `out`).
- Perceptron gives no confidence, so a fresh read uses `1.0`.

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
- `say` is the line the voice server speaks, or `null`. Only the controller writes these lines, so wording lives in one place.
- Every field except `type` and `t` can be `null`.
- `case_id` (optional): the case this event belongs to, same value as in State.
- `fake_arm` (optional, bool): `true` on fake-arm and sim runs. `sim` (optional, bool) has the same effect. The ledger leaves these rows out of the `/stats` rates and medians; `GET /api/stats?sim=1` includes them.
- `out_camera` (optional) on `count` events: the same value as in State at that moment. The voice server uses it to group the end-of-case text.
- The voice server speaks Event `say` lines only. The `say` in the `/command` reply repeats the same line, for keyboard and curl use.
- Optional extra fields on `command` events: `action`, `heard`, `source`, `accepted`, `reason`. Every event carries `out` (the State's list at that moment), so pages don't need to re-read `/state`. On `error` events: `error`, and for the robot model's API errors (Perceptron) `code` (the HTTP status as an int, or `null` when it didn't answer) and `reason` (a short message with no keys, e.g. "Perceptron HTTP 503"). An `error` event from pre-opening sessions after a setting change has `command_id: null` and leaves `step` as it was (the arm is not held); one from a skill run holds the arm (`step: "error"`) like any error. Every event also carries `judge` (bool). On `stopped` events from the hand watcher: `reason` (`hand_lost` or `hand_blocked`); the arm holds the item until a reset.

## Vision endpoints (port 8001)

Read by the controller (`/tray_check`, `/snapshot`) and the dashboard (`/stream`, `/snapshot`, `/vision/tray`). All optional.

| Endpoint | Returns |
| --- | --- |
| `GET /health` | `{"ok": true, "camera": bool, "exposure_locked": bool, "controls": {...}}` |
| `GET /snapshot`, `GET /stream` | the annotated overhead frame as a JPEG, or MJPEG |
| `GET /vision/hand`, `GET /vision/tray` | the last Hand and TrayState it posted |
| `GET /lighting` | `{"lighting", "lux", "brightness", "t"}` |
| `GET /tray_check` | `{"ok", "ready", "setting", "missing": [ids], "wrong_slot": [{"item", "in_slot_of": id or null, "found_in"}], "extra": [], "correct", "slots", "return_spot", "stale", "summary", "t"}`. Reads the last tray read, never calls Perceptron. `stale` is true with no read yet, a failed read, or one older than 3 s |
| `POST /clinician` | `{"name", "hand_height_m"}` -> `{"ok", "clinician", "hand_height_m"}` |
| `POST /gripper` | `{"px": [x, y] or null}` -> `{"ok", "px"}` |
| `GET /clips?case_id=`, `POST /clips/record`, `POST /clips/label`, `GET /clips/{case_id}/{file}` | X4 event clips (`docs/PERCEPTRON.md`) |

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

## Arm interface (Python, the controller imports it)

`arm/real_arm.py` (Anish) and `controller/fake_arm.py` (Caiden) both implement this. The controller picks one with `--fake-arm`.

```python
class Arm:
    def connect(self) -> None: ...
    def run_skill(self, instruction: str, max_s: float = 20.0) -> bool: ...   # "pick the hemostat"
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
```

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
