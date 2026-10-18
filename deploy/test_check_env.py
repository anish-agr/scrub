"""Redaction and the key table. No network."""

import os
import unittest
from unittest import mock

from deploy.check_env import format_table, key_lines, redact


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

    def test_table_has_pass_and_fail(self):
        text = format_table([("Gemini", "FAIL", "missing GEMINI_API_KEY"), ("MongoDB Atlas", "PASS", "ping ok")])
        self.assertIn("PASS", text)
        self.assertIn("FAIL", text)
        self.assertIn("Gemini", text)


if __name__ == "__main__":
    unittest.main()
