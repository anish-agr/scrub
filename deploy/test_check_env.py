"""Redaction and the key table. No network."""

import os
import unittest
from unittest import mock

from deploy.check_env import check_backboard, check_tiger, detect_verdict, format_table, key_lines, need, present, redact


class CheckEnvTests(unittest.TestCase):
    def test_redact_removes_secret_values(self):
        with mock.patch.dict(os.environ, {"HF_TOKEN": "hf_secretvalue"}):
            self.assertNotIn("hf_secretvalue", redact("failed hf_secretvalue"))

    def test_missing_required_key_is_marked(self):
        env = {name: "" for name in (
            "PERCEPTRON_TEAM_API_KEY", "PERCEPTRON_DEPLOYMENT_ID", "HF_TOKEN", "SO101_PORT",
            "MONGODB_URI", "PERCEPTRON_API_KEY", "GEMINI_API_KEY", "ELEVENLABS_API_KEY",
            "ELEVENLABS_AGENT_ID", "PHOTON_API_KEY", "PHOTON_PROJECT_ID",
        )}
        with mock.patch.dict(os.environ, env, clear=False):
            text = "\n".join(key_lines())
        self.assertIn("arm laptop", text)
        self.assertIn("voice laptop", text)
        self.assertIn("PERCEPTRON_TEAM_API_KEY", text)
        self.assertIn("MISSING", text)
        self.assertNotIn("hf_secretvalue", text)

    def test_photon_accepts_the_spectrum_names(self):
        env = {"PHOTON_API_KEY": "", "PHOTON_PROJECT_ID": "",
               "SPECTRUM_PROJECT_ID": "proj-abc123", "SPECTRUM_PROJECT_SECRET": "secret-abc123"}
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertTrue(present("PHOTON_API_KEY"))
            self.assertTrue(present("PHOTON_PROJECT_ID"))
            self.assertIsNone(need("PHOTON_API_KEY"))
            text = "\n".join(key_lines())
        self.assertIn("SPECTRUM_PROJECT_SECRET", text)
        self.assertNotIn("secret-abc123", text)
        self.assertNotIn("proj-abc123", text)

    def test_tiger_and_backboard_missing_stay_redacted(self):
        env = {
            "TIGER_DATABASE_URL": "",
            "BACKBOARD_API_KEY": "",
            "BACKBOARD_ASSISTANT_ID": "",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            tiger = check_tiger()
            board = check_backboard()
        self.assertEqual(tiger[0], "Tiger Data")
        self.assertEqual(tiger[1], "FAIL")
        self.assertIn("missing", tiger[2])
        self.assertEqual(board[1], "FAIL")
        self.assertNotIn("postgresql", tiger[2])

    def test_photon_missing_when_neither_pair_is_set(self):
        env = {"PHOTON_API_KEY": "", "PHOTON_PROJECT_ID": "", "SPECTRUM_PROJECT_ID": "", "SPECTRUM_PROJECT_SECRET": ""}
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertFalse(present("PHOTON_API_KEY"))
            self.assertIsNotNone(need("PHOTON_API_KEY"))

    def test_detect_400_on_the_tiny_image_is_a_good_key(self):
        self.assertEqual(detect_verdict(400), (True, "key ok, HTTP 400 on test image"))
        self.assertTrue(detect_verdict(200)[0])
        self.assertFalse(detect_verdict(401)[0])
        self.assertFalse(detect_verdict(403)[0])

    def test_table_has_pass_and_fail(self):
        text = format_table([("Gemini", "FAIL", "missing GEMINI_API_KEY"), ("MongoDB Atlas", "PASS", "ping ok")])
        self.assertIn("PASS", text)
        self.assertIn("FAIL", text)
        self.assertIn("Gemini", text)


if __name__ == "__main__":
    unittest.main()
