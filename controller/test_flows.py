"""Forces each failure case on the fake arm. Run: .venv/bin/python -m controller.test_flows"""
import json
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path

from . import core, lines, settings
from .core import Controller
from .fake_arm import FakeArm

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
    assert client.get("/design/scrub.css").status_code == 200
    st = client.get("/state").json()
    assert {"skills", "latency_ms", "arm_telemetry"} <= set(st), st
    nurse = client.get("/nurse").text  # its tray-age limit follows TRAY_STALE_S
    assert nurse.count(f"tray_age_s>{core.TRAY_STALE_S:g}") == 2 and "tray_age_s>3" not in nurse


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


if __name__ == "__main__":
    main()
