"""State, events and the step machine. Arm calls run on one worker thread; stop never waits on it."""
import json
import os
import statistics
import threading
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import lines, settings

try:
    import ledger  # Evan's; optional
    if not hasattr(ledger, "log"):  # folder exists but nothing in it yet
        ledger = None
except Exception:  # noqa: BLE001 - run without it
    ledger = None

HAND_STALE_S = 0.5          # contract: older Hand counts as seen: false
TRACKING_ACTIVE_S = 5.0     # a Hand posted this recently means vision is running
TRAY_STALE_S = 3.0
HAND_WAIT_S = 10.0
PULL_WAIT_S = 30.0
PULL_DELTA = float(os.environ.get("PULL_LOAD_DELTA", "80"))
GRIPPER_CLOSED = 0.95       # at or above this the gripper closed on nothing
APPROACH_BACK_M = 0.08      # stop this far short at normal speed, then creep in
SPEED_NORMAL, SPEED_NEAR = 0.3, 0.1
MAX_QUEUE = 3
DEFAULT_SPOT = [0.22, -0.10, 0.18]  # clinician's saved spot when no hand tracking


def _saved_spot() -> list:
    rig = Path(__file__).resolve().parent.parent / "arm" / "rig.json"
    try:
        spot = json.loads(rig.read_text()).get("handoff_spot")
        if spot:
            return list(spot)
    except Exception:  # noqa: BLE001
        pass
    return list(DEFAULT_SPOT)


class Stopped(Exception):
    pass


class Controller:
    def __init__(self, arm, fake_arm: bool, setting_id: str = "surgical"):
        self.arm = arm
        self.fake_arm = fake_arm
        self.lock = threading.RLock()
        self.setting = settings.load(setting_id)
        self.step = "idle"
        self.item = None
        self.out: list[str] = []
        self.lighting = "normal"
        self.lux = None
        self.jobs: deque = deque()
        self.jobs_cv = threading.Condition(self.lock)
        self.gen = 0                    # bumped by stop; running flows abort when it changes
        self.got_it = threading.Event()
        self.hand: dict | None = None
        self.hand_at = 0.0
        self.tray: dict | None = None
        self.tray_at = 0.0
        self.history: deque = deque(maxlen=500)
        self.listeners: list = []       # (loop, asyncio.Queue)
        self.cmd = None                 # command being run
        self._ledger_pool = ThreadPoolExecutor(1)
        threading.Thread(target=self._worker, daemon=True).start()

    # ---------- events ----------
    def emit(self, type_: str, say: str | None = None, **kw) -> dict:
        cmd = self.cmd
        ev = {
            "type": type_, "item": kw.pop("item", self.item), "step": self.step, "say": say,
            "request_to_hand_s": kw.pop("request_to_hand_s", None), "retries": kw.pop("retries", None),
            "setting": self.setting["id"], "lighting": self.lighting,
            "command_id": kw.pop("command_id", cmd["id"] if cmd else None), "t": time.time(),
        }
        ev.update(kw)
        self.history.append(ev)
        for loop, q in list(self.listeners):
            loop.call_soon_threadsafe(q.put_nowait, ev)
        if ledger is not None:
            self._ledger_pool.submit(ledger.log, dict(ev))
        return ev

    def set_step(self, step: str, item=...) -> None:
        with self.lock:
            self.step = step
            if item is not ...:
                self.item = item
        self.emit("step")

    def state(self) -> dict:
        with self.lock:
            return {
                "step": self.step, "item": self.item, "queue": [j["item"] for j in self.jobs],
                "out": list(self.out), "setting": self.setting["id"], "lighting": self.lighting,
                "fake_arm": self.fake_arm, "hand_seen": self._hand_fresh() is not None, "t": time.time(),
            }

    # ---------- inputs ----------
    def submit(self, cmd: dict) -> dict:
        """Every spoken line goes out as an event; the reply's `say` repeats it for convenience."""
        cmd.setdefault("id", uuid.uuid4().hex)
        cmd.setdefault("t", time.time())
        cmd["received"] = time.time()
        action = cmd.get("action")
        if action == "stop":
            self.stop()
            self._emit_command(cmd, True, None, None)
            return {"accepted": True, "reason": None, "say": lines.STOPPED}
        if action == "count":
            say = lines.count(self._names(self.out))
            self._emit_command(cmd, True, None, None)
            self.emit("count", say=say, item=None, command_id=cmd["id"], out=list(self.out))
            return {"accepted": True, "reason": None, "say": say}
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
            return False, "unknown command", lines.UNKNOWN
        if len(self.jobs) >= MAX_QUEUE:
            return False, "queue full", lines.BUSY
        busy = self.step not in ("idle", "stopped", "error") or bool(self.jobs)
        if action == "return":
            if item_id is None and not self.out and not self._return_spot_item():
                return False, "nothing is out", lines.NOTHING_OUT
            return True, None, None
        it = settings.item(self.setting, item_id or "")
        if it is None:
            return False, f"{item_id!r} is not in {self.setting['id']}", lines.NOT_IN_SETTING
        return True, None, lines.queued(it["name"]) if busy else lines.coming(it["name"])

    def stop(self) -> None:
        self.arm.freeze()  # first, from this thread, no locks needed
        with self.lock:
            self.gen += 1
            self.jobs.clear()
            self.step = "stopped"
        self.emit("stopped", say=lines.STOPPED)

    def set_setting(self, setting_id: str) -> dict:
        data = settings.load(setting_id)
        with self.lock:
            if self.step not in ("idle", "stopped", "error") or self.jobs:
                raise RuntimeError("busy")
            self.setting = data
            self.out = []
            self.step, self.item = "idle", None
        self.emit("step", item=None)
        return data

    def set_lighting(self, lighting: str, lux) -> None:
        with self.lock:
            self.lighting, self.lux = lighting, lux

    def post_hand(self, hand: dict) -> None:
        with self.lock:
            self.hand, self.hand_at = hand, time.time()

    def post_tray(self, tray: dict) -> None:
        with self.lock:
            self.tray, self.tray_at = tray, time.time()

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
        if h and h.get("open") and h.get("target") and h.get("path_clear", True):
            return h
        return None

    def _slot_present(self, item_id: str) -> bool | None:
        """True/False from a fresh TrayState, None if we don't know."""
        if not self.tray or time.time() - self.tray_at > TRAY_STALE_S:
            return None
        for s in self.tray.get("slots", []):
            if s.get("item") == item_id:
                return bool(s.get("present"))
        return None

    def _return_spot_item(self) -> str | None:
        if not self.tray or time.time() - self.tray_at > TRAY_STALE_S:
            return None
        return (self.tray.get("return_spot") or {}).get("item")

    def _names(self, ids) -> list[str]:
        return [(settings.item(self.setting, i) or {"name": i})["name"] for i in ids]

    # ---------- worker ----------
    def _worker(self) -> None:
        while True:
            with self.lock:
                while not self.jobs:
                    self.jobs_cv.wait()
                cmd = self.jobs.popleft()
                gen = self.gen
                self.cmd = cmd
            try:
                if cmd["action"] == "handover":
                    self._handover(cmd, gen)
                else:
                    self._return(cmd, gen)
            except Stopped:
                pass  # stop() already set the step and spoke
            except Exception as e:  # noqa: BLE001 - keep the worker alive
                with self.lock:
                    self.step = "error"
                self.emit("error", say=lines.ERROR, error=repr(e))
            finally:
                self.cmd = None

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

    def _pick(self, gen: int, it: dict, instruction: str, want_closed: bool) -> tuple[bool, int]:
        """Run a skill with one retry. Returns (ok, retries)."""
        for attempt in range(2):
            if want_closed or attempt:
                self.set_step("picking" if want_closed else "returning")
            ran = self._call(gen, self.arm.run_skill, instruction)
            if not want_closed:
                if ran:
                    return True, attempt
                continue
            self.set_step("checking")
            closed_on_nothing = self._call(gen, self.arm.gripper_position) >= GRIPPER_CLOSED
            still_there = self._slot_present(it["id"])
            if ran and not closed_on_nothing and still_there is not True:
                return True, attempt
            if attempt == 0:
                self.emit("missed", say=lines.retry(it["name"]), retries=1)
                self._call(gen, self.arm.open_gripper)
                self._call(gen, self.arm.go_home)
        return False, 1

    def _handover(self, cmd: dict, gen: int) -> None:
        it = settings.item(self.setting, cmd["item"])
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
        self.emit("picked", retries=retries)
        elapsed = lambda: round(time.time() - cmd["received"], 2)  # noqa: E731

        if it.get("sharp"):
            self._set_down(gen, it, lines.sharp_down(it["name"]), elapsed, retries)
            self._home(gen)
            return

        self.set_step("moving_to_hand")
        self._call(gen, self.arm.go_carry)
        if not self._reach_hand(gen, it):
            return
        self.set_step("waiting_for_pull")
        self.emit("handed", say=lines.handed(it["name"]), request_to_hand_s=elapsed(), retries=retries)
        if not self._wait_for_pull(gen):
            self._set_down(gen, it, lines.no_pull(it["name"]), None, retries)
            self._home(gen)
            return
        self.set_step("releasing")
        self._call(gen, self.arm.open_gripper)
        with self.lock:
            self.out.append(it["id"])
        self.emit("released")
        self._home(gen)

    def _set_down(self, gen, it, say, elapsed=None, retries=None) -> None:
        """elapsed: a function giving request-to-hand seconds, only for a planned (sharp) set-down."""
        self.set_step("setting_down")
        self._call(gen, self.arm.set_down_safe_spot)
        with self.lock:
            self.out.append(it["id"])
        self.emit("set_down", say=say, request_to_hand_s=elapsed() if elapsed else None, retries=retries)

    def _reach_hand(self, gen: int, it: dict) -> bool:
        """Move to the hand (or the saved spot). Slow near the hand; freeze if the hand is lost
        or the path is blocked. False means the flow already set the item down."""
        for attempt in range(2):
            if self._tracking():
                hand = self._wait(gen, self._hand_ready, HAND_WAIT_S, lines.SHOW_HAND)
                if hand is None:
                    self._set_down(gen, it, lines.no_hand(it["name"]), None, None)
                    self._home(gen)
                    return False
                target = list(hand["target"])
            else:
                target = _saved_spot()
            x, y, z = target
            back = (x - APPROACH_BACK_M, y, z) if x > APPROACH_BACK_M else (x, y, z)
            watch = self._watch_hand() if self._tracking() else None
            try:
                ok = self._call(gen, self.arm.move_to, *back, speed=SPEED_NORMAL) and \
                    self._call(gen, self.arm.move_to, x, y, z, speed=SPEED_NEAR)
            finally:
                lost = watch() if watch else False
            if ok and not lost:
                return True
            if lost:
                self.emit("missed", say=lines.HAND_LOST)
                continue  # wait for the hand again, one more try
            self.emit("missed", say=lines.OUT_OF_REACH)
            break
        self._set_down(gen, it, lines.set_down(it["name"]), None, None)
        self._home(gen)
        return False

    def _watch_hand(self):
        """Freeze the arm if the hand disappears or the path blocks while moving.
        Returns a function that stops watching and says whether it froze."""
        done, froze = threading.Event(), threading.Event()

        def run():
            while not done.wait(0.05):
                h = self.hand
                fresh = h and h.get("seen") and time.time() - self.hand_at <= HAND_STALE_S
                if not fresh or h.get("path_clear") is False:
                    froze.set()
                    self.arm.freeze()
                    return
        th = threading.Thread(target=run, daemon=True)
        th.start()

        def stop() -> bool:
            done.set()
            th.join()  # no late freeze landing on the next move
            return froze.is_set()
        return stop

    def _wait(self, gen: int, check, timeout: float, say: str | None):
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

    def _wait_for_pull(self, gen: int) -> bool:
        self.got_it.clear()
        base = self._call(gen, self.arm.gripper_load)
        end = time.time() + PULL_WAIT_S
        while time.time() < end:
            if self.gen != gen:
                raise Stopped
            if self.got_it.is_set() or self.arm.gripper_load() - base > PULL_DELTA:
                return True
            time.sleep(0.05)
        return False

    def _return(self, cmd: dict, gen: int) -> None:
        item_id = cmd.get("item") or self._return_spot_item() or (self.out[-1] if self.out else None)
        it = settings.item(self.setting, item_id or "")
        if it is None:
            self.emit("missed", say=lines.NOTHING_OUT, item=None)
            return
        self.set_step("returning", item=it["id"])
        ok, retries = self._pick(gen, it, it["return_instruction"], want_closed=False)
        if not ok:
            self.emit("missed", say=lines.couldnt_return(it["name"]), retries=retries)
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
        times = []
        for ev in self.history:
            if ev["type"] in ("handed", "set_down", "missed") and ev["item"]:
                row = by_item.setdefault(ev["item"], {"ok": 0, "missed": 0})
                row["missed" if ev["type"] == "missed" else "ok"] += 1
                if ev["request_to_hand_s"]:
                    times.append(ev["request_to_hand_s"])
        return {"source": "controller memory (ledger not loaded)", "by_item": by_item,
                "median_request_to_hand_s": statistics.median(times) if times else None}
