"""Reading: OCR accuracy per kind, latency, Perceptron vs Gemini fallback, captions.

Live `read` events do not carry the image filename, so a read is scored against explore/recognition/props/truth.json
by content. Reads do not depend on the arm: the camera is real even on a fake-arm run.
"""

from __future__ import annotations

import json
from pathlib import Path

from explore.analysis.source import ROOT, arm_kind, tag_start
from explore.analysis.stats import median, pct

TRUTH = ROOT / "explore" / "recognition" / "props" / "truth.json"
BENCH = "docs/RECOGNITION.md (Oct 18, rendered props, not photos): count sheets correct (Perceptron, 1.8-2.3 s); " \
        "tray tags correct (QR, 0.05 s); pack labels 4 of 4 (Perceptron, 2.4-2.5 s). Upper bound, not live accuracy."
RULE = ("Reads are split into scored and unscored. Scored = tied to a printed prop in truth.json: "
        "tray_tag always (a failed read counts as scored-incorrect); "
        "count_sheet when it is ok and its tray id and item ids equal a truth sheet's; "
        "pack_label when it is ok and at least one label's lot (or item+lot) is in truth. "
        "Other ok reads (test-scenario sheets, lots like L-4471) are unscored (not a printed prop); "
        "failed count_sheet and pack_label reads are counted as failed, not scored. "
        "A scored read is correct when tray_tag: tray id equals a truth tray_id; "
        "count_sheet: items (id, expected, initial, closing) equal a truth sheet's; "
        "pack_label: every label's (item, lot) matches a truth label. accuracy = correct / scored. "
        "Live events carry no filename, so this is content matching, not per-file scoring.")
KINDS = ("count_sheet", "tray_tag", "pack_label")


def load_truth(path: Path = TRUTH) -> dict:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {"files": {}}


def _sheet_key(items) -> tuple:
    return tuple(sorted((str(i.get("item") or i.get("id")), i.get("expected"), i.get("initial"), i.get("closing"))
                        for i in items or []))


def is_correct(read: dict, truth: dict) -> bool:
    if not read.get("ok"):
        return False
    kind = read.get("kind")
    files = [f for f in truth.get("files", {}).values() if f.get("kind") == ("pack_labels" if kind == "pack_label" else kind)]
    if kind == "tray_tag":
        return read.get("tray") in {f.get("tray_id") for f in files}
    if kind == "count_sheet":
        key = _sheet_key(read.get("items"))
        return bool(key) and any(key == _sheet_key(f.get("items")) for f in files)
    if kind == "pack_label":
        labels = read.get("labels") or []
        known = {(str(l.get("item")).replace(" ", "_"), l.get("lot")) for f in files for l in f.get("labels", [])}
        return bool(labels) and all((l.get("item"), l.get("lot")) in known for l in labels)
    return False


def _sheet_truths(read: dict, truth: dict) -> list[dict]:
    ids = {str(i.get("item") or i.get("id")) for i in read.get("items") or []}
    return [f for f in truth.get("files", {}).values()
            if f.get("kind") == "count_sheet" and f.get("tray_id") == read.get("tray")
            and ids and ids == {i["id"] for i in f.get("items", [])}]


def _lots(truth: dict) -> set:
    return {(str(l.get("item")).replace(" ", "_"), l.get("lot")) for f in truth.get("files", {}).values()
            if f.get("kind") == "pack_labels" for l in f.get("labels", [])}


def status(read: dict, truth: dict) -> str:
    """scored, unscored or failed."""
    if read.get("kind") == "tray_tag":
        return "scored"
    if not read.get("ok"):
        return "failed"
    if read.get("kind") == "count_sheet":
        return "scored" if _sheet_truths(read, truth) else "unscored"
    if read.get("kind") == "pack_label":
        known = _lots(truth)
        lots = {l for _, l in known}
        return "scored" if any(l.get("lot") in lots or (l.get("item"), l.get("lot")) in known
                               for l in read.get("labels") or []) else "unscored"
    return "unscored"


def item_fields(read: dict, truth: dict) -> tuple[int, int]:
    """(items read right, items) against the best-matching truth sheet."""
    best = (0, 0)
    for f in _sheet_truths(read, truth):
        t = {i["id"]: (i.get("expected"), i.get("initial"), i.get("closing")) for i in f["items"]}
        good = sum(1 for i in read.get("items") or []
                   if t.get(str(i.get("item") or i.get("id"))) == (i.get("expected"), i.get("initial"), i.get("closing")))
        if best[1] == 0 or good > best[0]:
            best = (good, len(t))
    return best


def _r(x):
    return None if x is None else round(x)


def analyse(events: list[dict], truth: dict) -> dict:
    reads = [e for e in events if e.get("type") == "read" and isinstance(e.get("read"), dict)]
    by_kind = []
    for k in sorted({e["read"].get("kind") for e in reads} | set(KINDS), key=str):
        rs = [e["read"] for e in reads if e["read"].get("kind") == k]
        ok = sum(1 for r in rs if r.get("ok"))
        st = [status(r, truth) for r in rs]
        scored = [r for r, x in zip(rs, st) if x == "scored"]
        good = sum(1 for r in scored if is_correct(r, truth))
        fg = fn = 0
        for r in scored:
            if r.get("kind") == "count_sheet":
                g, n = item_fields(r, truth)
                fg, fn = fg + g, fn + n
        lat = [r["latency_ms"] for r in rs if isinstance(r.get("latency_ms"), (int, float))]
        by_kind.append({"kind": k, "n": len(rs), "ok": ok, "scored": len(scored), "unscored": st.count("unscored"),
                        "failed": st.count("failed") + (sum(1 for r in scored if not r.get("ok"))
                                                         if k == "tray_tag" else 0),
                        "correct": good, "accuracy": round(good / len(scored), 3) if scored else None,
                        "field_accuracy": round(fg / fn, 3) if fn else None, "field_items": fn,
                        "median_ms": _r(median(lat)), "p90_ms": _r(pct(lat, 90))})
    # per method, from attempts (falls back to the answering method when attempts is missing)
    att: dict[str, dict] = {}
    rescues = 0
    for e in reads:
        r = e["read"]
        a = r.get("attempts") or ([{"method": r["method"], "ok": r.get("ok"), "latency_ms": r.get("latency_ms")}]
                                  if r.get("method") else [])
        for x in a:
            m = att.setdefault(x.get("method") or "?", {"answered": 0, "attempted": 0, "failed": 0, "lat": []})
            m["attempted"] += 1
            if x.get("ok"):
                m["answered"] += 1
            else:
                m["failed"] += 1
            if isinstance(x.get("latency_ms"), (int, float)):
                m["lat"].append(x["latency_ms"])
        if r.get("ok") and r.get("method") == "gemini" and any(
                x.get("method") == "perceptron" and not x.get("ok") for x in a):
            rescues += 1
    by_method = [{"method": k, "answered": v["answered"], "attempted": v["attempted"], "failed": v["failed"],
                  "median_ms": _r(median(v["lat"]))} for k, v in sorted(att.items())]
    errs: dict[str, int] = {}
    for e in reads:
        r = e["read"]
        if not r.get("ok"):
            # keep the first reason only so "perceptron: X; gemini: X" groups per read
            err = str(r.get("error") or "unknown").split(";")[0][:80]
            errs[err] = errs.get(err, 0) + 1
    caps = [e for e in events if e.get("type") == "caption"]
    clat = [c["caption_latency_ms"] for c in caps if isinstance(c.get("caption_latency_ms"), (int, float))]
    start = tag_start(events)
    split: dict[str, int] = {}
    for e in reads:
        k = arm_kind(e, start)
        split[k] = split.get(k, 0) + 1
    all_lat = [e["read"]["latency_ms"] for e in reads if isinstance(e["read"].get("latency_ms"), (int, float))]
    return {"rule": RULE, "total": len(reads), "by_kind": by_kind, "by_method": by_method,
            "fallback_rescues": rescues, "errors": [{"error": k, "n": v} for k, v in sorted(errs.items(), key=lambda x: -x[1])],
            "captions": {"n": len(caps), "agrees": sum(1 for c in caps if c.get("agrees")), "median_ms": _r(median(clat))},
            "bench": BENCH, "by_arm": split, "median_ms": _r(median(all_lat)), "p90_ms": _r(pct(all_lat, 90))}


def _fmt(x, unit=""):
    return "no data" if x is None else f"{x}{unit}"


def build(data: dict, charts_dir: Path) -> dict:
    s = analyse(data["events"], load_truth())
    arms = ", ".join(f"{k} {v}" for k, v in sorted(s["by_arm"].items())) or "none"
    md = ["## Reading (OCR)", "",
          f"{s['total']} `read` events ({arms}). Reads do not depend on the arm: the camera and the vision calls are real "
          "even on a fake-arm run, so every read here is real camera data.", "",
          f"Scoring: {s['rule']}", "",
          "| Kind | Reads | ok | Scored | Unscored (not a printed prop) | Failed | Correct | Accuracy | Item fields right | Median ms | p90 ms |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for k in s["by_kind"]:
        acc = "no real data yet" if not k["scored"] else f"{k['accuracy']:.0%}"
        fa = "n/a" if k["field_accuracy"] is None else f"{k['field_accuracy']:.0%} of {k['field_items']}"
        md.append(f"| {k['kind']} | {k['n']} | {k['ok']} | {k['scored']} | {k['unscored']} | {k['failed']} | {k['correct']} | {acc} | {fa} | {_fmt(k['median_ms'])} | {_fmt(k['p90_ms'])} |")
    md += ["", f"Overall latency: median {_fmt(s['median_ms'], ' ms')}, p90 {_fmt(s['p90_ms'], ' ms')}.", "",
           "| Method (per attempt) | Attempted | Answered | Failed | Median ms |", "| --- | --- | --- | --- | --- |"]
    md += [f"| {m['method']} | {m['attempted']} | {m['answered']} | {m['failed']} | {_fmt(m['median_ms'])} |" for m in s["by_method"]]
    md += ["", f"Gemini rescued a failed Perceptron read {s['fallback_rescues']} time(s).", ""]
    if s["errors"]:
        md += ["Error reasons:", ""] + [f"- {e['n']} x {e['error']}" for e in s["errors"]] + [""]
    c = s["captions"]
    md += [f"Captions: {c['n']}, agree with the label {c['agrees']}, median latency {_fmt(c['median_ms'], ' ms')}.", "",
           f"Offline bench (separate from live reads): {s['bench']}"]
    ks = {k["kind"]: k for k in s["by_kind"]}
    pm = {m["method"]: m for m in s["by_method"]}

    def acc(k):
        r = ks[k]
        if not r["scored"]:
            return "no real data yet"
        fa = f", item fields {r['field_accuracy']:.0%} of {r['field_items']}" if r["field_accuracy"] is not None else ""
        return f"{r['correct']}/{r['scored']} correct ({r['accuracy']:.0%}), {r['unscored']} unscored{fa}"
    p, g = pm.get("perceptron"), pm.get("gemini")
    pg = "no real data yet" if not p else (f"Perceptron {p['answered']}/{p['attempted']} answered, median {_fmt(p['median_ms'], ' ms')}; "
         f"Gemini {g['answered']}/{g['attempted']} answered, median {_fmt(g['median_ms'], ' ms')}; {s['fallback_rescues']} rescues"
         if g else f"Perceptron {p['answered']}/{p['attempted']} answered, median {_fmt(p['median_ms'], ' ms')}; Gemini never called")
    numbers = [
        {"name": "Reads logged", "value": s["total"] or "no real data yet", "query": 'db.events.countDocuments({type:"read"})'},
        *[{"name": f"{k} OCR accuracy", "value": acc(k), "query": f'db.events.find({{type:"read","read.kind":"{k}"}})'}
          for k in KINDS],
        {"name": "Median read latency", "value": _fmt(s["median_ms"], " ms") if s["total"] else "no real data yet",
         "query": 'db.events.find({type:"read"},{"read.latency_ms":1})'},
        {"name": "Perceptron vs Gemini", "value": pg, "query": 'db.events.find({type:"read","read.attempts":{$exists:true}},{"read.attempts":1})'},
    ]
    notes = ["For the vision and voice chats:", ""]
    tt = ks["tray_tag"]
    if tt["n"]:
        qr = pm.get("qr")
        notes.append(f"- Tray tag: {tt['ok']}/{tt['n']} ok, {tt['correct']} match a known tray. "
                     + (f"QR answered {qr['answered']}/{qr['attempted']}; " if qr else "")
                     + "when QR fails (dim light), Perceptron text often returns nothing or an unknown tray. "
                       "Vision: make QR the primary read, keep text OCR as the fallback.")
    if g and g["attempted"]:
        s_rate = g["answered"] / g["attempted"]
        gnote = (f"- Gemini fallback ran {g['attempted']} time(s), answered {g['answered']}, rescued "
                 f"{s['fallback_rescues']} failed Perceptron read(s) (median {_fmt(g['median_ms'], ' ms')}). ")
        gnote += ("It rarely helps: when Perceptron fails the frame is usually the problem, so ask the person to re-aim."
                  if s_rate < 0.5 else "It is worth keeping as the second opinion.")
        notes.append(gnote)
    if s["errors"]:
        top = s["errors"][0]
        notes.append(f"- Most common failure: \"{top['error']}\" ({top['n']}). Voice: say what to fix (aim the camera, "
                     "check vision is up) rather than a generic \"can't read\".")
    if s["median_ms"]:
        notes.append(f"- Latency: median {s['median_ms']} ms, p90 {_fmt(s['p90_ms'], ' ms')}. A read plus speech should stay "
                     "under about 3 s; voice should say \"reading\" immediately while the call runs.")
    if c["n"]:
        notes.append(f"- Captions agree with the label {c['agrees']}/{c['n']}; dark frames give \"no visible action\", "
                     "so fix lighting or exposure before trusting captions as a second check.")
    cs = ks["count_sheet"]
    if cs["unscored"]:
        notes.append(f"- {cs['unscored']} count-sheet reads are not our printed props, so they are unscored. Print and read "
                     "the real sheets live to get an honest count-sheet number.")
    return {"title": "Reading", "summary": {k: s[k] for k in ("rule", "total", "by_kind", "by_method", "fallback_rescues",
            "errors", "captions", "bench")}, "markdown": "\n".join(md), "notes": "\n".join(notes), "numbers": numbers}
