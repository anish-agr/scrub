"""No network. Run: .venv/bin/python -m controller.test_doctor"""
import json
import tempfile
import time
from pathlib import Path

import httpx

from . import doctor


def handler(request: httpx.Request) -> httpx.Response:
    u = str(request.url)
    if u.startswith("http://localhost:8000/state"):
        return httpx.Response(200, json={"step": "idle", "setting": "surgical", "fake_arm": True})
    if u.startswith("http://localhost:8000/events/recent"):
        return httpx.Response(200, json=[{"type": "error", "item": "scalpel", "say": "Too hot: wrist 61 C", "t": 1},
                                         {"type": "step", "step": "idle"}])
    if u.startswith("http://localhost:8001/health"):
        return httpx.Response(200, json={"ok": True, "camera": True})
    if u.startswith("http://localhost:8001/vision/tray"):
        return httpx.Response(200, json={"stale": True})
    if u.startswith("http://localhost:8090/status"):
        return httpx.Response(200, json={"phase": "preview", "episode": None})
    if u.startswith("https://generativelanguage"):
        assert "AIzaSECRET" not in request.content.decode()
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "a\nb"}]}}]})
    raise httpx.ConnectError("refused")


def main():
    client = httpx.Client(transport=httpx.MockTransport(handler))
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "arm-1.log").write_text("starting\nError: camera 1 not found\n")
        (d / "last-error.txt").write_text("boom token AIza" + "x" * 30 + "\n")
        (d / "thermal").mkdir()
        (d / "thermal" / "t.jsonl").write_text("{}\n")
        ex = d / "example"
        ex.write_text("GEMINI_API_KEY=\n# GEMINI_MODEL=x\nMONGODB_URI=\n")
        rep = doctor.build_report(client, {"GEMINI_API_KEY": "AIzaSECRET"}, d, ex)

    s = {x["service"]: x for x in rep["services"]}
    assert s["controller"]["up"] and s["controller"]["detail"].startswith("step idle"), s["controller"]
    assert s["vision"]["up"] and "tray stale" in s["vision"]["detail"], s["vision"]
    assert s["recorder"]["detail"] == "phase preview"
    assert not s["sim"]["up"] and s["sim"]["detail"] == "ConnectError"
    assert rep["controller_up"]
    keys = {k["name"]: k for k in rep["keys"]}
    assert keys["GEMINI_API_KEY"]["set"] and not keys["MONGODB_URI"]["set"] and keys["GEMINI_MODEL"]["optional"]
    assert "ledger" in keys["MONGODB_URI"]["disables"]
    assert rep["logs"]["error_events"][0]["say"] == "Too hot: wrist 61 C"
    assert any("last-error.txt" in f["path"] for f in rep["logs"]["files"])
    blob = json.dumps(rep)
    assert "AIza" + "x" * 30 not in blob and "AIzaSECRET" not in blob
    assert any("sim down" in x for x in rep["findings"]) and any("MONGODB_URI missing" in x for x in rep["findings"])
    assert doctor.ask_gemini(client, "AIzaSECRET", "m", rep["findings"]) == "a\nb"
    assert doctor.ask_gemini(httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))), "k", "m", ["x"]) is None
    assert doctor.scrub("Bearer abc123 mongodb+srv://u:p@h/db") == "[redacted] [redacted]"
    # controller down gives exit 1 path
    dead = httpx.Client(transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("x"))))
    t = time.time()
    rep2 = doctor.build_report(dead, {}, Path("/nonexistent"), Path("/nonexistent"))
    assert not rep2["controller_up"] and time.time() - t < 5
    print("doctor ok")


if __name__ == "__main__":
    main()
