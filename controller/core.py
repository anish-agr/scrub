"""State, events and the step machine. Arm calls run on one worker thread; stop never waits on it."""
import json
import math
import os
import re
import statistics
import threading
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import lines, picker, reads, settings
from vision import instances  # pure candidate validation; no camera or arm imports

try:
    import ledger  # Evan's; optional
    if not hasattr(ledger, "log"):  # folder exists but nothing in it yet
        ledger = None
except Exception:  # noqa: BLE001 - run without it
    ledger = None

HAND_STALE_S = 0.5          # contract: older Hand counts as seen: false
TRACKING_ACTIVE_S = 5.0     # a Hand posted this recently means vision is running
# A TrayState older than this is no camera reading (.env TRAY_STALE_S). Vision posts after each Perceptron detect,
# 3.8 to 4.7 s on 640x480 trays (docs/RECOGNITION.md), so 3 s made most reads stale and a gap over this resets
# auto return. 8 s matches vision's own VISION_TRAY_STALE_S.
TRAY_STALE_S = float(os.environ.get("TRAY_STALE_S") or 8.0)
TRAY_LAG_S = 1.0            # a TrayState this soon after the pick may show the tray from before it
HAND_WAIT_S = 10.0
# Hand watcher: this many Hand posts in a row with open: false on the fast leg freezes the arm (0 = off).
# One closed read is flicker; on the slow last leg a closing hand is the clinician taking the instrument.
HAND_CLOSED_READS = int(os.environ.get("HAND_CLOSED_READS") or 3)
PULL_WAIT_S = 30.0
PULL_DELTA = float(os.environ.get("PULL_LOAD_DELTA", "80"))
PULL_COLLAPSE = float(os.environ.get("PULL_COLLAPSE_FRAC", "0.3"))  # grip load at or under this share of the held load: let go
GRIPPER_CLOSED = float(os.environ.get("GRIPPER_CLOSED", "0.95"))  # at or above: closed on nothing
OPEN_MAX = 0.05             # at or below this the gripper is open
APPROACH_BACK_M = 0.08      # stop this far short at normal speed, then creep in
SPEED_NORMAL, SPEED_NEAR = 0.3, 0.1
MAX_QUEUE = 3
DEFAULT_SPOT = [0.22, -0.10, 0.18]  # clinician's saved spot when no hand tracking
REST_AFTER_S = 2.0          # home and nothing queued this long: arm.rest() (torque off) until the next command
AUTO_RETURN_S = 2.0         # an item in the return spot this long with the arm idle goes back on its own
PREPARE_TRIES = 3           # pre-opening the robot model's sessions (L2): tries per setting change
PREPARE_RETRY_S = 5.0
JUDGE_ACTIONS = ("handover", "count", "stop", "got_it")  # all a judge may ask for (L3)
STATE_MAX_AGE_S = 6 * 3600  # a saved count older than this is from another day: start a fresh case
SKILL_MODES = ("model", "taught", "auto", "smart")
TRIES_FILE = Path(os.environ.get("SCRUB_TRIES_FILE") or Path.home() / "scrub-logs" / "skill-tries.json")
AUTO_TRIES = 3              # --skills auto: the model runs an item once it passed this many real tries in a row
TRIES_KEPT = 20
TELEMETRY_S = 1.0           # arm.telemetry() poll period (its own thread; /state reads the cache)
# --skills smart (controller/picker.py chooses the grasp method per item) and the sharps rules (docs/PICKING.md)
LOCATE_S = 2.5              # vision /locate limit; no answer: pick without a located pose
ABSENT_CONFIDENCE = 0.6     # /locate found: false at or above this from a vision method: not on the tray
VISION_METHODS = ("local", "perceptron", "gemini")
WRIST_S = 3.0               # wrist camera "is it in the gripper" limit
KEEPOUT_WAIT_S = 8.0        # a hand inside the sharp keep-out: wait this long for it to move back
ZONE_WAIT_S = 10.0          # safe zone blocked: hold above it this long, then put the sharp back in its slot
ZONE_POLL_S = 0.5
PICK_EVENTS = ("picked", "missed", "handed", "set_down", "returned")
LOCATE_URL = None           # None: VISION_URL; tests set "" (no vision, no network)
CLARIFY_S = 15.0            # no queued motion: an unanswered choice is discarded, never resumed


def _saved_spot() -> list:
    rig = Path(__file__).resolve().parent.parent / "arm" / "rig.json"
    try:
        spot = json.loads(rig.read_text()).get("handoff_spot")
        if spot:
            return list(spot)
    except Exception:  # noqa: BLE001
        pass
    return list(DEFAULT_SPOT)


def _load_state(path, setting_id: str) -> dict | None:
    """The saved {out, case_id, setting, t} if it is for this setting and under STATE_MAX_AGE_S old."""
    try:
        d = json.loads(Path(path).read_text())
        if (d.get("setting") == setting_id and time.time() - float(d.get("t", 0)) < STATE_MAX_AGE_S
                and isinstance(d.get("out"), list) and d.get("case_id")):
            return d
    except Exception:  # noqa: BLE001 - missing or bad file: a fresh case
        pass
    return None


def _save_state(path, d: dict) -> None:
    """Temp file plus rename, so a crash mid-write never leaves half a file."""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(d))
        os.replace(tmp, p)
    except Exception as e:  # noqa: BLE001 - never let a disk problem touch the arm
        print(f"[state] not saved: {e!r}", flush=True)


def _load_tries(path) -> dict:
    """{"<setting>/<item>": [{"direction", "source", "ok", "t"}, ...]} of real-arm tries, or {}."""
    try:
        d = json.loads(Path(path).read_text())
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001 - missing or bad file: no record yet
        return {}


def _taught_available(setting_id: str) -> dict:
    """arm/taught.py's {item: {"pick", "return"}} for this setting; {} until that file exists."""
    try:
        from arm import taught  # Anish's; only the controller imports arm/
        return {k: set(v) for k, v in (taught.available(setting_id) or {}).items()}
    except Exception:  # noqa: BLE001
        return {}


def _rig() -> dict:
    try:
        return json.loads((Path(__file__).resolve().parent.parent / "arm" / "rig.json").read_text())
    except Exception:  # noqa: BLE001
        return {}


def _grasp():
    from arm import grasp  # pure functions (numpy); only the controller imports arm/
    return grasp


def _target_ok(t) -> bool:
    return (isinstance(t, (list, tuple)) and len(t) == 3
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in t))


def _is(e: Exception, name: str) -> bool:
    return any(c.__name__ == name for c in type(e).__mro__)


class Stopped(Exception):
    pass


def _api_error(e: Exception) -> tuple[int | None, str] | None:
    """(HTTP status or None, short reason) if e is a Perceptron APIError (arm/perceptron.py), else None.
    APIError carries no status field, only "Perceptron HTTP 503", so the code comes from the message."""
    if not _is(e, "APIError"):
        return None
    code = getattr(e, "status_code", None) or getattr(e, "status", None)
    m = re.search(r"HTTP (\d{3})", str(e))
    if code is None and m:
        code = int(m.group(1))
    return code, str(e)[:200]


class Controller:
    def __init__(self, arm, fake_arm: bool, setting_id: str = "surgical", judge: bool = False,
                 state_file: str | Path | None = None, skills: str = "model", deployment: bool = True,
                 tries_file: str | Path | None = None, arm_kind: str | None = None, locator=None):
        self.arm = arm
        self.fake_arm = fake_arm  # true for anything but the real arm (fake and sim): kept out of real stats
        self.arm_kind = arm_kind or ("real" if not fake_arm else "sim" if "Sim" in type(arm).__name__ else "fake")  # on /state and events
        self.test = bool(os.environ.get("SCRUB_TEST"))  # test runs tag their events test: true
        if skills not in SKILL_MODES:
            raise ValueError(f"skills must be one of {SKILL_MODES}")
        self.skills = skills            # --skills model|taught|auto
        self.deployment = deployment    # a robot model deployment exists (real arm: PERCEPTRON_DEPLOYMENT_ID set)
        self.tries_file = Path(tries_file) if tries_file else TRIES_FILE  # only the real arm writes it
        self.tries = _load_tries(self.tries_file)
        self.skill_source = None        # "model" or "taught" for the flow running now; on its events
        self._skill_ms: deque = deque(maxlen=50)  # run_skill durations
        self.telemetry = None           # last arm.telemetry(), read on its own thread
        self.lock = threading.RLock()
        self.setting = settings.load(setting_id)
        self.step = "idle"
        self.item = None
        self.out: list[str] = []
        self.out_instances: list[dict] = []
        self.case_id = self._new_case()
        # The count survives a controller restart mid-case: {out, case_id, setting, t} saved on change (None = off).
        self.state_file = state_file
        self._saved = None              # (out, case_id, setting) last written
        self._state_pool = ThreadPoolExecutor(1) if state_file else None
        saved = _load_state(state_file, self.setting["id"]) if state_file else None
        if saved:
            self.out, self.case_id = [str(i) for i in saved["out"]], str(saved["case_id"])
            self.out_instances = [r for r in saved.get("out_instances", []) if isinstance(r, dict) and r.get("item") in self.out]
            self._saved = (tuple(self.out), self.case_id, self.setting["id"])
            print(f"[state] restored case {self.case_id}, out: {self.out or 'nothing'}", flush=True)
        self.lighting = "normal"
        self.lux = None
        self.judge = judge              # L3: only handover, count, stop and got_it from /command
        self.jobs: deque = deque()
        self.jobs_cv = threading.Condition(self.lock)
        self.gen = 0                    # bumped by stop; running flows abort when it changes
        self.got_it = threading.Event()
        self.hand: dict | None = None
        self.hand_at = 0.0
        self.tray: dict | None = None
        self.tray_at = 0.0
        self._known_instances = {}     # multiplicity survives stale/local occupancy reads until a fresh detection disproves it
        self._spot_item = None          # item the return spot has shown since _spot_since
        self._spot_since = 0.0
        self._auto_done = None          # auto-returned already; not again until it leaves the spot
        self.history: deque = deque(maxlen=500)
        self._reading: set = set()      # read_* actions with a vision read in flight (one each at a time)
        self.listeners: list = []       # (loop, asyncio.Queue)
        self.cmd = None                 # command being run
        self.resting = False            # arm parked at home with torque off (arm.rest); woken per command
        self._idle_since = time.time()
        self.held = None                # item id picked and not yet released, set down or returned
        self.held_instance = None
        self._ledger_pool = ThreadPoolExecutor(1)
        self._flow_gen = 0              # gen of the job the worker is running
        self._worker_thread = threading.Thread(target=self._worker, daemon=True)
        self._worker_thread.start()
        self._prep_gen = 0              # bumped per prepare; an older prepare thread gives up
        self._prep_said = False         # spoke a prepare failure since the last setting change
        self.prepared = None            # setting id whose sessions the arm has open
        self.taught = _taught_available(self.setting["id"])
        # --skills smart: vision's /locate and /safe_zone, the chosen methods for this flow, its pick event fields
        url = os.environ.get("VISION_URL", "http://localhost:8001") if LOCATE_URL is None else LOCATE_URL
        self.locator = locator or picker.Locator(url)
        self._order: list = []
        self.pick_fields: dict = {}
        self.last_zone_check = None     # {zone_check, zone_confirm, t} of the last sharp set-down
        self.clarification = None       # pending candidate snapshot, never an arm job
        self._expired_choice = None
        if skills == "smart":
            picker.load_cache()
            self._refresh_policy()
        self._prepare()
        if callable(getattr(arm, "telemetry", None)):
            threading.Thread(target=self._telemetry_loop, daemon=True).start()

    def _telemetry_loop(self) -> None:
        while True:
            try:
                self.telemetry = self.arm.telemetry()
            except Exception:  # noqa: BLE001 - no reading this time
                self.telemetry = None
            time.sleep(TELEMETRY_S)

    # ---------- events ----------
    def emit(self, type_: str, say: str | None = None, **kw) -> dict:
        if (threading.current_thread() is self._worker_thread and self._flow_gen != self.gen
                and type_ not in ("stopped", "error")):
            raise Stopped  # a stop landed mid-flow: nothing after it may speak or change the step
        cmd = self.cmd
        ev = {
            "type": type_, "item": kw.pop("item", self.item), "step": self.step, "say": say,
            "request_to_hand_s": kw.pop("request_to_hand_s", None), "retries": kw.pop("retries", None),
            "setting": self.setting["id"], "lighting": self.lighting,
            "command_id": kw.pop("command_id", cmd["id"] if cmd else None), "out": list(self.out),
            "out_instances": self._out_records(),
            "case_id": self.case_id, "judge": self.judge, "fake_arm": self.fake_arm, **self._arm_tags(), "t": time.time(),
        }
        if self.skill_source and type_ not in ("command", "count"):
            ev["skill_source"] = self.skill_source
        if type_ in PICK_EVENTS:
            ev.update(self.pick_fields)
        if cmd and cmd.get("instance") and type_ not in ("command", "count"):
            ev["instance"] = dict(cmd["instance"])
        if self.test:
            ev["test"] = True
        ev.update(kw)
        self.history.append(ev)
        if self._state_pool is not None:
            key = (tuple(ev["out"]), ev["case_id"], ev["setting"], json.dumps(ev["out_instances"], sort_keys=True))
            if key != self._saved:  # only on a change, and off this thread (never block a stop or the loop)
                self._saved = key
                self._state_pool.submit(_save_state, self.state_file,
                                        {"out": ev["out"], "out_instances": ev["out_instances"], "case_id": ev["case_id"], "setting": ev["setting"], "t": ev["t"]})
        for loop, q in list(self.listeners):
            try:
                loop.call_soon_threadsafe(q.put_nowait, ev)
            except RuntimeError:  # that page's loop already closed; never let it kill the worker or a stop
                pass
        if ledger is not None:
            self._ledger_pool.submit(ledger.log, dict(ev))
        return ev

    def set_step(self, step: str, item=...) -> None:
        if threading.current_thread() is self._worker_thread and self._flow_gen != self.gen:
            raise Stopped
        with self.lock:
            self.step = step
            if item is not ...:
                self.item = item
        self.emit("step")

    def state(self) -> dict:
        with self.lock:
            now = time.time()
            ms = list(self._skill_ms)
            age = lambda at: round((now - at) * 1000) if at else None  # noqa: E731
            st = {
                "step": self.step, "item": self.item, "queue": [j["item"] for j in self.jobs],
                "out": list(self.out), "setting": self.setting["id"], "lighting": self.lighting,
                "out_instances": self._out_records(),
                "fake_arm": self.fake_arm, **self._arm_tags(), "hand_seen": self._hand_fresh() is not None,
                "out_camera": self._camera_out()[0], "case_id": self.case_id, "judge": self.judge,
                "resting": self.resting, "t": now,
                "clarify": self._public_choice(self.clarification) if self.clarification else None,
                "sheet": self.sheet, "packs": list(self.packs),
                # per item: the source its pick runs with (null: --skills taught and no taught skill)
                "skills": {"mode": self.skills,
                           "items": {it["id"]: self._skill_source(it["id"], "pick") for it in self.setting["items"]}},
                "safe_zone": self._zone_state(), "last_zone_check": self.last_zone_check,
                "latency_ms": {"skill": ms[-1] if ms else None, "skill_p50": statistics.median(ms) if ms else None,
                               "skill_n": len(ms), "hand_age": age(self.hand_at), "tray_age": age(self.tray_at)},
            }
            if self.skills == "smart":
                st["skills"]["policy"] = {it["id"]: {k: c.get(k) for k in ("method", "confidence", "why", "order")}
                                          for it in self.setting["items"] for c in [self._choice(it["id"])]}
            if hasattr(self.arm, "telemetry"):
                st["arm_telemetry"] = self.telemetry
            return st

    def _zone_state(self) -> dict:
        zone = self._safe_zone()
        return {"center": (zone or {}).get("center"), "size": (zone or {}).get("size"),
                "problems": self._zone_problems(zone)}

    def _safe_zone(self) -> dict | None:
        try:
            return self.arm.safe_zone() if callable(getattr(self.arm, "safe_zone", None)) else None
        except Exception:  # noqa: BLE001
            return None

    def _zone_problems(self, zone) -> list:
        """Why the safe zone can't take a sharp (real arm only; the sim's own zone is fine): [] when it can."""
        if self.arm_kind != "real":
            return []
        probs = list(_grasp().safe_zone_problems(getattr(self.arm, "rig", None) or _rig()))
        return probs or ([] if zone else ["no safe zone on the arm"])

    # ---------- skill source ----------
    def _skill_source(self, item_id: str, direction: str) -> str | None:
        """"model" or "taught" for one item's pick or return under --skills. None: taught asked for, none recorded."""
        taught = direction in self.taught.get(item_id, ())
        if self.skills == "smart":
            return self._choice(item_id, direction)["method"]
        if self.skills == "model":
            return "model"
        if self.skills == "taught":
            return "taught" if taught else None
        if self.deployment and self._model_proven(item_id):
            return "model"
        return "taught" if taught else "model"

    def _choice(self, item_id: str, direction: str = "pick") -> dict:
        """--skills smart: picker's in-memory choice {method, order, confidence, why} (no I/O)."""
        return picker.choose(item_id, self.setting["id"], deployment=self.deployment,
                             taught=direction in self.taught.get(item_id, ()))

    def _methods(self, item_id: str, direction: str) -> list:
        """Methods an item can use now: model with a deployment, taught ones with a taught skill, ik always."""
        taught = direction in self.taught.get(item_id, ())
        return ["model"] * self.deployment + ["taught", "taught_adjusted"] * taught + ["ik"]

    def _refresh_policy(self) -> None:
        """--skills smart: re-rank every item from the real-arm ledger rows on its own thread (MongoDB, the policy file)."""
        if self.skills != "smart":
            return
        sid, items = self.setting["id"], [i["id"] for i in self.setting["items"]]
        taught = {k for k, v in self.taught.items() if "pick" in v}
        dep, light = self.deployment, self.lighting

        def run():
            try:
                picker.refresh(sid, items, deployment=dep, taught=taught, lighting=light)
            except Exception as e:  # noqa: BLE001 - the cached choice stays
                print(f"[picker] refresh failed: {e!r}", flush=True)
        threading.Thread(target=run, daemon=True).start()

    def _model_proven(self, item_id: str) -> bool:
        """The model passed this item's last AUTO_TRIES real tries."""
        rows = [r for r in self.tries.get(f"{self.setting['id']}/{item_id}", []) if r.get("source") == "model"]
        rows = rows[-AUTO_TRIES:]
        return len(rows) == AUTO_TRIES and all(r.get("ok") for r in rows)

    def _arm_tags(self) -> dict:
        """arm: which arm runs ("fake", "sim", "real"); sim: true on the sim (the ledger and video tell it from the fake arm)."""
        return {"arm": self.arm_kind, "sim": self.arm_kind == "sim"}

    def _record_try(self, item_id: str, direction: str, source: str, ok: bool) -> None:
        """One real-arm try for --skills auto, saved to tries_file (worker thread; never the event loop)."""
        if self.fake_arm:
            return
        rows = self.tries.setdefault(f"{self.setting['id']}/{item_id}", [])
        rows.append({"direction": direction, "source": source, "ok": bool(ok), "t": time.time()})
        del rows[:-TRIES_KEPT]
        _save_state(self.tries_file, self.tries)

    # ---------- inputs ----------
    def submit(self, cmd: dict) -> dict:
        """Every spoken line goes out as an event; the reply's `say` repeats it for convenience."""
        if not cmd.get("id"):  # also replaces an explicit null
            cmd["id"] = uuid.uuid4().hex
        if not cmd.get("t"):
            cmd["t"] = time.time()
        cmd["received"] = time.time()
        action = cmd.get("action")
        if self.judge and action not in JUDGE_ACTIONS:
            self._emit_command(cmd, False, "judge mode", lines.JUDGE_ONLY)
            return {"accepted": False, "reason": "judge mode", "say": lines.JUDGE_ONLY}
        if action == "stop":
            self.stop()
            self._emit_command(cmd, True, None, None)
            return {"accepted": True, "reason": None, "say": lines.STOPPED}
        if action == "count":
            say, cam, mism = self._count_line()
            self._emit_command(cmd, True, None, None)
            extra = {} if mism is None else {"sheet_mismatch": mism}
            self.emit("count", say=say, item=None, command_id=cmd["id"], out=list(self.out), out_camera=cam, **extra)
            return {"accepted": True, "reason": None, "say": say}
        if action in reads.KINDS:
            return self._start_read(cmd)
        with self.lock:
            ok, reason, say = self._check(cmd)
            gen, sid = self.gen, self.setting["id"]
        if ok and action == "handover":
            reply = self._preflight(cmd, gen, sid)
            if reply is not None:
                return reply
        elif ok and action == "return":
            reply = self._preflight_return(cmd, gen, sid)
            if reply is not None:
                return reply
        with self.lock:
            if ok:
                if gen != self.gen or sid != self.setting["id"]:
                    ok, reason, say = False, "request cancelled", lines.NEEDS_RESET if gen != self.gen else lines.CHOICE_EXPIRED
                else:
                    ok, reason, say = self._check(cmd)
            self._emit_command(cmd, ok, reason, say)
            if ok and action in ("handover", "return"):
                self.jobs.append(cmd)
                self.jobs_cv.notify()
            elif ok and action == "got_it":
                self.got_it.set()
        return {"accepted": ok, "reason": reason, "say": say}

    def _emit_command(self, cmd, accepted, reason, say) -> None:
        extra = {"method": cmd["method"]} if cmd.get("method") else {}
        if cmd.get("instance"):
            extra["instance"] = cmd["instance"]
        if cmd.get("question_id"):
            extra["question_id"] = cmd["question_id"]
        self.emit("command", say=say, item=cmd.get("item"), command_id=cmd["id"],
                  action=cmd.get("action"), heard=cmd.get("heard"), source=cmd.get("source"),
                  accepted=accepted, reason=reason, **extra)

    @staticmethod
    def _public_choice(question):
        return {k: question[k] for k in ("say", "item", "candidates", "question_id", "confirm")}

    def _refuse_choice(self, cmd, reason, say):
        self._emit_command(cmd, False, reason, say)
        return {"accepted": False, "reason": reason, "say": say}

    def _ask_choice(self, cmd, options, gen, sid, say=None, confirm=False):
        with self.lock:
            if self.gen != gen or self.setting["id"] != sid:
                return self._refuse_choice(cmd, "request cancelled", lines.CHOICE_EXPIRED)
            name = settings.item(self.setting, cmd["item"])["name"]
            say = say or lines.which_one(name, [c["label"] for c in options])
            question = {"say": say, "item": cmd["item"], "candidates": options,
                        "question_id": uuid.uuid4().hex, "expires": time.monotonic() + CLARIFY_S,
                        "gen": gen, "setting": sid, "confirm": confirm, "action": cmd["action"]}
            if cmd["action"] == "handover" and len(options) > 1:
                self._known_instances[cmd["item"]] = options
            self.clarification = question
            self._expired_choice = None
            self._emit_command(cmd, False, "clarification needed", None)
            public = self._public_choice(question)
            self.emit("clarify", **public, command_id=cmd["id"])

        def expire():
            with self.lock:
                if self.clarification is question:
                    self.clarification = None
                    self._expired_choice = question
                    self.emit("clarify_timeout", say=lines.CHOICE_TIMEOUT, item=question["item"],
                              question_id=question["question_id"], command_id=cmd["id"])
        timer = threading.Timer(CLARIFY_S, expire)
        timer.daemon = True
        timer.start()
        return {"accepted": False, "reason": "clarification needed", "say": say, "clarify": public}

    def _tray_candidates(self, item_id):
        tray = self.tray
        if (not tray or tray.get("stale") or time.time() - self.tray_at > TRAY_STALE_S
                or tray.get("setting", self.setting["id"]) != self.setting["id"]):
            if item_id in self._known_instances:
                return self._known_instances[item_id], True  # old boxes may clarify, never authorize a pick
            return [], False
        if item_id in self._known_instances and (tray.get("detector") == "local" or tray.get("candidates_stale")):
            return self._known_instances[item_id], True
        if "candidates" in tray:
            rows = [s for s in tray["candidates"] if s.get("item") == item_id]
        else:
            rows = [s for s in tray.get("slots", []) if s.get("item") == item_id and s.get("present") and s.get("kind") != "configured"]
            # One configured slot is occupancy only, not proof of the physical candidate's slot number.
            if len(rows) == 1 and not any(k in rows[0] for k in ("instance", "slot", "id")):
                rows = []
            if not rows and item_id in self._known_instances:
                return self._known_instances[item_id], True
        variant = (settings.item(self.setting, item_id) or {}).get("variant")
        if variant:
            rows = [{"variant": variant, **s} for s in rows]
        options, unsafe = instances.candidates(rows, item_id)
        return options, unsafe or bool(tray.get("candidates_stale") and item_id in (tray.get("ambiguous_items") or []))

    def _candidate_is_out(self, candidate):
        for record in self._out_records():
            if record["item"] != candidate.get("item"):
                continue
            if candidate.get("id") and candidate["id"] == record["id"]:
                return True
            hint = record.get("instance") or {}
            if hint and instances.select([candidate], hint):
                return True
        return False

    def _preflight(self, cmd, gen, sid):
        """Validate identity before enqueue/wake. Network calls run outside the controller lock."""
        item_id, hint = cmd["item"], cmd.get("instance")
        hint = {k: v for k, v in (hint or {}).items() if v is not None}
        it = settings.item(self.setting, item_id) or {}
        named_variant = (set(hint) == {"variant"} and isinstance(it.get("variant"), str)
                         and it["variant"].casefold() == str(hint["variant"]).casefold())
        with self.lock:
            pending = self.clarification
            expired = self._expired_choice
            if pending and time.monotonic() >= pending["expires"]:
                self.clarification = None
                self._expired_choice = expired = pending
                pending = None
            qid = cmd.get("question_id")
            if qid and (not pending or pending["question_id"] != qid):
                return self._refuse_choice(cmd, "choice expired", lines.CHOICE_EXPIRED)
            if hint and expired and expired["item"] == item_id:
                return self._refuse_choice(cmd, "choice expired", lines.CHOICE_EXPIRED)
            if not hint and not qid:
                self._expired_choice = None  # a fresh full request, never a late answer
            if not hint and item_id in self._known_instances:
                # A question expiring (or vision timing out) is not evidence that a duplicate disappeared.
                # Only a subsequent fresh detection post can clear this knowledge.
                choices = [c for c in self._known_instances[item_id] if not self._candidate_is_out(c)]
                if not choices and item_id in self.out:
                    return self._refuse_choice(cmd, "already out", lines.with_you(it["name"]))
                say = lines.other_instance(it["name"]) if item_id in self.out and len(choices) == 1 else None
                return self._ask_choice(cmd, choices, gen, sid, say, confirm=bool(say))
            options, unsafe = self._tray_candidates(item_id)
            all_options = options
            options = [c for c in options if not self._candidate_is_out(c)]
            answering = pending and pending["item"] == item_id and bool(hint)
            if answering:
                if qid != pending["question_id"] or pending["action"] != cmd["action"]:
                    return self._refuse_choice(cmd, "question id required", lines.CHOICE_EXPIRED)
                chosen = instances.select(pending["candidates"], hint)
                if not chosen:
                    return self._ask_choice(cmd, pending["candidates"], gen, sid)
                # Resolve to a stable candidate slot, not just a relative word which can change next frame.
                hint = dict(chosen["instance"])
                cmd["instance"] = hint
                cmd["question_id"] = pending["question_id"]
                if unsafe:
                    # Old/local occupancy cannot reject a by-sight answer or authorize its pose.
                    # Let locate validate it afresh; never use these boxes as a timeout fallback.
                    options = []
            elif unsafe or len(options) > 1 and not hint:
                return self._ask_choice(cmd, options, gen, sid)
            elif item_id in self.out and (not hint or named_variant) and options:
                name = settings.item(self.setting, item_id)["name"]
                # One generic slot isn't evidence of a second physical instance.
                other = [c for c in options if c.get("box") or c.get("slot") or c.get("id")]
                if other:
                    return self._ask_choice(cmd, other, gen, sid, lines.other_instance(name), confirm=len(other) == 1)
            if hint and options and not (named_variant and len(options) == 1 and not answering):
                chosen = instances.select(options, hint)
                if unsafe or not chosen:
                    return self._ask_choice(cmd, options, gen, sid)
                cmd["instance"] = dict(chosen["instance"])
                hint = cmd["instance"]
            elif hint and any(instances.select([c], hint) and self._candidate_is_out(c) for c in all_options):
                return self._refuse_choice(cmd, "already out", lines.with_you(it["name"]))

        try:
            fetch = (lambda: self.locator.locate(item_id, LOCATE_S, instance=hint)) if hint else (lambda: self.locator.locate(item_id, LOCATE_S))
            loc = self._bounded(gen, fetch, LOCATE_S + 0.5)
        except Stopped:
            return self._refuse_choice(cmd, "request cancelled", lines.NEEDS_RESET)
        with self.lock:
            if self.gen != gen or self.setting["id"] != sid:
                return self._refuse_choice(cmd, "request cancelled", lines.CHOICE_EXPIRED)
            if loc and (loc.get("ambiguous") or len(loc.get("candidates") or []) > 1 and not hint):
                choices, bad = instances.candidates(loc.get("candidates") or [], item_id)
                self._known_instances[item_id] = choices
                choices = [c for c in choices if not self._candidate_is_out(c)]
                if not choices and item_id in self.out:
                    return self._refuse_choice(cmd, "already out", lines.with_you(it["name"]))
                say = lines.other_instance(settings.item(self.setting, item_id)["name"]) if item_id in self.out and len(choices) == 1 else None
                return self._ask_choice(cmd, choices, gen, sid, say, confirm=bool(say) and len(choices) == 1)
            if item_id in self.out and (not hint or named_variant and not answering):
                name = settings.item(self.setting, item_id)["name"]
                choices, bad = instances.candidates((loc or {}).get("candidates") or [], item_id)
                choices = [c for c in choices if not self._candidate_is_out(c)]
                if choices and not bad:
                    return self._ask_choice(cmd, choices, gen, sid, lines.other_instance(name), confirm=len(choices) == 1)
                return self._refuse_choice(cmd, "already out", lines.with_you(name))
            physical = bool(hint) and not named_variant
            if hint:
                choices, bad = instances.candidates((loc or {}).get("candidates") or [], item_id)
                chosen = instances.select(choices, hint)
                if chosen and self._candidate_is_out(chosen):
                    return self._refuse_choice(cmd, "already out", lines.with_you(it["name"]))
                if named_variant and not answering and len(choices) <= 1 and not bad:
                    # A named settings variant already identifies a different item/skill (e.g. Phillips).
                    # No side/slot inference is involved; preserve the hint for locate and the command event.
                    cmd["_located"] = loc
                    return None
                physical = True
                if (not loc or not loc.get("found") or not loc.get("instance_validated") or not chosen or bad):
                    # Fake tests may use a posted tray candidate without a separate vision service.
                    chosen = instances.select(options, hint) if self.fake_arm and loc is None and not unsafe else None
                    if chosen:
                        loc = {"item": item_id, "found": True, "method": "slot", "confidence": 1.0,
                               "candidate": chosen, "instance": chosen["instance"], "instance_validated": True,
                               "center_px": [(chosen["box"][0] + chosen["box"][2]) / 2,
                                             (chosen["box"][1] + chosen["box"][3]) / 2] if chosen.get("box") else None}
                    else:
                        return self._refuse_choice(cmd, "instance unverified", lines.CHOICE_UNVERIFIED)
                xy = loc.get("arm_xy")
                if self.arm_kind == "real" and physical and (not isinstance(xy, (list, tuple)) or len(xy) != 2
                        or not _target_ok([*xy, 0]) or float(loc.get("confidence") or 0) < 0.6 or loc.get("setting_ok") is False):
                    return self._refuse_choice(cmd, "instance unverified", lines.CHOICE_UNVERIFIED)
                cmd["_physical"] = physical
            cmd["_located"] = loc
            if not hint and pending and pending["item"] == item_id and item_id not in self._known_instances:
                self.clarification = None  # a fresh detection disproved multiplicity; this is a new full request
            if answering:
                if self.clarification is not pending or time.monotonic() >= pending["expires"]:
                    return self._refuse_choice(cmd, "choice expired", lines.CHOICE_EXPIRED)
                self.clarification = None
                self.emit("clarify_answer", item=item_id, question_id=pending["question_id"], answer=cmd.get("heard"),
                          answer_ms=round((time.monotonic() - (pending["expires"] - CLARIFY_S)) * 1000),
                          instance=cmd.get("instance"), command_id=cmd["id"])
        return None

    def _preflight_return(self, cmd, gen, sid):
        """A return removes only the identified physical item; unknown identity cannot reduce a multi-count."""
        with self.lock:
            here = self._out_here()
            item_id = cmd.get("item") or self._return_spot_item() or (here[-1] if here else None)
            if not item_id:
                return None
            cmd["item"] = item_id
            rows = [r for r in self._out_records() if r["item"] == item_id]
            hint = {k: v for k, v in (cmd.get("instance") or {}).items() if v is not None}
            pending, qid = self.clarification, cmd.get("question_id")
            if qid and (not pending or pending["question_id"] != qid or pending["item"] != item_id
                        or pending["action"] != "return" or time.monotonic() >= pending["expires"]):
                return self._refuse_choice(cmd, "choice expired", lines.CHOICE_EXPIRED)
            answering = bool(hint and pending and pending["item"] == item_id)
            if answering and (qid != pending["question_id"] or pending["action"] != "return"):
                return self._refuse_choice(cmd, "question id required", lines.CHOICE_EXPIRED)
            options = [{**r, **r["instance"], "label": r["instance"].get("side") or
                        (f"slot {r['instance']['slot']}" if "slot" in r["instance"] else r["id"])} for r in rows]
            if len(rows) > 1 and not hint:
                return self._ask_choice(cmd, options, gen, sid)
            chosen = instances.select(rows, hint) if hint else rows[0] if len(rows) == 1 else None
            if hint and not chosen:
                return self._refuse_choice(cmd, "instance unverified", lines.CHOICE_UNVERIFIED)
            if chosen:
                cmd["instance"] = dict(chosen["instance"])
                cmd["_return_instance"] = chosen
            if answering:
                self.clarification = None
                self.emit("clarify_answer", item=item_id, question_id=qid, answer=cmd.get("heard"),
                          instance=cmd.get("instance"), command_id=cmd["id"])
        return None

    def _check(self, cmd: dict) -> tuple[bool, str | None, str | None]:
        """(accepted, reason, say) for handover, return, got_it, unknown. Called with the lock held."""
        action, item_id = cmd.get("action"), cmd.get("item")
        if action == "got_it":
            if self.step != "waiting_for_pull":
                return False, "not holding anything out", None
            return True, None, None
        if action not in ("handover", "return"):
            return False, "unknown command", self._unknown_line()
        if self.step in ("stopped", "error"):
            return False, "stopped: reset first", lines.NEEDS_RESET  # the arm stays frozen until reset
        if len(self.jobs) >= MAX_QUEUE:
            return False, "queue full", lines.BUSY
        busy = self.step not in ("idle", "stopped", "error") or bool(self.jobs)
        if self.judge or self.skills != "smart":
            cmd.pop("method", None)  # a forced grasp method is for --skills smart trials, never a judge
        method = cmd.get("method")
        if action == "return":
            if item_id is None and not self._out_here() and not self._return_spot_item():
                return False, "nothing is out", lines.NOTHING_OUT
            it = settings.item(self.setting, item_id or "")
            if it and self._skill_source(it["id"], "return") is None:
                return False, "no taught skill", lines.no_taught(it["name"])
            if method and (not it or method not in self._methods(it["id"], "return")):
                return False, "method unavailable", lines.method_unavailable(method)
            return True, None, None
        it = settings.item(self.setting, item_id or "")
        if it is None:
            return False, f"{item_id!r} is not in {self.setting['id']}", lines.NOT_IN_SETTING
        if self._skill_source(it["id"], "pick") is None and not cmd.get("instance"):
            return False, "no taught skill", lines.no_taught(it["name"])
        if method and method not in self._methods(it["id"], "pick"):
            return False, "method unavailable", lines.method_unavailable(method)
        coming = lines.coming_sharp if it.get("sharp") else lines.coming
        return True, None, lines.queued(it["name"]) if busy else coming(it["name"])

    def stop(self) -> None:
        with self.lock:    # gen and the queue together: the worker can't pop a queued job under the new gen
            self.gen += 1  # first, so an arm call failing from the freeze already looks stopped
            self.jobs.clear()
            self._expired_choice = self.clarification or self._expired_choice
            self.clarification = None
        self.arm.freeze()  # the lock is only ever held briefly, never across an arm call
        with self.lock:
            self.jobs.clear()
            self.step = "stopped"
            self._held_out()
        self.emit("stopped", say=lines.STOPPED)

    def _out_records(self):
        """Optional physical count; `out` remains the backwards-compatible unique item-id list."""
        rows = [dict(r, instance=dict(r.get("instance") or {})) for r in self.out_instances if r.get("item") in self.out]
        for item_id in self.out:
            if not any(r["item"] == item_id for r in rows):
                rows.append({"item": item_id, "id": item_id + ":unspecified", "instance": {}})
        return rows

    def _instance_record(self, item_id, cmd=None):
        cmd = self.cmd if cmd is None else cmd
        hint = dict((cmd or {}).get("instance") or {})
        candidate = (((cmd or {}).get("_located") or {}).get("candidate") or {})
        key = candidate.get("id")
        if not key:
            key = (f"slot:{hint['slot']}" if "slot" in hint else f"variant:{hint['variant']}" if "variant" in hint
                   else f"side:{hint['side']}" if "side" in hint else "unspecified")
            key = f"{item_id}:{key}"
        return {"item": item_id, "id": str(key), "instance": hint}

    def _mark_out(self, item_id, record=None):
        rows = self._out_records()
        record = record or self._instance_record(item_id)
        if not any(r["id"] == record["id"] and r["item"] == item_id for r in rows):
            rows.append(record)
        self.out_instances = rows
        if item_id not in self.out:
            self.out.append(item_id)

    def _remove_out(self, item_id, hint=None):
        rows = self._out_records()
        same = [r for r in rows if r["item"] == item_id]
        chosen = instances.select(same, hint) if hint else same[0] if len(same) == 1 else None
        if not chosen:
            return None  # no arbitrary removal when several physical instances are out
        self.out_instances = [r for r in rows if r != chosen]
        if not any(r["item"] == item_id for r in self.out_instances) and item_id in self.out:
            self.out.remove(item_id)
        return chosen

    def _held_out(self) -> None:
        """An item off the tray when the arm stops is out (in the gripper or a hand) until it comes back.
        Called with the lock held."""
        if self.held:
            self._mark_out(self.held, self.held_instance)
        self.held = None

    def reset(self, clear_count: bool = False) -> None:
        """Clear a stop or error and home the arm. Keeps the count unless clear_count (a fresh demo run),
        so a stop mid-case never makes the count say everything is back. Raises RuntimeError if busy."""
        with self.lock:
            if self.step not in ("idle", "stopped", "error") or self.jobs:
                raise RuntimeError("busy")
            self.jobs.append({"id": uuid.uuid4().hex, "action": "reset", "item": None,
                              "clear_count": clear_count, "received": time.time()})
            self.jobs_cv.notify()

    def _reset(self, gen: int, clear_count: bool = False) -> None:
        """Operator rearm. The real arm stays frozen after a stop until resume(). If it still holds
        an item, carry it home and set it at the safe spot rather than opening wherever it froze."""
        resume = getattr(self.arm, "resume", None)
        if resume:
            if self.gen != gen:
                raise Stopped
            resume()
            if self.gen != gen:  # a stop landed while it rearmed: freeze again, it must win
                self.arm.freeze()
                raise Stopped
        held = self.item
        held_record = self.held_instance
        holding = OPEN_MAX < self._call(gen, self.arm.gripper_position) < GRIPPER_CLOSED
        with self.lock:
            if clear_count:
                self.out = []
                self.out_instances = []
                self.case_id = self._new_case()
            self.held = None
        self.set_step("homing", item=held if holding else None)
        self._call(gen, self.arm.go_home)  # saved poses keep the gripper as it is
        if holding:
            self.set_step("setting_down")
            if not self._call(gen, self.arm.set_down_safe_spot):
                self._fail(lines.SET_DOWN_FAILED, "set_down_safe_spot returned False")
            with self.lock:
                if held:
                    self._mark_out(held, held_record)  # at the safe spot, still off the tray
            self._call(gen, self.arm.go_home)
        else:
            self._call(gen, self.arm.open_gripper)
        with self.lock:
            self.step, self.item = "idle", None
            self.held_instance = None
        self.emit("step", say=lines.RESET)
        if self.prepared != self.setting["id"]:
            self._prepare()  # a prepare cancelled by the freeze, or one that failed: try again

    def log_restock(self, body: dict) -> bool:
        """F3: {"item", "qty", "setting", "from", "heard"} to the ledger. False when the ledger isn't loaded."""
        rec = {"type": "restock", "item": body.get("item"), "qty": int(body.get("qty") or 1),
               "setting": body.get("setting") or self.setting["id"], "from": body.get("from"),
               "heard": body.get("heard"), "case_id": self.case_id, "fake_arm": self.fake_arm,
               **self._arm_tags(), "t": body.get("t") or time.time()}
        if ledger is None:
            return False
        self._ledger_pool.submit(ledger.log, rec)
        return True

    def log_caption(self, body: dict) -> bool:
        """A clip caption from vision (POST /vision/caption) to the ledger as {"type": "caption", ...}. Not an Event."""
        keys = ("event_type", "item", "label", "label_source", "agrees", "caption_item", "caption_action",
                "caption_latency_ms", "filename")
        rec = {"type": "caption", **{k: body.get(k) for k in keys}, "case_id": body.get("case_id") or self.case_id,
               "setting": self.setting["id"], "fake_arm": self.fake_arm, "t": body.get("t") or time.time()}
        if ledger is None:
            return False
        self._ledger_pool.submit(ledger.log, rec)
        return True

    # ---------- reading (OCR) ----------
    def _start_read(self, cmd: dict) -> dict:
        """read_sheet, read_tray, read_pack: vision reads the overhead frame on its own thread (up to
        reads.TIMEOUT_S), then a `read` event speaks the answer. Never the arm worker: stop never waits on it."""
        action = cmd["action"]
        with self.lock:
            busy = action in self._reading
            if not busy:
                self._reading.add(action)
        if busy:
            self._emit_command(cmd, False, "already reading", lines.STILL_READING)
            return {"accepted": False, "reason": "already reading", "say": lines.STILL_READING}
        say = lines.READING[action]
        self._emit_command(cmd, True, None, say)
        threading.Thread(target=self._read, args=(cmd,), daemon=True).start()
        return {"accepted": True, "reason": None, "say": say}

    def _read(self, cmd: dict) -> None:
        action = cmd["action"]
        kind = reads.KINDS[action]
        try:
            res = reads.fetch(kind, self.setting["id"])
            fields = {k: v for k, v in (res or {}).items() if k not in ("kind", "t", "say")}
            read = {"kind": kind, "method": None, "latency_ms": None, **fields, "ok": bool(res and res.get("ok"))}
            if res is None:
                read["error"] = "vision unreachable"
            say = {"count_sheet": self._read_sheet, "tray_tag": self._read_tray, "pack_label": self._read_pack}[kind](read)
            self.emit("read", say=say, item=None, command_id=cmd["id"], read=read)
        except Exception as e:  # noqa: BLE001 - a broken read never touches the arm
            print(f"[read] {kind}: {e!r}", flush=True)
        finally:
            with self.lock:
                self._reading.discard(action)

    def _read_sheet(self, read: dict) -> str:
        """Closing counts written: compare each with Scrub's on-tray count. Else the initial counts with the expected."""
        if not read["ok"]:
            return lines.CANT_READ_SHEET
        sheet = reads.sheet_state(read, time.time())
        with self.lock:
            self.sheet = sheet
            out, sid = list(self.out), self.setting["id"]
        parts = []
        if sheet["tray"] and sheet["tray"] != sid:
            parts.append(lines.sheet_other_tray(reads.tray_label(sheet["tray"]) or sheet["tray"], reads.tray_label(sid) or sid))
        mism, read["compare"] = reads.closing_mismatch(sheet, out), "closing"
        if mism is None:
            mism, read["compare"] = reads.initial_mismatch(sheet), "initial"
        if mism is None:
            read["compare"] = None
            parts.append(lines.SHEET_NO_COUNTS)
        elif not mism:
            parts.append(lines.SHEET_MATCHES)
        read["mismatch"] = mism or []
        for m in mism or []:
            name = self._names([m["item"]])[0]
            parts.append(lines.sheet_closing(name, m["sheet"], m["scrub"]) if "scrub" in m
                         else lines.sheet_initial(name, m["sheet"], m["expected"]))
        return " ".join(parts)

    def _read_tray(self, read: dict) -> str:
        """A known tray other than this one switches the setting (as POST /setting does) when the arm is idle or stopped."""
        tray = read.get("tray") if read["ok"] else None
        label = reads.tray_label(tray) if tray else None
        read["switched"] = False
        if not label:
            return lines.CANT_READ_TAG
        if tray == self.setting["id"]:
            return lines.tray_is(label)
        try:
            self.set_setting(tray)  # raises RuntimeError while busy
        except RuntimeError:
            return lines.tray_busy(label)
        read["switched"] = True
        return lines.tray_switched(label)

    def _read_pack(self, read: dict) -> str:
        labels = [lab for lab in read.get("labels") or [] if isinstance(lab, dict)] if read["ok"] else []
        if not labels:
            return lines.CANT_READ_PACK
        rows = [{"item": lab.get("item"), "lot": lab.get("lot"), "expires": lab.get("expires"),
                 "expired": bool(lab.get("expired"))} for lab in labels]
        with self.lock:
            self.packs.extend(rows)
        parts = []
        for lab, row in zip(labels, rows):
            name = self._names([row["item"]])[0] if row["item"] else str(lab.get("item_text") or "instrument")
            parts.append(lines.pack_expired(name.lower(), row["expires"]) if row["expired"]
                         else lines.pack(name, row["expires"]))
        return " ".join(parts)

    def read_result(self, kind: str, result: dict | None, heard: str | None = None, source: str | None = "photo") -> dict:
        """POST /read_result: vision's answer for a texted photo, run like a camera read minus the fetch.
        Sets `sheet` / `packs` and may switch the tray, then emits the `read` event. {"ok", "say", "read"}.
        Blocking (a tray switch rebuilds the sim scene): the server runs it off the event loop."""
        if self.judge:
            return {"ok": False, "say": lines.JUDGE_ONLY, "read": None, "reason": "judge mode"}
        res = result if isinstance(result, dict) else {}
        fields = {k: v for k, v in res.items() if k not in ("kind", "t", "say")}
        read = {"kind": kind, "method": None, "latency_ms": None, **fields, "ok": bool(res.get("ok")),
                "source": source or "photo"}
        say = {"count_sheet": self._read_sheet, "tray_tag": self._read_tray, "pack_label": self._read_pack}[kind](read)
        self.emit("read", say=say, item=None, command_id=None, read=read, heard=heard)
        return {"ok": read["ok"], "say": say, "read": read}

    def _new_case(self) -> str:
        """CONTRACTS: case_id = <setting>-<unix start seconds>. A new case starts with no sheet or pack read."""
        self.sheet, self.packs = None, []
        return f"{self.setting['id']}-{int(time.time())}"

    def set_setting(self, setting_id: str) -> dict:
        data = settings.load(setting_id)
        with self.lock:
            if self.step not in ("idle", "stopped", "error") or self.jobs:
                raise RuntimeError("busy")
            self.setting = data
            self._known_instances = {}
            self.clarification = None
            self._expired_choice = None
            # `out` survives a tray switch: an instrument still out of the last tray stays in the count
            # until it comes back or a person clears it (POST /reset {"clear_count": true}).
            self.case_id = self._new_case()
            if self.step not in ("stopped", "error"):  # a tray switch never clears a stop: only a reset rearms
                self.step, self.item = "idle", None
            self._prep_said = False
        self.taught = _taught_available(setting_id)
        self._refresh_policy()
        sync = getattr(self.arm, "set_setting", None)  # the sim arm rebuilds its scene for the new tray
        if sync:
            try:
                sync(setting_id)
            except Exception as e:  # noqa: BLE001 - the tray switch itself already happened
                print(f"[setting] arm scene not switched: {e!r}", flush=True)
        self.emit("step", item=None)
        self._prepare()
        return data

    def set_judge(self, on: bool) -> None:
        """L3 judge mode. The step event carries the new `judge` so pages see it change."""
        with self.lock:
            self.judge = bool(on)
        self.emit("step", command_id=None)

    def _prepare(self) -> None:
        """L2: pre-open the robot model's sessions for this tray's skills with the arm's optional
        prepare(instructions). It blocks on the network, so it runs on its own thread, never under
        the lock; stop never waits on it (a freeze cancels it inside the arm)."""
        prepare = getattr(self.arm, "prepare", None)
        if not prepare:
            return
        with self.lock:
            self._prep_gen += 1
            gen, sid = self._prep_gen, self.setting["id"]
            todo = [s for it in self.setting["items"]
                    for s in (it.get("pick_instruction"), it.get("return_instruction")) if s]
        threading.Thread(target=self._prepare_run, args=(prepare, todo, gen, sid), daemon=True).start()

    def _prepare_run(self, prepare, todo: list, gen: int, sid: str) -> None:
        for attempt in range(PREPARE_TRIES):
            if attempt:
                time.sleep(PREPARE_RETRY_S)
            if gen != self._prep_gen:
                return  # the setting changed again; that prepare takes over
            try:
                prepare(todo)
                with self.lock:
                    if gen == self._prep_gen:
                        self.prepared = sid
                print(f"[prepare] {sid}: {len(todo)} sessions open", flush=True)
                return
            except Exception as e:  # noqa: BLE001 - never crash; skills open sessions on demand anyway
                api = _api_error(e)
                print(f"[prepare] {sid} try {attempt + 1}: {e!r}", flush=True)
                if api is None or api[0] in (401, 403):
                    return  # frozen, not configured, or a refused key: retrying won't help
                with self.lock:
                    speak = gen == self._prep_gen and not self._prep_said
                    self._prep_said = self._prep_said or speak
                if speak:  # once per setting change, not on every retry
                    self.emit("error", say=lines.api_error(api[0]), item=None, command_id=None,
                              error=repr(e), code=api[0], reason=api[1])

    def _unknown_line(self) -> str:
        """Ask which instrument, with a teaching hint: the first non-sharp item and an example word this tray
        doesn't have yet (hinting the item's own alias, "call the hemostat a kelly", taught a word that already works)."""
        it = next((i for i in self.setting["items"] if not i.get("sharp")), None)
        have = {settings.norm(w) for i in self.setting["items"]
                for w in [i["name"], i["id"].replace("_", " "), *(i.get("aliases") or [])]}
        word = next((w for w in lines.HINT_WORDS if w not in have), None)
        return lines.unknown(it["name"], word) if it and word else lines.UNKNOWN

    def add_alias(self, item_id: str, alias: str) -> dict:
        """X6: a clinic-taught word for an item in the current setting. Writes settings/<id>.local.json and
        reloads the setting in memory. Works while busy; never touches the arm, out or the case."""
        word = settings.norm(alias or "")
        if self.judge:
            return {"ok": False, "say": lines.JUDGE_ONLY, "reason": "judge mode"}
        with self.lock:
            sid = self.setting["id"]
            it = settings.item(self.setting, item_id or "")
            if it is None:
                return {"ok": False, "say": lines.NOT_IN_SETTING, "reason": f"{item_id!r} is not in {sid}"}
            if not word or len(word) > 40:
                return {"ok": False, "say": lines.BAD_ALIAS, "reason": "bad alias"}
            other = next((o for o in self.setting["items"] if o["id"] != it["id"] and word in settings.words_for(o)), None)
            if other:
                return {"ok": False, "say": lines.alias_taken(word, other["name"]), "reason": f"already {other['id']}"}
            if word not in settings.words_for(it):
                settings.add_alias(sid, it["id"], word)
                self.setting = settings.load(sid)
        print(f"[alias] {word} -> {it['id']} ({sid})")
        return {"ok": True, "say": lines.alias_added(word, it["name"]), "reason": None}

    def set_lighting(self, lighting: str, lux) -> None:
        with self.lock:
            self.lighting, self.lux = lighting, lux

    def post_hand(self, hand: dict) -> None:
        with self.lock:
            self.hand, self.hand_at = hand, time.time()

    def post_tray(self, tray: dict) -> None:
        with self.lock:
            now = time.time()
            gap = now - self.tray_at
            self.tray, self.tray_at = tray, now
            if tray.get("setting", self.setting["id"]) == self.setting["id"] and not tray.get("stale"):
                for it in self.setting["items"]:
                    options, unsafe = self._tray_candidates(it["id"])
                    if unsafe or len(options) > 1 or it["id"] in (tray.get("ambiguous_items") or []):
                        self._known_instances[it["id"]] = options
                    elif "candidates" in tray and tray.get("detector") == "perceptron" and not tray.get("candidates_stale"):
                        self._known_instances.pop(it["id"], None)
            if tray.get("stale"):
                self._spot_item = None  # breaks "continuously", but isn't proof the item left
                return
            spot = (tray.get("return_spot") or {}).get("item")
            if spot != self._auto_done:
                self._auto_done = None  # it left the return spot
            if spot != self._spot_item or gap > TRAY_STALE_S:
                self._spot_item, self._spot_since = spot, now
            if (spot and spot != self._auto_done and now - self._spot_since >= AUTO_RETURN_S
                    and self.step == "idle" and not self.jobs and self.cmd is None and not self.clarification
                    and settings.item(self.setting, spot)):
                self._auto_done = spot
                self._auto_return(spot, now)

    def _auto_return(self, item_id: str, now: float) -> None:
        """F1: an item sat in the return spot with the arm idle. Queue a return. Called with the lock held."""
        cmd = {"id": uuid.uuid4().hex, "action": "return", "item": item_id, "heard": None,
               "source": "auto", "t": now, "received": now}
        if self._preflight_return(cmd, self.gen, self.setting["id"]) is not None:
            return
        self._emit_command(cmd, True, None, lines.auto_return(settings.item(self.setting, item_id)["name"]))
        self.jobs.append(cmd)
        self.jobs_cv.notify()

    # ---------- vision helpers ----------
    def _hand_fresh(self) -> dict | None:
        h = self.hand
        if h and h.get("seen") and time.time() - self.hand_at <= HAND_STALE_S:
            return h
        return None

    def _tracking(self) -> bool:
        return time.time() - self.hand_at <= TRACKING_ACTIVE_S

    def _hand_ready(self) -> dict | None:
        h = self._hand_fresh()
        if h and h.get("open") and _target_ok(h.get("target")) and h.get("path_clear", True):
            return h
        return None

    def _slot_present(self, item_id: str, after: float = 0.0) -> bool | None:
        """True/False from a fresh TrayState (seen after `after`), None if we don't know."""
        tray = self.tray
        if not tray or tray.get("stale") or time.time() - self.tray_at > TRAY_STALE_S:
            return None
        if float(tray.get("t") or self.tray_at) < after:
            return None  # from a frame before the arm moved
        rows = [s for s in tray.get("slots", []) if s.get("item") == item_id]
        chosen = ((self.cmd or {}).get("_located") or {}).get("candidate")
        if chosen and "candidates" in tray:
            if tray.get("candidates_stale"):
                return None
            same = [c for c in tray["candidates"] if c.get("item") == item_id and
                    (c.get("id") == chosen.get("id") and c.get("id") is not None
                     or c.get("slot") == chosen.get("slot") and c.get("slot") is not None
                     or c.get("box") == chosen.get("box") and c.get("box") is not None)]
            return bool(same)
        if chosen and len(rows) == 1 and not any(k in rows[0] for k in ("slot", "id", "instance")):
            return None  # one generic configured slot cannot judge a selected physical instance
        if chosen and len(rows) > 1:
            rows = [s for s in rows if (s.get("box") == chosen.get("box") and chosen.get("box")
                                       or s.get("slot") == chosen.get("slot") and s.get("slot") is not None)]
            if len(rows) != 1:
                return None  # do not use the other instance to check this grasp
        return any(s.get("present") for s in rows) if rows else None

    def _return_spot_item(self) -> str | None:
        if not self.tray or time.time() - self.tray_at > TRAY_STALE_S:
            return None
        return (self.tray.get("return_spot") or {}).get("item")

    def _camera_out(self) -> tuple[list | None, set]:
        """F2: (items whose slot is empty minus the return-spot item, items the camera reports on)
        from a fresh TrayState, else (None, empty set)."""
        tray = self.tray
        if not tray or tray.get("stale") or time.time() - self.tray_at > TRAY_STALE_S:
            return None, set()
        spot = (tray.get("return_spot") or {}).get("item")
        slots = [s for s in tray.get("slots", []) if settings.item(self.setting, s.get("item") or "")]
        out = [s.get("item") for s in slots if not s.get("present") and s.get("item") != spot]
        return out, {s.get("item") for s in slots} | ({spot} if spot else set())

    def _count_line(self) -> tuple[str, list | None, list | None]:
        """(the count line, the camera's out, sheet_mismatch). The line adds a short note where the camera or a
        count sheet read this case (its closing counts) disagrees. sheet_mismatch is None with no closing counts."""
        with self.lock:
            out = list(self.out)
            cam, known = self._camera_out()
            sheet = self.sheet
        records = self._out_records()
        names = self._names(out)
        for index, item_id in enumerate(out):
            n = sum(r["item"] == item_id for r in records)
            if n > 1:
                names[index] = lines.quantity(names[index], n)
        say = lines.count(names)
        if cam is not None:
            gone = [i for i in cam if i not in out]
            back = [i for i in out if i not in cam and i in known]
            if gone:
                say += " " + lines.camera_gone(self._names(gone))
            if back:
                say += " " + lines.camera_back(self._names(back))
        mism = reads.closing_mismatch(sheet, out) if sheet else None
        if mism:
            say += " " + lines.sheet_disagrees(self._names([m["item"] for m in mism]))
        return say, cam, mism

    def _names(self, ids) -> list[str]:
        return [(settings.item(self.setting, i) or {"name": i.replace("_", " ")})["name"] for i in ids]

    def _out_here(self) -> list[str]:
        """What's out from the current tray (out can still hold items from a tray switched away from)."""
        return [i for i in self.out if settings.item(self.setting, i)]

    # ---------- worker ----------
    def _worker(self) -> None:
        while True:
            rest_now = False
            with self.lock:
                while not self.jobs:
                    # Parked at home with nothing to do: torque off (the servos heat up just holding).
                    if not self.resting and self.step == "idle" and callable(getattr(self.arm, "rest", None)):
                        left = REST_AFTER_S - (time.time() - self._idle_since)
                        if left <= 0:
                            rest_now = True
                            break
                        self.jobs_cv.wait(timeout=left)
                    else:
                        self.jobs_cv.wait()
                if not rest_now:
                    cmd = self.jobs.popleft()
                    gen = self.gen
                    self._flow_gen = gen
                    self.cmd = cmd
            if rest_now:
                try:
                    self.arm.rest()
                    self.resting = True
                except Exception:  # noqa: BLE001 - stay awake rather than fail
                    self._idle_since = time.time() + 60  # don't retry every loop
                continue
            try:
                if self.resting:  # inside the try: a wake that raises holds as an error, never kills this thread
                    try:
                        self.arm.wake()  # torque on, holding the parked pose, before any motion
                    finally:
                        self.resting = False
                if cmd["action"] == "handover":
                    self._handover(cmd, gen)
                elif cmd["action"] == "reset":
                    self._reset(gen, cmd.get("clear_count", False))
                else:
                    self._return(cmd, gen)
            except Stopped:
                pass  # stop() already set the step and spoke
            except Exception as e:  # noqa: BLE001 - keep the worker alive
                if self.gen == gen:  # otherwise a stop caused it and already spoke
                    api = _api_error(e)  # the robot model refused or is down: say which
                    try:
                        if api:
                            self._fail(lines.api_failed(api[0]), repr(e), code=api[0], reason=api[1])
                        if _is(e, "ArmFault"):  # arm/hardware.py: thermal stop; its message says which motor
                            self._fail(str(e) or lines.ERROR, repr(e))
                        self._fail(lines.ERROR, repr(e))
                    except Stopped:
                        pass
            finally:
                self.cmd = None
                self.skill_source = None
                self._order, self.pick_fields = [], {}
                self._idle_since = time.time()

    def _call(self, gen: int, fn, *args, **kw):
        """Run one arm call; raise Stopped if stop came before or during it."""
        if self.gen != gen:
            raise Stopped
        result = fn(*args, **kw)
        if self.gen != gen:
            raise Stopped
        return result

    def _home(self, gen: int) -> None:
        self.set_step("homing")
        self._call(gen, self.arm.go_home)
        self.set_step("idle", item=None)

    def _fail(self, say: str, error: str, **kw) -> None:
        """Hold where it is and wait for a reset. kw: extra event fields (code, reason for API errors)."""
        self.arm.freeze()
        with self.lock:
            self.jobs.clear()
            self.step = "error"
            self._held_out()
        self.emit("error", say=say, error=error, **kw)
        raise Stopped

    def _hold(self, say: str, reason: str) -> None:
        """The hand watcher froze the arm: treat it as a stop. Only a reset rearms it (arm/README.md)."""
        with self.lock:
            self.gen += 1
            self.jobs.clear()
        self.arm.freeze()
        with self.lock:
            self.step = "stopped"
            self._held_out()
        self.emit("stopped", say=say, reason=reason)
        raise Stopped

    def _skill(self, gen: int, instruction: str, located: dict | None = None) -> bool:
        t0 = time.monotonic()
        if located is None and self.cmd and self.cmd.get("instance"):
            located = self.cmd.get("_located")
        kw = {"located": located} if located is not None else {}
        try:
            return self._call(gen, self.arm.run_skill, instruction, source=self.skill_source or "model", **kw)
        finally:
            self._skill_ms.append(round((time.monotonic() - t0) * 1000))

    def _pick(self, gen: int, it: dict, instruction: str, want_closed: bool) -> tuple[bool, int]:
        """Run a skill with one retry. Returns (ok, retries). Each real-arm run is a try for --skills auto."""
        ok, retries = self._pick_once(gen, it, instruction, want_closed)
        self._record_try(it["id"], "pick" if want_closed else "return", self.skill_source or "model", ok)
        return ok, retries

    def _pick_once(self, gen: int, it: dict, instruction: str, want_closed: bool) -> tuple[bool, int]:
        for attempt in range(2):
            if want_closed or attempt:
                self.set_step("picking" if want_closed else "returning")
            ran = self._skill(gen, instruction)
            done_at = time.time()
            if not want_closed:
                if ran and self._placed(gen, it, done_at) is not False:
                    return True, attempt
                continue
            self.set_step("checking")
            closed_on_nothing = self._call(gen, self.arm.gripper_position) >= GRIPPER_CLOSED
            if ran and not closed_on_nothing:
                self._call(gen, self.arm.go_carry)  # lift clear; the tray check rides on this move
                if self._lifted(gen, it, done_at + TRAY_LAG_S) is not False:
                    return True, attempt
            if attempt == 0:
                self.emit("missed", say=lines.retry(it["name"]), retries=1)
                self._call(gen, self.arm.open_gripper)
                self._call(gen, self.arm.go_home)
        return False, 1

    def _use_source(self, it: dict, direction: str, method: str | None = None) -> bool:
        """Pick the skill source for this flow; False (and say so) when taught is asked for and none exists.
        --skills smart: the method order from the picker (a command's method first); a handover sets its
        skill_source per attempt in _pick_smart."""
        if direction == "pick" and self.cmd and self.cmd.get("_physical"):
            # Plain taught/model paths ignore a located candidate; IK targets its calibrated arm_xy.
            self.skill_source, self._order = "ik", ["ik"]
            return True
        self.taught = _taught_available(self.setting["id"])  # a skill taught since start counts
        if self.skills == "smart":
            order = self._choice(it["id"], direction)["order"]
            self._order = [method] + [m for m in order if m != method] if method else order
            self.skill_source = self._order[0] if direction == "return" else None
            return True
        src = self._skill_source(it["id"], direction)
        if src is None:
            self.emit("missed", say=lines.no_taught(it["name"]), item=it["id"])
            return False
        self.skill_source = src
        return True

    def _handover(self, cmd: dict, gen: int) -> None:
        it = settings.item(self.setting, cmd["item"])
        if not self._use_source(it, "pick", cmd.get("method")):
            return
        if not it.get("sharp"):
            return self._hand_over(cmd, gen, it)
        if not self._zone_ok(it):
            return
        sharp = getattr(self.arm, "sharp_mode", None)  # slower moves the whole time a sharp is in the flow
        if sharp:
            sharp(True)
        try:
            self._hand_over(cmd, gen, it)
        finally:
            if sharp:
                try:
                    sharp(False)
                except Exception as e:  # noqa: BLE001
                    print(f"[sharp] sharp_mode off failed: {e!r}", flush=True)

    def _zone_ok(self, it: dict) -> bool:
        """Real arm: refuse a sharp before moving when the safe zone isn't taught or is too near the handoff."""
        probs = self._zone_problems(self._safe_zone())
        if not probs:
            return True
        taught = not any("no safe" in p for p in probs)
        self.skill_source = None  # a refusal, not a try
        self.emit("missed", say=(lines.zone_too_close if taught else lines.zone_not_taught)(it["name"]),
                  item=it["id"], reason="safe zone: " + "; ".join(probs))
        return False

    def _hand_over(self, cmd: dict, gen: int, it: dict) -> None:
        self.set_step("finding", item=it["id"])
        if self._slot_present(it["id"]) is False:
            self.emit("missed", say=lines.not_on_tray(it["name"]))
            self.set_step("idle", item=None)
            return
        if self.skills == "smart":
            ok, retries = self._pick_smart(gen, it)
            if self.arm_kind == "real":
                self._refresh_policy()
            if ok is None:
                return  # vision says it isn't on the tray (said)
        else:
            ok, retries = self._pick(gen, it, it["pick_instruction"], want_closed=True)
        if not ok:
            self.emit("missed", say=lines.couldnt_pick(it["name"]), retries=retries)
            self._call(gen, self.arm.open_gripper)
            self._home(gen)
            return
        with self.lock:
            self.held = it["id"]
            self.held_instance = self._instance_record(it["id"])
        self.emit("picked", retries=retries)
        elapsed = lambda: round(time.time() - cmd["received"], 2)  # noqa: E731

        if it.get("sharp"):  # never to a hand, whatever was asked
            self._sharp_down(gen, it, lines.sharp_down(it["name"]), elapsed, retries)
            self._home(gen)
            return

        self.set_step("moving_to_hand")  # already at the carry pose
        if not self._reach_hand(gen, it):
            return
        self.set_step("waiting_for_pull")
        self.emit("handed", say=lines.handed(it["name"]), request_to_hand_s=elapsed(), retries=retries)
        why = self._wait_for_pull(gen)
        if not why:
            self._set_down(gen, it, lines.no_pull(it["name"]), None, retries)
            self._home(gen)
            return
        self.set_step("releasing")
        with self.lock:  # out before the jaw opens: a stop mid-open still counts it
            self._mark_out(it["id"])
            self.held = None
            self.held_instance = None
        self._call(gen, self.arm.open_gripper)
        self.emit("released", release=why)
        self._home(gen)

    def _set_down(self, gen, it, say, elapsed=None, retries=None) -> None:
        """elapsed: a function giving request-to-hand seconds, only for a planned (sharp) set-down."""
        self.set_step("setting_down")
        if not self._call(gen, self.arm.set_down_safe_spot):
            self._fail(lines.SET_DOWN_FAILED, "set_down_safe_spot returned False")
        with self.lock:
            self._mark_out(it["id"])
            self.held = None
            self.held_instance = None
        self.emit("set_down", say=say, request_to_hand_s=elapsed() if elapsed else None, retries=retries)

    def _reach_hand(self, gen: int, it: dict) -> bool:
        """Move to the hand (or the saved spot). Slow near the hand; freeze if the hand is lost
        or the path is blocked. False means the flow already set the item down."""
        sharp = it if it.get("sharp") else settings.item(self.setting, self.held or "")
        if sharp and sharp.get("sharp"):  # defense in depth: a sharp never goes to a hand
            print(f"[sharp] refused to hand over the {sharp['id']}", flush=True)
            self._sharp_down(gen, sharp, lines.sharp_down(sharp["name"]))
            self._home(gen)
            return False
        if self._tracking():
            hand = self._wait(gen, self._hand_ready, HAND_WAIT_S, lines.SHOW_HAND)
            if hand is None:
                # A hand seen but with the path blocked is not "No hand": say what is wrong.
                h = self._hand_fresh()
                blocked = h is not None and h.get("path_clear") is False
                say = lines.path_blocked_down(it["name"]) if blocked else lines.no_hand(it["name"])
                self._set_down(gen, it, say, None, None)
                self._home(gen)
                return False
            target = list(hand["target"])
        else:  # the sim arm names its own spot (its hand zone), so the viewer and the overhead render show the real target
            target = list(getattr(self.arm, "handoff_spot", None) or _saved_spot())
        x, y, z = target
        r = math.hypot(x, y)
        k = max(0.0, 1 - APPROACH_BACK_M / r) if r else 1.0
        back = (x * k, y * k, z)  # short of the hand, toward the arm base
        watch = self._watch_hand() if self._tracking() else None
        try:
            ok = self._call(gen, self.arm.move_to, *back, speed=SPEED_NORMAL)
            if not ok and not (watch and watch(peek=True)):
                ok = True  # approach point outside the handoff region: go straight in, slowly
            if watch:
                watch(near_leg=True)  # from here a closing hand is a grab, not a stop
            ok = ok and self._call(gen, self.arm.move_to, x, y, z, speed=SPEED_NEAR)
        finally:
            lost = watch() if watch else None
        if lost:  # frozen with the item, near the hand; a reset carries it to the safe spot
            say = {"blocked": lines.PATH_BLOCKED, "closed": lines.HAND_CLOSED}.get(lost, lines.HAND_LOST)
            self._hold(say, f"hand_{lost}")
        if ok:
            return True
        self.emit("missed", say=lines.OUT_OF_REACH)
        self._set_down(gen, it, lines.set_down(it["name"]), None, None)
        self._home(gen)
        return False

    # ---------- smart pick ----------
    def _bounded(self, gen: int, fn, limit: float):
        """fn() on its own thread for at most limit seconds (None after, or if it raises). A stop wins at once."""
        box, done = [None], threading.Event()

        def run():
            try:
                box[0] = fn()
            except Exception as e:  # noqa: BLE001
                print(f"[smart] {e!r}", flush=True)
            finally:
                done.set()
        threading.Thread(target=run, daemon=True).start()
        end = time.monotonic() + limit
        while not done.wait(0.05):
            if self.gen != gen:
                raise Stopped
            if time.monotonic() >= end:
                return None
        if self.gen != gen:
            raise Stopped
        return box[0]

    def _pick_smart(self, gen: int, it: dict) -> tuple[bool | None, int]:
        """--skills smart: locate, pick with the first method, check the grip (jaw, then the wrist camera); on a miss
        open, back off and retry once with the next method. (True, retry), (False, 1), or (None, 0) when vision
        is sure the item isn't on the tray."""
        order = self._order or ["model"]
        for attempt, method in enumerate([order[0], order[1] if len(order) > 1 else order[0]]):
            loc = self.cmd.get("_located") if self.cmd and "_located" in self.cmd and (attempt == 0 or self.cmd.get("instance")) else None
            if loc is None and not (self.cmd and self.cmd.get("instance")):
                loc = self._bounded(gen, lambda: self.locator.locate(it["id"], LOCATE_S), LOCATE_S + 0.5)
            if loc and (loc.get("ambiguous") or len(loc.get("candidates") or []) > 1 and not (self.cmd or {}).get("instance")):
                choices, _ = instances.candidates(loc.get("candidates") or [], it["id"])
                self._ask_choice(self.cmd, choices, gen, self.setting["id"])
                self.set_step("idle", item=None)
                return None, 0
            where = {"locate_method": loc.get("method") if loc else None,
                     "locate_confidence": loc.get("confidence") if loc else None}
            if (attempt == 0 and loc and loc.get("found") is False and loc.get("method") in VISION_METHODS
                    and float(loc.get("confidence") or 0) >= ABSENT_CONFIDENCE):
                self.emit("missed", say=lines.not_on_tray(it["name"]), **where)
                self.set_step("idle", item=None)
                return None, 0
            self.skill_source = method
            self.pick_fields = {**where, "grasp_check": "none", "retry": attempt}
            self.set_step("picking")
            ran = self._skill(gen, it["pick_instruction"], located=loc)
            done_at = time.time()
            self.set_step("checking")
            ok = ran and self._grip_ok(gen, it)
            if ok:
                self._call(gen, self.arm.go_carry)  # lift clear; the tray check rides on this move
                ok = self._lifted(gen, it, done_at + TRAY_LAG_S) is not False
            self._record_try(it["id"], "pick", method, ok)
            if ok:
                return True, attempt
            if attempt == 0:
                self.emit("missed", say=lines.retry(it["name"]), retries=1)
                self._call(gen, self.arm.open_gripper)
                self._call(gen, self.arm.go_home)  # back above the slot area before the next method
        return False, 1

    def _grip_ok(self, gen: int, it: dict) -> bool:
        """The jaw says held/empty/unknown; the wrist camera (bounded) says yes/no/None. A miss: the jaw shut on
        nothing, or the jaw can't tell and the camera says no. Held but the camera says no: still a pick, flagged."""
        says = _grasp().gripper_says(self._call(gen, self.arm.gripper_position), self._load())
        wrist = None
        if says != "empty":
            try:
                jpeg = self.arm.wrist_jpeg() if callable(getattr(self.arm, "wrist_jpeg", None)) else None
            except Exception:  # noqa: BLE001 - no frame: the jaw decides
                jpeg = None
            if jpeg:
                wrist = self._bounded(gen, lambda: picker.ask_in_gripper(jpeg, it["name"], WRIST_S), WRIST_S + 0.5)
        jaw = says != "unknown"
        self.pick_fields["grasp_check"] = ("gripper+wrist" if jaw and wrist is not None else "gripper" if jaw
                                           else "wrist" if wrist is not None else "none")
        if says == "held" and wrist is False:
            self.pick_fields["wrist_disagrees"] = True
        return not (says == "empty" or (says == "unknown" and wrist is False))

    # ---------- sharps ----------
    def _hand_target(self) -> list | None:
        h = self._hand_fresh()
        t = h.get("target") if h else None
        return list(t) if _target_ok(t) else None

    def _near_sharp(self, target) -> bool:
        """A hand target within HAND_KEEPOUT_M of the gripper tip or the safe zone center."""
        pts = []
        try:
            tip = self.arm.tip() if callable(getattr(self.arm, "tip", None)) else None
            if tip is not None:
                pts.append([float(v) for v in tip][:3])
        except Exception:  # noqa: BLE001
            pass
        zone = self._safe_zone()
        if zone and zone.get("center"):
            pts.append([float(v) for v in zone["center"]][:3])
        keep = _grasp().HAND_KEEPOUT_M
        return any(math.dist(target, p) < keep for p in pts if len(p) == 3)

    def _hand_near(self) -> bool:
        t = self._hand_target()
        return t is not None and self._near_sharp(t)

    def _keepout_wait(self, gen: int) -> None:
        """A hand inside the keep-out before a sharp move: say so and wait up to KEEPOUT_WAIT_S for it to clear."""
        if self._hand_near():
            self.emit("step", say=lines.HAND_BACK)
            self._wait(gen, lambda: not self._hand_near(), KEEPOUT_WAIT_S, None)

    def _sharp_move(self, gen: int, fn) -> bool:
        """One arm move while a sharp is held: freeze (a stop; reset rearms) if a hand comes inside the keep-out."""
        done, why = threading.Event(), [None]

        def run():
            while not done.wait(0.05):
                if self._hand_near():
                    why[0] = "keepout"
                    self.arm.freeze()
                    return
        th = threading.Thread(target=run, daemon=True)
        th.start()
        try:
            ok = self._call(gen, fn)
        finally:
            done.set()
            th.join()
            if why[0]:
                self._hold(lines.HAND_BACK, "hand_keepout")
        return ok

    def _zone_clear(self, gen: int):
        z = self._bounded(gen, lambda: self.locator.safe_zone(2.0), 2.5)
        return z.get("clear") if z else None

    def _zone_wait(self, gen: int) -> str:
        """"clear", "cleared_after_wait", "no_camera" or "timeout" from vision's /safe_zone."""
        clear = self._zone_clear(gen)
        if clear is None:
            return "no_camera"
        if clear:
            return "clear"
        self.emit("step", say=lines.CLEAR_ZONE)
        end = time.time() + ZONE_WAIT_S
        while time.time() < end:
            self._wait(gen, lambda: False, ZONE_POLL_S, None)
            if self._zone_clear(gen) is True:
                return "cleared_after_wait"
        return "timeout"

    def _sharp_down(self, gen, it, say, elapsed=None, retries=None) -> bool:
        """A held sharp to the safe zone: wait out a hand in the keep-out, hover above the zone, wait for it to clear
        (else back to its slot: False), set down under the keep-out watcher, confirm it from the overhead camera."""
        self._keepout_wait(gen)
        self.set_step("setting_down")
        hover = getattr(self.arm, "hover_safe_spot", None)
        if hover and not self._sharp_move(gen, hover):
            print("[sharp] hover_safe_spot refused; set_down_safe_spot decides", flush=True)
        check = self._zone_wait(gen)
        if check == "timeout":
            self._sharp_to_slot(gen, it)
            return False
        if not self._sharp_move(gen, self.arm.set_down_safe_spot):
            self._fail(lines.SET_DOWN_FAILED, "set_down_safe_spot returned False")
        with self.lock:
            self._mark_out(it["id"])
            self.held = None
            self.held_instance = None
        z = self._bounded(gen, lambda: self.locator.safe_zone(2.0), 2.5)
        confirm = z.get("item_in_zone") == it["id"] if z and z.get("method", "none") != "none" else None
        self.last_zone_check = {"zone_check": check, "zone_confirm": confirm, "t": time.time()}
        self.emit("set_down", say=say, request_to_hand_s=elapsed() if elapsed else None, retries=retries,
                  zone_check=check, zone_confirm=confirm)
        return True

    def _sharp_to_slot(self, gen: int, it: dict) -> None:
        """The safe zone stayed blocked: put the sharp back in its slot (same method order), or hold for a reset."""
        src = self.skill_source
        self.set_step("returning")
        for m in (self._order or [src or "model"])[:2]:
            self.skill_source = m
            if self._sharp_move(gen, lambda: self._skill(gen, it["return_instruction"])):
                break
        else:
            self._fail(lines.couldnt_return(it["name"]) + " Holding.", "safe zone blocked and the return failed")
        with self.lock:
            self.held = None
            self._remove_out(it["id"], (self.cmd or {}).get("instance"))
        self.skill_source = src  # the event is about the pick's method
        self.last_zone_check = {"zone_check": "timeout_to_slot", "zone_confirm": None, "t": time.time()}
        self.emit("missed", say=lines.zone_blocked_back(it["name"]), zone_check="timeout_to_slot")

    def _watch_hand(self):
        """Freeze the arm if the hand disappears or the path blocks while moving, or (fast leg only) the hand
        stays closed for HAND_CLOSED_READS posts in a row. Returns a function that stops watching and gives
        why it froze: "lost", "blocked", "closed" or None. stop(near_leg=True) marks the slow last leg."""
        done, near = threading.Event(), threading.Event()
        why = [None]

        def run():
            closed, last_at = 0, None
            while not done.wait(0.05):
                h, at = self.hand, self.hand_at
                fresh = h and h.get("seen") and time.time() - at <= HAND_STALE_S
                if fresh and at != last_at:  # count posts, not polls
                    last_at = at
                    closed = closed + 1 if h.get("open") is False else 0
                shut = HAND_CLOSED_READS > 0 and closed >= HAND_CLOSED_READS and not near.is_set()
                if not fresh or h.get("path_clear") is False or shut:
                    why[0] = "lost" if not fresh else "blocked" if h.get("path_clear") is False else "closed"
                    self.arm.freeze()
                    return
        th = threading.Thread(target=run, daemon=True)
        th.start()

        def stop(peek: bool = False, near_leg: bool = False):
            if near_leg:
                near.set()
                return why[0]
            if peek:
                return why[0]
            done.set()
            th.join()  # no late freeze landing on the next move
            return why[0]
        return stop

    def _wait(self, gen: int, check, timeout: float, say: str | None):
        """Poll check() until it's truthy; speak `say` only if it isn't already."""
        r = check()
        if r:
            return r
        if say:
            self.emit("step", say=say)
        end = time.time() + timeout
        while time.time() < end:
            if self.gen != gen:
                raise Stopped
            r = check()
            if r:
                return r
            time.sleep(0.05)
        return None

    def _load(self) -> float | None:
        try:
            return float(self.arm.gripper_load())
        except Exception:  # noqa: BLE001 - real arm: no fresh bus reading; got_it still works
            return None

    def _wait_for_pull(self, gen: int) -> str | None:
        """Why to let go: "pull" (a load change over the delta either way; the bus value is signed), "collapse"
        (the grip load falls to PULL_COLLAPSE of the held load or less for two reads running: the clinician
        took the weight) or "got_it". None after PULL_WAIT_S. Never a made-up load."""
        self.got_it.clear()
        base = self._call(gen, self._load)
        if base is None:
            self.emit("step", say=lines.SAY_GOT_IT)
        delta = getattr(self.arm, "pull_delta", PULL_DELTA)  # load units differ per arm
        end = time.time() + PULL_WAIT_S
        low = 0
        while time.time() < end:
            if self.gen != gen:
                raise Stopped
            if self.got_it.is_set():
                return "got_it"
            load = self._load()
            if base is None:
                base = load
            elif load is not None:
                if abs(load - base) > delta:
                    return "pull"
                # Only from a real grip (held load at least the delta), so noise near zero never drops it.
                low = low + 1 if abs(base) >= delta and abs(load) <= PULL_COLLAPSE * abs(base) else 0
                if low >= 2:
                    return "collapse"
            time.sleep(0.05)
        return None

    def _lifted(self, gen: int, it: dict, after: float) -> bool | None:
        """After the pick: False if a TrayState from after `after` still shows the item in its slot."""
        if self._slot_present(it["id"]) is None:
            return None  # no tray vision: trust the gripper
        while time.time() < after + 0.5:
            if self.gen != gen:
                raise Stopped
            seen = self._slot_present(it["id"], after=after)
            if seen is not None:
                return not seen
            time.sleep(0.05)
        return None

    def _placed(self, gen: int, it: dict, after: float) -> bool | None:
        """After a put-back, wait for a TrayState from after the skill. None without tray vision."""
        if self._slot_present(it["id"]) is None:
            return None
        end = time.time() + TRAY_STALE_S + 1
        while time.time() < end:
            if self.gen != gen:
                raise Stopped
            seen = self._slot_present(it["id"], after=after)
            if seen is not None:
                return seen
            time.sleep(0.05)
        return None

    def _return(self, cmd: dict, gen: int) -> None:
        here = self._out_here()
        item_id = cmd.get("item") or self._return_spot_item() or (here[-1] if here else None)
        it = settings.item(self.setting, item_id or "")
        if it is None:
            self.emit("missed", say=lines.NOTHING_OUT, item=None)
            return
        if not self._use_source(it, "return", cmd.get("method")):
            return
        self.set_step("returning", item=it["id"])
        ok, retries = self._pick(gen, it, it["return_instruction"], want_closed=False)
        if not ok:
            self.emit("missed", say=lines.couldnt_return(it["name"]), retries=retries)
            if OPEN_MAX < self._call(gen, self.arm.gripper_position) < GRIPPER_CLOSED:
                # Still holding it: carry it home and set it at the safe spot, as a reset would.
                with self.lock:
                    self.held = it["id"]
                    self.held_instance = cmd.get("_return_instance") or self._instance_record(it["id"], cmd)
                self.set_step("homing")
                self._call(gen, self.arm.go_home)
                self._set_down(gen, it, lines.set_down(it["name"]))
            self._home(gen)
            return
        with self.lock:
            returned = self._remove_out(it["id"], cmd.get("instance"))
        self.emit("returned", say=lines.returned(it["name"]), retries=retries,
                  instance=(returned or {}).get("instance", cmd.get("instance")))
        self._home(gen)

    # ---------- stats ----------
    def stats(self) -> dict:
        if ledger is not None:
            try:
                return ledger.stats()
            except Exception:  # noqa: BLE001
                pass
        by_item: dict = {}
        times: dict = {}
        for ev in self.history:
            if ev["type"] in ("handed", "set_down", "missed") and ev["item"]:
                row = by_item.setdefault(ev["item"], {"ok": 0, "missed": 0})
                row["missed" if ev["type"] == "missed" else "ok"] += 1
                if ev["request_to_hand_s"]:
                    times.setdefault(ev["item"], []).append(ev["request_to_hand_s"])
        med = lambda xs: statistics.median(xs) if xs else None  # noqa: E731
        rows = [{"item": i, "attempts": r["ok"] + r["missed"], "successes": r["ok"],
                 "success_rate": r["ok"] / (r["ok"] + r["missed"]), "wilson_low": None, "wilson_high": None,
                 "median_request_to_hand_s": med(times.get(i))} for i, r in sorted(by_item.items())]
        # Same shape as ledger.stats(), so the dashboard tables fill without the ledger.
        return {"source": "controller memory (ledger not loaded)", "by_item": rows, "by_lighting": [],
                "median_request_to_hand_s": med([t for ts in times.values() for t in ts]),
                "out": list(self.out), "next_likely": None, "t": time.time()}
