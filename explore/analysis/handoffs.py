"""Handoffs: tries, successes, timing, misses and stops per item, lighting and skill source.

Real-arm rows only for the real table; fake and sim rows go in a separate table labeled simulation.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from explore.analysis.source import arm_kind, tag_start
from explore.analysis.stats import median, pct, wilson

TITLE = "Handoffs: what the arm did, per item, lighting and skill source"

DEFINITION = (
    "A try is one accepted handover command (a `command` event with action `handover` and accepted true), "
    "keyed by command_id; all later events with that command_id belong to it. A success is a try whose flow emitted "
    "`handed` (the arm reached the hand and offered the item) or `set_down` (sharp items such as the scalpel are "
    "set on a safe spot by design); the same two events ledger.stats counts. A miss is a "
    "`missed` event in the try (retries are the `retries` field on handed/missed). A stop is a `stopped` event in the "
    "try. Time is request_to_hand_s on the `handed` event. Lighting and skill_source come from the try's own events "
    "(skill_source 'none' when the flow ended before one was chosen). Rate range is the Wilson 95% interval."
)
NO_REAL = "no real data yet"
LEAK_S = 1.0  # no real SO-101 hands over this fast; faster tagged-real tries are leaked tests
MIN_TRIES = 10  # per method per item before the picker should lean on the numbers
HEAD = ["item", "lighting", "skill_source", "tries", "successes", "rate", "low", "high", "median_s", "p90_s",
        "retries", "misses", "stops"]


def tries_from(events: list[dict]) -> list[dict]:
    """One dict per accepted handover command_id."""
    by_cmd: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        if e.get("command_id"):
            by_cmd[e["command_id"]].append(e)
    out = []
    for cid, rows in by_cmd.items():
        cmds = [r for r in rows if r.get("type") == "command" and r.get("action") == "handover" and r.get("accepted")]
        if not cmds:
            continue
        flow = [r for r in rows if r.get("type") != "command"]
        handed = [r for r in flow if r["type"] in ("handed", "set_down")]
        miss = [r for r in flow if r["type"] == "missed"]
        light = next((r["lighting"] for r in flow + rows if r.get("lighting")), "unknown")
        src = next((r["skill_source"] for r in flow if r.get("skill_source")), "none")
        rets = [r.get("retries") or 0 for r in flow if r["type"] in ("handed", "missed")]
        out.append({
            "command_id": cid, "item": cmds[0].get("item") or "unknown", "lighting": light, "skill_source": src,
            "ok": bool(handed), "time": next((h["request_to_hand_s"] for h in handed
                                               if isinstance(h.get("request_to_hand_s"), (int, float))), None),
            "retries": max(rets) if rets else 0,
            "misses": [(m.get("step") or "?", m.get("say") or m.get("reason") or "?") for m in miss],
            "stopped": any(r["type"] == "stopped" for r in flow),
        })
    return out


def table(tries: list[dict], keys=("item", "lighting", "skill_source")) -> list[dict]:
    g: dict[tuple, list[dict]] = defaultdict(list)
    for t in tries:
        g[tuple(t[k] for k in keys)].append(t)
    rows = []
    for key, ts in sorted(g.items()):
        n, k = len(ts), sum(t["ok"] for t in ts)
        w = wilson(k, n)
        times = [t["time"] for t in ts if t["ok"] and t["time"] is not None]
        row = dict(zip(("item", "lighting", "skill_source"), ("all",) * 3))
        row.update(zip(keys, key))
        row.update({"tries": n, "successes": k, "rate": k / n, "low": w[0], "high": w[1],
                    "median_s": median(times), "p90_s": pct(times, 90),
                    "retries": sum(t["retries"] for t in ts), "misses": sum(len(t["misses"]) for t in ts),
                    "stops": sum(t["stopped"] for t in ts)})
        rows.append(row)
    return rows


def ranking(tries: list[dict]) -> list[dict]:
    rows = table(tries, ("item", "skill_source"))
    rows = [{"item": r["item"], "skill_source": r["skill_source"], "rate": r["rate"], "low": r["low"],
             "tries": r["tries"]} for r in rows]
    return sorted(rows, key=lambda r: (r["item"], -r["low"]))


def reasons(tries: list[dict]) -> list[dict]:
    c = Counter(f"{step}: {say}" for t in tries for step, say in t["misses"])
    return [{"reason": r, "n": n} for r, n in c.most_common()]


def verdict(events: list[dict], real: list[dict], start) -> tuple[bool, str]:
    """Trusted only if timings look like a real arm. Evidence gathered from the data itself."""
    hs = [e["request_to_hand_s"] for e in real if e.get("type") == "handed" and isinstance(e.get("request_to_hand_s"), (int, float))]
    if not hs:
        return False, "There are no real-tagged handed rows with a time, so there is nothing to trust yet."
    fh = [e["request_to_hand_s"] for e in events if e.get("type") == "handed" and arm_kind(e, start) == "fake"
          and isinstance(e.get("request_to_hand_s"), (int, float))]
    rm, fm = median(hs), median(fh)
    cases = Counter(e.get("case_id") for e in real if e.get("type") == "handed")
    if rm is not None and fm is not None and rm < 1.0 and abs(rm - fm) < 0.1:
        return False, (
            f"The {len(hs)} real-tagged handed rows have median {rm:.2f} s and span {min(hs):.2f}-{max(hs):.2f} s, "
            f"matching the fake arm's median {fm:.2f} s, with no misses or retries across {len(cases)} cases. "
            f"They are the test real_tries_are_recorded_fake_ones_are_not in controller/test_flows.py "
            f"(RecordingArm motion_s=0.1, auto_pull_s=0.2, fake_arm=False), which wrote to Atlas whenever the "
            f"tests ran with MONGODB_URI set; no real SO-101 hands over in 0.4 s.")
    if hs and max(hs) - min(hs) < 0.1 and len(hs) >= 5:
        return False, f"All {len(hs)} real handed times sit within {max(hs) - min(hs):.2f} s of each other, which no real arm does."
    return True, f"{len(hs)} real handed rows with median {rm:.2f} s and a normal spread."


def md_table(rows: list[dict]) -> list[str]:
    if not rows:
        return ["(no rows)", ""]
    f = lambda v, d=2: "-" if v is None else f"{v:.{d}f}"  # noqa: E731
    out = ["| item | lighting | skill | tries | ok | rate | 95% range | median s | p90 s | retries | misses | stops |",
           "| --- | --- | --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |"]
    for r in rows:
        out.append(f"| {r['item']} | {r['lighting']} | {r['skill_source']} | {r['tries']} | {r['successes']} | "
                   f"{r['rate'] * 100:.0f}% | {r['low'] * 100:.0f}-{r['high'] * 100:.0f}% | {f(r['median_s'])} | "
                   f"{f(r['p90_s'])} | {r['retries']} | {r['misses']} | {r['stops']} |")
    return out + [""]


def chart(rank: list[dict], path) -> bool:
    if not rank:
        return False
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = {"model": "#2a6fdb", "taught": "#d9731a", "none": "#8a8f98"}
    fig, ax = plt.subplots(figsize=(7, 0.5 * len(rank) + 1.6))
    for i, r in enumerate(rank):
        c = colors.get(r["skill_source"], "#8a8f98")
        ax.barh(i, r["rate"] * 100, color=c, height=0.55)
        hi = r["rate"] * 100 + 0
        ax.text(101, i, f"{r['rate'] * 100:.0f}% (low {r['low'] * 100:.0f}%, n={r['tries']})", va="center", fontsize=8)
    ax.set_yticks(range(len(rank)), [f"{r['item']} / {r['skill_source']}" for r in rank], fontsize=8)
    ax.set_xlim(0, 100)
    ax.invert_yaxis()
    ax.set_xlabel("handoff success rate, % (blue model, orange taught)")
    ax.set_title("Simulation: handoff success by item and skill source", fontsize=10, loc="left")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.subplots_adjust(right=0.62)
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return True


def build(data: dict, charts_dir) -> dict:
    events = data["events"]
    start = tag_start(events)
    real_ev = [e for e in events if arm_kind(e, start) == "real"]
    sim_ev = [e for e in events if arm_kind(e, start) in ("fake", "sim")]
    real_t, sim_t = tries_from(real_ev), tries_from(sim_ev)
    trusted, why = verdict(events, real_ev, start)
    # Tries handed over in under LEAK_S are test runs that leaked into Atlas, not the arm; once real tries
    # exist, drop the leaked ones and judge the rest alone.
    leaked = {t["command_id"] for t in real_t if t["time"] is not None and t["time"] < LEAK_S}
    rest = [t for t in real_t if t["command_id"] not in leaked]
    if leaked and rest:
        real_ev = [e for e in real_ev if e.get("command_id") not in leaked]
        real_t = rest
        trusted, why2 = verdict(events, real_ev, start)
        why = f"{len(leaked)} tries under {LEAK_S:g} s are left out as test runs (see below). {why2}"
    t_real, t_sim = table(real_t), table(sim_t)
    rank_real, rank_sim = ranking(real_t), ranking(sim_t)
    mr = reasons(real_t)
    ok_real = sum(t["ok"] for t in real_t)
    times = [t["time"] for t in real_t if t["ok"] and t["time"] is not None]
    handed_q = 'db.events.countDocuments({type:"handed", fake_arm:false})'
    # Untagged rows after the tags started: some controller build left fake_arm out (06:32 on Oct 18, voice,
    # 11 s pick to set-down). Possibly the real arm, but unproven, so shown apart and never in the numbers.
    untagged_ev = [e for e in events if start is not None and "fake_arm" not in e and (e.get("t") or 0) >= start
                   and not (e.get("sim") or e.get("sim_arm"))]
    untagged_t = tries_from(untagged_ev)
    summary = {"untagged_rows": len(untagged_ev), "untagged_tries": len(untagged_t),
               "untagged_table": table(untagged_t), "untagged_miss_reasons": reasons(untagged_t),
               "definition": DEFINITION, "real_rows": len(real_ev), "trusted": trusted, "why": why,
               "table": t_real, "sim_table": t_sim, "miss_reasons": mr, "method_ranking": rank_real,
               "sim_method_ranking": rank_sim, "real_tries": len(real_t), "sim_tries": len(sim_t)}
    charted = False
    try:
        charted = chart(rank_sim, charts_dir / "handoffs_sim.png")
    except Exception:
        pass
    label = "real" if trusted else "tagged real, suspect"
    md = ["**Definition.** " + DEFINITION, "",
          f"**Trusted: {'yes' if trusted else 'NO'}.** {why}", "",
          f"### Real arm ({label}): {len(real_ev)} rows, {len(real_t)} tries", ""]
    md += md_table(t_real)
    if not trusted:
        md += ["Do not quote these as real results. The pitch says \"no real data yet\".", ""]
    md += ["### Miss reasons (real-tagged)", ""] + ([f"- {m['reason']}: {m['n']}" for m in mr] or ["- none"]) + [""]
    if untagged_t:
        md += [f"### Untagged after tags started (possibly the real arm, unproven): {len(untagged_ev)} rows, "
               f"{len(untagged_t)} tries", "",
               "These rows carry no `fake_arm` field, so the controller that wrote them did not say which arm it ran. "
               "Not counted as real. A `set_down` counts as a success here, including \"No hand ... safe spot\".", ""]
        md += md_table(table(untagged_t))
        md += ["Miss reasons: " + ("; ".join(f"{m['reason']} ({m['n']})" for m in reasons(untagged_t)) or "none"), ""]
    md += [f"### Simulation (fake and sim arms, never real): {len(sim_ev)} rows, {len(sim_t)} tries", ""]
    md += md_table(t_sim)
    md += ["### Simulation miss reasons", ""] + ([f"- {m['reason']}: {m['n']}" for m in reasons(sim_t)[:10]] or ["- none"]) + [""]
    if charted:
        md += ["![Simulation handoff success](media/data/handoffs_sim.png)", ""]

    def rk(rows):
        return [f"- {r['item']} / {r['skill_source']}: {r['rate'] * 100:.0f}% of {r['tries']}, Wilson low {r['low'] * 100:.0f}%"
                for r in rows] or ["- none"]
    notes = [
        f"Real-arm data is {'usable' if trusted else 'NOT trustworthy'}: {why}", "",
        "Queries (mongo shell):", "",
        f"- `{handed_q}` real handed rows",
        '- `db.events.find({type:"command", action:"handover", accepted:true, fake_arm:false})` real tries',
        '- `db.events.find({command_id:"<id>"}).sort({t:1})` one try',
        '- `db.events.find({type:"missed", fake_arm:false}, {step:1, say:1, item:1, skill_source:1})` misses', "",
        "Python: `from explore.analysis.source import load, tag_start, arm_kind`; keep events with "
        "`arm_kind(e, tag_start(events)) == 'real'`, then `explore.analysis.handoffs.tries_from(rows)` and `ranking(tries)`.", "",
        "Method ranking per item, by Wilson lower bound (real-tagged):", *rk(rank_real), "",
        "Same ranking from simulation (not real, shows the shape only):", *rk(rank_sim), "",
        f"Picker default: with fewer than {MIN_TRIES} trusted real tries per method on an item, or when the real data is not "
        "trusted (now), use `model` for every item (the controller's --skills default) and fall back to `taught` only "
        "where model has missed. Do not pick a method from a rate whose range is wide."]
    nums = [
        {"name": "Real handoff success rate",
         "value": f"{ok_real}/{len(real_t)} ({ok_real / len(real_t) * 100:.0f}%)" if trusted and real_t else NO_REAL,
         "query": handed_q},
        {"name": "Real median request-to-hand (s)",
         "value": f"{median(times):.2f}" if trusted and times else NO_REAL,
         "query": 'db.events.find({type:"handed", fake_arm:false}, {request_to_hand_s:1})'},
        {"name": "Simulated handoff tries", "value": str(len(sim_t)),
         "query": 'db.events.countDocuments({type:"command", action:"handover", accepted:true, fake_arm:true})'},
    ]
    return {"title": TITLE, "summary": summary, "markdown": "\n".join(md), "notes": "\n".join(notes), "numbers": nums}
