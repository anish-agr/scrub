"""No hardware, no real dataset: qa and variety on a tiny synthetic LeRobot v3 dataset.

  .venv/bin/python -m pytest explore/dataset/test_dataset_tools.py -q
"""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from explore.dataset import qa, variety

CAMS = ("side", "wrist")


def make_dataset(root: Path, n=90):
    """Two episodes in two data files; the episode metadata lists episode 1 first."""
    (root / "meta/episodes/chunk-000").mkdir(parents=True)
    feats = {f"observation.images.{c}": {"dtype": "video", "shape": [480, 640, 3]} for c in CAMS}
    (root / "meta/info.json").write_text(json.dumps({
        "fps": 30, "features": feats,
        "data_path": "data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet",
        "video_path": "videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4"}))
    pd.DataFrame({"task_index": [0]}, index=["pick the hemostat"]).to_parquet(root / "meta/tasks.parquet")
    rows = []
    for ep in (1, 0):
        row = {"episode_index": ep, "length": n, "tasks": ["pick the hemostat"],
               "data/chunk_index": 0, "data/file_index": ep}
        for c in CAMS:
            k = f"videos/observation.images.{c}"
            row.update({f"{k}/chunk_index": 0, f"{k}/file_index": 0, f"{k}/from_timestamp": 0.0})
        rows.append(row)
    pd.DataFrame(rows).to_parquet(root / "meta/episodes/chunk-000/file-000.parquet")
    (root / "data/chunk-000").mkdir(parents=True)
    t = np.arange(n)
    for ep in (0, 1):
        grip = np.where((t > 30) & (t < 60), 5.0, 90.0)  # closes, then reopens
        state = [np.array([0, -20 + 30 * i / n, 40, 30, 0, g], dtype=np.float32) for i, g in zip(t, grip)]
        pd.DataFrame({"timestamp": t / 30.0, "frame_index": t, "episode_index": ep, "task_index": 0,
                      "observation.state": state, "action": state}).to_parquet(
            root / f"data/chunk-000/file-{ep:03d}.parquet")


class DatasetToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "ds"
        self.root.mkdir()
        make_dataset(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_qa_reports_every_episode_and_missing_video(self):
        out = Path(self.tmp.name) / "qa.html"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            qa.main(["--root", str(self.root), "--out", str(out)])
        text = buf.getvalue()
        self.assertIn("0 pass, 0 warn, 2 fail of 2", text)
        self.assertIn("side: video unreadable", text)
        self.assertNotIn("gripper never", text)
        self.assertTrue(out.exists())

    def test_qa_refuses_out_inside_dataset(self):
        with self.assertRaises(SystemExit):
            qa.main(["--root", str(self.root), "--out", str(self.root / "qa.html")])

    def test_qa_empty_dataset_is_a_clear_exit(self):
        empty = Path(self.tmp.name) / "empty"
        (empty / "meta").mkdir(parents=True)
        (empty / "meta/info.json").write_text("{}")
        with self.assertRaises(SystemExit) as e:
            qa.main(["--root", str(empty), "--out", str(Path(self.tmp.name) / "q.html")])
        self.assertIn("no readable parquet", str(e.exception))

    def test_variety_loads_episodes_by_index_across_files(self):
        episodes, _ = variety.load_episodes(self.root)
        self.assertEqual(sorted(e["episode_index"] for e in episodes), [0, 1])
        self.assertTrue(all(len(e["data"]) == 90 for e in episodes))
        self.assertTrue(all((e["data"]["episode_index"] == e["episode_index"]).all() for e in episodes))


if __name__ == "__main__":
    unittest.main()
