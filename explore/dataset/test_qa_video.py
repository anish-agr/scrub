"""Tests for qa_video: synthetic frames and a tiny synthetic v3 dataset, fake HTTP, no network.

  .venv/bin/python -m explore.dataset.test_qa_video
"""
import json
import os
import tempfile
import unittest

import cv2
import numpy as np
import pandas as pd

from explore.dataset import qa_video as qv


def read(path: str) -> str:
    with open(path) as f:
        return f.read()


def frame(level: int) -> np.ndarray:
    return np.full((48, 64, 3), level, dtype=np.uint8)


class FakeResp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


def fake_post(content, status=200, calls=None):
    def post(url, json=None, headers=None, timeout=None):  # noqa: A002
        if calls is not None:
            calls.append(json)
        return FakeResp(status, {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]})
    return post


def make_dataset(root: str, levels: dict[str, int], episodes: int = 2, n: int = 20, fps: int = 10) -> None:
    """A LeRobot v3-shaped dataset: one shared mp4 per camera, episodes back to back."""
    os.makedirs(os.path.join(root, "meta", "episodes", "chunk-000"))
    features = {f"observation.images.{c}": {"dtype": "video", "shape": [48, 64, 3]} for c in levels}
    info = {"codebase_version": "v3.0", "fps": fps, "features": features,
            "video_path": "videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4"}
    with open(os.path.join(root, "meta", "info.json"), "w") as f:
        json.dump(info, f)
    rows = []
    for e in range(episodes):
        row = {"episode_index": e, "tasks": ["pick the hemostat"], "length": n}
        for c in levels:
            k = f"videos/observation.images.{c}"
            row.update({f"{k}/chunk_index": 0, f"{k}/file_index": 0,
                        f"{k}/from_timestamp": e * n / fps, f"{k}/to_timestamp": (e + 1) * n / fps})
        rows.append(row)
    pd.DataFrame(rows).to_parquet(os.path.join(root, "meta", "episodes", "chunk-000", "file-000.parquet"))
    for c, level in levels.items():
        d = os.path.join(root, "videos", f"observation.images.{c}", "chunk-000")
        os.makedirs(d)
        w = cv2.VideoWriter(os.path.join(d, "file-000.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), fps, (64, 48))
        for _ in range(episodes * n):
            w.write(frame(level))
        w.release()


class DarkCheck(unittest.TestCase):
    def test_dark_and_bright(self):
        self.assertTrue(qv.camera_check({"start": frame(5), "middle": frame(10), "end": frame(200)})["dark"])
        self.assertFalse(qv.camera_check({"start": frame(120), "middle": frame(110), "end": frame(5)})["dark"])

    def test_threshold_edge(self):
        self.assertTrue(qv.camera_check({"a": frame(39), "b": frame(39)})["dark"])
        self.assertFalse(qv.camera_check({"a": frame(40), "b": frame(40)})["dark"])

    def test_unreadable(self):
        c = qv.camera_check({"start": None, "middle": None, "end": None})
        self.assertTrue(c["unreadable"])
        self.assertIsNone(c["luma"])
        self.assertTrue(qv.camera_check({"start": frame(100), "middle": None, "end": frame(100)})["unreadable"])


class PromptAndParse(unittest.TestCase):
    def test_prompt_has_task_and_keys(self):
        p = qv.build_qa_prompt("pick the hemostat")
        for s in ("pick the hemostat", "holding_at_end", "dropped", "caption", "JSON"):
            self.assertIn(s, p)

    def test_payload_uses_video_frames(self):
        body = qv.build_qa_payload([(0, b"a"), (500, b"b"), (1000, b"c")], "q")
        part = body["messages"][0]["content"][0]
        self.assertEqual(part["type"], "video_frames")
        self.assertEqual([f["timestamp_ms"] for f in part["video_frames"]["frames"]], [0, 500, 1000])
        self.assertTrue(part["video_frames"]["frames"][0]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(body["model"], "perceptron-mk1.5")

    def test_parse_answer(self):
        body = {"choices": [{"message": {"content": '<think>x</think>```json\n{"caption": "arm lifts it", '
                                                    '"holding_at_end": "Yes", "dropped": "maybe"}\n```'}}]}
        self.assertEqual(qv.parse_answer(body), {"caption": "arm lifts it", "holding_at_end": "yes", "dropped": "unclear"})
        self.assertIsNone(qv.parse_answer({"choices": [{"message": {"content": "no json here"}}]}))
        self.assertIsNone(qv.parse_answer({}))

    def test_api_flags(self):
        a = {"caption": "", "holding_at_end": "no", "dropped": "yes"}
        self.assertEqual([f for f, _ in qv.api_flags(a, "pick the hemostat")], ["grasp_failed", "dropped"])
        self.assertEqual([f for f, _ in qv.api_flags(a, "return the hemostat")], ["dropped"])  # empty at end is right
        self.assertEqual(qv.api_flags({"caption": "", "holding_at_end": "unclear", "dropped": "no"}, "pick x"), [])


class EpisodesAndReport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "ds")
        make_dataset(self.root, {"side": 120, "wrist": 3})

    def test_load_and_local_check(self):
        info, eps = qv.load_episodes(self.root)
        self.assertEqual([e["episode_index"] for e in eps], [0, 1])
        self.assertEqual(eps[1]["videos"]["observation.images.side"]["from_s"], 2.0)
        row = qv.check_episode(eps[1], 10.0, key=None, calls_left=0)
        self.assertEqual(row["flags"], ["dark"])
        self.assertIn("wrist: dark", row["reasons"][0])
        self.assertIsNone(row["api"])

    def test_api_on_brightest_camera_and_budget(self):
        _, eps = qv.load_episodes(self.root)
        calls = []
        post = fake_post('{"caption": "arm misses", "holding_at_end": "no", "dropped": "no"}', calls=calls)
        row = qv.check_episode(eps[0], 10.0, key="k", calls_left=1, post=post)
        self.assertEqual(len(calls), 1)
        self.assertEqual(row["api"]["camera"], "side")
        self.assertEqual(row["flags"], ["dark", "grasp_failed"])
        self.assertEqual(row["caption"], "arm misses")
        frames = calls[0]["messages"][0]["content"][0]["video_frames"]["frames"]
        self.assertEqual([f["timestamp_ms"] for f in frames], [0, 950, 1900])
        row = qv.check_episode(eps[1], 10.0, key="k", calls_left=0, post=post)  # budget spent
        self.assertEqual(len(calls), 1)
        self.assertIsNone(row["api"])

    def test_api_error_keeps_local_flags(self):
        _, eps = qv.load_episodes(self.root)
        row = qv.check_episode(eps[0], 10.0, key="k", calls_left=5, post=fake_post("", status=500))
        self.assertEqual(row["api"]["error"], "HTTP 500")
        self.assertEqual(row["flags"], ["dark"])

    def test_report_writer(self):
        _, eps = qv.load_episodes(self.root)
        rows = [qv.check_episode(eps[0], 10.0, key="k", calls_left=1,
                                 post=fake_post('{"caption": "a | b", "holding_at_end": "yes", "dropped": "yes"}')),
                qv.check_episode(eps[1], 10.0, key=None, calls_left=0)]
        summary = qv.summarize(rows)
        self.assertEqual(summary["dark"], [0, 1])
        self.assertEqual(summary["dropped"], [0])
        self.assertEqual(summary["api_calls"], 1)
        md = os.path.join(self.tmp, "out.md")
        path_json = qv.write_report(md, "ds", rows, summary)
        text = read(md)
        self.assertEqual(sum(1 for ln in text.splitlines() if ln.startswith("| 0 ") or ln.startswith("| 1 ")), 2)
        self.assertIn("a \\| b", text)  # a pipe in a caption does not break the table
        data = json.loads(read(path_json))
        self.assertEqual(len(data["episodes"]), 2)
        self.assertEqual(data["summary"]["flagged"], [0, 1])

    def test_main_no_api_and_refuses_report_inside_dataset(self):
        md = os.path.join(self.tmp, "r.md")
        self.assertEqual(qv.main(["--dataset", self.root, "--no-api", "--report", md]), 0)
        self.assertEqual(json.loads(read(os.path.join(self.tmp, "r.json")))["summary"]["dark"], [0, 1])
        with self.assertRaises(SystemExit):
            qv.main(["--dataset", self.root, "--no-api", "--report", os.path.join(self.root, "r.md")])


if __name__ == "__main__":
    unittest.main()
