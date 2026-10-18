"""The arm.dataset_check CLI, without reading a real dataset."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from . import dataset_check


class CliTests(unittest.TestCase):
    def run_main(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = dataset_check.main(argv)
        return rc, out.getvalue()

    def test_default_cadence_report_sits_next_to_root(self):
        with mock.patch.object(dataset_check, "local_check", return_value={"episodes": 2}) as check:
            rc, out = self.run_main(["/tmp/ds"])
        self.assertEqual(rc, 0)
        check.assert_called_once_with(Path("/tmp/ds"), Path("/tmp/ds-cadence.json"))
        self.assertIn('"episodes": 2', out)

    def test_missing_root_is_not_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, out = self.run_main([str(Path(tmp) / "none"), "--cadence-report", str(Path(tmp) / "c.json")])
        self.assertEqual(rc, 1)
        self.assertTrue(out.startswith("NOT READY:"))

    def test_failed_check_is_not_ready(self):
        with mock.patch.object(dataset_check, "local_check", side_effect=ValueError("Dataset fps must be exactly 30")):
            rc, out = self.run_main(["/tmp/ds"])
        self.assertEqual((rc, out.strip()), (1, "NOT READY: Dataset fps must be exactly 30"))


if __name__ == "__main__":
    unittest.main()
