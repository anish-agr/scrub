"""Forces each failure case on the fake arm. Run: .venv/bin/python -m controller.test_flows"""
import threading
import time

from . import core, lines
from .core import Controller
from .fake_arm import FakeArm

core.HAND_WAIT_S = 1.0
core.PULL_WAIT_S = 1.0


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
    tray(ctl, "hemostat", True)  # slot still full after the pick: the grasp failed
    _, evs = run(ctl, HANDOVER)
    assert says(evs)[-1] == lines.couldnt_pick("hemostat"), says(evs)


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
def tracking_on_but_no_hand():
    ctl, arm = make()
    stop = threading.Event()
    hand_feed(ctl, stop, seen=lambda: False)
    _, evs = run(ctl, HANDOVER)
    stop.set()
    assert lines.SHOW_HAND in says(evs) and says(evs)[-1] == lines.no_hand("hemostat"), says(evs)
    assert arm.moves == []


@test
def hand_lost_mid_move_freezes_then_retries():
    ctl, arm = make()
    stop = threading.Event()
    lost_until = [0.0]
    hand_feed(ctl, stop, seen=lambda: time.time() > lost_until[0])
    arm.moves.clear()
    orig = arm.move_to

    def move_and_lose(*a, **kw):  # the hand vanishes during the first move only
        if len(arm.moves) == 0:
            lost_until[0] = time.time() + 0.4  # well inside HAND_WAIT_S
        return orig(*a, **kw)
    arm.move_to = move_and_lose
    t0 = time.time()
    _, evs = run(ctl, HANDOVER)
    stop.set()
    assert lines.HAND_LOST in says(evs), says(evs)
    assert "released" in types(evs), types(evs)
    assert time.time() - t0 < 6


@test
def path_blocked_freezes():
    ctl, arm = make()
    stop = threading.Event()
    hand_feed(ctl, stop, clear=lambda: len(arm.moves) == 0)  # blocks once the arm starts moving
    _, evs = run(ctl, HANDOVER)
    stop.set()
    assert lines.HAND_LOST in says(evs) and says(evs)[-1] == lines.no_hand("hemostat"), says(evs)


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
    _, evs = run(ctl, {"action": "handover", "item": "mayo_scissors"})  # works again after stop
    assert "released" in types(evs)


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
def reset_clears_stop_and_count():
    ctl, arm = make()
    run(ctl, HANDOVER)
    ctl.stop()
    ctl.reset()
    end = time.time() + 5
    while ctl.step != "idle" and time.time() < end:
        time.sleep(0.02)
    assert ctl.step == "idle" and ctl.out == [] and arm.pose == "home"
    assert ctl.history[-1]["say"] == lines.RESET and ctl.history[-1]["out"] == []


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
