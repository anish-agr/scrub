"""Which-one safety/API tests on the fake arm; no hardware, keys, or network."""
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from controller import core, picker
from controller.fake_arm import FakeArm
from controller.server import make_app
from vision import instances
from vision.tray import tray_from_detections


ROWS = [{"item": "hemostat", "present": True, "box": [20, 20, 80, 50]},
        {"item": "hemostat", "present": True, "box": [220, 60, 280, 90]}]


def wait_for(check, seconds=3):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.01)
    return False


class Locator:
    def __init__(self, rows=None):
        self.rows, self.calls = rows, []

    def locate(self, item, timeout_s=2, instance=None):
        self.calls.append((item, instance))
        if self.rows is None:
            return None
        options, unsafe = instances.candidates(self.rows, item)
        chosen = instances.select(options, instance)
        if not chosen or unsafe:
            return {"found": False, "ambiguous": True, "candidates": options, "method": "perceptron"}
        return {"item": item, "found": True, "instance_validated": True, "instance": chosen["instance"],
                "candidate": chosen, "candidates": options, "method": "perceptron", "confidence": 0.9,
                "arm_xy": [0.2, 0.1] if chosen["slot"] == 1 else [0.2, -0.1]}

    def safe_zone(self, timeout_s=2):
        return None


class WhichOneTests(unittest.TestCase):
    def setUp(self):
        self.patches = [patch.object(core, "ledger", None), patch.object(core, "CLARIFY_S", 0.35),
                        patch.object(core, "TRAY_LAG_S", 0.01)]
        for p in self.patches:
            p.start()
        self.controllers = []

    def tearDown(self):
        for ctl in self.controllers:
            ctl.stop()
        for p in reversed(self.patches):
            p.stop()

    def make(self, rows=None, skills="model"):
        arm = FakeArm(motion_s=0.005, auto_pull_s=0.01)
        arm.wakes = 0
        arm.wake = lambda: setattr(arm, "wakes", arm.wakes + 1)
        ctl = core.Controller(arm, True, locator=Locator(rows), skills=skills)
        ctl.resting = True
        self.controllers.append(ctl)
        return ctl, arm

    def tray(self, ctl, rows=ROWS):
        ctl.post_tray({"setting": "surgical", "slots": rows, "t": time.time()})

    def test_tray_ambiguity_returns_question_without_wake(self):
        ctl, arm = self.make()
        self.tray(ctl)
        reply = ctl.submit({"action": "handover", "item": "hemostat"})
        self.assertFalse(reply["accepted"])
        self.assertEqual([c["side"] for c in reply["clarify"]["candidates"]], ["left", "right"])
        self.assertEqual(ctl.history[-1]["type"], "clarify")
        self.assertEqual(ctl.step, "idle")
        self.assertFalse(ctl.jobs)
        self.assertEqual(arm.wakes, 0)
        self.assertIsNone(arm.last_located)

    def test_by_sight_ambiguity_and_answer_reach_picker_and_arm(self):
        for mode in ("model", "smart"):
            with self.subTest(mode=mode):
                ctl, arm = self.make(ROWS, mode)
                q = ctl.submit({"action": "handover", "item": "hemostat"})["clarify"]
                self.assertEqual(arm.wakes, 0)
                reply = ctl.submit({"action": "handover", "item": "hemostat", "instance": {"side": "right"},
                                    "question_id": q["question_id"], "heard": "the right one"})
                self.assertTrue(reply["accepted"], reply)
                self.assertTrue(wait_for(lambda: arm.last_located is not None))
                self.assertEqual(ctl.locator.calls[-1][1], {"side": "right", "slot": 2})
                self.assertEqual(arm.last_located["candidate"]["box"], ROWS[1]["box"])
                self.assertEqual(arm.last_source, "ik")
                self.assertEqual(arm.wakes, 1)
                self.assertTrue(any(e["type"] == "clarify_answer" for e in ctl.history))

    def test_invalid_hint_does_not_pick_first_candidate(self):
        ctl, arm = self.make(ROWS)
        self.tray(ctl)
        qid = None
        for hint in ({"slot": 99}, {"side": "right", "slot": 1}, {"variant": "invented"}):
            reply = ctl.submit({"action": "handover", "item": "hemostat", "instance": hint,
                                **({"question_id": qid} if qid else {})})
            self.assertFalse(reply["accepted"])
            self.assertIn("clarify", reply)
            qid = reply["clarify"]["question_id"]
        self.assertEqual(arm.wakes, 0)

    def test_timeout_late_answer_and_stop_never_resume(self):
        ctl, arm = self.make(ROWS)
        q = ctl.submit({"action": "handover", "item": "hemostat"})["clarify"]
        self.assertTrue(wait_for(lambda: ctl.clarification is None))
        for extra in ({"question_id": q["question_id"]}, {}):
            reply = ctl.submit({"action": "handover", "item": "hemostat", "instance": {"side": "left"}, **extra})
            self.assertFalse(reply["accepted"])
        ctl.stop()
        reply = ctl.submit({"action": "handover", "item": "hemostat", "instance": {"side": "left"}})
        self.assertFalse(reply["accepted"])
        self.assertEqual(arm.wakes, 0)
        self.assertFalse(ctl.jobs)

    def test_stop_during_locate_cancels_before_wake(self):
        import threading
        ctl, arm = self.make()
        started, release = threading.Event(), threading.Event()
        def locate(*a, **kw):
            started.set()
            release.wait(2)
            return None
        ctl.locator.locate = locate
        result = []
        th = threading.Thread(target=lambda: result.append(ctl.submit({"action": "handover", "item": "hemostat"})))
        th.start()
        self.assertTrue(started.wait(1))
        t = time.monotonic()
        ctl.stop()
        self.assertLess(time.monotonic() - t, 0.1)
        release.set()
        th.join(1)
        self.assertFalse(result[0]["accepted"])
        self.assertEqual(arm.wakes, 0)

    def test_already_out_is_with_you_not_a_failed_pick_and_offers_other(self):
        ctl, arm = self.make()
        ctl.out = ["hemostat"]
        reply = ctl.submit({"action": "handover", "item": "hemostat"})
        self.assertEqual(reply["say"], "The hemostat is with you.")
        self.assertFalse(any(e["type"] == "missed" for e in ctl.history))
        ctl.locator = Locator([ROWS[1]])
        reply = ctl.submit({"action": "handover", "item": "hemostat"})
        self.assertIn("clarify", reply)
        self.assertIn("other one", reply["say"])
        self.assertTrue(reply["clarify"]["confirm"])
        self.assertEqual(arm.wakes, 0)

    def test_real_path_requires_calibrated_pose_before_wake(self):
        ctl, arm = self.make()
        self.tray(ctl)
        ctl.arm_kind = "real"
        reply = ctl.submit({"action": "handover", "item": "hemostat", "instance": {"side": "left"}})
        self.assertFalse(reply["accepted"])
        self.assertEqual(arm.wakes, 0)

    def test_selected_slot_not_other_instance_checks_grasp(self):
        ctl, _ = self.make()
        self.tray(ctl, [dict(ROWS[0], present=False), ROWS[1]])
        ctl.cmd = {"_located": {"candidate": {"box": ROWS[1]["box"], "slot": 2}}}
        self.assertTrue(ctl._slot_present("hemostat"))
        ctl.cmd = {"_located": {"candidate": {"box": ROWS[0]["box"], "slot": 1}}}
        self.assertFalse(ctl._slot_present("hemostat"))
        ctl.cmd = None

    def test_api_preserves_instance_and_telemetry_never_enqueues(self):
        ctl, arm = self.make(ROWS)
        client = TestClient(make_app(ctl))
        q = client.post("/command", json={"action": "handover", "item": "hemostat"}).json()["clarify"]
        for type_ in ("clarify", "clarify_answer"):
            r = client.post("/clarify", json={"type": type_, "say": "Which one?" if type_ == "clarify" else None,
                                             "question_id": "voice-only", "item": "hemostat", "answer": "right",
                                             "answer_ms": 200, "context": {"source": "voice"}})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(ctl.history[-1]["question_id"], "voice-only")
        self.assertFalse(ctl.jobs)
        self.assertEqual(arm.wakes, 0)
        self.assertEqual(client.post("/command", json={"action": "handover", "item": "hemostat",
                                                      "instance": {"side": "up"}}).status_code, 422)
        reply = client.post("/command", json={"action": "handover", "item": "hemostat",
                                             "instance": {"slot": 2}, "question_id": q["question_id"]}).json()
        self.assertTrue(reply["accepted"])

    def test_locator_serializes_instance_query(self):
        import httpx
        seen = []
        def handler(req):
            seen.append(dict(req.url.params))
            return httpx.Response(200, json={"found": False})
        loc = picker.Locator("http://vision", httpx.Client(transport=httpx.MockTransport(handler)))
        loc.locate("hemostat", instance={"variant": "curved", "side": "right", "slot": 2})
        self.assertEqual(seen, [{"item": "hemostat", "variant": "curved", "side": "right", "slot": "2"}])

    def test_named_settings_variant_needs_no_physical_instance_guess(self):
        ctl, arm = self.make()
        ctl.set_setting("bench")
        ctl.post_tray({"setting": "bench", "slots": [{"item": "phillips_screwdriver", "present": True, "box": None}]})
        reply = ctl.submit({"action": "handover", "item": "phillips_screwdriver", "instance": {"variant": "Phillips"}})
        self.assertTrue(reply["accepted"], reply)
        self.assertEqual(ctl.locator.calls[-1], ("phillips_screwdriver", {"variant": "Phillips"}))
        self.assertTrue(wait_for(lambda: getattr(arm, "last_source", None) == "model"))

    def production_tray(self, ctl):
        import copy
        setting = copy.deepcopy(ctl.setting)
        next(i for i in setting["items"] if i["id"] == "hemostat")["slot"] = [10, 10, 100, 60]
        detections = [{"mention": "hemostat", "point_box": {
            "top_left": {"x": r["box"][0], "y": r["box"][1]},
            "bottom_right": {"x": r["box"][2], "y": r["box"][3]}}} for r in ROWS]
        state = tray_from_detections(setting, detections, detector="perceptron")
        ctl.post_tray(state)
        return state

    def test_production_duplicates_survive_one_configured_slot_and_locate_timeout(self):
        ctl, arm = self.make()
        state = self.production_tray(ctl)
        self.assertEqual(len([s for s in state["slots"] if s["item"] == "hemostat"]), 1)
        self.assertEqual(len(state["candidates"]), 2)
        q = ctl.submit({"action": "handover", "item": "hemostat"})["clarify"]
        self.assertEqual(len(q["candidates"]), 2)
        self.assertEqual(arm.wakes, 0)
        # A physical answer can be simulated on the fake arm without vision, but the real path cannot guess.
        ctl.arm_kind = "real"
        reply = ctl.submit({"action": "handover", "item": "hemostat", "instance": {"slot": 2},
                            "question_id": q["question_id"]})
        self.assertFalse(reply["accepted"])
        self.assertEqual(arm.wakes, 0)
        ctl.post_tray({**state, "stale": True})
        q = ctl.submit({"action": "handover", "item": "hemostat"})["clarify"]
        self.assertEqual(len(q["candidates"]), 2)
        self.assertEqual(arm.wakes, 0)
        ctl.post_tray({"setting": "surgical", "slots": state["slots"], "stale": False, "detector": "local"})
        reply = ctl.submit({"action": "handover", "item": "hemostat"})
        self.assertFalse(reply["accepted"])
        self.assertEqual(arm.wakes, 0)

    def test_bysight_right_answer_is_not_rejected_by_generic_configured_slot(self):
        ctl, arm = self.make(ROWS)
        ctl.post_tray({"setting": "surgical", "slots": [{"item": "hemostat", "present": True,
                       "box": [10, 10, 100, 60], "kind": "configured"}], "t": time.time()})
        q = ctl.submit({"action": "handover", "item": "hemostat"})["clarify"]
        reply = ctl.submit({"action": "handover", "item": "hemostat", "instance": {"side": "right", "slot": 2},
                            "question_id": q["question_id"]})
        self.assertTrue(reply["accepted"], reply)
        self.assertTrue(wait_for(lambda: arm.last_located is not None))
        self.assertEqual(arm.last_located["candidate"]["box"], ROWS[1]["box"])

    def test_missing_and_superseded_question_ids_do_not_move(self):
        ctl, arm = self.make(ROWS)
        a = ctl.submit({"action": "handover", "item": "hemostat"})["clarify"]
        reply = ctl.submit({"action": "handover", "item": "hemostat", "instance": {"side": "right"}})
        self.assertFalse(reply["accepted"])
        b = ctl.submit({"action": "handover", "item": "hemostat"})["clarify"]
        self.assertNotEqual(a["question_id"], b["question_id"])
        reply = ctl.submit({"action": "handover", "item": "hemostat", "instance": {"side": "right"},
                            "question_id": a["question_id"]})
        self.assertFalse(reply["accepted"])
        self.assertEqual(arm.wakes, 0)

    def test_two_physical_handoffs_and_return_one_preserve_count(self):
        ctl, arm = self.make(ROWS)
        self.production_tray(ctl)
        q = ctl.submit({"action": "handover", "item": "hemostat"})["clarify"]
        first = ctl.submit({"action": "handover", "item": "hemostat", "instance": {"slot": 1},
                            "question_id": q["question_id"]})
        self.assertTrue(first["accepted"])
        self.assertTrue(wait_for(lambda: ctl.cmd is None and not ctl.jobs and len(ctl._out_records()) == 1))
        offer = ctl.submit({"action": "handover", "item": "hemostat"})["clarify"]
        self.assertTrue(offer["confirm"])
        self.assertEqual(offer["candidates"][0]["slot"], 2)
        second = ctl.submit({"action": "handover", "item": "hemostat", "instance": {"slot": 2},
                             "question_id": offer["question_id"]})
        self.assertTrue(second["accepted"], second)
        self.assertTrue(wait_for(lambda: ctl.cmd is None and not ctl.jobs and len(ctl._out_records()) == 2))
        self.assertEqual(ctl.state()["out"], ["hemostat"])
        self.assertEqual({r["instance"]["slot"] for r in ctl.state()["out_instances"]}, {1, 2})
        self.assertEqual(ctl.submit({"action": "count"})["say"].split(".")[0], "Out: 2 hemostats")
        ctl.tray = None
        wakes = arm.wakes
        question = ctl.submit({"action": "return", "item": None})["clarify"]
        self.assertEqual(arm.wakes, wakes)
        self.assertEqual(len(ctl._out_records()), 2)
        reply = ctl.submit({"action": "return", "item": "hemostat", "instance": {"slot": 1},
                            "question_id": question["question_id"]})
        self.assertTrue(reply["accepted"], reply)
        self.assertTrue(wait_for(lambda: ctl.cmd is None and not ctl.jobs and len(ctl._out_records()) == 1))
        self.assertEqual(ctl.state()["out"], ["hemostat"])
        self.assertEqual(ctl.state()["out_instances"][0]["instance"]["slot"], 2)
        returned = [e for e in ctl.history if e["type"] == "returned"][-1]
        self.assertEqual(returned["instance"]["slot"], 1)

    def test_physical_count_survives_saved_state_restore(self):
        import json
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            ctl = core.Controller(FakeArm(motion_s=0.005), True, locator=Locator(), state_file=path)
            self.controllers.append(ctl)
            ctl._mark_out("hemostat", {"item": "hemostat", "id": "hemostat:slot:1", "instance": {"slot": 1}})
            ctl._mark_out("hemostat", {"item": "hemostat", "id": "hemostat:slot:2", "instance": {"slot": 2}})
            ctl.emit("count")
            self.assertTrue(wait_for(lambda: path.exists() and len(json.loads(path.read_text()).get("out_instances", [])) == 2))
            restored = core.Controller(FakeArm(motion_s=0.005), True, locator=Locator(), state_file=path)
            self.controllers.append(restored)
            self.assertEqual(restored.out, ["hemostat"])
            self.assertEqual(len(restored.state()["out_instances"]), 2)
            restored._remove_out("hemostat", {"slot": 1})
            self.assertEqual(restored.out, ["hemostat"])
            self.assertEqual(restored.state()["out_instances"][0]["instance"], {"slot": 2})
            # Flush the optional state workers before the temporary folder is removed.
            ctl._state_pool.shutdown(wait=True)
            restored._state_pool.shutdown(wait=True)
            ctl._state_pool = restored._state_pool = None


if __name__ == "__main__":
    unittest.main()
