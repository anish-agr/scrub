from pathlib import Path

from explore.analysis import handoffs as H
from explore.analysis.stats import wilson

T0 = 1_000_000.0
_n = [0]


def ev(type_, cid, fake=False, t=None, **kw):
    _n[0] += 1
    base = {"type": type_, "command_id": cid, "item": "hemostat", "step": "x", "lighting": "normal",
            "t": t if t is not None else T0 + _n[0], "request_to_hand_s": None, "retries": None}
    if fake is not None:
        base["fake_arm"] = fake
    return {**base, **kw}


def flow(cid, fake=False, ok=True, item="hemostat", src="model", secs=5.0, stop=False, miss=None):
    rows = [ev("command", cid, fake, action="handover", accepted=True, item=item)]
    rows.append(ev("step", cid, fake, item=item, skill_source=src))
    if miss:
        rows.append(ev("missed", cid, fake, item=item, skill_source=src, step="picking", say=miss, retries=1))
    if stop:
        rows.append(ev("stopped", cid, fake, item=item, skill_source=src))
    if ok:
        rows.append(ev("handed", cid, fake, item=item, skill_source=src, request_to_hand_s=secs, retries=0))
    return rows


def fixture():
    rows = [ev("step", "tag", True, t=T0 - 5)]  # tags start at T0-5
    rows += [ev("step", "old", None, t=T0 - 100, )]  # pretag, no fake_arm
    rows += flow("r1", secs=4.0) + flow("r2", secs=6.0) + flow("r3", ok=False, miss="Missed it.", stop=True)
    rows += flow("r4", item="scalpel", src="taught", secs=8.0)
    rows += flow("f1", fake=True, secs=0.4) + flow("f2", fake=True, secs=0.4, src="taught")
    rows += [ev("command", "no", False, action="handover", accepted=False, item="hemostat")]
    return rows


def test_real_only_and_grouping():
    data = {"events": fixture(), "episodes": [], "thermal": [], "read_at": T0}
    out = H.build(data, Path("/tmp"))
    s = out["summary"]
    assert s["real_rows"] > 0
    tabs = {(r["item"], r["skill_source"]): r for r in s["table"]}
    hm = tabs[("hemostat", "model")]
    assert hm["tries"] == 3 and hm["successes"] == 2 and hm["misses"] == 1 and hm["stops"] == 1
    assert abs(hm["low"] - wilson(2, 3)[0]) < 1e-9 and abs(hm["high"] - wilson(2, 3)[1]) < 1e-9
    assert hm["median_s"] == 5.0 and hm["p90_s"] == 5.8
    assert ("scalpel", "taught") in tabs
    assert all(r["skill_source"] != "taught" or r["item"] == "scalpel" for r in s["table"])  # fake taught not mixed in
    assert sum(r["tries"] for r in s["sim_table"]) == 2
    assert s["miss_reasons"] == [{"reason": "picking: Missed it.", "n": 1}]
    assert s["trusted"] is True


def test_unaccepted_command_is_not_a_try():
    real = [e for e in fixture() if e["command_id"] == "no"]
    assert H.tries_from(real) == []


def test_fake_looking_timings_are_not_trusted():
    rows = [ev("step", "tag", True, t=T0 - 5)]
    for i in range(6):
        rows += flow(f"r{i}", secs=0.42) + flow(f"f{i}", fake=True, secs=0.42)
    data = {"events": rows, "episodes": [], "thermal": [], "read_at": T0}
    out = H.build(data, Path("/tmp"))
    assert out["summary"]["trusted"] is False
    assert out["numbers"][0]["value"] == "no real data yet"


def test_ranking_orders_by_wilson_low():
    rows = [ev("step", "tag", True, t=T0 - 5)]
    for i in range(10):
        rows += flow(f"m{i}", src="model", ok=i < 9)
    rows += flow("t0", src="taught")
    r = H.ranking(H.tries_from(rows))
    assert [x["skill_source"] for x in r] == ["model", "taught"]


def test_leaked_test_tries_drop_out_once_real_tries_exist():
    rows = [ev("step", "tag", True, t=T0 - 5)]
    for i in range(6):
        rows += flow(f"leak{i}", secs=0.42)
    for i in range(4):
        rows += flow(f"arm{i}", secs=6.0 + i)
    out = H.build({"events": rows, "episodes": [], "thermal": [], "read_at": T0}, Path("/tmp"))
    s = out["summary"]
    assert s["trusted"] is True and s["real_tries"] == 4 and "6 tries under 1 s" in s["why"]


def test_untagged_rows_after_tags_are_shown_apart():
    rows = [ev("step", "tag", True, t=T0 - 5)] + flow("u1", secs=9.0)
    for r in rows[1:]:
        r.pop("fake_arm", None)
    s = H.build({"events": rows, "episodes": [], "thermal": [], "read_at": T0}, Path("/tmp"))["summary"]
    assert s["untagged_tries"] == 1 and s["real_tries"] == 0 and s["untagged_table"][0]["successes"] == 1
