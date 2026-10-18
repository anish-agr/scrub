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

from . import lines, reads, settings

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
SKILL_MODES = ("model", "taught", "auto")
TRIES_FILE = Path(os.environ.get("SCRUB_TRIES_FILE") or Path.home() / "scrub-logs" / "skill-tries.json")
AUTO_TRIES = 3              # --skills auto: the model runs an item once it passed this many real tries in a row
TRIES_KEPT = 20
TELEMETRY_S = 1.0           # arm.telemetry() poll period (its own thread; /state reads the cache)


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
                 tries_file: str | Path | None = None, arm_kind: str | None = None):
        self.arm = arm
        self.fake_arm = fake_arm  # true for anything but the real arm (fake and sim): kept out of real stats
        self.arm_kind = arm_kind or ("fake" if fake_arm else "real")  # "fake" | "sim" | "real", on /state and events
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
        self.case_id = self._new_case()
        # The count survives a controller restart mid-case: {out, case_id, setting, t} saved on change (None = off).
        self.state_file = state_file
        self._saved = None              # (out, case_id, setting) last written
        self._state_pool = ThreadPoolExecutor(1) if state_file else None
        saved = _load_state(state_file, self.setting["id"]) if state_file else None
        if saved:
            self.out, self.case_id = [str(i) for i in saved["out"]], str(saved["case_id"])
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
        self._ledger_pool = ThreadPoolExecutor(1)
        self._flow_gen = 0              # gen of the job the worker is running
        self._worker_thread = threading.Thread(target=self._worker, daemon=True)
        self._worker_thread.start()
        self._prep_gen = 0              # bumped per prepare; an older prepare thread gives up
        self._prep_said = False         # spoke a prepare failure since the last setting change
        self.prepared = None            # setting id whose sessions the arm has open
        self.taught = _taught_available(self.setting["id"])
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
            "case_id": self.case_id, "judge": self.judge, "fake_arm": self.fake_arm, **self._arm_tags(), "t": time.time(),
        }
        if self.skill_source and type_ not in ("command", "count"):
            ev["skill_source"] = self.skill_source
        ev.update(kw)
        self.history.append(ev)
        if self._state_pool is not None:
            key = (tuple(ev["out"]), ev["case_id"], ev["setting"])
            if key != self._saved:  # only on a change, and off this thread (never block a stop or the loop)
                self._saved = key
                self._state_pool.submit(_save_state, self.state_file,
                                        {"out": ev["out"], "case_id": ev["case_id"], "setting": ev["setting"], "t": ev["t"]})
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
                "fake_arm": self.fake_arm, **self._arm_tags(), "hand_seen": self._hand_fresh() is not None,
                "out_camera": self._camera_out()[0], "case_id": self.case_id, "judge": self.judge,
                "resting": self.resting, "t": now,
                "sheet": self.sheet, "packs": list(self.packs),
                # per item: the source its pick runs with (null: --skills taught and no taught skill)
                "skills": {"mode": self.skills,
                           "items": {it["id"]: self._skill_source(it["id"], "pick") for it in self.setting["items"]}},
                "latency_ms": {"skill": ms[-1] if ms else None, "skill_p50": statistics.median(ms) if ms else None,
                               "skill_n": len(ms), "hand_age": age(self.hand_at), "tray_age": age(self.tray_at)},
            }
            if hasattr(self.arm, "telemetry"):
                st["arm_telemetry"] = self.telemetry
            return st

    # ---------- skill source ----------
    def _skill_source(self, item_id: str, direction: str) -> str | None:
        """"model" or "taught" for one item's pick or return under --skills. None: taught asked for, none recorded."""
        taught = direction in self.taught.get(item_id, ())
        if self.skills == "model":
            return "model"
        if self.skills == "taught":
            return "taught" if taught else None
        if self.deployment and self._model_proven(item_id):
            return "model"
        return "taught" if taught else "model"

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
            self._emit_command(cmd, ok, reason, say)
            if ok and action in ("handover", "return"):
                self.jobs.append(cmd)
                self.jobs_cv.notify()
            elif ok and action == "got_it":
                self.got_it.set()
        return {"accepted": ok, "reason": reason, "say": say}

    def _emit_command(self, cmd, accepted, reason, say) -> None:
        self.emit("command", say=say, item=cmd.get("item"), command_id=cmd["id"],
                  action=cmd.get("action"), heard=cmd.get("heard"), source=cmd.get("source"),
                  accepted=accepted, reason=reason)

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
        if action == "return":
            if item_id is None and not self._out_here() and not self._return_spot_item():
                return False, "nothing is out", lines.NOTHING_OUT
            it = settings.item(self.setting, item_id or "")
            if it and self._skill_source(it["id"], "return") is None:
                return False, "no taught skill", lines.no_taught(it["name"])
            return True, None, None
        it = settings.item(self.setting, item_id or "")
        if it is None:
            return False, f"{item_id!r} is not in {self.setting['id']}", lines.NOT_IN_SETTING
        if self._skill_source(it["id"], "pick") is None:
            return False, "no taught skill", lines.no_taught(it["name"])
        coming = lines.coming_sharp if it.get("sharp") else lines.coming
        return True, None, lines.queued(it["name"]) if busy else coming(it["name"])

    def stop(self) -> None:
        with self.lock:    # gen and the queue together: the worker can't pop a queued job under the new gen
            self.gen += 1  # first, so an arm call failing from the freeze already looks stopped
            self.jobs.clear()
        self.arm.freeze()  # the lock is only ever held briefly, never across an arm call
        with self.lock:
            self.jobs.clear()
            self.step = "stopped"
            self._held_out()
        self.emit("stopped", say=lines.STOPPED)

    def _held_out(self) -> None:
        """An item off the tray when the arm stops is out (in the gripper or a hand) until it comes back.
        Called with the lock held."""
        if self.held and self.held not in self.out:
            self.out.append(self.held)
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
        holding = OPEN_MAX < self._call(gen, self.arm.gripper_position) < GRIPPER_CLOSED
        with self.lock:
            if clear_count:
                self.out = []
                self.case_id = self._new_case()
            self.held = None
        self.set_step("homing", item=held if holding else None)
        self._call(gen, self.arm.go_home)  # saved poses keep the gripper as it is
        if holding:
            self.set_step("setting_down")
            if not self._call(gen, self.arm.set_down_safe_spot):
                self._fail(lines.SET_DOWN_FAILED, "set_down_safe_spot returned False")
            with self.lock:
                if held and held not in self.out:
                    self.out.append(held)  # at the safe spot, still off the tray
            self._call(gen, self.arm.go_home)
        else:
            self._call(gen, self.arm.open_gripper)
        with self.lock:
            self.step, self.item = "idle", None
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
            # `out` survives a tray switch: an instrument still out of the last tray stays in the count
            # until it comes back or a person clears it (POST /reset {"clear_count": true}).
            self.case_id = self._new_case()
            if self.step not in ("stopped", "error"):  # a tray switch never clears a stop: only a reset rearms
                self.step, self.item = "idle", None
            self._prep_said = False
        self.taught = _taught_available(setting_id)
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
            if tray.get("stale"):
                self._spot_item = None  # breaks "continuously", but isn't proof the item left
                return
            spot = (tray.get("return_spot") or {}).get("item")
            if spot != self._auto_done:
                self._auto_done = None  # it left the return spot
            if spot != self._spot_item or gap > TRAY_STALE_S:
                self._spot_item, self._spot_since = spot, now
            if (spot and spot != self._auto_done and now - self._spot_since >= AUTO_RETURN_S
                    and self.step == "idle" and not self.jobs and self.cmd is None
                    and settings.item(self.setting, spot)):
                self._auto_done = spot
                self._auto_return(spot, now)

    def _auto_return(self, item_id: str, now: float) -> None:
        """F1: an item sat in the return spot with the arm idle. Queue a return. Called with the lock held."""
        cmd = {"id": uuid.uuid4().hex, "action": "return", "item": item_id, "heard": None,
               "source": "auto", "t": now, "received": now}
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
        t = h.get("target") if h else None
        good = (isinstance(t, (list, tuple)) and len(t) == 3
                and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in t))
        if h and h.get("open") and good and h.get("path_clear", True):
            return h
        return None

    def _slot_present(self, item_id: str, after: float = 0.0) -> bool | None:
        """True/False from a fresh TrayState (seen after `after`), None if we don't know."""
        tray = self.tray
        if not tray or tray.get("stale") or time.time() - self.tray_at > TRAY_STALE_S:
            return None
        if float(tray.get("t") or self.tray_at) < after:
            return None  # from a frame before the arm moved
        for s in tray.get("slots", []):
            if s.get("item") == item_id:
                return bool(s.get("present"))
        return None

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
        say = lines.count(self._names(out))
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

    def _skill(self, gen: int, instruction: str) -> bool:
        t0 = time.monotonic()
        try:
            return self._call(gen, self.arm.run_skill, instruction, source=self.skill_source or "model")
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

    def _use_source(self, it: dict, direction: str) -> bool:
        """Pick the skill source for this flow; False (and say so) when taught is asked for and none exists."""
        self.taught = _taught_available(self.setting["id"])  # a skill taught since start counts
        src = self._skill_source(it["id"], direction)
        if src is None:
            self.emit("missed", say=lines.no_taught(it["name"]), item=it["id"])
            return False
        self.skill_source = src
        return True

    def _handover(self, cmd: dict, gen: int) -> None:
        it = settings.item(self.setting, cmd["item"])
        if not self._use_source(it, "pick"):
            return
        self.set_step("finding", item=it["id"])
        if self._slot_present(it["id"]) is False:
            self.emit("missed", say=lines.not_on_tray(it["name"]))
            self.set_step("idle", item=None)
            return
        ok, retries = self._pick(gen, it, it["pick_instruction"], want_closed=True)
        if not ok:
            self.emit("missed", say=lines.couldnt_pick(it["name"]), retries=retries)
            self._call(gen, self.arm.open_gripper)
            self._home(gen)
            return
        with self.lock:
            self.held = it["id"]
        self.emit("picked", retries=retries)
        elapsed = lambda: round(time.time() - cmd["received"], 2)  # noqa: E731

        if it.get("sharp"):
            self._set_down(gen, it, lines.sharp_down(it["name"]), elapsed, retries)
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
            if it["id"] not in self.out:
                self.out.append(it["id"])
            self.held = None
        self._call(gen, self.arm.open_gripper)
        self.emit("released", release=why)
        self._home(gen)

    def _set_down(self, gen, it, say, elapsed=None, retries=None) -> None:
        """elapsed: a function giving request-to-hand seconds, only for a planned (sharp) set-down."""
        self.set_step("setting_down")
        if not self._call(gen, self.arm.set_down_safe_spot):
            self._fail(lines.SET_DOWN_FAILED, "set_down_safe_spot returned False")
        with self.lock:
            if it["id"] not in self.out:
                self.out.append(it["id"])
            self.held = None
        self.emit("set_down", say=say, request_to_hand_s=elapsed() if elapsed else None, retries=retries)

    def _reach_hand(self, gen: int, it: dict) -> bool:
        """Move to the hand (or the saved spot). Slow near the hand; freeze if the hand is lost
        or the path is blocked. False means the flow already set the item down."""
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
        if not self._use_source(it, "return"):
            return
        self.set_step("returning", item=it["id"])
        ok, retries = self._pick(gen, it, it["return_instruction"], want_closed=False)
        if not ok:
            self.emit("missed", say=lines.couldnt_return(it["name"]), retries=retries)
            if OPEN_MAX < self._call(gen, self.arm.gripper_position) < GRIPPER_CLOSED:
                # Still holding it: carry it home and set it at the safe spot, as a reset would.
                with self.lock:
                    self.held = it["id"]
                self.set_step("homing")
                self._call(gen, self.arm.go_home)
                self._set_down(gen, it, lines.set_down(it["name"]))
            self._home(gen)
            return
        with self.lock:
            if it["id"] in self.out:
                self.out.remove(it["id"])
        self.emit("returned", say=lines.returned(it["name"]), retries=retries)
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
