"""Reading engine (OCR) checks with fake HTTP: no network calls. Run: python -m vision.test_reading

The render_* helpers draw the test images (count sheet, tray tag with QR, pack label) with OpenCV.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import unittest

os.environ["CONTROLLER_URL"] = "http://127.0.0.1:9"  # hermetic: never read a live controller

import cv2
import httpx
import numpy as np

from vision import reading
from vision.reading import (
    GeminiOCR, PerceptronOCR, decode_qr, is_expired, match_name, parse_count, parse_date, read_count_sheet,
    read_pack_label, read_tray_tag, validate_count_sheet,
)

ROOT = reading.ROOT
SURGICAL = reading.load_setting_merged(ROOT, "surgical")
BENCH = reading.load_setting_merged(ROOT, "bench")
SETTINGS = reading.known_settings(ROOT)

# ---------------------------------------------------------------- test images

FONT = cv2.FONT_HERSHEY_SIMPLEX
HAND = cv2.FONT_HERSHEY_SCRIPT_SIMPLEX
INK = (20, 20, 20)
PEN = (140, 60, 10)  # blue ballpoint, BGR


def _text(img, s, xy, scale=1.0, font=FONT, color=INK, thick=2):
    cv2.putText(img, s, xy, font, scale, color, thick, cv2.LINE_AA)


def render_count_sheet(setting: dict, rows: list[tuple[str, int, int | None, int | None]]) -> np.ndarray:
    """A printed count sheet. rows: (printed name, expected, initial, closing); counts are 'handwritten'."""
    img = np.full((1400, 1100, 3), 255, np.uint8)
    _text(img, "INSTRUMENT COUNT SHEET", (60, 100), 1.6, thick=3)
    _text(img, f"Tray: {setting['label']} ({setting['id']})", (60, 170), 1.1)
    _text(img, "Case: ____________   Date: ____________", (60, 225), 0.9)
    cols = [60, 520, 720, 900]
    top, h = 280, 90
    for c, head in zip(cols, ["Instrument", "Expected", "Initial", "Closing"]):
        _text(img, head, (c + 10, top + 55), 0.9, thick=2)
    for i in range(len(rows) + 2):
        cv2.line(img, (60, top + i * h), (1040, top + i * h), INK, 2)
    for x in cols + [1040]:
        cv2.line(img, (x, top), (x, top + (len(rows) + 1) * h), INK, 2)
    for r, (name, exp, ini, clo) in enumerate(rows, start=1):
        y = top + r * h + 58
        _text(img, name, (cols[0] + 10, y), 1.0)
        _text(img, str(exp), (cols[1] + 60, y), 1.0)
        if ini is not None:
            _text(img, str(ini), (cols[2] + 60, y + 4), 1.8, HAND, PEN, 3)
        if clo is not None:
            _text(img, str(clo), (cols[3] + 60, y + 4), 1.8, HAND, PEN, 3)
    _text(img, "Counted by: ________  Verified by: ________", (60, top + (len(rows) + 1) * h + 80), 0.9)
    return img


def qr_image(payload: str, size: int = 300) -> np.ndarray:
    code = cv2.QRCodeEncoder.create().encode(payload)
    code = cv2.resize(code, (size, size), interpolation=cv2.INTER_NEAREST)
    return cv2.cvtColor(code, cv2.COLOR_GRAY2BGR)


def render_tray_tag(setting_id: str, label: str, qr: bool = True) -> np.ndarray:
    img = np.full((500, 900, 3), 255, np.uint8)
    cv2.rectangle(img, (10, 10), (890, 490), INK, 4)
    x = 60
    if qr:
        img[100:400, 40:340] = qr_image(f"scrub:tray:{setting_id}")
        x = 380
    _text(img, "SCRUB TRAY", (x, 150), 1.3, thick=3)
    _text(img, setting_id.upper(), (x, 270), 2.6, thick=6)
    _text(img, label, (x, 360), 1.2)
    return img


def render_pack_label(item: str, lot: str, sterilized: str, expires: str, indicator: str = "STERILIZED") -> np.ndarray:
    img = np.full((620, 1000, 3), 255, np.uint8)
    cv2.rectangle(img, (10, 10), (990, 610), INK, 3)
    _text(img, "STERILE PACK", (40, 80), 1.4, thick=3)
    _text(img, f"Contents: {item}", (40, 170), 1.1)
    _text(img, f"Lot: {lot}", (40, 240), 1.1)
    _text(img, f"Sterilized: {sterilized}", (40, 310), 1.1)
    _text(img, f"Expires: {expires}", (40, 380), 1.1)
    cv2.rectangle(img, (40, 430), (620, 560), (60, 60, 200), -1)
    _text(img, indicator, (60, 510), 1.3, color=(255, 255, 255), thick=3)
    return img


def warp(img: np.ndarray, seed: int = 0) -> np.ndarray:
    """The image as a phone photo at an angle: perspective warp onto a gray table, mild blur and noise."""
    rng = np.random.default_rng(seed)
    h, w = img.shape[:2]
    W, H = int(w * 1.4), int(h * 1.4)
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    ox, oy = (W - w) / 2, (H - h) / 2
    dst = np.float32([[ox + 0.10 * w, oy + 0.04 * h], [ox + 0.97 * w, oy - 0.05 * h],
                      [ox + 1.05 * w, oy + 1.02 * h], [ox - 0.04 * w, oy + 0.92 * h]])
    out = cv2.warpPerspective(img, cv2.getPerspectiveTransform(src, dst), (W, H), borderValue=(110, 115, 120))
    out = cv2.GaussianBlur(out, (3, 3), 0)
    noise = rng.normal(0, 4, out.shape)
    return np.clip(out.astype(np.float32) * 0.92 + 10 + noise, 0, 255).astype(np.uint8)


def jpeg(img: np.ndarray) -> bytes:
    return cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 90])[1].tobytes()


# ---------------------------------------------------------------- fakes

class FakeBackend:
    """Answers with a fixed dict, or raises. Records the call."""

    def __init__(self, name, answer=None, error: Exception | None = None):
        self.name, self.answer, self.error, self.calls = name, answer, error, []

    def extract(self, jpeg_bytes, prompt, schema, schema_name):
        self.calls.append({"jpeg": jpeg_bytes, "prompt": prompt, "schema": schema, "name": schema_name})
        if self.error:
            raise self.error
        return self.answer


class FakeResponse:
    def __init__(self, status: int, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class FakeClient:
    """Stands in for httpx: .post(url, json=, headers=, timeout=) returns a FakeResponse or raises."""

    def __init__(self, response=None, error: Exception | None = None):
        self.response, self.error, self.posts = response, error, []

    def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        if self.error:
            raise self.error
        return self.response


def perceptron_reply(obj) -> FakeResponse:
    return FakeResponse(200, {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": json.dumps(obj)}}]})


def gemini_reply(obj) -> FakeResponse:
    return FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": json.dumps(obj)}]}}]})


SHEET_ANSWER = {"tray": "surgical", "tray_text": "Operating room (surgical)", "items": [
    {"item": "scalpel", "printed_name": "Scalpel", "expected": 1, "initial": 1, "closing": 1},
    {"item": "hemostat", "printed_name": "Hemostat (Kelly)", "expected": 2, "initial": 2, "closing": 1},
    {"item": "mayo_scissors", "printed_name": "Mayo scissors", "expected": 1, "initial": 1, "closing": None},
]}


# ---------------------------------------------------------------- tests

class MatchingTests(unittest.TestCase):
    def test_names_and_aliases_map_to_ids(self):
        cases = {"Scalpel": "scalpel", "SCALPEL HANDLE #3": "scalpel", "Kelly clamp (curved)": "hemostat",
                 "Hemostat (Kelly)": "hemostat", "Scissors, Mayo": "mayo_scissors", "hemostatt": "hemostat",
                 "mayo_scissors": "mayo_scissors"}
        for text, want in cases.items():
            self.assertEqual(match_name(text, SURGICAL), want, text)
        self.assertEqual(match_name("Needle-nose pliers", BENCH), "needle_nose_pliers")
        self.assertEqual(match_name("Pliers", BENCH), "needle_nose_pliers")  # bench.local.json alias
        self.assertEqual(match_name("Allen wrench", BENCH), "hex_key")

    def test_unknown_names_never_match(self):
        for text in ("Army-Navy retractor", "DeBakey forceps", "sponge", "", "   ", "Needle holder"):
            self.assertIsNone(match_name(text, SURGICAL), text)
        self.assertIsNone(match_name("scalpel", BENCH))  # an id from another setting

    def test_known_settings_skip_local_overlays(self):
        self.assertIn("surgical", SETTINGS)
        self.assertIn("bench", SETTINGS)
        self.assertFalse(any(s.endswith(".local") for s in SETTINGS))


class DateTests(unittest.TestCase):
    def test_parse_date_formats(self):
        for text in ("2026-10-18", "2026/10/18", "10/18/2026", "10/18/26", "18/10/2026", "18 Oct 2026",
                     "Oct 18, 2026", "OCT-18-2026", "EXP: 2026-10-18", "2026.10.18"):
            self.assertEqual(parse_date(text), "2026-10-18", text)
        self.assertEqual(parse_date("2026-11"), "2026-11-30")
        self.assertEqual(parse_date("02/2027"), "2027-02-28")
        for bad in (None, "", "lot 4471", "2026-02-30", "13/13/2026"):
            self.assertIsNone(parse_date(bad), bad)

    def test_expired_is_strictly_before_today(self):
        today = dt.date(2026, 10, 18)
        self.assertTrue(is_expired("2026-10-17", today))
        self.assertFalse(is_expired("2026-10-18", today))
        self.assertFalse(is_expired("2027-01-01", "2026-10-18"))
        self.assertFalse(is_expired(None, today))

    def test_counts(self):
        self.assertEqual([parse_count(v) for v in (2, "3", " 10 ", 0)], [2, 3, 10, 0])
        for bad in (None, "", "x", -1, 1000, 1.5, True, "2?"):
            self.assertIsNone(parse_count(bad), bad)


class ValidationTests(unittest.TestCase):
    def test_count_sheet_drops_invented_items(self):
        raw = {"tray": "surgical", "tray_text": "Operating room", "items": [
            {"item": "scalpel", "printed_name": "Scalpel", "expected": 1, "initial": 1, "closing": 1},
            {"item": "other", "printed_name": "Army-Navy retractor", "expected": 2, "initial": 2, "closing": 2},
            {"item": "hemostat", "printed_name": "DeBakey forceps", "expected": 1, "initial": 1, "closing": 1},
            {"item": "retractor", "printed_name": "", "expected": 1, "initial": 1, "closing": 1},
            {"item": "scalpel", "printed_name": "Scalpel", "expected": 9, "initial": 9, "closing": 9},
        ]}
        out = validate_count_sheet(raw, SURGICAL, SETTINGS)
        self.assertEqual([i["item"] for i in out["items"]], ["scalpel"])
        self.assertEqual(out["items"][0]["expected"], 1)  # the first row of a repeated item wins
        self.assertIn("Army-Navy retractor", out["dropped"])
        self.assertIn("DeBakey forceps", out["dropped"])
        self.assertEqual(out["tray"], "surgical")

    def test_count_sheet_with_no_known_item_is_invalid(self):
        with self.assertRaises(ValueError):
            validate_count_sheet({"tray": "other", "tray_text": "", "items": [
                {"item": "other", "printed_name": "sponge", "expected": 5, "initial": 5, "closing": 5}]}, SURGICAL, SETTINGS)
        with self.assertRaises(ValueError):
            validate_count_sheet({"tray": "surgical"}, SURGICAL, SETTINGS)

    def test_schema_enums_are_the_setting_ids(self):
        schema = reading.count_sheet_schema(SURGICAL, SETTINGS)
        self.assertEqual(schema["properties"]["items"]["items"]["properties"]["item"]["enum"],
                         ["scalpel", "hemostat", "mayo_scissors", "other"])
        self.assertEqual(schema["properties"]["tray"]["enum"], SETTINGS + ["other"])
        gem = reading.gemini_schema(reading.pack_label_schema(BENCH))
        label = gem["properties"]["labels"]["items"]
        self.assertEqual(label["properties"]["item"]["enum"], ["needle_nose_pliers", "wire_cutters", "hex_key", "other"])
        self.assertEqual(label["properties"]["lot"], {"type": "STRING", "nullable": True})
        self.assertNotIn("additionalProperties", label)


class QrTests(unittest.TestCase):
    def test_qr_tag_answers_without_ocr(self):
        boom = FakeBackend("perceptron", error=AssertionError("OCR must not run when the QR reads"))
        for img in (render_tray_tag("bench", "Robotics bench"), warp(render_tray_tag("surgical", "Operating room"))):
            self.assertTrue(decode_qr(img))
            out = read_tray_tag(jpeg(img), backends=[boom])
            self.assertTrue(out["ok"])
            self.assertEqual(out["method"], "qr")
            self.assertIn(out["tray"], ("bench", "surgical"))
        self.assertEqual(boom.calls, [])

    def test_unknown_qr_payload_falls_back_to_ocr(self):
        img = render_tray_tag("bench", "Robotics bench", qr=False)
        img[100:400, 40:340] = qr_image("scrub:tray:kitchen")
        ocr = FakeBackend("perceptron", answer={"tray": "other", "text": "SCRUB TRAY BENCH Robotics bench"})
        out = read_tray_tag(img, backends=[ocr])
        self.assertEqual((out["tray"], out["method"]), ("bench", "perceptron"))
        self.assertEqual(out["qr"], ["scrub:tray:kitchen"])
        self.assertEqual(out["attempts"][0]["method"], "qr")

    def test_tag_naming_no_known_tray(self):
        ocr = FakeBackend("perceptron", answer={"tray": "other", "text": "KITCHEN"})
        gem = FakeBackend("gemini", answer={"tray": "other", "text": "KITCHEN"})
        out = read_tray_tag(render_tray_tag("bench", "x", qr=False)[:, :300], backends=[ocr, gem])
        self.assertFalse(out["ok"])
        self.assertIsNone(out["tray"])
        self.assertEqual(len(gem.calls), 1)

    def test_tray_never_inferred_without_tag_text(self):
        # Live, Oct 18: a frame with instruments and no tag came back {"tray": "surgical", "text": "Surgical"}.
        ocr = FakeBackend("perceptron", answer={"tray": "surgical", "text": "Surgical"})
        gem = FakeBackend("gemini", answer={"tray": "surgical", "text": ""})
        out = read_tray_tag(render_tray_tag("bench", "x", qr=False)[:, :300], backends=[ocr, gem])
        self.assertFalse(out["ok"])
        self.assertIsNone(out["tray"])


class FallbackTests(unittest.TestCase):
    def test_perceptron_failure_then_gemini(self):
        img = render_count_sheet(SURGICAL, [("Scalpel", 1, 1, 1)])
        for failing in (FakeBackend("perceptron", error=httpx.ReadTimeout("slow")),
                        FakeBackend("perceptron", error=RuntimeError("Perceptron HTTP 503")),
                        FakeBackend("perceptron", answer={"tray": "surgical", "items": "not a list"}),
                        FakeBackend("perceptron", answer={"tray": "surgical", "tray_text": "", "items": [
                            {"item": "other", "printed_name": "retractor", "expected": 1, "initial": 1, "closing": 1}]})):
            gem = FakeBackend("gemini", answer=SHEET_ANSWER)
            out = read_count_sheet(img, SURGICAL, backends=[failing, gem])
            self.assertTrue(out["ok"])
            self.assertEqual(out["method"], "gemini")
            self.assertEqual([a["method"] for a in out["attempts"]], ["perceptron", "gemini"])
            self.assertFalse(out["attempts"][0]["ok"])
            self.assertEqual(len(failing.calls), 1)
        self.assertEqual(out["tray"], "surgical")
        self.assertEqual({i["item"]: i["closing"] for i in out["items"]}, {"scalpel": 1, "hemostat": 1, "mayo_scissors": None})

    def test_perceptron_answer_wins(self):
        per = FakeBackend("perceptron", answer=SHEET_ANSWER)
        gem = FakeBackend("gemini", error=AssertionError("not called"))
        out = read_count_sheet(render_count_sheet(SURGICAL, [("Scalpel", 1, 1, 1)]), SURGICAL, backends=[per, gem])
        self.assertEqual(out["method"], "perceptron")
        self.assertEqual(gem.calls, [])
        self.assertEqual(out["items"][1], {"item": "hemostat", "name": "hemostat", "printed_name": "Hemostat (Kelly)",
                                           "expected": 2, "initial": 2, "closing": 1})

    def test_all_fail_and_no_keys(self):
        out = read_pack_label(render_pack_label("Scalpel", "A1", "2026-10-01", "2026-12-01"), SURGICAL,
                              today="2026-10-18", backends=[FakeBackend("perceptron", error=RuntimeError("down")),
                                                            FakeBackend("gemini", error=RuntimeError("down"))])
        self.assertFalse(out["ok"])
        self.assertIsNone(out["method"])
        self.assertEqual(out["labels"], [])
        self.assertIn("perceptron", out["error"])
        out = read_pack_label(render_pack_label("Scalpel", "A1", "x", "y"), SURGICAL, backends=[])
        self.assertEqual(out["error"], "no OCR backend (no API key set)")

    def test_pack_label_dates_and_expired(self):
        answer = {"labels": [
            {"item": "hemostat", "item_text": "Kelly hemostat", "lot": "L-4471", "sterilized": "09/20/2026",
             "expires": "10/17/2026", "indicator_text": "STERILIZED"},
            {"item": "scalpel", "item_text": "Mystery tool", "lot": None, "sterilized": None,
             "expires": "2027-03", "indicator_text": None},
        ]}
        out = read_pack_label(jpeg(render_pack_label("x", "x", "x", "x")), SURGICAL, today="2026-10-18",
                              backends=[FakeBackend("gemini", answer=answer)])
        a, b = out["labels"]
        self.assertEqual((a["item"], a["sterilized"], a["expires"], a["expired"]), ("hemostat", "2026-09-20", "2026-10-17", True))
        self.assertEqual((b["item"], b["expires"], b["expired"]), (None, "2027-03-31", False))  # unknown name: no id
        self.assertTrue(out["expired"])
        self.assertEqual(out["method"], "gemini")


    def test_label_without_a_printed_name_is_dropped(self):
        # What Perceptron answered live for a frame with no label in it (Oct 18).
        invented = {"labels": [{"item": "other", "item_text": "null", "lot": "123456789", "sterilized": "01/01/2023",
                                "expires": "01/01/2025", "indicator_text": "STERILE"}]}
        gem = FakeBackend("gemini", answer={"labels": []})
        out = read_pack_label(jpeg(np.zeros((480, 640, 3), np.uint8)), SURGICAL, today="2026-10-18",
                              backends=[FakeBackend("perceptron", answer=invented), gem])
        self.assertFalse(out["ok"])
        self.assertEqual(out["labels"], [])
        self.assertFalse(out["expired"])
        self.assertEqual(len(gem.calls), 1)


class BackendRequestTests(unittest.TestCase):
    def test_perceptron_request_shape_and_downscale(self):
        client = FakeClient(perceptron_reply({"tray": "bench", "text": "TRAY BENCH"}))
        big = cv2.resize(render_tray_tag("bench", "Robotics bench", qr=False), (3200, 1800))
        out = read_tray_tag(big, backends=[PerceptronOCR("test-key", client=client, timeout=7.0)])
        self.assertEqual((out["tray"], out["method"]), ("bench", "perceptron"))
        post = client.posts[0]
        self.assertTrue(post["url"].endswith("/v1/chat/completions"))
        self.assertEqual(post["timeout"], 7.0)
        body = post["json"]
        self.assertEqual(body["model"], "perceptron-mk1.5")
        self.assertEqual(body["response_format"]["type"], "json_schema")
        self.assertTrue(body["response_format"]["json_schema"]["strict"])
        self.assertEqual(body["response_format"]["json_schema"]["schema"]["properties"]["tray"]["enum"], SETTINGS + ["other"])
        url = body["messages"][0]["content"][0]["image_url"]["url"]
        sent = cv2.imdecode(np.frombuffer(base64.b64decode(url.split(",", 1)[1]), np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(max(sent.shape[:2]), 1600)

    def test_perceptron_errors_hand_over(self):
        gem_client = FakeClient(gemini_reply({"tray": "surgical", "text": "TRAY SURGICAL"}))
        for bad in (FakeClient(error=httpx.ConnectTimeout("t")), FakeClient(FakeResponse(503, {})),
                    FakeClient(FakeResponse(200, {"choices": [{"finish_reason": "length", "message": {"content": "{"}}]})),
                    FakeClient(FakeResponse(200, {"choices": [{"finish_reason": "stop", "message": {"content": "no json"}}]}))):
            out = read_tray_tag(render_tray_tag("surgical", "Operating room", qr=False),
                                backends=[PerceptronOCR("k", client=bad), GeminiOCR("k", client=gem_client)])
            self.assertEqual((out["tray"], out["method"]), ("surgical", "gemini"))
        self.assertEqual(out["attempts"][1]["method"], "perceptron")
        timed = read_tray_tag(render_tray_tag("surgical", "x", qr=False),
                              backends=[PerceptronOCR("k", client=FakeClient(error=httpx.ReadTimeout("t")))])
        self.assertEqual(timed["attempts"][-1]["error"], "timeout")

    def test_gemini_request_shape(self):
        client = FakeClient(gemini_reply(SHEET_ANSWER))
        out = read_count_sheet(render_count_sheet(SURGICAL, [("Scalpel", 1, 1, 1)]), SURGICAL,
                               backends=[GeminiOCR("k", client=client, model="gemini-test")])
        self.assertEqual(out["method"], "gemini")
        post = client.posts[0]
        self.assertIn("/models/gemini-test:generateContent", post["url"])
        self.assertEqual(post["headers"], {"x-goog-api-key": "k"})
        cfg = post["json"]["generationConfig"]
        self.assertEqual(cfg["responseMimeType"], "application/json")
        self.assertEqual(cfg["responseSchema"]["properties"]["items"]["items"]["properties"]["item"]["enum"],
                         ["scalpel", "hemostat", "mayo_scissors", "other"])

    def test_keys_never_in_results(self):
        out = read_tray_tag(render_tray_tag("bench", "x", qr=False),
                            backends=[PerceptronOCR("secret-test-key", client=FakeClient(FakeResponse(401, {})))])
        self.assertNotIn("secret-test-key", json.dumps(out))


class RouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient

        from vision.app import create_app
        from vision.camera import FakeCapture
        from vision.service import build_runtime
        from vision.tray import FakeDetector

        cls.runtime = build_runtime(FakeCapture(), detector=FakeDetector())
        cls.app = create_app(cls.runtime)
        cls.client = TestClient(cls.app)

    @classmethod
    def tearDownClass(cls):
        cls.runtime.grabber.stop()

    def test_jpeg_body_multipart_and_overhead(self):
        tag = jpeg(render_tray_tag("bench", "Robotics bench"))
        r = self.client.post("/read/tray_tag", content=tag, headers={"Content-Type": "image/jpeg"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()["tray"], r.json()["method"]), ("bench", "qr"))
        r = self.client.post("/read/tray_tag", files={"file": ("tag.jpg", tag, "image/jpeg")})
        self.assertEqual(r.json()["tray"], "bench")
        fake = FakeBackend("perceptron", answer=SHEET_ANSWER)
        self.app.state.read_backends = [fake]
        try:
            r = self.client.post("/read/count_sheet", json={"source": "overhead"})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["setting"], "surgical")  # the setting vision tracks (controller down)
            self.assertEqual(len(r.json()["items"]), 3)
            r = self.client.post("/read/pack_label?setting=bench&today=2026-10-18",
                                 files={"file": ("p.jpg", jpeg(render_pack_label("x", "x", "x", "x")), "image/jpeg")},
                                 data={"setting": "surgical"})
            self.assertEqual(r.json()["setting"], "surgical")  # a form field beats the query
            self.assertEqual(r.json()["today"], "2026-10-18")
        finally:
            self.app.state.read_backends = None
        self.assertEqual(self.client.get("/read/last").json()["tray_tag"]["tray"], "bench")

    def test_bad_requests(self):
        self.assertEqual(self.client.post("/read/menu", content=b"x").status_code, 404)
        self.assertEqual(self.client.post("/read/tray_tag", json={}).status_code, 400)
        self.assertEqual(self.client.post("/read/tray_tag", content=b"not a jpeg",
                                          headers={"Content-Type": "image/jpeg"}).status_code, 400)
        self.assertEqual(self.client.post("/read/count_sheet?setting=kitchen", json={"source": "overhead"}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
