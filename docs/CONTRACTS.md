# Contracts

Every part codes against these. Build against fake inputs that match them, and things connect on the first try.

**Changing a contract:** say it in the group chat first, then edit this file. Caiden owns this file because the controller is where everything meets. Adding an optional field is fine without asking. Renaming or removing a field needs everyone's OK.

## Conventions

- JSON everywhere. Times are Unix seconds as floats (`time.time()` in Python, `Date.now() / 1000` in TypeScript), field name `t`.
- Item ids are lowercase with underscores: `scalpel`, `hemostat`, `mayo_scissors`, `mouth_mirror`, `explorer`, `cotton_pliers`, `needle_nose_pliers`, `wire_cutters`, `hex_key`.
- Setting ids: `surgical`, `dental`, `bench`.
- Pixel boxes are `[x1, y1, x2, y2]` in the vision camera's image.
- Arm points are meters in the arm's base frame: x forward, y left, z up. Anish confirms the axes against the SO-101 URDF.

## Ports

| Process | Port | Owner |
| --- | --- | --- |
| controller (also serves the dashboard at `/`) | 8000 | Caiden |
| vision (camera stream and debug) | 8001 | Brandon |
| voice server | 3000 | Caiden |

## Controller endpoints (port 8000)

| Endpoint | Body | Returns |
| --- | --- | --- |
| `POST /command` | a Command | `{"accepted": bool, "reason": str or null, "say": str or null}` |
| `POST /stop` | nothing | `{"accepted": true}`. Always accepted, skips the queue, freezes the arm |
| `GET /state` | | a State |
| `POST /setting` | `{"setting": "surgical"}` | the loaded setting file. 409 if the arm is busy (idle or stopped only; clears `out`), 404 for an unknown id |
| `POST /lighting` | `{"lighting": "bright" or "normal" or "dim", "lux": number or null}` | `{"ok": true}`. Tags later events for the tables |
| `POST /vision/tray` | a TrayState | `{"ok": true}` |
| `POST /vision/hand` | a Hand | `{"ok": true}` |
| `GET /stats` | | the success tables, from the ledger |
| `WS /events` | | a stream of Events |
| `GET /` | | the dashboard (static files from `dashboard/`) |
| `GET /setting` | | the current setting file (optional, added Sat 2 PM) |
| `POST /reset` | nothing | `{"ok": true}`: clears a stop or error, opens the gripper, homes, clears `out`. 409 if busy (optional) |
| `GET /events/recent?n=50` | | the last n Events, oldest first (optional) |

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
- `source` is one of `voice`, `keyboard`, `dashboard`.
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
  "t": 1760731200.12
}
```

`step` is one of `idle`, `finding`, `picking`, `checking`, `moving_to_hand`, `setting_down`, `waiting_for_pull`, `releasing`, `homing`, `returning`, `stopped`, `error`.

## TrayState (vision to the controller, about once a second)

```json
{
  "setting": "surgical",
  "slots": [
    {"item": "hemostat", "present": true, "confidence": 0.91, "box": [120, 80, 260, 140]},
    {"item": "scalpel", "present": false, "confidence": 0.88, "box": [120, 160, 260, 210]}
  ],
  "return_spot": {"item": null, "confidence": 0.0, "box": null},
  "t": 1760731200.12
}
```

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
- The voice server speaks Event `say` lines only. The `say` in the `/command` reply repeats the same line, for keyboard and curl use.
- Optional extra fields on `command` events: `action`, `heard`, `source`, `accepted`, `reason`. Every event carries `out` (the State's list at that moment), so pages don't need to re-read `/state`. On `error` events: `error`.

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
```

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

## Keys

Every key comes from environment variables loaded from `.env` at the repo root. `.env` is git-ignored. `.env.example` lists the names.
