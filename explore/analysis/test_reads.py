from pathlib import Path

from explore.analysis import reads

TRUTH = {"files": {
    "t.png": {"kind": "tray_tag", "tray_id": "surgical"},
    "s.png": {"kind": "count_sheet", "tray_id": "surgical",
              "items": [{"id": "scalpel", "expected": 1, "initial": 1, "closing": 1}]},
}}


def ev(read, t=1.0):
    return {"type": "read", "t": t, "fake_arm": True, "read": read}


EVENTS = [
    ev({"kind": "tray_tag", "method": "qr", "latency_ms": 20, "ok": True, "tray": "surgical",
        "attempts": [{"method": "qr", "ok": True, "latency_ms": 20}]}),
    ev({"kind": "tray_tag", "method": "gemini", "latency_ms": 2000, "ok": True, "tray": "bench",
        "attempts": [{"method": "qr", "ok": False, "latency_ms": 10, "error": "no QR code"},
                     {"method": "perceptron", "ok": False, "latency_ms": 900, "error": "x"},
                     {"method": "gemini", "ok": True, "latency_ms": 1000}]}),
    ev({"kind": "tray_tag", "method": None, "latency_ms": 5, "ok": False, "error": "vision unreachable"}),
    ev({"kind": "count_sheet", "method": "perceptron", "latency_ms": 1800, "ok": True, "tray": "surgical",
        "items": [{"item": "scalpel", "expected": 1, "initial": 1, "closing": 1}]}),
    ev({"kind": "count_sheet", "method": "perceptron", "latency_ms": 1500, "ok": True, "tray": "surgical",
        "items": [{"item": "other", "expected": 1, "initial": None, "closing": None}]}),
    ev({"kind": "count_sheet", "method": None, "latency_ms": 5, "ok": False, "error": "timeout"}),
    ev({"kind": "count_sheet", "method": "perceptron", "latency_ms": 2000, "ok": True, "tray": "surgical",
        "items": [{"item": "scalpel", "expected": 2, "initial": 1, "closing": 1}]}),
    {"type": "caption", "agrees": True, "caption_latency_ms": 1000},
]


def test_scoring():
    s = reads.analyse(EVENTS, TRUTH)
    k = {x["kind"]: x for x in s["by_kind"]}
    assert s["total"] == 7
    assert (k["tray_tag"]["n"], k["tray_tag"]["ok"], k["tray_tag"]["correct"]) == (3, 2, 1)  # bench not in this truth
    assert k["tray_tag"]["scored"] == 3 and k["tray_tag"]["failed"] == 1
    c = k["count_sheet"]
    assert (c["scored"], c["unscored"], c["failed"], c["correct"], c["accuracy"]) == (2, 1, 1, 1, 0.5)
    assert c["field_accuracy"] == 0.5 and c["field_items"] == 2
    assert k["pack_label"]["scored"] == 0 and k["pack_label"]["accuracy"] is None


def test_methods_and_rescue():
    s = reads.analyse(EVENTS, TRUTH)
    m = {x["method"]: x for x in s["by_method"]}
    assert (m["perceptron"]["attempted"], m["perceptron"]["failed"]) == (4, 1)
    assert m["gemini"]["answered"] == 1 and s["fallback_rescues"] == 1
    assert {"error": "vision unreachable", "n": 1} in s["errors"]
    assert s["captions"] == {"n": 1, "agrees": 1, "median_ms": 1000}


def test_build_empty_and_full():
    out = reads.build({"events": EVENTS}, Path("."))
    assert set(out) >= {"title", "summary", "markdown", "notes", "numbers"}
    empty = reads.build({"events": []}, Path("."))
    assert any(n["value"] == "no real data yet" for n in empty["numbers"])
