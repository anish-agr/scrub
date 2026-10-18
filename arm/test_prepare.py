import threading
import tempfile
from pathlib import Path
import unittest

from PIL import Image

from .backends import SavedImageBackend
from .real_arm import Arm
from .sessions import DryPolicySession


class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.opened = []

        def factory(instruction):
            session = DryPolicySession(instruction)
            self.opened.append(session)
            return session

        self.arm = Arm(dry_run=True, session_factory=factory)
        self.addCleanup(self.arm.disconnect)

    def test_optional_prepare_without_arm_key_or_motion(self):
        result = self.arm.prepare(["pick the hemostat", "return the hemostat", "pick the hemostat"])
        self.assertEqual(result, ["pick the hemostat", "return the hemostat"])
        self.assertIsNone(self.arm._backend)
        self.assertIsNone(self.arm._thread)
        self.assertEqual(len(self.opened), 2)
        self.arm.prepare(result)
        self.assertEqual(len(self.opened), 2)

    def test_alternating_instructions_reuses_prepared_sessions(self):
        self.arm.prepare(["pick the hemostat", "return the hemostat"])
        a = self.arm._get_session("pick the hemostat")
        b = self.arm._get_session("return the hemostat")
        self.assertIs(self.arm._get_session("pick the hemostat"), a)
        self.assertIs(self.arm._get_session("return the hemostat"), b)
        self.assertFalse(a.closed)
        self.assertFalse(b.closed)
        self.assertEqual(len(self.opened), 2)

    def test_setting_change_and_empty_list_close_obsolete_sessions(self):
        self.arm.prepare(["pick the hemostat", "return the hemostat"])
        first = self.opened.copy()
        self.arm.prepare(["pick the hemostat", "pick the hex key"])
        self.assertFalse(first[0].closed)
        self.assertTrue(first[1].closed)
        self.assertEqual(len(self.opened), 3)
        self.arm.prepare([])
        self.assertTrue(all(s.closed for s in self.opened))

    def test_on_demand_session_can_be_adopted(self):
        a = self.arm._get_session("pick the hemostat")
        self.arm.prepare(["pick the hemostat"])
        self.assertIs(self.arm._get_session("pick the hemostat"), a)
        self.assertEqual(len(self.opened), 1)

    def test_expired_session_requests_new_grant_factory(self):
        self.arm.prepare(["pick the hemostat"])
        old = self.opened[0]
        old.expires_at = 0
        new = self.arm._get_session("pick the hemostat")
        self.assertIsNot(new, old)
        self.assertTrue(old.closed)
        self.assertIn("pick the hemostat", self.arm._sessions.prepared)

    def test_deployment_or_contract_change_cannot_reuse_old_grants(self):
        self.arm.prepare(["pick the hemostat"])
        first = self.opened[0]
        self.arm.deployment_id = "new-deployment"
        self.arm.prepare(["pick the hemostat"])
        self.assertTrue(first.closed)
        second = self.opened[1]
        self.arm.rig["verified_contract_id"] = "new-contract"
        self.arm.prepare(["pick the hemostat"])
        self.assertTrue(second.closed)
        self.assertEqual(len(self.opened), 3)

    def test_partial_failure_rolls_back_only_new_sessions(self):
        self.arm.prepare(["pick the hemostat"])
        existing = self.opened[0]
        original_factory = self.arm._sessions.factory

        def sometimes_fails(instruction):
            if instruction == "bad":
                raise RuntimeError("fake unavailable")
            return original_factory(instruction)

        self.arm._sessions.factory = sometimes_fails
        with self.assertRaises(RuntimeError):
            self.arm.prepare(["pick the hemostat", "return the hemostat", "bad"])
        self.assertFalse(existing.closed)
        self.assertTrue(self.opened[1].closed)
        self.assertEqual(set(self.arm._sessions.entries), {"pick the hemostat"})

    def test_freeze_during_open_never_rearms_or_keeps_new_session(self):
        entered, release = threading.Event(), threading.Event()
        original_factory = self.arm._sessions.factory

        def blocked(instruction):
            entered.set()
            release.wait(2)
            return original_factory(instruction)

        self.arm._sessions.factory = blocked
        errors = []

        def run():
            try:
                self.arm.prepare(["pick the hemostat"])
            except RuntimeError as error:
                errors.append(error)

        worker = threading.Thread(target=run)
        worker.start()
        self.assertTrue(entered.wait(1))
        self.arm.freeze()
        release.set()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertTrue(self.arm._frozen.is_set())
        self.assertTrue(self.opened[0].closed)
        self.assertFalse(self.arm._sessions.entries)

    def test_invalid_instructions_do_not_open_anything(self):
        for instructions in ("pick the hemostat", [""], [None]):
            with self.assertRaises(ValueError):
                self.arm.prepare(instructions)
        self.assertFalse(self.opened)

    def test_disconnect_deletes_all_prepared_sessions(self):
        self.arm.prepare(["pick the hemostat", "return the hemostat"])
        self.arm.disconnect()
        self.assertTrue(all(s.closed for s in self.opened))
        self.assertFalse(self.arm._sessions.entries)

    def test_real_run_loop_uses_preopened_sessions_and_resets_between_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            side, wrist = Path(directory) / "side.png", Path(directory) / "wrist.png"
            Image.new("RGB", (640, 480)).save(side)
            Image.new("RGB", (640, 480)).save(wrist)
            self.arm._backend = SavedImageBackend(side, wrist)
            self.arm.connect()
            self.arm.prepare(["pick the hemostat", "return the hemostat"])
            for instruction in ("pick the hemostat", "return the hemostat", "pick the hemostat"):
                self.arm.run_skill(instruction, max_s=.1)
            self.assertEqual(len(self.opened), 2)
            self.assertEqual([s.reset_count for s in self.opened], [2, 1])
            self.assertTrue(all(r["sequence"] == 0 and "rtc" not in r
                                for s in self.opened for r in s.requests))
            self.assertTrue(all(not s.closed for s in self.opened))


if __name__ == "__main__":
    unittest.main()
