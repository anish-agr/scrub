"""Offline checks for the ledger. Run: python -m unittest ledger.test_ledger"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from pathlib import Path

import ledger
import ledger.memory as memory
from ledger.cases import case_view, list_cases
from ledger.logbook import log_batch
from ledger.memory import answer, remember_event
from ledger.qr import png_bytes
from ledger.tiger import series, series_from


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
        self._notes = memory.NOTES
        memory.NOTES = Path(self.tmp.name) / "memory-buffer.jsonl"

    def tearDown(self):
        ledger.BUFFER = self._buffer
        ledger._db = self._db
        ledger._uri = self._uri
        memory.NOTES = self._notes
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
        self.assertIsNone(report["next_likely"])
        low, high = report["by_item"][0]["wilson_low"], report["by_item"][0]["wilson_high"]
        self.assertLess(low, 1)
        self.assertGreater(high, low)
        self.assertTrue(self.buffer.exists())

    def test_bad_numbers_stay_out_of_the_json(self):
        ledger.log({"type": "step", "out": "hemostat", "setting": "surgical", "t": 1})
        ledger.log(
            {
                "type": "handed",
                "item": "hemostat",
                "request_to_hand_s": "nope",
                "out": ["hemostat"],
                "setting": "surgical",
                "t": 2,
            }
        )
        ledger.log_test("hemostat", "surgical", "normal", True, float("nan"), 0)
        report = ledger.stats()
        self.assertEqual(report["out"], ["hemostat"])
        self.assertEqual(report["by_item"][0]["successes"], 1)
        self.assertIsNone(report["median_request_to_hand_s"])
        self.assertNotIn("NaN", json.dumps(report))

    def test_a_bad_timestamp_does_not_blank_the_tables(self):
        ledger.log({"type": "step", "out": ["hemostat"], "setting": "surgical", "t": "nope"})
        ledger.log_test("hemostat", "surgical", "normal", True, 4.0, 0)
        report = ledger.stats()
        self.assertEqual(report["by_item"][0]["successes"], 1)
        self.assertEqual(report["out"], ["hemostat"])

    def test_fake_arm_events_stay_out_of_the_medians(self):
        for t, secs, fake in ((1, 30.0, True), (2, 6.0, False), (3, 8.0, False)):
            ledger.log({"type": "handed", "item": "hemostat", "request_to_hand_s": secs,
                        "setting": "surgical", "fake_arm": fake, "out": ["hemostat"], "t": t})
        self.assertEqual(ledger.stats()["median_request_to_hand_s"], 7.0)
        self.assertEqual(ledger.stats(include_sim=True)["median_request_to_hand_s"], 8.0)
        self.assertEqual(ledger.stats()["out"], ["hemostat"])

    def test_untagged_events_still_count(self):
        ledger.log({"type": "handed", "item": "hemostat", "request_to_hand_s": 5.0, "out": ["hemostat"], "t": 1})
        self.assertEqual(ledger.stats()["median_request_to_hand_s"], 5.0)

    def test_likely_next_uses_what_usually_follows(self):
        stamp = 1
        for case, second in enumerate(("scalpel", "scalpel", "mayo_scissors")):
            for item in ("hemostat", second):
                ledger.log(
                    {
                        "type": "command",
                        "action": "handover",
                        "accepted": True,
                        "item": item,
                        "setting": "surgical",
                        "case_id": f"case-{case}",
                        "out": [],
                        "t": stamp,
                    }
                )
                stamp += 1
        # Latest request is still inside a case that ended on mayo, so add one more hemostat.
        ledger.log(
            {
                "type": "command",
                "action": "handover",
                "accepted": True,
                "item": "hemostat",
                "setting": "surgical",
                "case_id": "case-now",
                "out": [],
                "t": stamp,
            }
        )
        guess = ledger.stats()["next_likely"]
        self.assertEqual(guess["after"], "hemostat")
        self.assertEqual(guess["item"], "scalpel")
        self.assertAlmostEqual(guess["share"], 2 / 3)
        rows = list_cases()
        self.assertEqual(rows[0]["case_id"], "case-now")
        view = case_view("case-0")
        self.assertIn("hemostat", view["summary"])
        self.assertEqual(len(view["events"]), 2)

    def test_even_count_median_uses_both_middle_times(self):
        events = [
            {
                "type": "handed",
                "item": "mayo_scissors",
                "request_to_hand_s": 2.0,
                "setting": "surgical",
                "case_id": "even",
                "out": ["mayo_scissors"],
                "t": 1,
            },
            {
                "type": "handed",
                "item": "mayo_scissors",
                "request_to_hand_s": 4.0,
                "setting": "surgical",
                "case_id": "even",
                "out": ["mayo_scissors"],
                "t": 2,
            },
            {"type": "step", "case_id": "bad", "setting": "bench", "t": "nope"},
            {"type": "step", "case_id": "later", "setting": "bench", "t": 9},
        ]
        view = case_view("even", events)
        self.assertIn("mayo scissors in 2.0s", view["summary"])
        self.assertIn("Median request to hand 3.0s", view["summary"])
        rows = list_cases(events)
        self.assertEqual(rows[0]["case_id"], "later")

    def test_case_view_keeps_skill_source_when_present(self):
        events = [
            {"type": "picked", "item": "hemostat", "case_id": "s", "t": 1, "skill_source": "taught"},
            {"type": "released", "item": "hemostat", "case_id": "s", "t": 2},
        ]
        view = case_view("s", events)
        self.assertEqual([e["skill_source"] for e in view["events"]], ["taught", None])


class PaperTests(unittest.TestCase):
    def _events(self):
        return [
            {"type": "read", "case_id": "p", "t": 1, "say": "Count sheet read.",
             "read": {"kind": "count_sheet", "ok": True, "method": "perceptron", "latency_ms": 2100,
                      "tray": "A", "items": [
                          {"item": "scalpel", "name": "scalpel", "expected": 1, "initial": 1, "closing": 1},
                          {"item": "hemostat", "name": "hemostat", "expected": 1, "initial": 1, "closing": 0}]}},
            {"type": "read", "case_id": "p", "t": 2,
             "read": {"kind": "pack_label", "ok": True, "method": "gemini", "latency_ms": 900, "labels": [
                 {"item": "scalpel", "lot": "L1", "expires": "2020-01-01", "expired": True},
                 {"item": "hemostat", "lot": "L2", "expires": "2030-01-01", "expired": False}]}},
            {"type": "handed", "item": "hemostat", "case_id": "p", "t": 100, "request_to_hand_s": 3.0, "out": ["hemostat"]},
            {"type": "handed", "item": "scalpel", "case_id": "p", "t": 101, "request_to_hand_s": 4.0, "out": ["hemostat", "scalpel"]},
            {"type": "caption", "case_id": "p", "event_type": "handed", "item": "hemostat", "t": 104,
             "label": "gripper holding a hemostat", "label_source": "perceptron", "agrees": False},
            {"type": "caption", "case_id": "p", "event_type": "handed", "item": "scalpel", "t": 150,
             "label": "far away", "label_source": "perceptron", "agrees": True},
            {"type": "caption", "case_id": "p", "event_type": "handed", "item": "scalpel", "t": 102,
             "label": "fallback text", "label_source": "fallback", "agrees": None},
        ]

    def test_reads_are_rows_and_expired_is_marked(self):
        view = case_view("p", self._events())
        self.assertEqual(len(view["events"]), 4)
        first, second = view["events"][0], view["events"][1]
        self.assertIn("Count sheet read (perceptron, 2.1 s)", first["read_line"])
        self.assertIn("hemostat 1/0", first["read_line"])
        self.assertIn("scalpel lot L1 expires 2020-01-01 EXPIRED", second["read_line"])
        self.assertNotIn("L2 expires 2030-01-01 EXPIRED", second["read_line"])

    def test_caption_matches_by_type_item_and_time(self):
        view = case_view("p", self._events())
        hemostat, scalpel = view["events"][2], view["events"][3]
        self.assertEqual(hemostat["caption"]["label"], "gripper holding a hemostat")
        self.assertTrue(hemostat["caption"]["disagrees"])
        self.assertNotIn("caption", scalpel)  # one is out of range, one is fallback

    def test_captions_and_reads_do_not_change_stats_or_counts(self):
        events = self._events()
        base = [e for e in events if e["type"] == "handed"]
        self.assertEqual(list_cases(events)[0]["n"], len(base) + 2)
        self.assertEqual(ledger._out(events), ledger._out(base))
        self.assertEqual(ledger._samples([], events), ledger._samples([], base))
        self.assertEqual(ledger.next_likely(events), ledger.next_likely(base))

    def test_old_events_without_paper_fields(self):
        view = case_view("s", [{"type": "handed", "item": "hemostat", "case_id": "s", "t": 1}])
        self.assertNotIn("caption", view["events"][0])


class FakeCollection:
    def __init__(self, db, name):
        self.db, self.name, self.rows, self.batches = db, name, [], []

    def insert_one(self, doc):
        self.db.gate()
        doc["_id"] = len(self.rows) + 1000 * len(self.name)
        self.rows.append(dict(doc))

    def insert_many(self, docs):
        # a real client must not be called while the ledger lock is held
        free = ledger._lock.acquire(blocking=False)
        if free:
            ledger._lock.release()
        self.db.lock_free.append(free)
        self.db.gate()
        if self.db.fail_after is not None and len(self.batches) >= self.db.fail_after:
            raise RuntimeError("mongo went away")
        self.batches.append(len(docs))
        for doc in docs:
            doc["_id"] = len(self.rows) + 1000 * len(self.name)
            self.rows.append(dict(doc))

    def find(self, _query):
        self.db.gate()
        return [dict(row) for row in self.rows]


class FakeDb:
    """Stands in for client["scrub"]. `block` holds every call until it is set."""

    def __init__(self):
        self.events = FakeCollection(self, "events")
        self.tests = FakeCollection(self, "tests")
        self.block = threading.Event()
        self.block.set()
        self.fail_after = None
        self.lock_free = []

    def gate(self):
        self.block.wait(10)

    def __getitem__(self, name):
        return getattr(self, name)


class MongoTests(unittest.TestCase):
    """Atlas is a fake client here. Nothing reaches a real cluster."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (ledger.BUFFER, ledger._db, ledger._uri, ledger._cache, list(ledger._recent), ledger._next_try)
        ledger.BUFFER = Path(self.tmp.name) / "buffer.jsonl"
        ledger._db = None
        ledger._uri = lambda: ""
        ledger._cache = {"events": [], "tests": [], "start": 0.0, "at": 0.0}
        ledger._recent[:] = []
        ledger._next_try = 0.0
        self.db = FakeDb()
        self._memory = (memory.NOTES, ledger._side_tracks)
        memory.NOTES = Path(self.tmp.name) / "memory-buffer.jsonl"
        ledger._side_tracks = lambda doc: None

    def tearDown(self):
        self.db.block.set()
        time.sleep(0.05)
        ledger.BUFFER, ledger._db, ledger._uri, ledger._cache, _recent, ledger._next_try = self.saved
        ledger._recent[:] = _recent
        memory.NOTES, ledger._side_tracks = self._memory
        self.tmp.cleanup()

    def fill_buffer(self, count):
        for n in range(count):
            ledger._append("event", {"type": "step", "n": n, "t": n})

    def test_reconnect_uploads_in_batches_outside_the_lock(self):
        self.fill_buffer(1200)
        ledger._append("test", {"item": "hemostat", "success": True})
        ledger._db = self.db
        ledger._flush()
        self.assertEqual(self.db.events.batches, [500, 500, 200])
        self.assertEqual(self.db.tests.batches, [1])
        self.assertTrue(all(self.db.lock_free))
        self.assertFalse(ledger.BUFFER.exists())
        self.assertFalse(ledger._flushing().exists())

    def test_a_failed_batch_goes_back_to_the_buffer(self):
        self.fill_buffer(1200)
        self.db.fail_after = 1
        ledger._db = self.db
        ledger._flush()
        self.assertEqual(self.db.events.batches, [500])
        self.assertEqual(len(ledger.BUFFER.read_text().splitlines()), 700)
        self.assertIsNone(ledger._db)
        self.assertFalse(ledger._flushing().exists())

    def test_rows_logged_during_a_flush_are_kept(self):
        self.fill_buffer(3)
        ledger._db = self.db
        self.db.block.clear()
        worker = threading.Thread(target=ledger._flush)
        worker.start()
        time.sleep(0.2)
        ledger._append("event", {"type": "step", "n": "late", "t": 9})  # lands while insert_many waits
        self.db.block.set()
        worker.join(5)
        self.assertEqual(len(self.db.events.rows), 3)
        self.assertEqual(len(ledger.BUFFER.read_text().splitlines()), 1)

    def test_stats_does_not_wait_while_mongo_is_down(self):
        ledger._db = self.db
        ledger.log({"type": "handed", "item": "hemostat", "request_to_hand_s": 5.0, "out": ["hemostat"], "t": 1})
        self.db.block.clear()  # every Mongo call now hangs
        ledger._cache["at"] = time.monotonic() - 60  # stale, so a refresh starts in the background
        began = time.time()
        report = ledger.stats()
        self.assertLess(time.time() - began, 0.5)
        self.assertEqual(report["out"], ["hemostat"])

    def test_stats_does_not_wait_for_the_first_connection(self):
        client = mock.Mock()
        client.admin.command.side_effect = lambda *_: self.db.block.wait(10)
        fake = mock.Mock(MongoClient=mock.Mock(return_value=client))
        ledger._uri = lambda: "mongodb://fake"
        self.db.block.clear()
        ledger._append("event", {"type": "handed", "item": "hemostat", "out": ["hemostat"], "t": 1})
        with mock.patch.dict(sys.modules, {"pymongo": fake}):
            began = time.time()
            report = ledger.stats()
            self.assertLess(time.time() - began, 0.5)
            self.assertEqual(report["out"], ["hemostat"])
            self.db.block.set()
            time.sleep(0.2)

    def test_connect_flushes_and_loads_the_atlas_copy(self):
        client = {"scrub": self.db}
        fake_client = mock.MagicMock()
        fake_client.__getitem__.side_effect = client.__getitem__
        fake = mock.Mock(MongoClient=mock.Mock(return_value=fake_client))
        ledger._uri = lambda: "mongodb://fake"
        self.fill_buffer(4)
        with mock.patch.dict(sys.modules, {"pymongo": fake}):
            ledger._connect()
        self.assertEqual(len(self.db.events.rows), 4)
        self.assertFalse(ledger.BUFFER.exists())
        ledger._uri = lambda: ""
        events, _tests = ledger.stored_rows()
        self.assertEqual(len(events), 4)
        self.assertNotIn("_id", events[0])

    def test_a_direct_insert_shows_once_not_twice(self):
        ledger._db = self.db
        ledger.log({"type": "handed", "item": "hemostat", "request_to_hand_s": 5.0, "out": ["hemostat"], "t": 1})
        events, _tests = ledger.stored_rows()
        self.assertEqual(len(events), 1)
        ledger._refresh_cache()  # the read now includes the same row
        events, _tests = ledger.stored_rows()
        self.assertEqual(len(events), 1)


class TrackTests(unittest.TestCase):
    def test_series_buckets_one_minute(self):
        buckets = series_from(
            [
                {"type": "handed", "item": "hemostat", "request_to_hand_s": 4, "t": 120, "fake_arm": True},
                {"type": "handed", "item": "hemostat", "request_to_hand_s": 6, "t": 130, "fake_arm": False},
                {"type": "step", "t": 140},
            ]
        )
        self.assertEqual(len(buckets), 1)
        self.assertEqual(buckets[0]["t"], 120)
        self.assertEqual(buckets[0]["n"], 2)
        self.assertEqual(buckets[0]["real"], 1)
        self.assertEqual(buckets[0]["median_s"], 5)
        previous = os.environ.pop("TIGER_DATABASE_URL", None)
        try:
            self.assertEqual(series([])["source"], "local")
        finally:
            if previous is not None:
                os.environ["TIGER_DATABASE_URL"] = previous

    def test_memory_answers_from_the_ledger_without_backboard(self):
        events = []
        stamp = 1
        for case, second in enumerate(("scalpel", "scalpel")):
            for item in ("hemostat", second):
                events.append(
                    {
                        "type": "command",
                        "action": "handover",
                        "accepted": True,
                        "item": item,
                        "case_id": f"m-{case}",
                        "t": stamp,
                    }
                )
                stamp += 1
        saved = {name: os.environ.pop(name, None) for name in ("BACKBOARD_API_KEY", "BACKBOARD_ASSISTANT_ID")}
        try:
            reply = answer("what usually follows hemostat", events)
        finally:
            for name, value in saved.items():
                if value is not None:
                    os.environ[name] = value
        self.assertEqual(reply["source"], "local")
        self.assertIn("scalpel", reply["answer"])
        self.assertFalse(reply["backboard"])

    def test_remember_writes_a_local_note_only(self):
        path = Path(tempfile.mkdtemp()) / "memory-buffer.jsonl"
        previous = memory.NOTES
        memory.NOTES = path
        try:
            remember_event(
                {
                    "type": "command",
                    "action": "handover",
                    "accepted": True,
                    "item": "mayo_scissors",
                    "setting": "surgical",
                    "t": 3,
                }
            )
            text = path.read_text(encoding="utf-8")
        finally:
            memory.NOTES = previous
        self.assertIn("mayo scissors", text)


class QrTests(unittest.TestCase):
    def test_png_bytes_is_a_png(self):
        body = png_bytes("http://127.0.0.1:8080")
        self.assertTrue(body.startswith(b"\x89PNG"))


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


class CorsTests(unittest.TestCase):
    def test_api_allows_any_origin_to_read(self):
        import threading
        import urllib.request
        from http.server import ThreadingHTTPServer

        from ledger.serve import Handler

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            port = server.server_address[1]
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/public", timeout=5) as reply:
                self.assertEqual(reply.headers["Access-Control-Allow-Origin"], "*")
            request = urllib.request.Request(f"http://127.0.0.1:{port}/api/stats", method="OPTIONS")
            with urllib.request.urlopen(request, timeout=5) as reply:
                self.assertEqual(reply.status, 204)
                self.assertIn("GET", reply.headers["Access-Control-Allow-Methods"])
        finally:
            server.shutdown()
            server.server_close()


class PublicUrlTests(unittest.TestCase):
    def _url(self, **env):
        import ledger.qr as qr

        clean = {"SCRUB_PUBLIC_URL": "", "SCRUB_SERVER_IP": ""}
        clean.update(env)
        with mock.patch.dict(os.environ, clean), mock.patch("dotenv.load_dotenv", lambda *a, **k: None):
            return qr.public_url()

    def test_domain_wins_and_loses_trailing_slash(self):
        self.assertEqual(self._url(SCRUB_PUBLIC_URL="https://scrub.example.com/"), "https://scrub.example.com")

    def test_no_setting_points_at_the_vultr_box(self):
        self.assertEqual(self._url(), "http://144.202.95.111")

    def test_loopback_setting_is_never_used(self):
        for bad in ("http://127.0.0.1:8080", "http://localhost:8080", "http://0.0.0.0"):
            self.assertEqual(self._url(SCRUB_PUBLIC_URL=bad), "http://144.202.95.111")

    def test_lan_when_asked_or_when_no_vultr_address(self):
        import ledger.qr as qr

        with mock.patch.object(qr, "lan_url", lambda port=None: "http://10.0.0.5:8080"):
            self.assertEqual(self._url(SCRUB_PUBLIC_URL="lan"), "http://10.0.0.5:8080")
            with mock.patch.object(qr, "VULTR_URL", ""):
                self.assertEqual(self._url(), "http://10.0.0.5:8080")

    def test_lan_url_is_not_loopback(self):
        import ledger.qr as qr

        found = qr.lan_url()
        self.assertFalse(qr._loopback(found) if found else False)

    def test_api_public_never_reports_loopback(self):
        import ledger.qr as qr

        self.assertFalse(qr._loopback(self._url()))


class PublicPageFilesTests(unittest.TestCase):
    def test_every_page_links_the_shared_stylesheet_and_page_css(self):
        from ledger.serve import FILES, PUBLIC

        for page in ("index", "cases", "case", "series", "memory", "card"):
            text = (PUBLIC / f"{page}.html").read_text(encoding="utf-8")
            self.assertIn('href="style.css"', text, page)
            self.assertIn('href="pages.css"', text, page)
            self.assertNotIn("127.0.0.1", text, page)
        self.assertIn("/pages.css", FILES)
        self.assertIn("/style.css", FILES)

    def test_judge_page_keeps_the_hooks_the_script_uses(self):
        from ledger.serve import PUBLIC

        text = (PUBLIC / "index.html").read_text(encoding="utf-8")
        for hook in ("id=\"out\"", "id=\"median\"", "id=\"handoffs\"", "id=\"by-item\"", "id=\"by-lighting\"", "id=\"replays\"", "id=\"status\""):
            self.assertIn(hook, text)
