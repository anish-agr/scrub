"""Offline telemetry fixtures only: no motor bus, cameras or MongoDB connections."""
import unittest

import thermal_analyze as A


def samples(session="stub", start=0, duration=60, phase="recording", rate=1, moving=False,
            load=10, current=2):
    return [{"kind": "sample", "session": session, "t": start + i / 2, "phase": phase,
             "motors": {"shoulder_lift": {"temp": 40 + rate * i / 120,
                                           "pos": i / 2 if moving else 0,
                                           "load": load, "current": current}}}
            for i in range(duration * 2 + 1)]


class ThermalAnalyzeTests(unittest.TestCase):
    def test_separate_sessions_do_not_create_a_heating_window(self):
        rows = samples("a", duration=30) + samples("b", start=31, duration=30, rate=10)
        report = A.analyze(rows)
        self.assertEqual(report.count("Insufficient continuous coverage"), 2)
        self.assertIn("Rates are never fitted across session boundaries", report)

    def test_phase_boundary_is_not_a_window(self):
        rows = samples(duration=30) + samples(start=31, duration=30, phase="resetting")
        self.assertIn("Insufficient continuous coverage", A.analyze(rows))

    def test_gap_is_not_a_window(self):
        rows = samples(duration=30) + samples(start=40, duration=30)
        self.assertIn("Insufficient continuous coverage", A.analyze(rows))

    def test_short_session_is_not_reported_as_zero_heating(self):
        report = A.analyze(samples(duration=12))
        self.assertIn("insufficient varying windows", report)
        self.assertIn("- C/min", report)
        self.assertNotIn("0.00 C/min", report)
        self.assertNotIn("| motor |  |", report)

    def test_sampling_jitter_allows_nearly_complete_window(self):
        self.assertNotIn("Insufficient continuous coverage", A.analyze(samples(duration=59)))

    def test_empty_input(self):
        self.assertIn("No recorder samples", A.analyze([]))

    def test_holding_and_moving_are_separate(self):
        rows = samples(duration=60, phase="resetting", rate=1)
        rows += samples(start=61, duration=60, rate=2, moving=True)
        report = A.analyze(rows)
        self.assertIn("| 1.50 | 1.00 | 2.00 |", report)
        self.assertIn("| shoulder_lift | 2.00 (1) | 1.00 (1) |", report)

    def test_current_correlation_is_reported(self):
        rows = []
        for i in range(3):
            rows += samples(start=i * 61, duration=60, rate=i + 1,
                            current=i + 1, load=3 - i)
        report = A.analyze(rows)
        self.assertIn("heat vs current r", report)
        self.assertIn("| -1.00 | 1.00 |", report)

    def test_missing_values_are_not_zero_current_or_stillness(self):
        rows = samples(current=None, load=None)
        for row in rows:
            row["motors"]["shoulder_lift"]["pos"] = None
        report = A.analyze(rows)
        self.assertIn("| 1.00 | - | - | - | - | - | - |", report)

    def test_constant_signal_correlation_is_unknown(self):
        self.assertIsNone(A.correlation([0, 0, 0], [1, 2, 3]))
        self.assertIsNone(A.correlation([1, 2], [1, 2]))
        self.assertIsNone(A.correlation([None, None, None], [1, 2, 3]))

    def test_experiment_rows_use_milliamps_without_conversion(self):
        rows = [{"kind": "experiment", "session": "hold", "t": i * 10,
                 "phase": "torque_on_hold", "temps": {"elbow_flex": 40 + i / 6},
                 "current_mA": {"elbow_flex": 0}} for i in range(25)]
        report = A.analyze(rows)
        self.assertIn("| elbow_flex | 40.0 | 44.0 | 44.0 | 1.00 | 1.00 | 1.00 | 0 to 0 |", report)

    def test_unsorted_input_is_sorted(self):
        rows = samples()
        self.assertEqual(A.analyze(rows), A.analyze(list(reversed(rows))))


if __name__ == "__main__":
    unittest.main()
