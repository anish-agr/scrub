"""Clip caption tests: prompt, payload, fallback and label_source, with fake HTTP and synthetic frames.

  .venv/bin/python -m vision.test_clips
"""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from vision.clips import (
    ClipManager,
    build_caption_payload,
    build_caption_prompt,
    caption_from_response,
    sample_clip_frames,
    with_request_to_hand,
)


class FakeResp:
    def __init__(self, status: int, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


def reply(content: str, status: int = 200):
    return FakeResp(status, {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]})


def recorded(event: dict) -> tuple[ClipManager, dict]:
    """A manager with 30 synthetic frames (a bright square moving across) and one recorded clip."""
    mgr = ClipManager(clips_dir=Path(tempfile.mkdtemp()))
    t0 = float(event["t"]) - 1.5
    for i in range(30):
        f = np.zeros((120, 160, 3), dtype=np.uint8)
        f[40:80, 5 * i:5 * i + 20] = 255
        mgr.add_frame(f, timestamp=t0 + i * 0.1)
    return mgr, mgr.record_event(event)


def handed(**kw) -> dict:
    ev = {"type": "handed", "item": "hemostat", "case_id": "case-cap", "t": time.time(), "request_to_hand_s": 6.4}
    ev.update(kw)
    return ev


class PromptTests(unittest.TestCase):
    def test_prompt_has_event_context(self):
        _, clip = recorded(handed(item="mayo_scissors"))
        p = build_caption_prompt(clip)
        self.assertIn("Item: mayo scissors", p)
        self.assertIn("Event type: handed", p)
        self.assertIn("6.4 s", p)
        self.assertIn("hand-off spot", p)

    def test_prompt_without_request_to_hand(self):
        _, clip = recorded({"type": "returned", "item": "scalpel", "case_id": "c", "t": time.time()})
        p = build_caption_prompt(clip)
        self.assertIn("put the item back in its tray slot", p)
        self.assertNotIn("asked for it", p)

    def test_payload_sends_several_frames_as_video_frames(self):
        _, clip = recorded(handed())
        frames = sample_clip_frames(clip)
        self.assertEqual(len(frames), 5)
        stamps = [ms for ms, _ in frames]
        self.assertEqual(stamps, sorted(stamps))
        self.assertEqual(stamps[0], 0)
        self.assertGreater(stamps[-1], 2000)  # spread over the whole 3 s clip, not the key frame only
        body = build_caption_payload(frames, "p")
        part = body["messages"][0]["content"][0]
        self.assertEqual(part["type"], "video_frames")
        self.assertEqual(len(part["video_frames"]["frames"]), 5)
        self.assertTrue(part["video_frames"]["frames"][0]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(body["messages"][0]["content"][1], {"type": "text", "text": "p"})
        self.assertEqual(body["model"], "perceptron-mk1.5")

    def test_missing_video_falls_back_to_two_thumbnail_frames(self):
        _, clip = recorded(handed())
        Path(clip["path"]).unlink()
        frames = sample_clip_frames(clip)
        self.assertEqual(len(frames), 2)  # the API wants at least 2

    def test_caption_cleanup(self):
        self.assertEqual(caption_from_response({"choices": [{"message": {
            "content": "<think>looking</think>\n\"hemostat handed to the surgeon's right hand.\"\nextra"}}]}),
            "hemostat handed to the surgeon's right hand")
        self.assertIsNone(caption_from_response({"choices": [{"message": {"content": "<think>only</think>"}}]}))
        self.assertIsNone(caption_from_response({"error": "x"}))

    def test_request_to_hand_appended_once(self):
        clip = {"event": {"request_to_hand_s": 6.43}}
        self.assertEqual(with_request_to_hand("hemostat handed", clip), "hemostat handed, 6.4 s")
        self.assertEqual(with_request_to_hand("hemostat handed, 6.4 s", clip), "hemostat handed, 6.4 s")
        self.assertEqual(with_request_to_hand("hemostat picked", {"event": {}}), "hemostat picked")


class LabelSourceTests(unittest.TestCase):
    def test_perceptron_caption(self):
        mgr, clip = recorded(handed())
        sent = []

        def post(url, json=None, headers=None, timeout=None):  # noqa: A002
            sent.append((url, json, headers))
            return reply("hemostat handed to the surgeon's right hand")

        with patch("httpx.post", post):
            label = mgr.label_clip(clip, api_key="k")
        self.assertEqual(label, "hemostat handed to the surgeon's right hand, 6.4 s")
        self.assertEqual(clip["label_source"], "perceptron")
        self.assertEqual(clip["caption_frames"], 5)
        self.assertIsInstance(clip["caption_latency_ms"], int)
        self.assertIsNone(clip["caption_error"])
        self.assertTrue(sent[0][0].endswith("/v1/chat/completions"))
        self.assertIn("Event type: handed", sent[0][1]["messages"][0]["content"][1]["text"])
        saved = json.loads((mgr.clips_dir / "case-cap" / "metadata.json").read_text())
        self.assertEqual(saved[0]["label_source"], "perceptron")  # GET /clips returns these fields

    def test_fallback_without_key(self):
        mgr, clip = recorded(handed())
        with patch("httpx.post") as post:
            label = mgr.label_clip(clip, api_key="")
        post.assert_not_called()
        self.assertIn("hemostat presented to clinician", label)
        self.assertEqual(clip["label_source"], "fallback")
        self.assertIsNone(clip["caption_latency_ms"])
        self.assertEqual(clip["caption_error"], "PERCEPTRON_API_KEY unset")

    def test_fallback_on_http_error_and_empty_and_exception(self):
        cases = [
            (lambda *a, **k: reply("", status=503), "HTTP 503"),
            (lambda *a, **k: FakeResp(200, {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]}),
             "empty caption (finish_reason length)"),
            (lambda *a, **k: (_ for _ in ()).throw(TimeoutError("slow")), "TimeoutError"),
        ]
        for post, err in cases:
            mgr, clip = recorded(handed())
            with patch("httpx.post", post):
                label = mgr.label_clip(clip, api_key="k")
            self.assertEqual(clip["label_source"], "fallback", err)
            self.assertEqual(clip["caption_error"], err)
            self.assertIsInstance(clip["caption_latency_ms"], int)
            self.assertIn("hemostat presented to clinician", label)

    def test_label_route_returns_caption_fields(self):
        from fastapi.testclient import TestClient
        from vision.app import create_app
        from vision.camera import FakeCapture
        from vision.service import build_runtime
        from vision.tray import FakeDetector

        runtime = build_runtime(FakeCapture(), fake_hands=lambda _f: [], detector=FakeDetector(),
                                controller_url="http://127.0.0.1:9")
        runtime.clips, clip = recorded(handed(case_id="case-route"))
        client = TestClient(create_app(runtime))
        with patch("httpx.post", lambda *a, **k: reply("hemostat handed to the scrub nurse")):
            body = client.post("/clips/label", json={"case_id": "case-route", "api_key": "k"}).json()
        self.assertEqual(body["clips"][0]["label_source"], "perceptron")
        listed = client.get("/clips?case_id=case-route").json()[0]
        self.assertEqual(listed["label"], "hemostat handed to the scrub nurse, 6.4 s")
        self.assertIn("caption_latency_ms", listed)


if __name__ == "__main__":
    unittest.main()
