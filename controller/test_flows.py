"""Forces each failure case on the fake arm. Run: .venv/bin/python -m controller.test_flows"""
import json
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path

# Test runs never reach MongoDB, Backboard or the repo's ledger buffer and policy file; their events say test: true.
_SCRATCH = Path(tempfile.mkdtemp(prefix="scrub-test-flows-"))
os.environ.update(MONGODB_URI="", BACKBOARD_API_KEY="", SCRUB_TEST="1", LEDGER_BUFFER=str(_SCRATCH / "buffer.jsonl"),
                  SKILL_POLICY_FILE=str(_SCRATCH / "skill_policy.json"))

from . import core, lines, picker, settings  # noqa: E402
from .core import Controller  # noqa: E402
from .fake_arm import FakeArm  # noqa: E402

core.ledger = None  # never write the shared ledger (MongoDB): see conftest.py
core.LOCATE_URL = ""  # no vision: /locate and /safe_zone answer None (no network)
core.KEEPOUT_WAIT_S = 1.0
core.ZONE_WAIT_S = 1.0
core.ZONE_POLL_S = 0.05
core.HAND_WAIT_S = 1.0
core.PULL_WAIT_S = 1.0
core.TRAY_LAG_S = 0.05
core.AUTO_RETURN_S = 0.3
core.PREPARE_RETRY_S = 0.1


class RecordingArm(FakeArm):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.moves = []

    def move_to(self, x, y, z, speed=0.3):
        self.moves.append((round(x, 3), round(y, 3), round(z, 3), speed))
        return super().move_to(x, y, z, speed)


def make(pull_s=0.2):
    arm = RecordingArm(motion_s=0.1, auto_pull_s=pull_s)
    return Controller(arm, fake_arm=True), arm


def run(ctl, cmd, timeout=8.0):
    """Submit and wait for the controller to go idle (or stopped/error). Returns this run's events."""
    start = len(ctl.history)
    reply = ctl.submit(dict(cmd))
    end = time.time() + timeout
    time.sleep(0.05)
    while time.time() < end:
        if not ctl.jobs and ctl.cmd is None and ctl.step in ("idle", "stopped", "error"):
            break
        time.sleep(0.02)
    return reply, list(ctl.history)[start:]


def types(evs):
    return [e["type"] for e in evs if e["type"] != "step"]


def steps(evs):
    return [e["step"] for e in evs if e["type"] == "step"]


def says(evs):
    return [e["say"] for e in evs if e["say"]]


def hand_feed(ctl, stop_evt, seen=lambda: True, clear=lambda: True, open_=lambda: True):
    def loop():
        while not stop_evt.is_set():
            ctl.post_hand({"seen": seen(), "open": open_(), "palm_px": [300, 200],
                           "target": [0.22, -0.1, 0.18], "path_clear": clear(), "t": time.time()})
            time.sleep(0.05)
    threading.Thread(target=loop, daemon=True).start()


def tray(ctl, item, present):
    ctl.post_tray({"setting": "surgical", "slots": [{"item": item, "present": present, "confidence": 0.9, "box": None}],
                   "return_spot": {"item": None, "confidence": 0.0, "box": None}, "t": time.time()})


def tray_feed(ctl, stop_evt, item, present=lambda: True):
    def loop():
        while not stop_evt.is_set():
            tray(ctl, item, present())
            time.sleep(0.05)
    threading.Thread(target=loop, daemon=True).start()


def post_scene(ctl, scene):
    """One TrayState from a scene: {"spot": item or None, "empty": set of item ids off their slots}."""
    ctl.post_tray({"setting": "surgical",
                   "slots": [{"item": i, "present": i not in scene["empty"], "confidence": 0.9, "box": None}
                             for i in ("scalpel", "hemostat", "mayo_scissors")],
                   "return_spot": {"item": scene["spot"], "confidence": 0.9, "box": None}, "t": time.time()})


def scene_feed(ctl, stop_evt, scene, period=0.05):
    """TrayStates from a mutable scene, like vision posting them."""
    def loop():
        while not stop_evt.is_set():
            post_scene(ctl, scene)
            time.sleep(period)
    threading.Thread(target=loop, daemon=True).start()


def put_back_moves_it(arm, scene):
    """The fake arm's return skill moves the item from the return spot into its slot."""
    orig = arm.run_skill

    def run_skill(instruction, max_s=20.0, source="model"):
        ok = orig(instruction, max_s, source)
        if ok and instruction.startswith("return") and scene["spot"]:
            scene["empty"].discard(scene["spot"])
            scene["spot"] = None
        return ok
    arm.run_skill = run_skill


def autos(evs):
    return [e for e in evs if e["type"] == "command" and e.get("source") == "auto"]


def wait_for(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end and not cond():
        time.sleep(0.02)
    return cond()


def reset(ctl, timeout=5.0):
    start = len(ctl.history)
    ctl.reset()
    end = time.time() + timeout
    while time.time() < end and not (ctl.step == "idle" and ctl.cmd is None and not ctl.jobs):
        time.sleep(0.02)
    return list(ctl.history)[start:]


HANDOVER = {"action": "handover", "item": "hemostat", "source": "keyboard"}
TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


@test
def happy_path_every_step_and_timer():
    ctl, arm = make()
    reply, evs = run(ctl, HANDOVER)
    assert reply["accepted"] and reply["say"] == "Hemostat coming."
    assert steps(evs) == ["finding", "picking", "checking", "moving_to_hand", "waiting_for_pull",
                          "releasing", "homing", "idle"], steps(evs)
    assert types(evs) == ["command", "picked", "handed", "released"], types(evs)
    handed = next(e for e in evs if e["type"] == "handed")
    assert handed["request_to_hand_s"] and handed["request_to_hand_s"] > 0
    assert ctl.out == ["hemostat"]


@test
def slows_near_the_hand():
    ctl, arm = make()
    run(ctl, HANDOVER)
    (x1, _, _, s1), (x2, _, _, s2) = arm.moves
    assert s1 == core.SPEED_NORMAL and s2 == core.SPEED_NEAR and x2 - x1 > 0.05, arm.moves


@test
def grasp_miss_then_retry_succeeds():
    ctl, arm = make()
    arm.force["miss_grasp"] = 1
    _, evs = run(ctl, HANDOVER)
    assert types(evs) == ["command", "missed", "picked", "handed", "released"], types(evs)
    assert lines.retry("hemostat") in says(evs)
    assert next(e for e in evs if e["type"] == "picked")["retries"] == 1


@test
def grasp_miss_twice_says_so():
    ctl, arm = make()
    arm.force["miss_grasp"] = 2
    _, evs = run(ctl, HANDOVER)
    assert types(evs) == ["command", "missed", "missed"], types(evs)
    assert says(evs)[-1] == lines.couldnt_pick("hemostat")
    assert ctl.out == [] and ctl.step == "idle" and arm.pose == "home"


@test
def grasp_check_uses_tray_slot():
    ctl, arm = make()
    stop = threading.Event()
    tray_feed(ctl, stop, "hemostat")  # slot still full after the pick: the grasp failed
    _, evs = run(ctl, HANDOVER)
    stop.set()
    assert says(evs)[-1] == lines.couldnt_pick("hemostat"), says(evs)


@test
def grasp_check_ignores_tray_from_before_the_pick():
    ctl, arm = make()
    tray(ctl, "hemostat", True)  # one TrayState, taken before the arm moved
    _, evs = run(ctl, HANDOVER)
    assert "released" in types(evs), says(evs)


@test
def stale_tray_is_ignored():
    ctl, arm = make()
    tray(ctl, "hemostat", False)
    ctl.tray["stale"] = True
    _, evs = run(ctl, HANDOVER)
    assert "released" in types(evs), says(evs)


@test
def empty_slot_before_pick():
    ctl, arm = make()
    tray(ctl, "hemostat", False)
    _, evs = run(ctl, HANDOVER)
    assert types(evs) == ["command", "missed"] and says(evs)[-1] == lines.not_on_tray("hemostat")
    assert "picking" not in steps(evs)


@test
def skill_fails_counts_as_miss():
    ctl, arm = make()
    arm.force["skill_fail"] = 2
    _, evs = run(ctl, HANDOVER)
    assert says(evs)[-1] == lines.couldnt_pick("hemostat")


@test
def no_load_reading_waits_for_got_it():
    ctl, arm = make()
    arm.force["no_load"] = 1  # real arm: gripper_load() raises with no fresh bus reading
    ctl.submit(dict(HANDOVER))
    end = time.time() + 5
    while ctl.step != "waiting_for_pull" and time.time() < end:
        time.sleep(0.02)
    time.sleep(0.3)
    assert ctl.step == "waiting_for_pull" and lines.SAY_GOT_IT in says(ctl.history), ctl.step
    _, evs = run(ctl, {"action": "got_it", "source": "voice"})
    assert "released" in types(evs), types(evs)


@test
def rests_at_home_then_wakes_for_the_next_command():
    """After a handover it goes home, waits REST_AFTER_S, rests (torque off), and wakes for the next one."""
    import controller.core as core
    old, core.REST_AFTER_S = core.REST_AFTER_S, 0.3
    try:
        ctl, arm = make()
        _, evs = run(ctl, dict(HANDOVER))
        assert "released" in types(evs), types(evs)
        run(ctl, {"action": "return", "item": HANDOVER["item"]})  # put it back before asking for it again
        assert wait_for(lambda: ctl.state()["resting"], 3.0), "never rested after going home"
        assert arm.resting
        _, evs = run(ctl, dict(HANDOVER))
        assert "released" in types(evs), types(evs)
        assert getattr(arm, "rest_count", 0) >= 1
    finally:
        core.REST_AFTER_S = old


@test
def a_wake_that_raises_holds_and_the_worker_lives():
    old, core.REST_AFTER_S = core.REST_AFTER_S, 0.1
    try:
        ctl, arm = make()
        assert wait_for(lambda: ctl.resting)

        def bad_wake():
            raise RuntimeError("bus timeout on torque on")
        arm.wake = bad_wake
        _, evs = run(ctl, HANDOVER)
        assert ctl.step == "error" and says(evs)[-1] == lines.ERROR, says(evs)
        arm.wake = FakeArm.wake.__get__(arm)
        reset(ctl)
        _, evs = run(ctl, HANDOVER)  # the worker thread is still there
        assert "released" in types(evs), types(evs)
    finally:
        core.REST_AFTER_S = old


@test
def pull_detected_when_load_drops():
    ctl, arm = make(pull_s=None)
    t0 = [None]

    def load():  # the bus value is signed: a tug can read as a drop
        if ctl.step != "waiting_for_pull":
            return 100.0
        t0[0] = t0[0] or time.time()
        return -50.0 if time.time() - t0[0] > 0.2 else 100.0
    arm.gripper_load = load
    _, evs = run(ctl, HANDOVER)
    assert "released" in types(evs), types(evs)


@test
def no_pull_times_out_and_sets_down():
    ctl, arm = make()
    arm.force["no_pull"] = 1
    _, evs = run(ctl, HANDOVER)
    assert types(evs) == ["command", "picked", "handed", "set_down"], types(evs)
    assert arm.pose == "home" and ctl.out == ["hemostat"]


@test
def got_it_releases():
    ctl, arm = make(pull_s=None)
    ctl.submit(dict(HANDOVER))
    end = time.time() + 5
    while ctl.step != "waiting_for_pull" and time.time() < end:
        time.sleep(0.02)
    bad = ctl.submit({"action": "got_it"}) if ctl.step != "waiting_for_pull" else None
    assert bad is None
    reply, evs = run(ctl, {"action": "got_it", "source": "voice"})
    assert reply["accepted"] and "released" in types(evs), types(evs)
    assert not ctl.submit({"action": "got_it"})["accepted"]  # nothing out now


@test
def let_go_opens_the_clasp_at_the_hand():
    ctl, arm = make(pull_s=None)
    threading.Thread(target=lambda: ctl.submit(dict(HANDOVER)), daemon=True).start()
    assert wait_for(lambda: ctl.step == "waiting_for_pull")
    reply = ctl.submit({"action": "let_go", "heard": "let go", "source": "voice"})
    assert reply["accepted"] and reply["say"] == lines.LET_GO
    assert wait_for(lambda: ctl.step == "idle" and arm._gripper == 0.0 and ctl.out == ["hemostat"])


@test
def let_go_opens_while_carrying_and_does_nothing_when_empty():
    ctl, arm = make(pull_s=30)
    threading.Thread(target=lambda: ctl.submit(dict(HANDOVER)), daemon=True).start()
    assert wait_for(lambda: ctl.step == "moving_to_hand" and ctl.held == "hemostat")
    reply = ctl.submit({"action": "let_go", "heard": "let go", "source": "voice"})
    assert reply["accepted"] and reply["say"] == lines.LET_GO
    assert wait_for(lambda: arm._gripper == 0.0 and ctl.held is None and "hemostat" in ctl.out)
    assert wait_for(lambda: ctl.step == "idle" and ctl.cmd is None)
    empty = ctl.submit({"action": "let_go", "source": "voice"})
    assert not empty["accepted"] and empty["say"] == lines.NOT_HOLDING and empty["reason"] == "not holding"


@test
def sharp_goes_to_safe_spot_with_timer():
    ctl, arm = make()
    _, evs = run(ctl, {"action": "handover", "item": "scalpel"})
    assert "moving_to_hand" not in steps(evs) and arm.moves == []
    sd = next(e for e in evs if e["type"] == "set_down")
    assert sd["say"] == lines.sharp_down("scalpel") and sd["say"].startswith("Scalpel down") and sd["request_to_hand_s"] >= 0.15


@test
def sharp_acknowledged_as_safe_spot_not_coming():
    ctl, arm = make()
    reply, evs = run(ctl, {"action": "handover", "item": "scalpel"})
    assert reply["accepted"] and reply["say"] == "Scalpel to the safe spot."
    cmd = next(e for e in evs if e["type"] == "command")
    assert cmd["say"] == "Scalpel to the safe spot." and "coming" not in " ".join(says(evs))
    assert lines.sharp_seen("scalpel") in says(evs)


@test
def camera_sharp_warns_before_the_arm_hands_it_out():
    ctl, arm = make()
    seen = []

    def camera(item_id):
        seen.append(item_id)
        return item_id == "hemostat"

    import controller.sharpness as sharpness
    old = sharpness.camera_says_sharp
    sharpness.camera_says_sharp = camera
    # core imported the function directly, so patch that binding too.
    old_core = core.camera_says_sharp
    core.camera_says_sharp = camera
    try:
        _, evs = run(ctl, HANDOVER)
    finally:
        sharpness.camera_says_sharp = old
        core.camera_says_sharp = old_core
    assert seen == ["hemostat"]
    warning = next(i for i, e in enumerate(evs) if e.get("say") == lines.sharp_seen("hemostat"))
    move = next(i for i, e in enumerate(evs) if e.get("step") == "moving_to_hand")
    assert warning < move, [e.get("type") for e in evs]
    assert "handed" in types(evs)


@test
def tracking_on_but_no_hand():
    ctl, arm = make()
    stop = threading.Event()
    hand_feed(ctl, stop, seen=lambda: False)
    _, evs = run(ctl, HANDOVER)
    stop.set()
    assert lines.SHOW_HAND in says(evs) and says(evs)[-1] == lines.no_hand("hemostat"), says(evs)
    assert arm.moves == []


@test
def hand_seen_but_path_blocked_says_so():
    """M11: an open, seen hand with the path blocked sets down with "Something's in the way", not "No hand"."""
    ctl, arm = make()
    stop = threading.Event()
    hand_feed(ctl, stop, clear=lambda: False)
    _, evs = run(ctl, HANDOVER)
    stop.set()
    assert says(evs)[-1] == lines.path_blocked_down("hemostat") == "Something's in the way. Hemostat is at the safe spot.", says(evs)
    assert arm.moves == [] and "set_down" in types(evs)


@test
def count_survives_a_restart():
    """H2: out and case_id saved on change to a temp file and restored by a new controller (same setting, fresh)."""
    import json
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "state.json")
        ctl, arm = make()
        ctl.state_file, ctl._state_pool = path, core.ThreadPoolExecutor(1)  # make() leaves it off
        run(ctl, HANDOVER)
        wait_for(lambda: os.path.exists(path) and json.load(open(path))["out"] == ["hemostat"])
        saved = json.load(open(path))
        assert saved["case_id"] == ctl.case_id and saved["setting"] == "surgical", saved
        n = len(os.listdir(d))
        mtime = os.stat(path).st_mtime_ns
        run(ctl, {"action": "count"})  # nothing changed: no write
        time.sleep(0.2)
        assert os.stat(path).st_mtime_ns == mtime and len(os.listdir(d)) == n
        again = Controller(RecordingArm(motion_s=0.1), fake_arm=True, state_file=path)
        assert again.out == ["hemostat"] and again.case_id == ctl.case_id, (again.out, again.case_id)
        assert again.submit({"action": "count"})["say"] == "Out: hemostat."
        other = Controller(RecordingArm(motion_s=0.1), fake_arm=True, setting_id="bench", state_file=path)
        assert other.out == [] and other.case_id != ctl.case_id  # another tray: a fresh case
        json.dump({**saved, "t": time.time() - 7 * 3600}, open(path, "w"))
        old = Controller(RecordingArm(motion_s=0.1), fake_arm=True, state_file=path)
        assert old.out == [], old.out  # over 6 h old: a fresh case
        open(path, "w").write("{not json")
        assert Controller(RecordingArm(motion_s=0.1), fake_arm=True, state_file=path).out == []


@test
def tray_check_falls_back_to_the_controllers_tray():
    """M3: no vision process (sim, backup): a fresh TrayState the controller holds answers the tray check."""
    from . import settings, traycheck
    surgical = settings.load("surgical")
    slots = [{"item": i["id"], "present": True} for i in surgical["items"]]
    tray_state = {"setting": "surgical", "slots": slots, "t": time.time()}
    v = traycheck.from_tray(tray_state, time.time())
    r = traycheck.check(surgical, fetch=lambda: v)
    assert r["ok"] and r["available"] and r["say"].startswith("Tray's ready"), r
    tray_state["slots"][0]["present"] = False
    r = traycheck.check(surgical, fetch=lambda: traycheck.from_tray(tray_state, time.time()))
    assert not r["ok"] and r["say"] == "Missing the scalpel.", r
    assert traycheck.from_tray(tray_state, time.time() - core.TRAY_STALE_S - 1) is None  # older than the cutoff
    assert traycheck.from_tray({**tray_state, "stale": True}, time.time()) is None
    assert traycheck.from_tray(None, 0.0) is None and traycheck.from_tray({"slots": []}, time.time()) is None


@test
def set_down_failure_holds_for_reset():
    ctl, arm = make()
    arm.set_down_safe_spot = lambda: False  # real arm: didn't reach the safe spot
    _, evs = run(ctl, {"action": "handover", "item": "scalpel"})
    assert ctl.step == "error" and says(evs)[-1] == lines.SET_DOWN_FAILED, says(evs)
    assert "set_down" not in types(evs) and ctl.out == ["scalpel"]  # still in the gripper: off the tray
    assert ctl.submit(dict(HANDOVER))["say"] == lines.NEEDS_RESET


@test
def arm_exception_freezes_and_holds():
    ctl, arm = make()

    def boom():
        raise RuntimeError("bus timeout")
    arm.go_carry = boom
    _, evs = run(ctl, HANDOVER)
    assert ctl.step == "error" and arm._frozen.is_set() and says(evs)[-1] == lines.ERROR, says(evs)


@test
def hand_lost_mid_move_holds_until_reset():
    ctl, arm = make()
    stop = threading.Event()
    lost_until = [0.0]
    hand_feed(ctl, stop, seen=lambda: time.time() > lost_until[0])
    orig = arm.move_to

    def move_and_lose(*a, **kw):  # the hand vanishes during the first move only
        if len(arm.moves) == 0:
            lost_until[0] = time.time() + 0.4
        return orig(*a, **kw)
    arm.move_to = move_and_lose
    _, evs = run(ctl, HANDOVER)
    stop.set()
    assert says(evs)[-1] == lines.HAND_LOST and ctl.step == "stopped", says(evs)
    assert arm._frozen.is_set() and len(arm.moves) == 1  # no second move on a latched arm
    assert ctl.submit(dict(HANDOVER))["say"] == lines.NEEDS_RESET
    evs = reset(ctl)
    assert "setting_down" in steps(evs) and ctl.out == ["hemostat"] and arm.pose == "home", steps(evs)
    assert evs[-1]["say"] == lines.RESET


@test
def hand_closed_on_the_fast_leg_holds():
    ctl, arm = make()
    arm.scale = 0.5  # a 0.5 s first move: about ten Hand posts
    stop = threading.Event()
    hand_feed(ctl, stop, open_=lambda: len(arm.moves) == 0)  # the hand closes once the arm starts moving
    _, evs = run(ctl, HANDOVER)
    stop.set()
    assert says(evs)[-1] == lines.HAND_CLOSED and ctl.step == "stopped", says(evs)
    assert arm._frozen.is_set() and len(arm.moves) == 1 and ctl.out == ["hemostat"]
    evs = reset(ctl)
    assert "setting_down" in steps(evs) and arm.pose == "home", steps(evs)


@test
def hand_flicker_and_a_grab_at_the_hand_never_stop():
    ctl, arm = make()
    arm.scale = 0.5
    stop = threading.Event()
    flip = iter(range(10 ** 6))
    # Fast leg: open and closed alternate (flicker). Slow last leg: closed (the clinician reaching for it).
    hand_feed(ctl, stop, open_=lambda: len(arm.moves) < 2 and next(flip) % 2 == 0)
    _, evs = run(ctl, HANDOVER, timeout=15)
    stop.set()
    assert "released" in types(evs) and ctl.step == "idle", says(evs)


@test
def path_blocked_freezes():
    ctl, arm = make()
    stop = threading.Event()
    hand_feed(ctl, stop, clear=lambda: len(arm.moves) == 0)  # blocks once the arm starts moving
    _, evs = run(ctl, HANDOVER)
    stop.set()
    assert says(evs)[-1] == lines.PATH_BLOCKED and ctl.step == "stopped", says(evs)


@test
def outside_handoff_region():
    ctl, arm = make()
    arm.force["out_of_region"] = 2  # approach point and the target both refused
    _, evs = run(ctl, HANDOVER)
    assert lines.OUT_OF_REACH in says(evs) and "set_down" in types(evs), says(evs)


@test
def approach_outside_region_goes_straight_in():
    ctl, arm = make()
    arm.force["out_of_region"] = 1
    _, evs = run(ctl, HANDOVER)
    assert "released" in types(evs) and arm.moves[-1][3] == core.SPEED_NEAR, (types(evs), arm.moves)


@test
def stop_mid_pick_is_instant():
    ctl, arm = make()
    arm.scale = 2.0  # slow motions so stop lands mid-call
    ctl.submit(dict(HANDOVER))
    ctl.submit({"action": "handover", "item": "mayo_scissors"})
    time.sleep(0.3)
    t0 = time.time()
    ctl.submit({"action": "stop", "source": "voice"})
    n = len(ctl.history)
    time.sleep(0.5)
    later = [e for e in list(ctl.history)[n:] if e["type"] != "command"]
    assert ctl.step == "stopped" and not ctl.jobs and later == [], later
    assert time.time() - t0 < 1.0
    arm.scale = 0.1
    r = ctl.submit({"action": "handover", "item": "mayo_scissors"})
    assert not r["accepted"] and r["say"] == lines.NEEDS_RESET, r  # the arm stays frozen until reset
    reset(ctl)
    _, evs = run(ctl, {"action": "handover", "item": "mayo_scissors"})  # works again after reset
    assert "released" in types(evs)


def stop_at(step, pull_s=None):
    ctl, arm = make(pull_s=pull_s)
    ctl.submit(dict(HANDOVER))
    end = time.time() + 5
    while ctl.step != step and time.time() < end:
        time.sleep(0.005)
    assert ctl.step == step, ctl.step
    ctl.submit({"action": "stop"})
    n = len(ctl.history)
    time.sleep(0.5)
    later = [e for e in list(ctl.history)[n:] if e["type"] != "command"]
    assert ctl.step == "stopped" and later == [], later
    return ctl, arm


@test
def stop_while_moving_to_the_hand():
    ctl, _ = stop_at("moving_to_hand")
    assert ctl.out == ["hemostat"] and ctl.state()["out"] == ["hemostat"]  # held item counts as out
    assert ctl.history[-1]["out"] == ["hemostat"]


@test
def stop_mid_pick_counts_nothing_out():
    ctl, _ = stop_at("picking")
    assert ctl.out == []  # not lifted yet


@test
def stop_while_holding_out_then_reset_sets_it_down():
    ctl, arm = stop_at("waiting_for_pull")
    evs = reset(ctl)
    assert "setting_down" in steps(evs) and arm.pose == "home" and ctl.out == ["hemostat"], steps(evs)


@test
def return_and_count():
    ctl, arm = make()
    run(ctl, HANDOVER)
    reply, _ = run(ctl, {"action": "count"})
    assert reply["say"] == "Out: hemostat."
    _, evs = run(ctl, {"action": "return"})
    assert says(evs)[-1] == "Hemostat back in its slot." and ctl.out == []
    assert not ctl.submit({"action": "return"})["accepted"]


@test
def return_checked_against_the_tray():
    ctl, arm = make()
    run(ctl, HANDOVER)
    stop = threading.Event()
    tray_feed(ctl, stop, "hemostat", present=lambda: False)  # the slot stays empty after the put-back
    _, evs = run(ctl, {"action": "return", "item": "hemostat"})
    stop.set()
    assert says(evs)[-1] == lines.couldnt_return("hemostat") and ctl.out == ["hemostat"], says(evs)


@test
def failed_return_still_holding_sets_it_down():
    ctl, arm = make()
    run(ctl, HANDOVER)
    arm._gripper = 0.6  # the return skill fails twice with the item still in the jaw
    arm.force["skill_fail"] = 2
    _, evs = run(ctl, {"action": "return", "item": "hemostat"})
    assert lines.couldnt_return("hemostat") in says(evs) and "set_down" in types(evs), says(evs)
    assert ctl.step == "idle" and arm.pose == "home" and arm._gripper == 0.0 and ctl.out == ["hemostat"]
    assert steps(evs)[-3:] == ["setting_down", "homing", "idle"], steps(evs)


@test
def failed_return_with_an_open_gripper_just_homes():
    ctl, arm = make()
    run(ctl, HANDOVER)
    arm.force["skill_fail"] = 2
    _, evs = run(ctl, {"action": "return", "item": "hemostat"})
    assert "set_down" not in types(evs) and arm.pose == "home" and ctl.out == ["hemostat"], types(evs)


@test
def tray_stale_cutoff_comes_from_env():
    import subprocess
    import sys
    code = "from controller import core; print(core.TRAY_STALE_S)"
    env = {**os.environ, "TRAY_STALE_S": "6.5"}
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True).stdout
    assert out.strip() == "6.5", out
    env.pop("TRAY_STALE_S")
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True).stdout
    assert out.strip() == "8.0", out


@test
def slow_tray_posts_inside_the_cutoff_still_auto_return():
    """Vision posting every 0.4 s with the cutoff at 0.3 s never auto-returns; a raised cutoff does."""
    old = core.TRAY_STALE_S
    try:
        for cutoff, want in ((0.3, False), (1.0, True)):
            core.TRAY_STALE_S = cutoff
            ctl, arm = make()
            run(ctl, HANDOVER)
            scene = {"spot": "hemostat", "empty": {"hemostat"}}
            stop = threading.Event()
            scene_feed(ctl, stop, scene, period=0.4)
            got = wait_for(lambda: autos(list(ctl.history)), timeout=2.0)
            stop.set()
            assert bool(got) == want, (cutoff, got)
    finally:
        core.TRAY_STALE_S = old


@test
def ops_page_shows_no_taught_skill_for_null():
    import re
    import subprocess
    node = shutil.which("node")
    if not node:
        return  # no Node here: nothing to run the page script with
    html = (Path(__file__).parent / "ops.html").read_text()
    fn = re.search(r"function renderSkills\(.*?\n}\n", html, re.S).group(0)
    esc = re.search(r"const esc = .*?;\n", html).group(0)
    js = ("const el = {}; const $ = id => (el[id] = el[id] || {});\n" + esc + fn +
          "renderSkills({skills: {mode: 'taught', items: {hemostat: 'taught', scalpel: null}}}, []);\n"
          "console.log(el.skills.innerHTML);")
    out = subprocess.run([node, "-e", js], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert "no taught skill" in out.stdout and "<td>taught</td>" in out.stdout, out.stdout


@test
def count_agrees_with_the_camera():
    ctl, arm = make()
    run(ctl, HANDOVER)
    assert ctl.state()["out_camera"] is None  # no TrayState yet
    post_scene(ctl, {"spot": None, "empty": {"hemostat"}})
    assert ctl.state()["out_camera"] == ["hemostat"]
    reply, evs = run(ctl, {"action": "count"})
    assert reply["say"] == "Out: hemostat." and evs[-1]["out_camera"] == ["hemostat"], reply


@test
def count_says_when_the_camera_disagrees():
    ctl, arm = make()
    run(ctl, HANDOVER)
    post_scene(ctl, {"spot": None, "empty": {"hemostat", "mayo_scissors"}})
    reply, _ = run(ctl, {"action": "count"})
    assert reply["say"] == "Out: hemostat. " + lines.camera_gone(ctl._names(["mayo_scissors"])), reply
    post_scene(ctl, {"spot": "hemostat", "empty": {"hemostat"}})  # set down in the return spot
    assert ctl.state()["out_camera"] == []
    reply, _ = run(ctl, {"action": "count"})
    assert reply["say"] == "Out: hemostat. " + lines.camera_back(["hemostat"]), reply
    ctl.tray["stale"] = True  # stale: back to the plain line
    assert ctl.state()["out_camera"] is None
    assert run(ctl, {"action": "count"})[0]["say"] == "Out: hemostat."
    ctl.stop()


@test
def auto_return_from_the_return_spot():
    ctl, arm = make()
    run(ctl, HANDOVER)
    scene = {"spot": None, "empty": {"hemostat"}}
    put_back_moves_it(arm, scene)
    stop = threading.Event()
    scene_feed(ctl, stop, scene)
    time.sleep(0.2)
    scene["spot"] = "hemostat"  # the clinician sets it down
    time.sleep(0.15)
    assert autos(ctl.history) == [], "triggered before the item sat long enough"
    assert wait_for(lambda: any(e["type"] == "returned" for e in ctl.history))
    assert wait_for(lambda: ctl.step == "idle" and ctl.cmd is None)
    stop.set()
    a = autos(ctl.history)
    assert len(a) == 1 and a[0]["say"] == lines.auto_return("hemostat") and a[0]["action"] == "return", a
    evs = [e for e in ctl.history if e["command_id"] == a[0]["command_id"]]
    assert types(evs) == ["command", "returned"] and ctl.out == [], types(evs)


@test
def auto_return_once_per_visit_to_the_spot():
    ctl, arm = make()
    arm.force["skill_fail"] = 2  # the put-back fails: the item stays in the return spot
    scene = {"spot": "hemostat", "empty": {"hemostat"}}
    stop = threading.Event()
    scene_feed(ctl, stop, scene)
    assert wait_for(lambda: any(e["type"] == "missed" for e in ctl.history))
    assert wait_for(lambda: ctl.step == "idle" and ctl.cmd is None)
    time.sleep(0.8)
    assert len(autos(ctl.history)) == 1, says(ctl.history)  # still there: no second try
    scene["spot"] = None  # picked up, then set down again
    time.sleep(0.2)
    scene["spot"] = "hemostat"
    assert wait_for(lambda: len(autos(ctl.history)) == 2), says(ctl.history)
    stop.set()
    wait_for(lambda: ctl.step == "idle" and ctl.cmd is None)


@test
def auto_return_never_while_stopped_or_busy():
    ctl, arm = make(pull_s=None)
    ctl.submit(dict(HANDOVER))
    assert wait_for(lambda: ctl.step == "waiting_for_pull")
    stop = threading.Event()
    scene_feed(ctl, stop, {"spot": "mayo_scissors", "empty": {"hemostat", "mayo_scissors"}})
    time.sleep(0.8)
    assert autos(ctl.history) == [] and ctl.step == "waiting_for_pull"  # busy
    ctl.stop()
    time.sleep(0.8)
    assert autos(ctl.history) == [] and ctl.step == "stopped"
    stop.set()


@test
def stop_interrupts_auto_return():
    ctl, arm = make()
    arm.scale = 2.0
    scene = {"spot": "hemostat", "empty": {"hemostat"}}
    stop = threading.Event()
    scene_feed(ctl, stop, scene)
    assert wait_for(lambda: ctl.step == "returning")
    t0 = time.time()
    ctl.submit({"action": "stop", "source": "voice"})
    n = len(ctl.history)
    time.sleep(0.5)
    later = [e for e in list(ctl.history)[n:] if e["type"] != "command"]
    assert ctl.step == "stopped" and later == [] and time.time() - t0 < 1.0, later
    arm.scale = 0.1
    reset(ctl)
    time.sleep(0.8)  # same item still in the spot: no retrigger after the reset
    stop.set()
    assert len(autos(ctl.history)) == 1 and ctl.step == "idle", says(ctl.history)


@test
def reset_keeps_count_unless_asked():
    ctl, arm = make()
    run(ctl, HANDOVER)
    ctl.stop()
    reset(ctl)
    assert ctl.step == "idle" and ctl.out == ["hemostat"] and arm.pose == "home"
    _, evs = run(ctl, {"action": "count"})
    assert says(evs)[-1] == "Out: hemostat.", says(evs)
    ctl.stop()
    ctl.reset(clear_count=True)
    end = time.time() + 5
    while ctl.step != "idle" and time.time() < end:
        time.sleep(0.02)
    assert ctl.step == "idle" and ctl.out == [] and arm.pose == "home"
    assert ctl.history[-1]["say"] == lines.RESET and ctl.history[-1]["out"] == []


@test
def case_id_on_state_and_every_event():
    ctl, arm = make()
    cid = ctl.state()["case_id"]
    setting, start = cid.rsplit("-", 1)
    assert setting == "surgical" and abs(int(start) - time.time()) < 5, cid
    _, evs = run(ctl, HANDOVER)
    assert {e["case_id"] for e in evs} == {cid}
    ctl.case_id = "old"  # same second would give the same id; mark it to see it change
    ctl.stop()
    reset(ctl)
    assert ctl.case_id == "old"  # a plain reset keeps the case
    ctl.reset(clear_count=True)
    assert wait_for(lambda: ctl.case_id != "old") and ctl.case_id.startswith("surgical-")
    assert wait_for(lambda: ctl.step == "idle" and ctl.cmd is None)
    assert ctl.history[-1]["case_id"] == ctl.case_id
    ctl.set_setting("dental")
    assert ctl.state()["case_id"].startswith("dental-") and ctl.history[-1]["case_id"] == ctl.case_id


@test
def null_command_id_gets_one():
    ctl, arm = make()
    reply, evs = run(ctl, {"id": None, "action": "handover", "item": "hemostat", "t": None})
    ids = {e["command_id"] for e in evs}
    assert reply["accepted"] and None not in ids and len(ids) == 1, ids


@test
def rejects():
    ctl, arm = make()
    assert not ctl.submit({"action": "handover", "item": "hex_key"})["accepted"]
    assert not ctl.submit({"action": "unknown", "heard": "uh"})["accepted"]
    replies = [ctl.submit(dict(HANDOVER)) for _ in range(6)]
    assert any(r["reason"] == "queue full" for r in replies), replies
    ctl.stop()


TRAY_OK = {"ok": True, "setting": "surgical", "missing": [], "wrong_slot": [], "extra": [], "stale": False, "t": 1760731200.1}


@test
def tray_check_ready_missing_wrong_slot():
    from . import settings, traycheck
    surgical = settings.load("surgical")
    r = traycheck.check(surgical, fetch=lambda: dict(TRAY_OK))
    names = [i["name"] for i in surgical["items"]]
    assert r["ok"] and r["available"] and r["say"] == lines.tray_ready(names), r
    assert r["label"] == surgical["label"] and r["items"] == names and r["t"] == 1760731200.1
    r = traycheck.check(surgical, fetch=lambda: {**TRAY_OK, "ok": False, "missing": ["scalpel"]})
    assert not r["ok"] and r["say"] == "Missing the scalpel.", r
    slot = settings.item(surgical, "mayo_scissors")["name"]
    r = traycheck.check(surgical, fetch=lambda: {**TRAY_OK, "ok": False,
                        "wrong_slot": [{"item": "hemostat", "in_slot_of": "mayo_scissors"}]})
    assert not r["ok"] and r["say"] == f"The hemostat is in the {slot}' slot.", r
    # Vision says ok but lists a missing item: the list wins. Missing fields are tolerated.
    r = traycheck.check(surgical, fetch=lambda: {"ok": True, "missing": ["scalpel", "hemostat"], "new_field": 1})
    assert not r["ok"] and r["say"] == "Missing the scalpel and the hemostat." and r["new_field"] == 1, r
    r = traycheck.check(surgical, fetch=lambda: {"missing": []})
    assert r["ok"] and r["say"].startswith("Tray's ready"), r
    r = traycheck.check(surgical, fetch=lambda: {**TRAY_OK, "stale": True})
    assert not r["ok"] and r["say"] == lines.CANT_CHECK_TRAY, r
    r = traycheck.check(surgical, fetch=lambda: {**TRAY_OK, "setting": "dental"})
    assert not r["ok"] and "dental" in r["say"], r


@test
def tray_check_route_and_vision_down():
    """GET /tray_check through the app against a tiny fake vision; then vision down, 404 and slow."""
    import json
    import os
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from fastapi.testclient import TestClient
    from . import server, traycheck
    answer = {"code": 200, "body": {**TRAY_OK, "ok": False, "missing": ["scalpel"]}, "delay": 0.0}

    class Vision(BaseHTTPRequestHandler):
        def do_GET(self):
            time.sleep(answer["delay"])
            ok = self.path == "/tray_check" and answer["code"] == 200
            self.send_response(200 if ok else 404)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(answer["body"] if ok else {"detail": "Not Found"}).encode())

        def log_message(self, *a):
            pass

    vision = HTTPServer(("127.0.0.1", 0), Vision)
    threading.Thread(target=vision.serve_forever, daemon=True).start()
    old, old_timeout = os.environ.get("VISION_URL"), traycheck.TIMEOUT_S
    os.environ["VISION_URL"] = f"http://127.0.0.1:{vision.server_port}"
    try:
        ctl, arm = make()
        client = TestClient(server.make_app(ctl))
        r = client.get("/tray_check").json()
        assert r["ok"] is False and r["available"] and r["say"] == "Missing the scalpel." and r["setting"] == "surgical", r
        answer["code"] = 404
        r = client.get("/tray_check").json()
        assert r == {**r, "ok": False, "available": False, "say": lines.CANT_CHECK_TRAY}, r
        traycheck.TIMEOUT_S, answer["code"], answer["delay"] = 0.3, 200, 1.0
        t0 = time.time()
        r = client.get("/tray_check").json()
        assert r["say"] == lines.CANT_CHECK_TRAY and time.time() - t0 < 1.0, r
        answer["delay"] = 0.0
        vision.shutdown()
        vision.server_close()
        r = client.get("/tray_check").json()
        assert not r["ok"] and not r["available"] and r["say"] == lines.CANT_CHECK_TRAY, r
    finally:
        traycheck.TIMEOUT_S = old_timeout
        if old is None:
            os.environ.pop("VISION_URL", None)
        else:
            os.environ["VISION_URL"] = old


class scratch_settings:
    """settings.SETTINGS_DIR pointed at a temp copy of settings/*.json, so overlays never land in the repo."""
    def __enter__(self):
        self.real, self.tmp = settings.SETTINGS_DIR, tempfile.TemporaryDirectory()
        d = Path(self.tmp.name) / "settings"
        d.mkdir()
        for f in self.real.glob("*.json"):
            if not f.name.endswith(".local.json"):
                shutil.copy(f, d / f.name)
        settings.SETTINGS_DIR = d
        return d

    def __exit__(self, *exc):
        settings.SETTINGS_DIR = self.real
        self.tmp.cleanup()


@test
def overlay_adds_aliases():
    with scratch_settings() as d:
        evan = (d / "surgical.json").read_bytes()
        (d / "surgical.local.json").write_text(json.dumps(
            {"aliases": {"hemostat": ["Snap", "crile", "kelly"], "bovie": ["pen"], "scalpel": ["Number Ten"]}}))
        s = settings.load("surgical")
        hemo = settings.item(s, "hemostat")["aliases"]
        assert "crile" in hemo and hemo.count("snap") == 1 and hemo.count("kelly") == 1, hemo
        assert "number ten" in settings.item(s, "scalpel")["aliases"]
        assert settings.item(s, "bovie") is None and len(s["items"]) == 3  # unknown ids ignored
        assert (d / "surgical.json").read_bytes() == evan
        assert "crile" not in json.loads(evan)["items"][1]["aliases"]


@test
def broken_overlay_is_ignored():
    with scratch_settings() as d:
        (d / "surgical.local.json").write_text("{not json")
        clean = settings.load("surgical")
        assert [i["id"] for i in clean["items"]] == ["scalpel", "hemostat", "mayo_scissors"]
        (d / "dental.local.json").write_text('{"aliases": {"explorer": "probe"}}')  # not a list: skipped
        assert settings.item(settings.load("dental"), "explorer")["aliases"] == settings.item(
            json.loads((d / "dental.json").read_text()), "explorer")["aliases"]


@test
def post_alias_writes_and_reloads():
    from fastapi.testclient import TestClient
    from .server import make_app
    with scratch_settings() as d:
        evan = (d / "surgical.json").read_bytes()
        ctl, arm = make(pull_s=0.5)
        client = TestClient(make_app(ctl))
        ctl.submit(dict(HANDOVER))  # busy: teaching still works and doesn't touch the arm
        assert wait_for(lambda: ctl.step not in ("idle",))
        busy, out, case = ctl.step, list(ctl.out), ctl.case_id
        r = client.post("/alias", json={"item": "hemostat", "alias": "The Crile"}).json()
        assert r["ok"] and r["say"] == "Got it: crile means the hemostat.", r
        assert json.loads((d / "surgical.local.json").read_text()) == {"aliases": {"hemostat": ["crile"]}}
        assert "crile" in settings.item(client.get("/setting").json(), "hemostat")["aliases"]
        assert ctl.case_id == case and ctl.out == out
        r = client.post("/alias", json={"item": "hemostat", "alias": "crile"}).json()  # again: fine, no duplicate
        assert r["ok"] and json.loads((d / "surgical.local.json").read_text())["aliases"]["hemostat"] == ["crile"]
        assert not list(d.glob("*.tmp")), list(d.iterdir())
        assert (d / "surgical.json").read_bytes() == evan
        assert wait_for(lambda: ctl.step == "idle" and ctl.cmd is None, 8)
        run(ctl, {"action": "return", "item": "hemostat"})
        _, evs = run(ctl, {"action": "handover", "item": "hemostat", "heard": "crile please"})
        assert busy != "idle" and "released" in types(evs), (busy, types(evs))
        ctl.set_setting("dental")  # the overlay is per tray
        assert "crile" not in str(client.get("/setting").json())
        ctl.set_setting("surgical")
        assert "crile" in settings.item(ctl.setting, "hemostat")["aliases"]


@test
def post_alias_refuses_conflicts():
    from fastapi.testclient import TestClient
    from .server import make_app
    with scratch_settings() as d:
        ctl, arm = make()
        client = TestClient(make_app(ctl))
        r = client.post("/alias", json={"item": "mayo_scissors", "alias": "clamp"}).json()
        assert not r["ok"] and r["say"] == "Clamp already means the hemostat.", r
        r = client.post("/alias", json={"item": "scalpel", "alias": "hemostat"}).json()
        assert not r["ok"] and r["say"] == "Hemostat already means the hemostat.", r
        r = client.post("/alias", json={"item": "hex_key", "alias": "allen"}).json()
        assert not r["ok"] and r["say"] == lines.NOT_IN_SETTING
        r = client.post("/alias", json={"item": "hemostat", "alias": " the "}).json()
        assert not r["ok"] and r["say"] == lines.BAD_ALIAS
        assert not (d / "surgical.local.json").exists()
        r = client.post("/alias", json={"item": "hemostat", "alias": "kelly"}).json()  # already its word: ok, no write
        assert r["ok"] and not (d / "surgical.local.json").exists()


@test
def unknown_hints_at_teaching():
    ctl, arm = make()
    r = ctl.submit({"action": "unknown", "heard": "hand me the bovie"})
    # Not "a kelly": that word already works. The hint is a word this tray doesn't have yet.
    assert not r["accepted"] and r["say"] == "Which instrument? You can say: call the hemostat a crile.", r
    assert ctl.history[-1]["say"] == r["say"]
    import copy
    ctl.setting = copy.deepcopy(ctl.setting)  # never touch a shared settings dict
    ctl.setting["items"][1]["aliases"].append("crile")  # taught since: the next example word
    assert ctl._unknown_line() == "Which instrument? You can say: call the hemostat a grabber."


@test
def plural_names_read_right():
    assert lines.returned("hemostat") == "Hemostat back in its slot."
    assert lines.returned("mayo scissors") == "Mayo scissors back in their slot."
    assert lines.returned("wire cutters") == "Wire cutters back in their slot."
    assert lines.no_hand("needle-nose pliers") == "No hand. Needle-nose pliers are at the safe spot."


def errors(ctl, start=0):
    return [e for e in list(ctl.history)[start:] if e["type"] == "error"]


@test
def prepare_opens_sessions_at_start_and_on_setting_change():
    ctl, arm = make()
    surgical = [s for i in ctl.setting["items"] for s in (i["pick_instruction"], i["return_instruction"])]
    assert wait_for(lambda: ctl.prepared == "surgical") and arm.prepared == surgical, arm.prepared
    ctl.set_setting("bench")
    assert wait_for(lambda: ctl.prepared == "bench")
    assert arm.prepared == [s for i in ctl.setting["items"] for s in (i["pick_instruction"], i["return_instruction"])]
    assert not errors(ctl)


@test
def prepare_api_error_speaks_once_per_setting_change():
    ctl, arm = make()
    assert wait_for(lambda: ctl.prepared == "surgical")
    tries = []

    def down(instructions):
        tries.append(1)
        raise type("APIError", (RuntimeError,), {})("Perceptron HTTP 503")
    arm.prepare = down
    start = len(ctl.history)
    ctl.set_setting("bench")
    assert wait_for(lambda: len(tries) == core.PREPARE_TRIES) and time.sleep(0.3) is None
    errs = errors(ctl, start)
    assert len(errs) == 1 and errs[0]["code"] == 503 and errs[0]["say"] == lines.API_DOWN, errs
    assert errs[0]["command_id"] is None and ctl.step == "idle" and ctl.prepared == "surgical"
    assert run(ctl, {"action": "handover", "item": "hex_key"})[0]["accepted"]  # skills still open sessions on demand


@test
def prepare_busy_retries_then_works():
    from fastapi.testclient import TestClient
    from .server import make_app
    ctl, arm = make()
    client = TestClient(make_app(ctl))
    assert wait_for(lambda: ctl.prepared == "surgical")
    assert client.post("/fake/force", json={"api_error": 409}).json()["force"]["api_error"] == 409
    start = len(ctl.history)
    assert client.post("/setting", json={"setting": "bench"}).status_code == 200
    assert wait_for(lambda: ctl.prepared == "bench")
    errs = errors(ctl, start)
    assert len(errs) == 1 and errs[0]["code"] == 409 and errs[0]["say"] == lines.API_BUSY, errs


@test
def prepare_never_blocks_stop_or_the_setting_change():
    ctl, arm = make()
    assert wait_for(lambda: ctl.prepared == "surgical")
    gate = threading.Event()
    arm.prepare = lambda instructions: gate.wait(5)
    t0 = time.time()
    ctl.set_setting("bench")
    ctl.stop()
    assert time.time() - t0 < 0.2 and ctl.step == "stopped" and arm._frozen.is_set()
    gate.set()


@test
def prepare_cancelled_by_a_stop_is_silent_and_retried_after_reset():
    ctl, arm = make()
    assert wait_for(lambda: ctl.prepared == "surgical")
    ctl.stop()
    start = len(ctl.history)
    ctl.set_setting("bench")  # the fake arm, like the real one, refuses to prepare while frozen
    time.sleep(0.2)
    assert ctl.prepared == "surgical" and not errors(ctl, start)
    reset(ctl)
    assert wait_for(lambda: ctl.prepared == "bench") and not errors(ctl, start)


@test
def skill_api_errors_say_why_and_hold():
    for code, line in ((401, lines.API_KEY_REFUSED), (409, lines.API_BUSY), (503, lines.API_DOWN)):
        ctl, arm = make()
        assert wait_for(lambda: ctl.prepared == "surgical")
        arm.force["api_error"] = code
        _, evs = run(ctl, HANDOVER)
        err = [e for e in evs if e["type"] == "error"]
        assert ctl.step == "error" and arm._frozen.is_set() and len(err) == 1, types(evs)
        assert err[0]["code"] == code and err[0]["say"] == lines.api_failed(code) and err[0]["say"].startswith(line)
        assert "503" in err[0]["reason"] or code != 503
        assert ctl.submit(dict(HANDOVER))["say"] == lines.NEEDS_RESET


@test
def judge_mode_takes_only_handover_count_stop_got_it():
    from fastapi.testclient import TestClient
    from .server import make_app
    with scratch_settings() as d:
        ctl, arm = make(pull_s=0)
        client = TestClient(make_app(ctl))
        assert client.get("/state").json()["judge"] is False
        r = client.post("/judge", json={"on": True}).json()
        assert r == {"ok": True, "judge": True} and ctl.history[-1]["judge"] is True
        assert client.get("/state").json()["judge"] is True
        for action in ("return", "unknown", "dance"):
            r = client.post("/command", json={"action": action, "source": "voice"}).json()
            assert not r["accepted"] and r["reason"] == "judge mode" and r["say"] == lines.JUDGE_ONLY, r
            assert ctl.history[-1]["type"] == "command" and ctl.history[-1]["reason"] == "judge mode"
        r = client.post("/alias", json={"item": "hemostat", "alias": "snap"}).json()
        assert not r["ok"] and r["reason"] == "judge mode" and r["say"] == lines.JUDGE_ONLY
        assert not (d / "surgical.local.json").exists()
        assert client.post("/command", json={"action": "handover", "item": "hemostat"}).json()["accepted"]
        assert wait_for(lambda: ctl.step == "waiting_for_pull")
        assert client.post("/command", json={"action": "count"}).json()["accepted"]
        assert client.post("/command", json={"action": "got_it"}).json()["accepted"]
        assert wait_for(lambda: ctl.step == "idle" and ctl.out == ["hemostat"])
        assert client.post("/lighting", json={"lighting": "bright"}).json()["ok"]  # operator endpoints stay open
        assert client.post("/setting", json={"setting": "bench"}).status_code == 200
        assert client.post("/command", json={"action": "stop"}).json()["accepted"] and ctl.step == "stopped"
        assert client.post("/reset", json={"clear_count": True}).json()["ok"]
        assert wait_for(lambda: ctl.step == "idle")
        client.post("/judge", json={"on": False})
        assert client.post("/alias", json={"item": "hex_key", "alias": "allen"}).json()["ok"]  # its word already
        assert client.post("/command", json={"action": "unknown"}).json()["reason"] == "unknown command"


@test
def judge_flag_starts_in_judge_mode():
    ctl = Controller(RecordingArm(motion_s=0.1), fake_arm=True, judge=True)
    assert ctl.state()["judge"] and ctl.submit({"action": "return"})["reason"] == "judge mode"


@test
def stop_never_lets_a_queued_job_run():
    """A slow freeze must not open a gap where the worker pops the next queued job under the new gen."""
    ctl, arm = make()
    skills = []
    orig_skill, orig_freeze = arm.run_skill, arm.freeze

    def run_skill(instruction, max_s=20.0, source="model"):
        skills.append(instruction)
        return orig_skill(instruction, max_s, source)

    def slow_freeze():
        orig_freeze()
        time.sleep(0.3)
    arm.run_skill, arm.freeze = run_skill, slow_freeze
    arm.scale = 1.0
    ctl.submit(dict(HANDOVER))
    ctl.submit({"action": "handover", "item": "mayo_scissors"})
    assert wait_for(lambda: ctl.step == "picking")
    ctl.stop()
    n = len(ctl.history)
    time.sleep(0.5)
    later = [e for e in list(ctl.history)[n:] if e["type"] != "command"]
    assert ctl.step == "stopped" and later == [] and skills == ["pick the hemostat"], (ctl.step, later, skills)


@test
def setting_change_never_clears_a_stop():
    ctl, arm = stop_at("moving_to_hand")
    ctl.set_setting("bench")
    assert ctl.step == "stopped" and arm._frozen.is_set()
    r = ctl.submit({"action": "handover", "item": "hex_key"})
    assert not r["accepted"] and r["say"] == lines.NEEDS_RESET, r
    evs = reset(ctl)
    assert ctl.step == "idle" and "setting_down" in steps(evs), steps(evs)  # the held hemostat went to the safe spot


@test
def stop_during_reset_rearm_stays_frozen():
    ctl, arm = stop_at("picking")
    orig = arm.resume

    def resume():
        ctl.stop()  # a stop lands just as the reset starts to rearm
        orig()
    arm.resume = resume
    ctl.reset()
    time.sleep(0.4)
    assert ctl.step == "stopped" and arm._frozen.is_set(), (ctl.step, arm._frozen.is_set())


@test
def bad_hand_target_is_never_a_move():
    ctl, arm = make()
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            ctl.post_hand({"seen": True, "open": True, "palm_px": [300, 200], "target": [float("nan"), -0.1, 0.18],
                           "path_clear": True, "t": time.time()})
            time.sleep(0.05)
    threading.Thread(target=loop, daemon=True).start()
    _, evs = run(ctl, HANDOVER)
    stop.set()
    assert arm.moves == [] and says(evs)[-1] == lines.no_hand("hemostat"), (arm.moves, says(evs))


@test
def events_say_fake_arm():
    ctl, _ = make()
    _, evs = run(ctl, HANDOVER)
    assert evs and all(e["fake_arm"] is True for e in evs), [e.get("fake_arm") for e in evs]
    real = Controller(RecordingArm(motion_s=0.1), fake_arm=False)
    assert real.emit("step")["fake_arm"] is False
    assert evs[-1]["arm"] == "fake" and evs[-1]["sim"] is False and ctl.state()["arm"] == "fake"
    assert real.emit("step")["arm"] == "real" and real.state()["sim"] is False


@test
def sim_arm_reports_sim_and_stays_out_of_real_numbers():
    sim = Controller(RecordingArm(motion_s=0.1), fake_arm=True, arm_kind="sim")
    st, ev = sim.state(), sim.emit("step")
    assert (st["fake_arm"], st["arm"], st["sim"]) == (True, "sim", True), st
    assert (ev["fake_arm"], ev["arm"], ev["sim"]) == (True, "sim", True), ev


@test
def tray_switch_keeps_what_is_still_out():
    ctl, arm = make()
    run(ctl, HANDOVER)
    assert ctl.out == ["hemostat"]
    ctl.set_setting("bench")
    assert ctl.out == ["hemostat"] and ctl.state()["out"] == ["hemostat"]  # never dropped by a switch
    reply, _ = run(ctl, {"action": "count"})
    assert reply["say"] == "Out: hemostat.", reply
    r = ctl.submit({"action": "return"})  # nothing from the bench tray is out
    assert not r["accepted"] and r["say"] == lines.NOTHING_OUT, r
    ctl.reset(clear_count=True)
    assert wait_for(lambda: ctl.out == [] and ctl.step == "idle" and ctl.cmd is None), (ctl.out, ctl.step)


@test
def stats_without_the_ledger_has_the_ledger_shape():
    ctl, _ = make()
    run(ctl, HANDOVER)
    saved, core.ledger = core.ledger, None
    try:
        st = ctl.stats()
    finally:
        core.ledger = saved
    row = st["by_item"][0]
    assert isinstance(st["by_item"], list) and st["by_lighting"] == [] and st["out"] == ["hemostat"], st
    assert (row["item"], row["attempts"], row["successes"], row["success_rate"]) == ("hemostat", 1, 1, 1.0), row
    assert row["median_request_to_hand_s"] and st["median_request_to_hand_s"] == row["median_request_to_hand_s"]


@test
def restocks_say_fake_arm():
    ctl, _ = make()
    logged = []

    class Ledger:
        log = staticmethod(logged.append)
    saved, core.ledger = core.ledger, Ledger
    try:
        assert ctl.log_restock({"item": "hemostat", "qty": 2})
        assert wait_for(lambda: logged)
    finally:
        core.ledger = saved
    assert logged[0]["type"] == "restock" and logged[0]["fake_arm"] is True, logged


@test
def a_closed_page_never_breaks_events():
    import asyncio
    ctl, _ = make()
    dead = asyncio.new_event_loop()
    dead.close()
    ctl.listeners.append((dead, asyncio.Queue()))
    _, evs = run(ctl, HANDOVER)
    assert "released" in types(evs) and ctl.step == "idle", types(evs)


@test
def collapse_releases_at_the_hand():
    """Release on pull: the grip load falls toward zero (under the pull delta) and the gripper opens."""
    ctl, arm = make()
    arm.force["collapse"] = 1
    _, evs = run(ctl, HANDOVER)
    rel = [e for e in evs if e["type"] == "released"]
    assert rel and rel[0]["release"] == "collapse" and ctl.out == ["hemostat"], types(evs)


@test
def release_says_why():
    ctl, arm = make()
    _, evs = run(ctl, HANDOVER)
    assert next(e for e in evs if e["type"] == "released")["release"] == "pull"
    old, core.PULL_COLLAPSE = core.PULL_COLLAPSE, 0.0  # collapse off: a drop under the delta is no pull
    try:
        ctl, arm = make()
        arm.force["collapse"] = 1
        _, evs = run(ctl, HANDOVER)
        assert types(evs) == ["command", "picked", "handed", "set_down"], types(evs)
    finally:
        core.PULL_COLLAPSE = old


@test
def collapse_ignores_noise_near_zero():
    """No grip to speak of (held load under the delta): a reading near zero is not a collapse."""
    ctl, arm = make(pull_s=None)
    arm.gripper_load = lambda: 20.0 if ctl.step != "waiting_for_pull" else 2.0
    _, evs = run(ctl, HANDOVER)
    assert "set_down" in types(evs) and "released" not in types(evs), types(evs)


class Taught:
    """Stands in for arm/taught.py's available()."""
    def __init__(self, have):
        self.have, self.saved = have, None

    def __enter__(self):
        self.saved, core._taught_available = core._taught_available, lambda sid: self.have
        return self

    def __exit__(self, *_):
        core._taught_available = self.saved


def sources(evs):
    return {e["type"]: e.get("skill_source") for e in evs if e["type"] != "step"}


@test
def model_skills_by_default_on_every_pick_event():
    ctl, arm = make()
    _, evs = run(ctl, HANDOVER)
    src = sources(evs)
    assert src["picked"] == src["handed"] == src["released"] == "model", src
    assert any(e["step"] == "picking" and e.get("skill_source") == "model" for e in evs)
    assert "skill_source" not in next(e for e in evs if e["type"] == "command")
    assert arm.last_source == "model" and ctl.state()["skills"] == {
        "mode": "model", "items": {i["id"]: "model" for i in ctl.setting["items"]}}
    _, evs = run(ctl, {"action": "return", "item": "hemostat"})
    assert sources(evs)["returned"] == "model", sources(evs)


@test
def taught_skills_play_taught_or_refuse():
    with Taught({"hemostat": {"pick", "return"}}):
        ctl = Controller(RecordingArm(motion_s=0.1, auto_pull_s=0.2), fake_arm=True, skills="taught")
        _, evs = run(ctl, HANDOVER)
        assert sources(evs)["released"] == "taught" and ctl.arm.last_source == "taught", sources(evs)
        reply = ctl.submit({"action": "handover", "item": "mayo_scissors"})
        assert not reply["accepted"] and reply["say"] == lines.no_taught(settings.item(ctl.setting, "mayo_scissors")["name"]), reply
        assert ctl.state()["skills"]["items"]["mayo_scissors"] is None


@test
def auto_skills_model_once_proven():
    tmp = Path(tempfile.mkdtemp())
    try:
        with Taught({"hemostat": {"pick", "return"}}):
            ctl = Controller(RecordingArm(motion_s=0.1), fake_arm=True, skills="auto", tries_file=tmp / "t.json")
            assert ctl.state()["skills"]["items"]["hemostat"] == "taught"  # taught recorded, model unproven
            assert ctl.state()["skills"]["items"]["mayo_scissors"] == "model"  # nothing taught: the model
            ok = [{"direction": "pick", "source": "model", "ok": True, "t": 1}] * 3
            (tmp / "t.json").write_text(json.dumps({"surgical/hemostat": ok}))
            ctl = Controller(RecordingArm(motion_s=0.1, auto_pull_s=0.2), fake_arm=True, skills="auto",
                             tries_file=tmp / "t.json")
            _, evs = run(ctl, HANDOVER)
            assert sources(evs)["released"] == "model", sources(evs)
            no_dep = Controller(RecordingArm(motion_s=0.1), fake_arm=True, skills="auto", deployment=False,
                                tries_file=tmp / "t.json")
            assert no_dep.state()["skills"]["items"]["hemostat"] == "taught"
            bad = ok[:2] + [{"direction": "pick", "source": "model", "ok": False, "t": 2}]
            (tmp / "t.json").write_text(json.dumps({"surgical/hemostat": bad}))
            ctl = Controller(RecordingArm(motion_s=0.1), fake_arm=True, skills="auto", tries_file=tmp / "t.json")
            assert ctl.state()["skills"]["items"]["hemostat"] == "taught"
    finally:
        shutil.rmtree(tmp)


@test
def real_tries_are_recorded_fake_ones_are_not():
    tmp = Path(tempfile.mkdtemp())
    try:
        ctl = Controller(RecordingArm(motion_s=0.1, auto_pull_s=0.2), fake_arm=False, tries_file=tmp / "t.json")
        run(ctl, HANDOVER)
        assert wait_for(lambda: (tmp / "t.json").exists())
        rows = json.loads((tmp / "t.json").read_text())["surgical/hemostat"]
        assert rows[-1]["ok"] and rows[-1]["source"] == "model" and rows[-1]["direction"] == "pick", rows
        ctl = Controller(RecordingArm(motion_s=0.1, auto_pull_s=0.2), fake_arm=True, tries_file=tmp / "f.json")
        run(ctl, HANDOVER)
        assert not (tmp / "f.json").exists()
    finally:
        shutil.rmtree(tmp)


@test
def state_has_telemetry_and_latency():
    old, core.TELEMETRY_S = core.TELEMETRY_S, 0.05
    try:
        ctl, arm = make()
        run(ctl, HANDOVER)
        assert wait_for(lambda: ctl.state()["arm_telemetry"] is not None)
        st = ctl.state()
        tel, lat = st["arm_telemetry"], st["latency_ms"]
        assert set(tel) >= {"temps", "loads", "hottest", "cooling", "t"} and len(tel["temps"]) == 6, tel
        assert lat["skill"] and lat["skill"] >= 50 and lat["skill_p50"] and lat["skill_n"] == 1, lat
    finally:
        core.TELEMETRY_S = old
    arm = FakeArm()
    cool = arm.telemetry()["hottest"]
    arm._busy, arm._heat_t = 1, arm._heat_t - 10  # ten seconds of moving
    hot = arm.telemetry()
    assert hot["hottest"] > cool and not hot["cooling"], (cool, hot)


@test
def thermal_fault_says_why_and_holds():
    ctl, arm = make()
    arm.force["hot"] = 1
    _, evs = run(ctl, HANDOVER)
    err = [e for e in evs if e["type"] == "error"]
    assert ctl.step == "error" and arm._frozen.is_set(), ctl.step
    assert err and err[-1]["say"] == "Too hot: shoulder_lift 71 C. Cooling down.", says(evs)
    assert not ctl.submit(dict(HANDOVER))["accepted"]  # holds until a reset


@test
def ops_page_and_design_are_served():
    from fastapi.testclient import TestClient
    from . import server
    ctl, _ = make()
    client = TestClient(server.make_app(ctl))
    r = client.get("/ops")
    assert r.status_code == 200 and "<" in r.text
    assert "renderReads" in r.text and 'id="packs"' in r.text  # the Reads panel
    assert client.get("/design/scrub.css").status_code == 200
    st = client.get("/state").json()
    assert {"skills", "latency_ms", "arm_telemetry"} <= set(st), st
    nurse = client.get("/nurse").text  # its tray-age limit follows TRAY_STALE_S
    assert nurse.count(f"tray_age_s>{core.TRAY_STALE_S:g}") == 2 and "tray_age_s>3" not in nurse


class fake_reader:
    """A tiny vision answering POST /read/<kind> from `answers[kind]` (a dict, or None for a 404), after `delay` s.
    Points VISION_URL at it; on exit shuts it down and puts VISION_URL back. `bodies` keeps each request body."""
    def __init__(self, **answers):
        self.answers, self.delay, self.bodies = answers, 0.0, []

    def __enter__(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        outer = self

        class Vision(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("content-length") or 0)
                outer.bodies.append((self.path, json.loads(self.rfile.read(n) or b"{}")))
                time.sleep(outer.delay)
                ans = outer.answers.get(self.path.rsplit("/", 1)[-1])
                self.send_response(200 if ans is not None else 404)
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(ans if ans is not None else {"detail": "Not Found"}).encode())

            def log_message(self, *a):
                pass
        self.server = HTTPServer(("127.0.0.1", 0), Vision)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.old = os.environ.get("VISION_URL")
        os.environ["VISION_URL"] = f"http://127.0.0.1:{self.server.server_port}"
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        if self.old is None:
            os.environ.pop("VISION_URL", None)
        else:
            os.environ["VISION_URL"] = self.old


def sheet(rows, tray="surgical"):
    """A vision count_sheet answer. rows: {item: (expected, initial, closing)}."""
    return {"ok": True, "method": "perceptron", "latency_ms": 1800, "error": None, "tray": tray, "setting": "surgical",
            "items": [{"item": i, "name": i, "expected": e, "initial": a, "closing": c} for i, (e, a, c) in rows.items()]}


def read_event(ctl, cmd, timeout=5.0):
    """Submit a read_* command; (reply, the read event it caused or None)."""
    reply = ctl.submit(dict(cmd))
    cid = cmd.get("id") or next(e["command_id"] for e in reversed(ctl.history) if e["type"] == "command")
    got = lambda: next((e for e in list(ctl.history) if e["type"] == "read" and e["command_id"] == cid), None)  # noqa: E731
    wait_for(got, timeout)
    return reply, got()


@test
def read_sheet_initial_counts_against_expected():
    ctl, _ = make()
    rows = {"scalpel": (1, 1, None), "hemostat": (2, 1, None), "mayo_scissors": (1, 1, None)}
    with fake_reader(count_sheet=sheet(rows)) as v:
        reply, ev = read_event(ctl, {"action": "read_sheet", "source": "voice"})
    assert reply["accepted"] and reply["say"] == "Reading the count sheet.", reply
    assert v.bodies == [("/read/count_sheet", {"source": "overhead", "setting": "surgical"})], v.bodies
    assert ev["say"] == "Sheet says 1 hemostat at the start, 2 expected.", ev["say"]
    r = ev["read"]
    assert r["kind"] == "count_sheet" and r["ok"] and r["method"] == "perceptron" and r["latency_ms"] == 1800, r
    assert r["compare"] == "initial" and r["mismatch"] == [{"item": "hemostat", "sheet": 1, "expected": 2}], r
    st = ctl.state()["sheet"]
    assert st["tray"] == "surgical" and st["method"] == "perceptron" and st["t"], st
    assert st["items"]["hemostat"] == {"expected": 2, "initial": 1, "closing": None}, st
    rows["hemostat"] = (2, 2, None)
    with fake_reader(count_sheet=sheet(rows)):
        _, ev = read_event(ctl, {"action": "read_sheet"})
    assert ev["say"] == lines.SHEET_MATCHES and ev["read"]["mismatch"] == [], ev
    with fake_reader(count_sheet=sheet({"scalpel": (1, None, None)})):
        _, ev = read_event(ctl, {"action": "read_sheet"})
    assert ev["say"] == lines.SHEET_NO_COUNTS and ev["read"]["compare"] is None, ev


@test
def read_sheet_closing_counts_against_what_is_out():
    ctl, _ = make()
    ctl.out = ["hemostat"]  # Scrub's on-tray hemostats: 1 expected - 1 out = 0
    rows = {"scalpel": (1, 1, 1), "hemostat": (1, 1, 1), "mayo_scissors": (1, 1, 1)}
    with fake_reader(count_sheet=sheet(rows)):
        _, ev = read_event(ctl, {"action": "read_sheet"})
    assert ev["say"] == "Sheet says 1 hemostat back, I count 0.", ev["say"]
    assert ev["read"]["compare"] == "closing" and ev["read"]["mismatch"] == [{"item": "hemostat", "sheet": 1, "scrub": 0}]
    ctl.out = []
    rows = {"scalpel": (1, 1, 1), "hemostat": (1, 1, 0), "mayo_scissors": (2, 2, 2)}  # the spec's example line
    with fake_reader(count_sheet=sheet(rows)):
        _, ev = read_event(ctl, {"action": "read_sheet"})
    assert ev["say"] == "Sheet says 0 hemostats back, I count 1.", ev["say"]
    # the count adds sheet_mismatch and names it
    _, evs = run(ctl, {"action": "count"})
    c = next(e for e in evs if e["type"] == "count")
    assert c["sheet_mismatch"] == [{"item": "hemostat", "sheet": 0, "scrub": 1}], c
    assert c["say"] == "Everything's on the tray. Sheet disagrees on the hemostat.", c["say"]
    ctl.out = ["hemostat"]
    _, evs = run(ctl, {"action": "count"})
    c = next(e for e in evs if e["type"] == "count")
    assert c["sheet_mismatch"] == [] and c["say"] == "Out: hemostat.", c


@test
def count_has_no_sheet_mismatch_without_closing_counts():
    ctl, _ = make()
    _, evs = run(ctl, {"action": "count"})
    assert "sheet_mismatch" not in next(e for e in evs if e["type"] == "count")
    with fake_reader(count_sheet=sheet({"hemostat": (1, 1, None)})):
        read_event(ctl, {"action": "read_sheet"})
    _, evs = run(ctl, {"action": "count"})
    assert "sheet_mismatch" not in next(e for e in evs if e["type"] == "count")


@test
def read_sheet_for_another_tray_says_so_and_a_new_case_clears_it():
    with scratch_settings():
        ctl, _ = make()
        with fake_reader(count_sheet=sheet({"hemostat": (1, 1, None)}, tray="bench")):
            _, ev = read_event(ctl, {"action": "read_sheet"})
        assert ev["say"] == "This sheet is for the robotics bench tray, not the operating room tray. Sheet matches my count.", ev["say"]
        assert ctl.state()["sheet"]
        ctl.set_setting("bench")
        assert ctl.state()["sheet"] is None and ctl.state()["packs"] == []


@test
def read_tray_switches_when_idle_or_stopped():
    with scratch_settings():
        ctl, _ = make()
        tag = {"ok": True, "method": "qr", "latency_ms": 12, "error": None, "tray": "bench", "text": "scrub:tray:bench"}
        with fake_reader(tray_tag=tag):
            case = ctl.case_id
            reply, ev = read_event(ctl, {"action": "read_tray"})
            assert reply["say"] == "Reading the tray tag."
            assert ev["say"] == "This is the robotics bench tray. Switched.", ev["say"]
            assert ev["read"]["switched"] and ev["read"]["method"] == "qr" and ctl.setting["id"] == "bench", ev
            assert ev["setting"] == "bench" and ev["case_id"].startswith("bench-") and case.startswith("surgical-"), ev
            _, ev = read_event(ctl, {"action": "read_tray"})
            assert ev["say"] == "This is the robotics bench tray." and not ev["read"]["switched"], ev
            ctl.set_setting("surgical")
            ctl.stop()
            _, ev = read_event(ctl, {"action": "read_tray"})
            assert ev["say"] == "This is the robotics bench tray. Switched." and ctl.step == "stopped", ev


@test
def read_tray_busy_and_unknown():
    with scratch_settings():
        ctl, _ = make()
        tag = {"ok": True, "method": "perceptron", "latency_ms": 900, "error": None, "tray": "bench", "text": "BENCH"}
        with fake_reader(tray_tag=tag):
            with ctl.lock:
                ctl.step = "moving_to_hand"
            _, ev = read_event(ctl, {"action": "read_tray"})
            with ctl.lock:
                ctl.step = "idle"
        assert ev["say"] == "This is the robotics bench tray. I can't switch while I'm busy.", ev["say"]
        assert ctl.setting["id"] == "surgical" and not ev["read"]["switched"]
        for bad in ({"ok": False, "method": None, "latency_ms": 3000, "error": "no known tray", "tray": None},
                    {"ok": True, "method": "gemini", "latency_ms": 10, "tray": "operating_theatre"}):
            with fake_reader(tray_tag=bad):
                _, ev = read_event(ctl, {"action": "read_tray"})
            assert ev["say"] == "I can't read the tray tag." and ctl.setting["id"] == "surgical", ev


@test
def read_pack_says_expiry_and_warns_when_expired():
    ctl, _ = make()
    labels = {"ok": True, "method": "perceptron", "latency_ms": 2100, "error": None, "expired": True, "today": "2026-10-18",
              "labels": [{"item": "hemostat", "item_text": "Kelly hemostat", "lot": "L-4471", "expires": "2027-04-30", "expired": False},
                         {"item": "mayo_scissors", "item_text": "Mayo scissors", "lot": "L-0930", "expires": "2026-09-30", "expired": True},
                         {"item": None, "item_text": "Army-Navy retractor", "lot": None, "expires": None, "expired": False}]}
    with fake_reader(pack_label=labels):
        reply, ev = read_event(ctl, {"action": "read_pack"})
    assert reply["say"] == "Reading the pack label."
    assert ev["say"] == ("Hemostat pack, expires 2027-04-30. Expired: mayo scissors pack, 2026-09-30. Don't open it. "
                         "Army-Navy retractor pack, no expiry date."), ev["say"]
    assert ctl.state()["packs"] == [{"item": "hemostat", "lot": "L-4471", "expires": "2027-04-30", "expired": False},
                                    {"item": "mayo_scissors", "lot": "L-0930", "expires": "2026-09-30", "expired": True},
                                    {"item": None, "lot": None, "expires": None, "expired": False}], ctl.state()["packs"]
    assert ev["read"]["kind"] == "pack_label" and ev["read"]["latency_ms"] == 2100


@test
def reads_with_vision_down_or_failing():
    ctl, _ = make()
    with fake_reader(count_sheet={"ok": False, "method": None, "latency_ms": 9000, "error": "perceptron: timeout"}):
        _, ev = read_event(ctl, {"action": "read_sheet"})
    assert ev["say"] == lines.CANT_READ_SHEET and not ev["read"]["ok"] and ctl.state()["sheet"] is None, ev
    with fake_reader() as v:  # every reader 404s, then vision is gone
        _, ev = read_event(ctl, {"action": "read_pack"})
        assert ev["say"] == lines.CANT_READ_PACK and ev["read"]["error"] == "vision unreachable", ev
    _, ev = read_event(ctl, {"action": "read_tray"})
    assert ev["say"] == lines.CANT_READ_TAG and ev["read"] == {**ev["read"], "kind": "tray_tag", "ok": False, "method": None}, ev
    with fake_reader(count_sheet={"ok": False, "error": "no overhead frame yet"}):  # vision's 503 body
        _, ev = read_event(ctl, {"action": "read_sheet"})
    assert ev["say"] == lines.CANT_READ_SHEET, ev
    assert v.bodies


@test
def stop_during_a_read_returns_at_once_and_one_read_at_a_time():
    ctl, arm = make()
    with fake_reader(count_sheet=sheet({"hemostat": (1, 1, None)})) as v:
        v.delay = 1.0
        assert ctl.submit({"action": "read_sheet"})["accepted"]
        again = ctl.submit({"action": "read_sheet"})
        assert not again["accepted"] and again["say"] == lines.STILL_READING, again
        t0 = time.time()
        ctl.stop()
        assert time.time() - t0 < 0.2 and ctl.step == "stopped"
        assert wait_for(lambda: any(e["type"] == "read" for e in ctl.history), 4.0)
        assert wait_for(lambda: not ctl._reading)
        assert ctl.submit({"action": "read_sheet"})["accepted"]  # the first one is done


@test
def judge_mode_refuses_reads():
    ctl, _ = make()
    ctl.set_judge(True)
    r = ctl.submit({"action": "read_pack"})
    assert not r["accepted"] and r["say"] == lines.JUDGE_ONLY


@test
def photo_read_result_sets_the_sheet_packs_and_tray():
    from fastapi.testclient import TestClient
    from . import server
    with scratch_settings():
        ctl, _ = make()
        client = TestClient(server.make_app(ctl))
        logged = []

        class Ledger:
            log = staticmethod(logged.append)
        saved, core.ledger = core.ledger, Ledger
        try:
            rows = {"scalpel": (1, 1, 1), "hemostat": (1, 1, 0), "mayo_scissors": (2, 2, 2)}
            r = client.post("/read_result", json={"kind": "count_sheet", "result": sheet(rows), "source": "photo",
                                                  "heard": "count sheet"}).json()
            assert r["ok"] and r["say"] == "Sheet says 0 hemostats back, I count 1.", r
            assert r["read"]["source"] == "photo" and r["read"]["compare"] == "closing" and r["read"]["method"] == "perceptron", r
            assert ctl.state()["sheet"]["items"]["hemostat"]["closing"] == 0
            ev = next(e for e in reversed(ctl.history) if e["type"] == "read")
            assert ev["read"]["source"] == "photo" and ev["command_id"] is None and ev["say"] == r["say"], ev
            assert wait_for(lambda: any(x["type"] == "read" and x["read"].get("source") == "photo" for x in logged))
        finally:
            core.ledger = saved
        _, evs = run(ctl, {"action": "count"})
        c = next(e for e in evs if e["type"] == "count")
        assert c["sheet_mismatch"] == [{"item": "hemostat", "sheet": 0, "scrub": 1}], c

        pack = {"ok": True, "method": "gemini", "latency_ms": 1200, "labels": [
            {"item": "mayo_scissors", "lot": "A12", "expires": "2026-09-30", "expired": True}]}
        r = client.post("/read_result", json={"kind": "pack_label", "result": pack, "source": "photo"}).json()
        assert r["say"] == "Expired: mayo scissors pack, 2026-09-30. Don't open it.", r
        assert ctl.state()["packs"] == [{"item": "mayo_scissors", "lot": "A12", "expires": "2026-09-30", "expired": True}]

        r = client.post("/read_result", json={"kind": "count_sheet", "result": {"ok": False, "error": "blurry"}}).json()
        assert not r["ok"] and r["say"] == lines.CANT_READ_SHEET, r

        tag = {"ok": True, "method": "qr", "latency_ms": 20, "tray": "bench", "text": "scrub:tray:bench"}
        r = client.post("/read_result", json={"kind": "tray_tag", "result": tag, "source": "photo"}).json()
        assert r["say"] == "This is the robotics bench tray. Switched." and r["read"]["switched"], r
        assert ctl.setting["id"] == "bench" and ctl.state()["sheet"] is None

        assert client.post("/read_result", json={"kind": "receipt", "result": tag}).status_code == 400
        ctl.set_judge(True)
        n = len(ctl.history)
        r = client.post("/read_result", json={"kind": "pack_label", "result": pack}).json()
        assert not r["ok"] and r["say"] == lines.JUDGE_ONLY and r["reason"] == "judge mode", r
        assert len(ctl.history) == n and ctl.state()["packs"] == []


@test
def stop_never_waits_on_a_photo_read_result():
    from fastapi.testclient import TestClient
    from . import server
    ctl, _ = make()
    client = TestClient(server.make_app(ctl))
    gate, real = threading.Event(), ctl._read_pack
    ctl._read_pack = lambda read: (gate.wait(3), real(read))[1]
    pack = {"ok": True, "labels": [{"item": "scalpel", "expires": "2027-01-31", "expired": False}]}
    th = threading.Thread(target=lambda: client.post("/read_result", json={"kind": "pack_label", "result": pack}), daemon=True)
    th.start()
    time.sleep(0.1)
    t0 = time.time()
    assert client.post("/stop").json() == {"accepted": True}
    assert time.time() - t0 < 0.5 and ctl.step == "stopped"
    gate.set()
    th.join(3)
    assert ctl.state()["packs"][0]["item"] == "scalpel"


@test
def read_events_and_captions_go_to_the_ledger():
    from fastapi.testclient import TestClient
    from . import server
    ctl, _ = make()
    logged = []

    class Ledger:
        log = staticmethod(logged.append)
    saved, core.ledger = core.ledger, Ledger
    try:
        with fake_reader(pack_label={"ok": True, "method": "gemini", "latency_ms": 5, "labels": [
                {"item": "scalpel", "lot": "1", "expires": "2027-01-31", "expired": False}]}):
            read_event(ctl, {"action": "read_pack"})
        assert wait_for(lambda: any(r["type"] == "read" for r in logged))
        rec = next(r for r in logged if r["type"] == "read")
        assert rec["case_id"] == ctl.case_id and rec["read"]["method"] == "gemini", rec
        client = TestClient(server.make_app(ctl))
        cap = {"case_id": "surgical-1792297259", "event_type": "handed", "item": "hemostat", "t": 1792297260.5,
               "label": "arm holds a hemostat out to a gloved hand, 6.4 s", "label_source": "perceptron", "agrees": True,
               "caption_item": "hemostat", "caption_action": "handed", "caption_latency_ms": 2400,
               "filename": "handed_hemostat_1792297260.mp4"}
        n = len(ctl.history)
        assert client.post("/vision/caption", json=cap).json() == {"ok": True}
        assert wait_for(lambda: any(r["type"] == "caption" for r in logged))
        rec = next(r for r in logged if r["type"] == "caption")
        assert rec == {**rec, **cap, "type": "caption", "fake_arm": True}, rec
        assert len(ctl.history) == n  # not an Event
    finally:
        core.ledger = saved


# ---------- --skills smart and the sharps rules ----------
class StubLocator:
    """Stands in for picker.Locator: locate() gives `loc`; safe_zone() gives `zones` in turn (the last one repeats)."""
    def __init__(self, loc=None, zones=None):
        self.loc, self.zones, self.calls = loc, list(zones or [None]), []

    def locate(self, item_id, timeout_s=2.0):
        self.calls.append(("locate", item_id))
        return self.loc

    def safe_zone(self, timeout_s=2.0):
        self.calls.append(("safe_zone",))
        return self.zones.pop(0) if len(self.zones) > 1 else self.zones[0]


FOUND = {"item": "hemostat", "found": True, "confidence": 0.9, "method": "local", "arm_offset": [0.01, 0.0]}
ROWS = [[]]  # what picker.load_rows() gives the controller's background refresh
if __name__ == "__main__":
    picker.load_rows = lambda: ROWS[0]
else:
    import pytest

    @pytest.fixture(scope="module", autouse=True)
    def _isolate_picker_rows():
        """Do not leave the flow suite's stub installed in the subsequent picker tests."""
        saved = picker.load_rows
        picker.load_rows = lambda: ROWS[0]
        try:
            yield
        finally:
            picker.load_rows = saved


def smart(locator=None, deployment=True, **kw):
    picker._CACHE.clear()
    Path(os.environ["SKILL_POLICY_FILE"]).unlink(missing_ok=True)
    arm = RecordingArm(motion_s=0.1, auto_pull_s=0.2)
    return Controller(arm, fake_arm=True, skills="smart", deployment=deployment,
                      locator=locator or StubLocator(FOUND), **kw), arm


def pick_ev(evs, type_="picked"):
    return next(e for e in evs if e["type"] == type_)


@test
def smart_picks_with_the_default_order():
    with Taught({"hemostat": {"pick", "return"}}):
        ctl, arm = smart()
        _, evs = run(ctl, HANDOVER)
        assert types(evs) == ["command", "picked", "handed", "released"], types(evs)
        p = pick_ev(evs)
        assert (p["skill_source"], p["locate_method"], p["locate_confidence"], p["grasp_check"], p["retry"]) == \
            ("model", "local", 0.9, "gripper", 0), p
        assert pick_ev(evs, "handed")["skill_source"] == "model" and arm.last_located == FOUND
        assert p["arm"] == "fake" and p["test"] is True
        pol = ctl.state()["skills"]
        assert pol["mode"] == "smart" and pol["items"]["hemostat"] == "model", pol
        assert pol["policy"]["hemostat"]["order"] == ["model", "taught_adjusted", "ik"], pol["policy"]
        assert pol["policy"]["mayo_scissors"]["order"] == ["model", "ik"]  # nothing taught for it
        assert pol["policy"]["hemostat"]["why"] == "no real tries yet: default order"


@test
def smart_miss_retries_with_the_next_method():
    with Taught({"hemostat": {"pick", "return"}}):
        ctl, arm = smart(deployment=False)
        arm.fail_sources = {"taught_adjusted"}
        _, evs = run(ctl, HANDOVER)
        assert types(evs) == ["command", "missed", "picked", "handed", "released"], types(evs)
        m, p = pick_ev(evs, "missed"), pick_ev(evs)
        assert (m["skill_source"], m["retry"], m["say"]) == ("taught_adjusted", 0, lines.retry("hemostat")), m
        assert (p["skill_source"], p["retry"], p["retries"]) == ("ik", 1, 1), p
        assert pick_ev(evs, "handed")["skill_source"] == "ik" and ctl.out == ["hemostat"]


@test
def smart_two_misses_say_so_and_log_missed():
    with Taught({"hemostat": {"pick", "return"}}):
        ctl, arm = smart(deployment=False)
        arm.fail_sources = {"taught_adjusted", "ik"}
        _, evs = run(ctl, HANDOVER)
        assert types(evs) == ["command", "missed", "missed"], types(evs)
        last = [e for e in evs if e["type"] == "missed"][-1]
        assert last["say"] == lines.couldnt_pick("hemostat") and last["skill_source"] == "ik" and last["retry"] == 1
        assert ctl.out == [] and ctl.step == "idle" and arm.pose == "home"


class wrist_says:
    """picker.ask_in_gripper answers `answer` (no network)."""
    def __init__(self, answer):
        self.answer, self.saved = answer, None

    def __enter__(self):
        self.saved, picker.ask_in_gripper = picker.ask_in_gripper, lambda jpeg, name, timeout_s=3.0: self.answer
        return self

    def __exit__(self, *_):
        picker.ask_in_gripper = self.saved


@test
def smart_jaw_unknown_and_wrist_no_is_a_miss():
    ctl, arm = smart()
    arm.wrist = b"\xff\xd8jpeg"
    arm.gripper_position = lambda: 0.1  # never closed far enough to say
    with wrist_says(False):
        _, evs = run(ctl, HANDOVER)
    assert types(evs) == ["command", "missed", "missed"], types(evs)
    assert pick_ev(evs, "missed")["grasp_check"] == "wrist"


@test
def smart_jaw_held_and_wrist_no_still_picks_but_says_so():
    ctl, arm = smart()
    arm.wrist = b"\xff\xd8jpeg"
    with wrist_says(False):
        _, evs = run(ctl, HANDOVER)
    p = pick_ev(evs)
    assert "released" in types(evs) and p["wrist_disagrees"] is True and p["grasp_check"] == "gripper+wrist", p
    ctl, arm = smart()
    arm.wrist = b"\xff\xd8jpeg"
    with wrist_says(True):
        _, evs = run(ctl, HANDOVER)
    assert "wrist_disagrees" not in pick_ev(evs) and pick_ev(evs)["grasp_check"] == "gripper+wrist"


@test
def smart_vision_sure_it_is_gone_says_not_on_tray():
    ctl, arm = smart(StubLocator({"item": "hemostat", "found": False, "confidence": 0.8, "method": "perceptron"}))
    _, evs = run(ctl, HANDOVER)
    assert types(evs) == ["command", "missed"] and says(evs)[-1] == lines.not_on_tray("hemostat"), types(evs)
    assert "skill_source" not in pick_ev(evs, "missed") and not hasattr(arm, "last_source")
    ctl, arm = smart(StubLocator(None))  # vision down: pick without a located pose
    _, evs = run(ctl, HANDOVER)
    assert "released" in types(evs) and pick_ev(evs)["locate_method"] is None and arm.last_located is None


def real_rows(src, item, oks, secs=5.0):
    rows = []
    for i, ok in enumerate(oks):
        base = {"item": item, "command_id": f"{src}-{i}", "skill_source": src, "setting": "surgical", "arm": "real",
                "fake_arm": False, "lighting": "normal", "t": float(i)}
        rows += [dict(base, type="picked"), dict(base, type="handed", request_to_hand_s=secs)] if ok \
            else [dict(base, type="missed")]
    return rows


@test
def smart_policy_from_fixed_ledger_rows():
    try:
        ROWS[0] = real_rows("model", "hemostat", [True] * 10) + real_rows("ik", "hemostat", [True] * 9 + [False])
        ctl, arm = smart()
        assert wait_for(lambda: ctl.state()["skills"]["policy"]["hemostat"]["confidence"] > 0), ctl.state()["skills"]
        pol = ctl.state()["skills"]["policy"]["hemostat"]
        assert pol["method"] == "model" and pol["order"][0] == "model" and pol["why"].startswith("model 10/10"), pol
        run(ctl, HANDOVER)
        assert arm.last_source == "model"
        ROWS[0] = real_rows("model", "hemostat", [True] * 4 + [False] * 6) + real_rows("ik", "hemostat", [True] * 10)
        ctl, arm = smart()
        assert wait_for(lambda: ctl.state()["skills"]["policy"]["hemostat"]["method"] == "ik"), ctl.state()["skills"]
        fake = [dict(r, arm="fake") for r in real_rows("model", "mayo_scissors", [False] * 10)]
        ROWS[0] = ROWS[0] + fake  # fake-arm rows never count
        ctl, arm = smart()
        assert wait_for(lambda: ctl.state()["skills"]["policy"]["hemostat"]["method"] == "ik")
        assert ctl.state()["skills"]["policy"]["mayo_scissors"]["method"] == "model"
    finally:
        ROWS[0] = []


@test
def smart_command_method_forces_the_first_try():
    with Taught({"hemostat": {"pick", "return"}}):
        ctl, arm = smart(deployment=False)
        _, evs = run(ctl, dict(HANDOVER, method="ik"))
        assert pick_ev(evs)["skill_source"] == "ik" and pick_ev(evs, "command")["method"] == "ik", evs
        _, evs = run(ctl, {"action": "return", "item": "hemostat", "method": "taught"})
        assert pick_ev(evs, "returned")["skill_source"] == "taught" and arm.last_source == "taught", types(evs)
        reply = ctl.submit(dict(HANDOVER, method="model"))  # no deployment
        assert not reply["accepted"] and reply["reason"] == "method unavailable", reply
        assert not ctl.submit({"action": "handover", "item": "mayo_scissors", "method": "taught"})["accepted"]
        judge, arm = smart(deployment=False, judge=True)
        reply, evs = run(judge, dict(HANDOVER, method="model"))  # a judge never forces a method: ignored
        assert reply["accepted"] and pick_ev(evs)["skill_source"] == "taught_adjusted", reply


SCALPEL = {"action": "handover", "item": "scalpel", "source": "voice", "heard": "hand me the scalpel"}


@test
def scalpel_by_voice_never_goes_to_a_hand():
    ctl, arm = make()
    stop = threading.Event()
    hand_feed(ctl, stop)  # an open hand, ready for it
    try:
        reply, evs = run(ctl, SCALPEL)
    finally:
        stop.set()
    assert reply["accepted"] and reply["say"] == "Scalpel to the safe spot.", reply
    assert arm.moves == [] and "moving_to_hand" not in steps(evs) and "handed" not in types(evs)
    sd = pick_ev(evs, "set_down")
    assert (sd["zone_check"], sd["zone_confirm"]) == ("no_camera", None) and ctl.out == ["scalpel"], sd
    assert ctl.state()["last_zone_check"]["zone_check"] == "no_camera"
    for mode in ("taught", "smart"):  # every mode, the model included above
        with Taught({"scalpel": {"pick", "return"}}):
            c = Controller(RecordingArm(motion_s=0.1), fake_arm=True, skills=mode, locator=StubLocator())
            _, evs = run(c, SCALPEL)
            assert c.arm.moves == [] and pick_ev(evs, "set_down")["zone_check"] == "no_camera", (mode, types(evs))


@test
def reach_hand_refuses_a_held_sharp():
    ctl, arm = make()
    ctl.held = "scalpel"
    assert ctl._reach_hand(ctl.gen, settings.item(ctl.setting, "scalpel")) is False
    assert arm.moves == [] and ctl.held is None and ctl.out == ["scalpel"]
    assert any(e["type"] == "set_down" for e in ctl.history)


@test
def sharp_zone_blocked_then_clears():
    zones = [{"clear": False, "blocked_by": ["hand"], "method": "local"}, {"clear": False, "method": "local"},
             {"clear": True, "method": "local"}, {"clear": True, "item_in_zone": "scalpel", "method": "local"}]
    ctl, arm = make()
    ctl.locator = StubLocator(zones=zones)
    _, evs = run(ctl, SCALPEL)
    sd = pick_ev(evs, "set_down")
    assert lines.CLEAR_ZONE in says(evs) and arm.pose == "home", says(evs)
    assert (sd["zone_check"], sd["zone_confirm"]) == ("cleared_after_wait", True), sd
    run(ctl, {"action": "return", "item": "scalpel"})
    ctl.locator = StubLocator(zones=[{"clear": True, "method": "local"}, {"clear": True, "item_in_zone": None, "method": "local"}])
    _, evs = run(ctl, SCALPEL)
    sd = pick_ev(evs, "set_down")
    assert (sd["zone_check"], sd["zone_confirm"]) == ("clear", False), sd


@test
def sharp_zone_blocked_to_timeout_goes_back_to_its_slot():
    ctl, arm = make()
    ctl.locator = StubLocator(zones=[{"clear": False, "blocked_by": ["hemostat"], "method": "local"}])
    _, evs = run(ctl, SCALPEL, timeout=10)
    assert "set_down" not in types(evs) and types(evs)[-1] == "missed", types(evs)
    m = [e for e in evs if e["type"] == "missed"][-1]
    assert m["zone_check"] == "timeout_to_slot" and m["say"] == lines.zone_blocked_back("scalpel"), m
    assert ctl.out == [] and ctl.held is None and ctl.step == "idle" and arm.pose == "home"
    assert ctl.state()["last_zone_check"]["zone_check"] == "timeout_to_slot"


def target_feed(ctl, stop_evt, target):
    """Hand posts whose target comes from target() (arm frame, m)."""
    def loop():
        while not stop_evt.is_set():
            ctl.post_hand({"seen": True, "open": True, "palm_px": [300, 200], "target": target(), "path_clear": True,
                           "t": time.time()})
            time.sleep(0.05)
    threading.Thread(target=loop, daemon=True).start()


NEAR_ZONE, FAR = [0.17, -0.18, 0.05], [0.30, 0.20, 0.25]


@test
def sharp_hand_in_keepout_waits_then_sets_down():
    ctl, arm = make()
    stop, said = threading.Event(), []

    def target():  # near the zone until 0.3 s after Scrub says "Hand back", then away
        if not said and any(e.get("say") == lines.HAND_BACK for e in list(ctl.history)):
            said.append(time.time())
        return NEAR_ZONE if not said or time.time() - said[0] < 0.3 else FAR
    target_feed(ctl, stop, target)
    try:
        _, evs = run(ctl, SCALPEL)
    finally:
        stop.set()
    assert lines.HAND_BACK in says(evs) and "set_down" in types(evs), says(evs)
    assert arm.sharp_log == [True, False] and arm.sharp is False, arm.sharp_log


@test
def sharp_hand_staying_in_keepout_freezes_the_move():
    ctl, arm = make()
    stop = threading.Event()
    target_feed(ctl, stop, lambda: NEAR_ZONE)
    try:
        _, evs = run(ctl, SCALPEL)
    finally:
        stop.set()
    assert ctl.step == "stopped" and pick_ev(evs, "stopped")["reason"] == "hand_keepout", types(evs)
    assert says(evs)[-1] == lines.HAND_BACK and ctl.out == ["scalpel"] and arm.sharp is False
    assert "set_down" not in types(evs)


@test
def sharp_mode_on_only_while_a_sharp_is_in_the_flow():
    ctl, arm = make()
    run(ctl, HANDOVER)
    assert arm.sharp_log == []
    seen = []
    orig = arm.set_down_safe_spot
    arm.set_down_safe_spot = lambda: seen.append(arm.sharp) or orig()
    run(ctl, SCALPEL)
    assert seen == [True] and arm.sharp_log == [True, False]


class RealishArm(RecordingArm):
    """A fake arm the controller treats as the real one (fake_arm=False), with its own rig."""
    rig = {"handoff_region": {"min": [0.05, -0.25, 0.08], "max": [0.35, 0.25, 0.35]}, "safe_zone": None}


@test
def real_arm_refuses_a_sharp_without_a_good_safe_zone():
    tmp = Path(tempfile.mkdtemp())
    try:
        arm = RealishArm(motion_s=0.1)
        arm.zone = None
        ctl = Controller(arm, fake_arm=False, tries_file=tmp / "t.json", locator=StubLocator())
        assert ctl.state()["safe_zone"]["problems"], ctl.state()["safe_zone"]
        reply, evs = run(ctl, SCALPEL)
        m = pick_ev(evs, "missed")
        assert m["say"] == lines.zone_not_taught("scalpel") and m["reason"].startswith("safe zone"), m
        assert not hasattr(arm, "last_source") and arm.pose == "home" and arm.sharp_log == [] and m["arm"] == "real"
        arm.rig = dict(RealishArm.rig, safe_zone={"center": [0.2, 0.0, 0.0], "size": [0.08, 0.08]})  # in the handoff box
        arm.zone = arm.rig["safe_zone"]
        _, evs = run(ctl, SCALPEL)
        assert pick_ev(evs, "missed")["say"] == lines.zone_too_close("scalpel") and not hasattr(arm, "last_source")
        arm.rig = dict(RealishArm.rig, safe_zone={"center": [0.0, -0.5, 0.0], "size": [0.08, 0.08]})
        arm.zone = arm.rig["safe_zone"]
        assert ctl.state()["safe_zone"] == {"center": [0.0, -0.5, 0.0], "size": [0.08, 0.08], "problems": []}
        _, evs = run(ctl, SCALPEL)
        assert "set_down" in types(evs), types(evs)
        sim_like = Controller(RecordingArm(motion_s=0.1), fake_arm=True, locator=StubLocator())
        sim_like.arm.zone = None
        assert sim_like.state()["safe_zone"]["problems"] == []  # fake and sim: no zone rules
    finally:
        shutil.rmtree(tmp)


def main():
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"pass  {fn.__name__}")
        except Exception as e:  # noqa: BLE001 - one broken test must not hide the rest
            failed += 1
            print(f"FAIL  {fn.__name__}: {e!r}")
    print(f"{len(TESTS) - failed}/{len(TESTS)} passed")
    raise SystemExit(1 if failed else 0)



test.__test__ = False  # the decorator; pytest runs each flow below as test_<name>
for _fn in TESTS:
    globals()[f"test_{_fn.__name__}"] = _fn


if __name__ == "__main__":
    main()
