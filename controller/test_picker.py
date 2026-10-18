"""Picker tests, no network. Run: .venv/bin/python -m controller.test_picker"""
import json
import os
import tempfile
from pathlib import Path

import httpx

from . import picker


def ev(cmd, item, type_, src, ok_time=None, lighting="normal", **kw):
    e = {"type": type_, "item": item, "command_id": cmd, "skill_source": src, "lighting": lighting, "setting": "surgical",
         "fake_arm": False, "request_to_hand_s": ok_time, "t": float(len(str(cmd))) + hash(cmd) % 7}
    e.update(kw)
    return e


def tries(src, item, oks, secs=6.0, lighting="normal", prefix=None, **kw):
    """One command per bool: picked+handed on success, missed on failure."""
    rows = []
    for i, ok in enumerate(oks):
        c = f"{prefix or src}-{item}-{lighting}-{i}"
        if ok:
            rows += [ev(c, item, "picked", src, lighting=lighting, t=1.0, **kw),
                     ev(c, item, "handed", src, secs, lighting=lighting, t=2.0, **kw)]
        else:
            rows.append(ev(c, item, "missed", src, lighting=lighting, t=1.0, **kw))
    return rows


def test_wilson():
    assert picker.wilson_lower(0, 0) == 0.0
    assert abs(picker.wilson_lower(10, 10) - 0.722) < 0.002
    assert abs(picker.wilson_lower(5, 10) - 0.237) < 0.002
    assert picker.wilson_lower(0, 10) == 0.0


def test_model_wins_when_lower_at_least_others():
    rows = tries("model", "hemostat", [True] * 9 + [False]) + tries("taught_adjusted", "hemostat", [True] * 7 + [False] * 3) \
        + tries("ik", "hemostat", [True] * 3 + [False] * 7)
    r = picker.rank(rows, "hemostat", picker.DEFAULT_ORDER, True)
    assert [e["method"] for e in r] == ["model", "taught_adjusted", "ik"], r
    assert (r[0]["ok"], r[0]["n"]) == (9, 10) and abs(r[0]["lower"] - 0.60) < 0.01
    assert picker.rank(rows, "hemostat", picker.DEFAULT_ORDER, False)[0]["method"] == "taught_adjusted"


def test_model_preferred_on_equal_lower_even_if_slower():
    rows = tries("model", "x", [True] * 10, secs=9.0) + tries("ik", "x", [True] * 10, secs=5.0)
    assert picker.rank(rows, "x", picker.DEFAULT_ORDER, True)[0]["method"] == "model"


def test_better_other_beats_model():
    rows = tries("model", "x", [True] * 5 + [False] * 5) + tries("ik", "x", [True] * 10)
    assert picker.rank(rows, "x", picker.DEFAULT_ORDER, True)[0]["method"] == "ik"


def test_tie_broken_by_median_time():
    rows = tries("taught_adjusted", "x", [True] * 8 + [False] * 2, secs=8.0) + tries("ik", "x", [True] * 8 + [False] * 2, secs=5.0)
    r = picker.rank(rows, "x", picker.DEFAULT_ORDER, False)
    assert r[0]["method"] == "ik" and r[0]["median_s"] == 5.0, r


def test_fake_and_sim_rows_ignored_and_other_items():
    rows = tries("ik", "x", [True] * 10, fake_arm=True) + tries("ik", "x", [True] * 4, prefix="s", sim=True) \
        + tries("ik", "y", [True] * 10, prefix="y") + tries("ik", "x", [True, False], prefix="r") \
        + [dict(e, arm="fake") for e in tries("ik", "x", [True] * 5, prefix="a")]
    ik = next(e for e in picker.rank(rows, "x", picker.DEFAULT_ORDER, False) if e["method"] == "ik")
    assert (ik["n"], ik["ok"]) == (2, 1), ik


def test_retry_success_counts_once_and_unsourced_miss_ignored():
    rows = [ev("c1", "x", "missed", "ik", t=1.0), ev("c1", "x", "picked", "ik", t=2.0), ev("c1", "x", "handed", "ik", 7.0, t=3.0),
            {"type": "missed", "item": "x", "command_id": "c2", "t": 1.0, "fake_arm": False}]
    ik = next(e for e in picker.rank(rows, "x", picker.DEFAULT_ORDER, False) if e["method"] == "ik")
    assert (ik["n"], ik["ok"], ik["median_s"]) == (1, 1, 7.0), ik


def test_lighting_grouping():
    dim = tries("ik", "x", [False] * 6, lighting="dim")
    normal = tries("ik", "x", [True] * 6, lighting="normal")
    rows = dim + normal
    f = lambda **k: next(e for e in picker.rank(rows, "x", picker.DEFAULT_ORDER, False, **k) if e["method"] == "ik")  # noqa: E731
    assert (f(lighting="dim")["n"], f(lighting="dim")["ok"]) == (6, 0)
    assert (f(lighting="normal")["n"], f(lighting="normal")["ok"]) == (6, 6)
    assert f(lighting="bright")["n"] == 12  # too few bright rows: all lighting
    small = tries("ik", "x", [False] * 4, lighting="dim") + normal
    assert next(e for e in picker.rank(small, "x", picker.DEFAULT_ORDER, False, lighting="dim") if e["method"] == "ik")["n"] == 10


def test_taught_is_prior_for_taught_adjusted():
    rows = tries("taught", "x", [True] * 9 + [False]) + tries("ik", "x", [True] * 4 + [False] * 6)
    r = picker.rank(rows, "x", picker.DEFAULT_ORDER, False)
    assert r[0]["method"] == "taught_adjusted" and r[0].get("prior") == "taught" and r[0]["n"] == 10
    rows += tries("taught_adjusted", "x", [True] * 2)
    r = picker.rank(rows, "x", picker.DEFAULT_ORDER, False)
    assert next(e for e in r if e["method"] == "taught_adjusted")["n"] == 2


def test_default_order_no_data():
    c = picker.refresh("s1", ["a"], deployment=True, taught={"a"}, rows=[], write=False)["a"]
    assert c["order"] == ["model", "taught_adjusted", "ik"] and c["why"] == "no real tries yet: default order"
    assert c["confidence"] == 0.0
    c = picker.refresh("s1", ["a"], deployment=False, taught={"a"}, rows=[], write=False)["a"]
    assert c["order"] == ["taught_adjusted", "ik"] and c["method"] == "taught_adjusted"
    c = picker.refresh("s1", ["a"], deployment=False, taught=set(), rows=[], write=False)["a"]
    assert c["order"] == ["ik"] and c["method"] == "ik"
    c = picker.refresh("s1", ["a"], deployment=True, taught=set(), rows=[], write=False)["a"]
    assert c["order"] == ["model", "ik"]


def test_choose_uses_cache_and_filters():
    rows = tries("model", "hemostat", [True] * 10) + tries("ik", "hemostat", [True] * 3 + [False] * 7)
    picker.refresh("surgical", ["hemostat", "scissors"], deployment=True, taught=True, rows=rows, write=False)
    c = picker.choose("hemostat", "surgical", deployment=True)
    assert c["method"] == "model" and "beats" in c["why"] or "untested" in c["why"], c
    assert picker.choose("hemostat", "surgical", deployment=False)["method"] != "model"
    assert picker.choose("nope", "surgical")["why"] == "no real tries yet: default order"
    assert picker.choose("scissors", "surgical", deployment=True)["method"] == "model"


def test_why_text():
    rows = tries("model", "x", [True] * 9 + [False]) + tries("taught_adjusted", "x", [True] * 7 + [False] * 3)
    c = picker.refresh("surgical", ["x"], deployment=True, taught=True, rows=rows, write=False)["x"]
    assert c["why"] == "model 9/10 (lower 0.60) beats taught_adjusted 7/10 (0.40)", c["why"]
    assert c["n"] == 10


def test_policy_round_trip():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "newdir" / "skill_policy.json"
        rows = tries("ik", "x", [True] * 3)
        picker.refresh("surgical", ["x"], deployment=False, taught=False, rows=rows, policy=picker.Policy(path))
        data = json.loads(path.read_text())
        assert data["surgical"]["x"]["method"] == "ik" and data["surgical"]["x"]["n"] == 3
        assert {"method", "order", "confidence", "why", "n", "t"} <= set(data["surgical"]["x"])
        # another setting is kept; no temp files left behind
        picker.refresh("dental", ["y"], rows=[], policy=picker.Policy(path))
        pol = picker.Policy(path)
        pol.load()
        assert pol.get("surgical", "x")["method"] == "ik" and pol.get("dental", "y") is not None
        assert [p.name for p in path.parent.iterdir()] == ["skill_policy.json"]
        picker.load_cache(pol)
        assert picker.choose("x", "surgical")["method"] == "ik"
        assert picker.Policy(Path(d) / "missing.json").load() == {}


def mock(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_locator():
    seen = []

    def handler(req):
        seen.append(req.url)
        if req.url.path == "/locate":
            return httpx.Response(200, json={"item": req.url.params["item"], "found": True, "confidence": 0.9})
        if req.url.path == "/safe_zone":
            return httpx.Response(200, json={"clear": True})
        return httpx.Response(500)

    loc = picker.Locator("http://vision:8001/", client=mock(handler))
    assert loc.locate("hemostat")["found"] is True and loc.safe_zone() == {"clear": True}
    assert str(seen[0]) == "http://vision:8001/locate?item=hemostat"
    assert picker.Locator("http://v", client=mock(lambda r: httpx.Response(500))).locate("x") is None
    assert picker.Locator("http://v", client=mock(lambda r: httpx.Response(200, text="nope"))).safe_zone() is None

    def boom(req):
        raise httpx.ConnectTimeout("slow", request=req)

    assert picker.Locator("http://v", client=mock(boom)).locate("x") is None
    assert picker.Locator("").locate("x") is None


class Env:
    def __init__(self, **kw):
        self.kw = kw

    def __enter__(self):
        self.old = {k: os.environ.get(k) for k in self.kw}
        for k, v in self.kw.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def __exit__(self, *a):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_ask_in_gripper():
    jpeg = b"\xff\xd8fake"
    calls = []

    def handler(req):
        calls.append(req.url.host)
        if "perceptron" in req.url.host:
            assert req.headers["authorization"] == "Bearer pk"
            return httpx.Response(200, json={"detections": calls_det[0]})
        assert req.headers["x-goog-api-key"] == "gk"
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps({"in_gripper": gem[0]})}]}}]})

    calls_det, gem = [[{"mention": "hemostat"}]], [False]
    with Env(PERCEPTRON_API_KEY="pk", GEMINI_API_KEY="gk"):
        assert picker.ask_in_gripper(jpeg, "hemostat", client=mock(handler)) is True
        assert calls == ["api.perceptron.inc"]
        calls_det[0] = []
        gem[0] = True
        assert picker.ask_in_gripper(jpeg, "hemostat", client=mock(handler)) is True  # perceptron empty, gemini yes
        gem[0] = False
        assert picker.ask_in_gripper(jpeg, "hemostat", client=mock(handler)) is False

        def slow(req):
            raise httpx.ReadTimeout("timeout", request=req)

        assert picker.ask_in_gripper(jpeg, "hemostat", timeout_s=0.5, client=mock(slow)) is None
    with Env(PERCEPTRON_API_KEY=None, GEMINI_API_KEY=None):
        def never(req):
            raise AssertionError("no key: no request")

        assert picker.ask_in_gripper(jpeg, "hemostat", client=mock(never)) is None
    with Env(PERCEPTRON_API_KEY=None, GEMINI_API_KEY="gk"):
        gem[0] = True
        assert picker.ask_in_gripper(jpeg, "hemostat", client=mock(handler)) is True
        assert picker.ask_in_gripper(b"", "hemostat", client=mock(handler)) is None


def test_load_rows_fallbacks():
    with tempfile.TemporaryDirectory() as d:
        buf = Path(d) / "buffer.jsonl"
        with Env(MONGODB_URI=None, LEDGER_BUFFER=str(buf)):
            assert picker.load_rows() == []  # no URI, no buffer file
            good = ev("c", "x", "picked", "ik")
            lines = [{"kind": "event", "doc": good}, {"kind": "event", "doc": dict(good, fake_arm=True)},
                     {"kind": "test", "doc": good}]
            buf.write_text("\n".join(json.dumps(r) for r in lines) + "\nnot json\n")
            assert picker.load_rows() == [good]
        with Env(MONGODB_URI="mongodb://127.0.0.1:1/?x=1", LEDGER_BUFFER=str(buf)):
            saved = picker._mongo_rows
            picker._mongo_rows = lambda: None  # no network in tests: Atlas "down"
            try:
                assert picker.load_rows() == [good]
            finally:
                picker._mongo_rows = saved


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]


def main():
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"pass  {fn.__name__}")
        except Exception as e:  # noqa: BLE001 - one broken test must not hide the rest
            failed += 1
            print(f"FAIL  {fn.__name__}: {e!r}")
    print(f"{len(TESTS) - failed}/{len(TESTS)} passed")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
