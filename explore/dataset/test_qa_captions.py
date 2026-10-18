"""qa --captions on a tiny synthetic v3 dataset: own report, read-only, never changes the QA result. No network.

  .venv/bin/python -m pytest -q explore/dataset/test_qa_captions.py
"""
import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

from explore.dataset import qa, qa_video
from explore.dataset.test_dataset_tools import CAMS, make_dataset


def add_videos(root: Path, levels: dict, n=90, fps=30):
    for c, level in levels.items():
        d = root / f"videos/observation.images.{c}/chunk-000"
        d.mkdir(parents=True)
        w = cv2.VideoWriter(str(d / "file-000.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), fps, (64, 48))
        for _ in range(n):
            w.write(np.full((48, 64, 3), level, np.uint8))
        w.release()


def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        h.update(str(p.relative_to(root)).encode())
        if p.is_file():
            st = p.stat()
            h.update(p.read_bytes())
            h.update(str(st.st_mtime_ns).encode())
    return h.hexdigest()


class CaptionFlagTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "ds"
        self.root.mkdir()
        make_dataset(self.root)
        # make_dataset leaves the to_timestamp out; both episodes share one 3 s file per camera.
        import pandas as pd
        f = self.root / "meta/episodes/chunk-000/file-000.parquet"
        df = pd.read_parquet(f)
        for c in CAMS:
            df[f"videos/observation.images.{c}/to_timestamp"] = 3.0
        df.to_parquet(f)
        add_videos(self.root, {"side": 120, "wrist": 8})
        self.out = Path(self.tmp.name) / "rep" / "qa.html"
        self.out.parent.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def run_qa(self, *extra):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            qa.main(["--root", str(self.root), "--out", str(self.out), *extra])
        return buf.getvalue()

    def test_off_by_default(self):
        text = self.run_qa()
        self.assertNotIn("caption check", text)
        self.assertFalse(Path(qa.caption_report_path(self.out)).exists())

    def test_local_only_report_and_read_only(self):
        before = tree_hash(self.root)
        text = self.run_qa("--captions", "--caption-no-api")
        self.assertEqual(tree_hash(self.root), before)
        md = Path(qa.caption_report_path(self.out))
        self.assertTrue(md.exists() and md.with_suffix(".json").exists())
        rep = json.loads(md.with_suffix(".json").read_text())
        self.assertEqual(rep["summary"]["dark"], [0, 1])  # the wrist camera is dark
        self.assertEqual(rep["summary"]["api_calls"], 0)
        self.assertIn("pass,", text)  # the QA line is still there

    def test_api_flags_with_fake_perceptron_and_limit(self):
        calls = []

        def fake_ask(frames, task, key, post=None):
            calls.append(task)
            return ({"caption": "the gripper closes on nothing", "holding": False, "dropped": False}, 1234, None)
        with mock.patch.dict(os.environ, {"PERCEPTRON_API_KEY": "test-not-a-key"}), \
                mock.patch.object(qa_video, "ask_perceptron", fake_ask), \
                mock.patch.object(qa_video, "api_flags", lambda ans, task: [("grasp_failed", "holds nothing at the end")]):
            self.run_qa("--captions", "--caption-episodes", "1", "--caption-max-calls", "5")
        rep = json.loads(Path(qa.caption_report_path(self.out)).with_suffix(".json").read_text())
        self.assertEqual(len(calls), 1)
        self.assertEqual(rep["summary"]["grasp_failed"], [0])
        self.assertEqual(rep["episodes"][0]["caption"], "the gripper closes on nothing")
        self.assertNotIn("test-not-a-key", Path(qa.caption_report_path(self.out)).read_text())

    def test_caption_failure_never_breaks_qa(self):
        with mock.patch.object(qa_video, "load_episodes", side_effect=RuntimeError("boom")):
            text = self.run_qa("--captions", "--caption-no-api")
        self.assertIn("caption check failed: RuntimeError: boom", text)
        self.assertIn("report:", text)


if __name__ == "__main__":
    unittest.main()
