"""arm.datalog on a temp metadata-only dataset (no frames, no real data)."""
import contextlib
import io
import shutil
import json
import tempfile
import unittest
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from . import datalog

LOG = "# Data log\n\n| Time | Setting | Item | Direction | Lighting | Demos | Dataset name | Notes |\n| --- | --- | --- | --- | --- | --- | --- | --- |\n"


def dataset(root: Path, tasks, version="v3.0"):
    (root / "meta").mkdir(parents=True)
    (root / "meta/info.json").write_text(json.dumps({"codebase_version": version, "fps": 30}))
    rows = [{"episode_index": i, "tasks": [t], "length": 450} for i, t in enumerate(tasks)]
    if version.startswith("v2"):
        (root / "meta/episodes.jsonl").write_text("\n".join(json.dumps({**r, "tasks": r["tasks"]}) for r in rows))
    else:
        (root / "meta/episodes/chunk-000").mkdir(parents=True)
        for i, row in enumerate(rows):
            pq.write_table(pa.Table.from_pylist([row]), root / f"meta/episodes/chunk-000/file-{i:03d}.parquet")


def cadence(path: Path, n, extra=None):
    extra = extra or {}
    path.write_text(json.dumps({"episodes": [
        {"episode_index": i, "measured_fps": 29.9 + i / 100, "seconds": 15.0,
         "camera_fps": {"side": 29.8, "wrist": 22.5}, "camera_stalls": {"wrist": 2} if i == 1 else {},
         "recorded_at": "2026-10-18T01:20:26-0700", **extra.get(i, {})} for i in range(n)]}))


class DatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "ds"
        self.log = self.base / "DATA-LOG.md"
        self.log.write_text(LOG)

    def sync(self, *extra):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(datalog.main(["sync", "--root", str(self.root), "--log", str(self.log), *extra]), 0)
        return out.getvalue()

    def rows(self):
        return [line for line in self.log.read_text().splitlines() if line.startswith("| 20")]

    def test_batches_by_task_and_no_duplicates(self):
        dataset(self.root, ["pick the hemostat"] * 3 + ["return the hemostat"] * 2 + ["pick the spatula"])
        cadence(Path(f"{self.root}-cadence.json"), 6)
        self.sync("--lighting", "normal")
        rows = self.rows()
        self.assertEqual(len(rows), 3)
        self.assertIn("| 2026-10-18 01:20 | Operating room | hemostat | hand-out | normal | 3 | local | ds ep 0-2;", rows[0])
        self.assertIn("loop 29.90-29.92 Hz", rows[0])
        self.assertIn("wrist cam 22.5 fps", rows[0])
        self.assertIn("stalls ep 1 {'wrist': 2}", rows[0])
        self.assertIn("| hemostat | put-back | normal | 2 |", rows[1])
        self.assertIn("| unknown | spatula | hand-out | normal | 1 | local | ds ep 5-5; task 'pick the spatula' not in settings", rows[2])
        self.assertIn("nothing new", self.sync())
        self.assertEqual(len(self.rows()), 3)

    def test_new_episodes_get_their_own_row_and_lighting_default_unknown(self):
        dataset(self.root, ["pick the hemostat"] * 2)
        cadence(Path(f"{self.root}-cadence.json"), 2)
        self.sync()
        self.assertIn("| unknown | 2 |", self.rows()[0])
        shutil.rmtree(self.root)
        dataset(self.root, ["pick the hemostat"] * 4)
        cadence(Path(f"{self.root}-cadence.json"), 4, {3: {"lighting": "bright"}})
        self.sync()
        rows = self.rows()
        self.assertEqual(len(rows), 3)
        self.assertIn("| unknown | 1 | local | ds ep 2-2;", rows[1])
        self.assertIn("| bright | 1 | local | ds ep 3-3;", rows[2])

    def test_missing_cadence_and_slow_loop_are_noted(self):
        dataset(self.root, ["pick the hemostat"] * 2, version="v2.1")
        cadence(Path(f"{self.root}-cadence.json"), 1, {0: {"measured_fps": 25.0}})
        self.sync("--dry-run")
        self.assertEqual(self.rows(), [])
        self.sync()
        row = self.rows()[0]
        self.assertIn("outside 29-31 on ep [0]", row)
        self.assertIn("no cadence for ep [1]", row)

    def test_other_dataset_names_do_not_count_as_logged(self):
        self.log.write_text(LOG + "| 2026-10-18 00:00 | x | y | hand-out | normal | 1 | local | old-ds ep 0-0 |\n")
        dataset(self.root, ["pick the hemostat"])
        cadence(Path(f"{self.root}-cadence.json"), 1)
        self.sync()
        self.assertEqual(len(self.rows()), 2)

    def test_reads_only_metadata(self):
        dataset(self.root, ["pick the hemostat"])
        (self.root / "data").mkdir()
        (self.root / "data/broken.parquet").write_bytes(b"not parquet")
        before = sorted((p, p.stat().st_mtime_ns) for p in self.root.rglob("*"))
        self.sync()
        self.assertEqual(sorted((p, p.stat().st_mtime_ns) for p in self.root.rglob("*")), before)


if __name__ == "__main__":
    unittest.main()
