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
    caption_agrees,
    parse_caption_reply,
    sample_clip_frames,
    tray_item_names,
    with_request_to_hand,
)

SURGICAL = ["scalpel", "hemostat", "mayo scissors"]


def answer(caption="arm holds a hemostat out to a gloved hand", item="hemostat", action="handed") -> str:
    return json.dumps({"caption": caption, "item_seen": item, "action": action})


class FakeResp:
    def __init__(self, status: int, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


def reply(content: str, status: int = 200):
    return FakeResp(status, {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]})


def recorded(event: dict) -> tuple[ClipManager, dict]:
    """A manager with 30 synthetic frames (a bright square moving across) and one recorded clip."""
    mgr = ClipManager(clips_dir=Path(tempfile.mkdtemp()), auto_caption=False)
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
    def test_prompt_lists_items_and_does_not_name_the_event(self):
        _, clip = recorded(handed(item="mayo_scissors", setting="surgical"))
        p = build_caption_prompt(clip)
        self.assertIn("Instruments on the tray: scalpel, hemostat, mayo scissors.", p)
        self.assertIn('"none"]', p)
        for action in ("picked", "handed", "set_down", "released", "returned", "none_or_unclear"):
            self.assertIn(f'"{action}"', p)
        for leak in ("6.4", "controller", "Event type", "logged", "mayo scissors handed"):
            self.assertNotIn(leak, p)
        # Same prompt whatever the event says: it cannot echo the event.
        _, other = recorded({"type": "returned", "item": "scalpel", "setting": "surgical", "case_id": "c",
                             "t": time.time()})
        self.assertEqual(build_caption_prompt(other), p)

    def test_item_list_is_fixed(self):
        self.assertEqual(tray_item_names({"item": "hemostat", "event": {"setting": "surgical"}}), SURGICAL)
        every = tray_item_names({"item": "hemostat", "event": {}})
        self.assertEqual(every[:3], SURGICAL)
        self.assertIn("hex key", every)
        odd = tray_item_names({"item": "spatula", "event": {"setting": "surgical"}})
        self.assertEqual(odd, sorted(SURGICAL + ["spatula"]))  # an item no tray lists is sorted in, not first

    def test_parse_reply(self):
        body = {"choices": [{"message": {"content": "<think>x</think>```json\n" + answer(
            caption="Arm lifts the Hemostat.", item="Hemostat", action="picked") + "\n```"}}]}
        self.assertEqual(parse_caption_reply(body, SURGICAL),
                         {"caption": "Arm lifts the Hemostat", "item_seen": "hemostat", "action": "picked"})
        weird = {"choices": [{"message": {"content": answer(item="spoon", action="waved")}}]}
        self.assertEqual(parse_caption_reply(weird, SURGICAL)["item_seen"], "none")
        self.assertEqual(parse_caption_reply(weird, SURGICAL)["action"], "none_or_unclear")
        plain = {"choices": [{"message": {"content": "hemostat on the tray\nmore"}}]}
        self.assertEqual(parse_caption_reply(plain, SURGICAL),
                         {"caption": "hemostat on the tray", "item_seen": None, "action": None})
        self.assertIsNone(parse_caption_reply({"choices": [{"message": {"content": answer(caption="")}}]}, SURGICAL))
        self.assertIsNone(parse_caption_reply({"error": "x"}, SURGICAL))

    def test_agrees(self):
        clip = {"event": {"type": "handed", "item": "mayo_scissors"}}
        self.assertTrue(caption_agrees(clip, "mayo scissors", "handed"))
        self.assertFalse(caption_agrees(clip, "mayo scissors", "none_or_unclear"))
        self.assertFalse(caption_agrees(clip, "none", "handed"))
        self.assertTrue(caption_agrees({"event": {"type": "waiting_for_pull", "item": "scalpel"}}, "scalpel", "handed"))
        self.assertIsNone(caption_agrees({"event": {"type": "stopped", "item": "scalpel"}}, "scalpel", "picked"))
        self.assertIsNone(caption_agrees(clip, None, None))

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
            return reply(answer(caption="hemostat handed to the surgeon's right hand"))

        with patch("httpx.post", post):
            label = mgr.label_clip(clip, api_key="k")
        self.assertEqual(label, "hemostat handed to the surgeon's right hand, 6.4 s")
        self.assertEqual(clip["label_source"], "perceptron")
        self.assertEqual((clip["caption_item"], clip["caption_action"], clip["agrees"]), ("hemostat", "handed", True))
        self.assertEqual(clip["caption_frames"], 5)
        self.assertIsInstance(clip["caption_latency_ms"], int)
        self.assertIsNone(clip["caption_error"])
        self.assertTrue(sent[0][0].endswith("/v1/chat/completions"))
        self.assertNotIn("handed", sent[0][1]["messages"][0]["content"][1]["text"].split("Answer with JSON")[0])
        saved = json.loads((mgr.clips_dir / "case-cap" / "metadata.json").read_text())
        self.assertEqual(saved[0]["agrees"], True)  # GET /clips returns these fields

    def test_disagreeing_caption_is_kept_and_marked(self):
        mgr, clip = recorded(handed())
        with patch("httpx.post", lambda *a, **k: reply(answer("arm at rest, gripper empty", "none", "none_or_unclear"))):
            label = mgr.label_clip(clip, api_key="k")
        self.assertEqual(label, "arm at rest, gripper empty, 6.4 s")
        self.assertEqual(clip["label_source"], "perceptron")
        self.assertEqual((clip["caption_item"], clip["caption_action"], clip["agrees"]),
                         ("none", "none_or_unclear", False))

    def test_fallback_without_key(self):
        mgr, clip = recorded(handed())
        with patch("httpx.post") as post:
            label = mgr.label_clip(clip, api_key="")
        post.assert_not_called()
        self.assertIn("hemostat presented to clinician", label)
        self.assertEqual(clip["label_source"], "fallback")
        self.assertIsNone(clip["caption_latency_ms"])
        self.assertEqual(clip["caption_error"], "PERCEPTRON_API_KEY unset")
        self.assertEqual((clip["caption_item"], clip["caption_action"], clip["agrees"]), (None, None, None))

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
        with patch("httpx.post", lambda *a, **k: reply(answer("hemostat handed to the scrub nurse"))):
            body = client.post("/clips/label", json={"case_id": "case-route", "api_key": "k"}).json()
        self.assertEqual(body["clips"][0]["label_source"], "perceptron")
        listed = client.get("/clips?case_id=case-route").json()[0]
        self.assertEqual(listed["label"], "hemostat handed to the scrub nurse, 6.4 s")
        for field in ("caption_latency_ms", "caption_item", "caption_action"):
            self.assertIn(field, listed)
        self.assertIs(listed["agrees"], True)


class AutoCaptionTests(unittest.TestCase):
    """After a clip is recorded, caption it on a thread and post it to the controller. No network: a local fake."""

    def controller(self):
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        got = []

        class Ctl(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("content-length") or 0)
                got.append((self.path, json.loads(self.rfile.read(n))))
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok": true}')

            def log_message(self, *a):
                pass
        srv = HTTPServer(("127.0.0.1", 0), Ctl)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return f"http://127.0.0.1:{srv.server_port}", got

    def test_default_follows_the_key_and_the_env_overrides(self):
        from vision.clips import auto_caption_on
        with patch.dict("os.environ", {"PERCEPTRON_API_KEY": "", "VISION_AUTO_CAPTION": ""}):
            self.assertFalse(auto_caption_on())
        with patch.dict("os.environ", {"PERCEPTRON_API_KEY": "k", "VISION_AUTO_CAPTION": ""}):
            self.assertTrue(auto_caption_on())
        with patch.dict("os.environ", {"PERCEPTRON_API_KEY": "k", "VISION_AUTO_CAPTION": "0"}):
            self.assertFalse(auto_caption_on())
        with patch.dict("os.environ", {"PERCEPTRON_API_KEY": "", "VISION_AUTO_CAPTION": "1"}):
            self.assertTrue(auto_caption_on())

    def test_recorded_clip_is_captioned_and_posted(self):
        url, got = self.controller()
        mgr = ClipManager(clips_dir=Path(tempfile.mkdtemp()), auto_caption=True, controller_url=url)
        ev = handed(case_id="surgical-1792297259", setting="surgical")
        for i in range(20):
            mgr.add_frame(np.zeros((120, 160, 3), dtype=np.uint8), timestamp=ev["t"] - 1.0 + i * 0.1)
        with patch.dict("os.environ", {"PERCEPTRON_API_KEY": ""}):  # no key: the fallback label, no API call
            t0 = time.time()
            clip = mgr.record_event(ev)
            self.assertLess(time.time() - t0, 1.0)
            end = time.time() + 5
            while not got and time.time() < end:
                time.sleep(0.02)
        self.assertEqual(len(got), 1)
        path, body = got[0]
        self.assertEqual(path, "/vision/caption")
        self.assertEqual(body["case_id"], "surgical-1792297259")
        self.assertEqual(body["event_type"], "handed")
        self.assertEqual(body["item"], "hemostat")
        self.assertEqual(body["filename"], clip["filename"])
        self.assertEqual(body["label_source"], "fallback")
        self.assertTrue(body["label"].startswith("hemostat presented to clinician"))
        for k in ("t", "agrees", "caption_item", "caption_action", "caption_latency_ms"):
            self.assertIn(k, body)

    def test_failures_never_raise(self):
        from vision.clips import post_caption
        _, clip = recorded(handed())
        self.assertFalse(post_caption(clip, "http://127.0.0.1:9"))  # nothing listens there
        mgr = ClipManager(clips_dir=Path(tempfile.mkdtemp()), auto_caption=False, controller_url="http://127.0.0.1:9")
        with patch.object(mgr, "label_clip", side_effect=RuntimeError("boom")):
            self.assertFalse(mgr.caption_and_post(clip))
        with patch("httpx.post", side_effect=OSError("down")):
            self.assertFalse(post_caption(clip))


if __name__ == "__main__":
    unittest.main()
