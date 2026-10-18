"""Offline checks for the ledger. Run: python -m unittest ledger.test_ledger"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import ledger
from ledger.logbook import log_batch


class OutTests(unittest.TestCase):
    def test_newest_event_out_replaces_older_handovers(self):
        events = [
            {"type": "handed", "item": "hemostat", "out": ["hemostat"], "t": 1},
            {"type": "set_down", "item": "scalpel", "out": ["hemostat", "scalpel"], "t": 2},
            {"type": "step", "item": None, "out": [], "t": 3},
        ]
        self.assertEqual(ledger._out(events), [])

    def test_falls_back_when_old_events_have_no_out_list(self):
        events = [
            {"type": "handed", "item": "hemostat", "t": 1},
            {"type": "returned", "item": "hemostat", "t": 2},
            {"type": "set_down", "item": "scalpel", "t": 3},
        ]
        self.assertEqual(ledger._out(events), ["scalpel"])


class StatsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.buffer = Path(self.tmp.name) / "buffer.jsonl"
        self._buffer = ledger.BUFFER
        self._db = ledger._db
        self._uri = ledger._uri
        ledger.BUFFER = self.buffer
        ledger._db = None
        ledger._uri = lambda: ""

    def tearDown(self):
        ledger.BUFFER = self._buffer
        ledger._db = self._db
        ledger._uri = self._uri
        self.tmp.cleanup()

    def test_handed_event_shows_up_in_stats_from_the_buffer(self):
        ledger.log(
            {
                "type": "released",
                "item": "hemostat",
                "request_to_hand_s": 6.4,
                "setting": "surgical",
                "lighting": "normal",
                "out": ["hemostat"],
                "t": 10,
            }
        )
        ledger.log_test("hemostat", "surgical", "normal", True, 6.4, 0)
        report = ledger.stats()
        self.assertEqual(report["out"], ["hemostat"])
        self.assertEqual(report["by_item"][0]["item"], "hemostat")
        self.assertEqual(report["by_item"][0]["successes"], 1)
        self.assertEqual(report["median_request_to_hand_s"], 6.4)
        self.assertTrue(self.buffer.exists())


class LogbookTests(unittest.TestCase):
    def test_row_matches_the_data_log_table(self):
        root = Path(tempfile.mkdtemp())
        settings = root / "settings"
        settings.mkdir()
        (settings / "surgical.json").write_text(
            json.dumps(
                {
                    "id": "surgical",
                    "label": "Operating room",
                    "items": [{"id": "hemostat", "name": "hemostat", "aliases": ["kelly"]}],
                }
            ),
            encoding="utf-8",
        )
        log = root / "DATA-LOG.md"
        log.write_text(
            "# Data log\n\n| Time | Setting | Item | Direction | Lighting | Demos | Dataset name | Notes |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- |\n",
            encoding="utf-8",
        )
        row = log_batch(
            "surgical",
            "kelly",
            "pick",
            "bright",
            5,
            dataset="local",
            notes="cadence ok",
            when="2026-10-17 18:05",
            path=log,
            repo=root,
        )
        self.assertEqual(
            row,
            "| 2026-10-17 18:05 | Operating room | hemostat | hand-out | bright | 5 | local | cadence ok |",
        )
        text = log.read_text(encoding="utf-8")
        self.assertEqual(text.count(row), 1)
        self.assertIn("| Time | Setting | Item | Direction | Lighting | Demos | Dataset name | Notes |", text)


if __name__ == "__main__":
    unittest.main()
