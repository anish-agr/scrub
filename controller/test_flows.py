"""Forces each failure case on the fake arm. Run: .venv/bin/python -m controller.test_flows"""
import threading
import time

from . import core, lines
from .core import Controller
from .fake_arm import FakeArm

core.HAND_WAIT_S = 1.0
core.PULL_WAIT_S = 1.0
core.TRAY_LAG_S = 0.05
core.AUTO_RETURN_S = 0.3


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


def hand_feed(ctl, stop_evt, seen=lambda: True, clear=lambda: True):
    def loop():
        while not stop_evt.is_set():
            ctl.post_hand({"seen": seen(), "open": True, "palm_px": [300, 200],
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

    def run_skill(instruction, max_s=20.0):
        ok = orig(instruction, max_s)
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
    assert sd["say"] == "Scalpel down." and sd["request_to_hand_s"] >= 0.15


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


def main():
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"pass  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {fn.__name__}: {e}")
    print(f"{len(TESTS) - failed}/{len(TESTS)} passed")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
