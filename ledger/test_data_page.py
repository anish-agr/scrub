"""Offline checks for the read-only judges' data page and /api/data."""

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from ledger import serve

FIXTURE = {
    "read_at": 1792300000.0,
    "read_at_text": "2026-10-18 09:00",
    "source": "mongo",
    "overview": {"events": 120, "episodes": 2, "thermal": 40, "tag_start": 1792200000.0, "hours_recorded": 0.05,
                 "events_by_arm": {"real": 30, "fake": 50, "sim": 20, "pretag": 20}},
    "numbers": [{"name": "real handoffs", "value": 12, "query": "events.find({fake_arm: false})", "read_at": "2026-10-18 09:00"}],
    "episodes": {"episodes": [{"episode_index": 0, "task": "pass hemostat", "length": 900, "duration_s": 30.0, "fps": 30,
                               "idle_start_s": 1.2, "idle_end_s": 2.0, "gripper_close_s": 11.5, "verdict": "keep", "reason": "clean"}],
                 "tasks": [{"task": "pass hemostat", "count": 1, "start_spread_deg": 3.1}],
                 "local_dataset": {"episodes": 1, "frames": 900}, "flags": ["episode 1 starts far from home"]},
    "handoffs": {"definition": "request to hand", "real_rows": 12, "trusted": False, "why": "real rows predate tags.",
                 "table": [{"item": "hemostat", "lighting": "bright", "skill_source": "act", "tries": 6, "successes": 5,
                            "rate": 0.83, "low": 0.44, "high": 0.97, "median_s": 8.2, "p90_s": 11.0, "retries": 1, "misses": 1, "stops": 0}],
                 "sim_table": [], "miss_reasons": [{"reason": "dropped", "n": 1}], "method_ranking": []},
    "heat": {"limit_c": 70, "guard_c": 60, "phase_map": {}, "hot_events": 0, "recommendations": ["rest the elbow"],
             "motors": [{"motor": "elbow_flex", "idle_c": 31, "moving_c": 38, "holding_c": 45, "max_c": 52.5,
                         "rise_c_per_min_holding": 1.4, "time_to_limit_s": 600, "cool_c_per_min": 0.8}],
             "series": {"session": "s1", "t_min": [0, 1, 2], "temps": {"elbow_flex": [31, 40, 52.5]}, "phase": ["idle", "holding", "holding"]}},
    "reads": {"rule": "count matches", "total": 9, "bench": None, "errors": [], "fallback_rescues": 1,
              "by_kind": [{"kind": "tray", "n": 9, "ok": 8, "correct": 7, "accuracy": 0.78, "median_ms": 900, "p90_ms": 1500}],
              "by_method": [{"method": "gemini", "answered": 8, "attempted": 9, "failed": 1, "median_ms": 900}],
              "captions": {"n": 3, "agrees": 2, "median_ms": 700}},
}


class DataPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fresh = Path(self.tmp.name) / "analysis.json"
        self.snapshot = Path(self.tmp.name) / "snapshot.json"
        patches = [mock.patch.object(serve, "DATA_FILES", [self.fresh, self.snapshot]),
                   mock.patch.object(serve, "stats", lambda: {"by_item": []})]  # no Atlas in tests
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def get(self, path):
        try:
            with urllib.request.urlopen(self.base + path, timeout=5) as r:
                return r.status, r.headers.get("Content-Type"), r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get("Content-Type"), e.read()

    def test_page_is_served_as_html(self):
        status, kind, body = self.get("/data.html")
        self.assertEqual(status, 200)
        self.assertIn("text/html", kind)
        text = body.decode()
        self.assertIn("/api/data", text)
        self.assertIn("python -m explore.analysis", text)
        self.assertNotIn("innerHTML", text)
        self.assertNotRegex(text, r"<script[^>]+src=")  # no external scripts

    def test_api_returns_fixture(self):
        self.fresh.write_text(json.dumps(FIXTURE))
        status, kind, body = self.get("/api/data")
        self.assertEqual(status, 200)
        self.assertEqual(kind, "application/json")
        data = json.loads(body)
        self.assertEqual(data["live"], {"by_item": []})
        data.pop("live")
        self.assertEqual(data, FIXTURE)

    def test_falls_back_to_committed_snapshot(self):
        self.snapshot.write_text(json.dumps({**FIXTURE, "read_at_text": "snapshot"}))
        status, _, body = self.get("/api/data")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["read_at_text"], "snapshot")

    def test_missing_file_is_404_json(self):
        status, kind, body = self.get("/api/data")
        self.assertEqual(status, 404)
        self.assertEqual(kind, "application/json")
        self.assertEqual(json.loads(body), {"error": "no analysis yet"})

    def test_dead_atlas_does_not_break_route(self):
        self.fresh.write_text(json.dumps(FIXTURE))

        def boom():
            raise RuntimeError("atlas down")

        with mock.patch.object(serve, "stats", boom):
            status, _, body = self.get("/api/data")
        self.assertEqual(status, 200)
        self.assertIsNone(json.loads(body)["live"])

    def test_post_is_not_accepted(self):
        self.fresh.write_text(json.dumps(FIXTURE))
        before = self.fresh.read_bytes()
        req = urllib.request.Request(self.base + "/api/data", data=b'{"x": 1}', method="POST",
                                     headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req, timeout=5)
        self.assertGreaterEqual(caught.exception.code, 400)
        self.assertEqual(self.fresh.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
