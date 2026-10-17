import unittest

import numpy as np

from .kinematics import Kinematics
from .streaming import DELAY, Timeline


def reply(sequence=0, value=10, rtc=None):
    rows = np.tile([value, 0, 0, 0, 0, 50], (30, 1)).astype(float)
    if rtc:
        rows[:DELAY] = rtc["committed_actions"]
    return {"sequence": sequence, "chunk_id": f"chunk-{sequence}", "actions": rows.tolist(),
            "execute_from_index": DELAY if rtc else 0, "prefix_length": DELAY if rtc else 0,
            "rtc_applied": bool(rtc)}


class StreamingTests(unittest.TestCase):
    def test_prefix_boundary_and_reserve_rows(self):
        line = Timeline(Kinematics())
        self.assertTrue(line.accept(reply(), 0, .1, 0, 0, None))
        old = np.array([10, 0, 0, 0, 0, 50.])
        rtc = line.rtc(15, old, old)
        self.assertEqual(rtc["prior_start_index"], 15)
        self.assertTrue(line.accept(reply(1, 20, rtc), 15, .6, .5, 1, rtc))
        # A reply at .6 s cannot change ticks 15..26, committed until .9 s.
        np.testing.assert_array_equal(line.command(26, old, old), old)
        self.assertEqual(line.active(26).chunk_id, "chunk-0")
        self.assertEqual(line.active(27).chunk_id, "chunk-1")
        self.assertIsNone(line.active(45))
        self.assertIsNone(line.rtc(45, old, old))
        np.testing.assert_array_equal(line.command(45, old, old), old)

    def test_late_replies_are_dropped_including_exact_deadline(self):
        for arrival in (.4, .5, 10):
            line = Timeline(Kinematics())
            self.assertFalse(line.accept(reply(), 0, arrival, 0, 0, None))
            self.assertFalse(line.chunks)

    def test_validation_and_committed_prefix(self):
        line = Timeline(Kinematics())
        bad = reply()
        bad["actions"][0][0] = 999
        with self.assertRaisesRegex(ValueError, "limits"):
            line.accept(bad, 0, .1, 0, 0, None)
        with self.assertRaisesRegex(ValueError, "sequence"):
            line.accept(reply(2), 0, .1, 0, 0, None)
        line.accept(reply(), 0, .1, 0, 0, None)
        rtc = line.rtc(15, np.zeros(6), np.zeros(6))
        bad = reply(1, rtc=rtc)
        bad["actions"][2][0] += 1
        with self.assertRaisesRegex(ValueError, "committed"):
            line.accept(bad, 15, .6, .5, 1, rtc)

    def test_commands_rate_limited_and_rtc_reports_actual_plan(self):
        line = Timeline(Kinematics())
        line.accept(reply(value=100), 0, .1, 0, 0, None)
        last = np.array([0, 0, 0, 0, 0, 100.])
        row = line.command(5, last, last)
        self.assertLessEqual(abs(row[0] - last[0]), line.limits[0])
        rtc = line.rtc(15, row, last)
        committed = np.array(rtc["committed_actions"])
        self.assertEqual(committed.shape, (12, 6))
        self.assertTrue(np.all(abs(np.diff(committed, axis=0)) <= line.limits + 1e-9))
        for index in range(12):
            np.testing.assert_array_equal(line.command(15 + index, last, last), committed[index])


if __name__ == "__main__":
    unittest.main()
