"""What made the arm hot? Reads explore/thermal_log.py rows and writes a short markdown report.

  .venv/bin/python explore/thermal_analyze.py                    # latest recorder session, from MongoDB
  .venv/bin/python explore/thermal_analyze.py --hours 6          # every session in the last 6 hours
  .venv/bin/python explore/thermal_analyze.py --session <id>     # one session
  .venv/bin/python explore/thermal_analyze.py --local            # read ~/scrub-logs/thermal instead of MongoDB
  ... --out report.md

Per motor: start/end/peak temperature, heating rate (deg C per minute, from 60 s windows) and what
it tracked: |load|, current, whether the joint was moving or holding still, and which phase
(recording, resetting, preview, teleop). Plus cooling rates with torque off, gravity load on
shoulder_lift by angle, guard events, and a ranked list of the likeliest heat sources.
Reports stay separate per session; windows never cross a phase change or a >5 s outage.
A window needs at least 54 s of coverage. Missing current/position is unknown, not zero.
"""
from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

import thermal_log as T

WINDOW_S = 60.0
MIN_WINDOW_S = 54.0  # allow sampling jitter, not seconds extrapolated to a minute
MAX_GAP_S = 5.0      # never fit across a telemetry outage
STILL_DEG = 1.0  # a joint that moved less than this in a window was holding still


def load_rows(a) -> list[dict]:
    if a.local:
        rows = [json.loads(line) for p in sorted(T.DIR.glob("*.jsonl")) for line in p.read_text().splitlines() if line]
    else:
        coll = T._collection()
        q: dict = {}
        if a.session:
            q["session"] = a.session
        elif a.hours:
            q["t"] = {"$gte": time.time() - a.hours * 3600}
        else:
            last = coll.find_one({"kind": "sample"}, sort=[("t", -1)])
            q["session"] = last["session"] if last else None
        rows = list(coll.find(q, {"_id": 0}).sort("t", 1))
    if a.session:
        rows = [r for r in rows if r.get("session") == a.session]
    elif a.hours and a.local:
        rows = [r for r in rows if r["t"] >= time.time() - a.hours * 3600]
    return rows


def slope_per_min(t, y):
    if len(t) < 3 or t[-1] - t[0] < 10:
        return None
    return float(np.polyfit(np.asarray(t) - t[0], np.asarray(y, float), 1)[0] * 60)


def mean_valid(values):
    values = [v for v in values if v is not None and np.isfinite(v)]
    return float(np.mean(values)) if values else None


def correlation(x, y):
    pairs = [(a, b) for a, b in zip(x, y) if a is not None and b is not None
             and np.isfinite(a) and np.isfinite(b)]
    if len(pairs) < 3:
        return None
    a, b = np.array(pairs).T
    if np.std(a) < 1e-9 or np.std(b) < 1e-9:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def heating_windows(s):
    """Non-overlapping windows within one session, phase and continuous sample stream."""
    t = np.array(s["t"])
    cuts = [0] + [i for i in range(1, len(t))
                  if s["phase"][i] != s["phase"][i - 1] or t[i] - t[i - 1] > MAX_GAP_S] + [len(t)]
    wins = []
    for start, end in zip(cuts, cuts[1:]):
        k = start
        while k < end:
            j = min(end, int(np.searchsorted(t, t[k] + WINDOW_S, side="right")))
            if j - k >= 5 and t[j - 1] - t[k] >= MIN_WINDOW_S:
                rate = slope_per_min(t[k:j], s["temp"][k:j])
                positions = s["pos"][k:j]
                still = (float(np.ptp(positions)) < STILL_DEG
                         if all(np.isfinite(p) for p in positions) else None)
                cur = mean_valid(s["cur"][k:j])
                wins.append({"rate": rate, "load": mean_valid(s["load"][k:j]),
                             "cur": cur * 6.5 if cur is not None else None,
                             "still": still, "phase": s["phase"][k], "t": float(t[k])})
            k = j if j > k else k + 1
    return wins


def experiment_report(rows):
    """Ad-hoc holds have temperatures and mA, not recorder motor samples."""
    groups = defaultdict(list)
    for row in rows:
        if row.get("kind") == "experiment":
            groups[row.get("phase", "?")].append(row)
    out = []
    for phase, group in sorted(groups.items()):
        out += [f"## Experiment: {phase}", "", "OLS rates over this experiment; early/late = first/last 60 s.", "",
                "| motor | start C | end C | peak C | whole-run C/min | early C/min | late C/min | current mA range |",
                "|---|---|---|---|---|---|---|---|"]
        for m in T.NAMES:
            pairs = [(r["t"], r.get("temps", {}).get(m)) for r in group]
            pairs = [(t, v) for t, v in pairs if v is not None]
            if not pairs:
                continue
            t, temp = zip(*pairs)
            rates = []
            for subset in (pairs, [(x, y) for x, y in pairs if x <= t[0] + WINDOW_S],
                           [(x, y) for x, y in pairs if x >= t[-1] - WINDOW_S]):
                rate = slope_per_min(*zip(*subset)) if subset else None
                rates.append("-" if rate is None else f"{rate:.2f}")
            currents = [r.get("current_mA", {}).get(m) for r in group]
            currents = [c for c in currents if c is not None]
            current = f"{min(currents)} to {max(currents)}" if currents else "-"
            out.append(f"| {m} | {temp[0]} | {temp[-1]} | {max(temp)} | " + " | ".join(rates) + f" | {current} |")
        out += ["", "Reported zero current is not proof of zero winding/driver losses; this is an association, not a causal test.", ""]
    return out


def analyze(rows: list[dict]) -> str:
    rows = sorted(rows, key=lambda r: r["t"])
    sessions = sorted({r["session"] for r in rows})
    if len(sessions) > 1:
        # A restart may change settings, temperature or pose. Never fit across it.
        return "# Arm thermal reports by session\n\nRates are never fitted across session boundaries.\n\n" + "\n".join(
            analyze([r for r in rows if r["session"] == sid]) for sid in sessions)
    samples = [r for r in rows if r.get("kind") == "sample"]
    out = [f"# Arm thermal report", "",
           f"{len(rows)} rows, {len(samples)} samples, sessions: {', '.join(sorted({r['session'] for r in rows}))}", ""]
    out += experiment_report(rows)
    if not samples:
        return "\n".join(out + ["No recorder samples in this session."]) + "\n"
    t0, t1 = samples[0]["t"], samples[-1]["t"]
    out += [f"Span {time.strftime('%H:%M', time.localtime(t0))} to {time.strftime('%H:%M', time.localtime(t1))} "
            f"({(t1 - t0) / 60:.1f} min)", ""]
    motors = sorted({m for r in samples for m in r["motors"]})
    series = {m: defaultdict(list) for m in motors}
    for r in samples:
        for m in motors:
            v = r["motors"].get(m) or {}
            if v.get("temp") is None:
                continue
            s = series[m]
            s["t"].append(r["t"]); s["temp"].append(v["temp"])
            s["load"].append(abs(v["load"]) if v.get("load") is not None else float("nan"))
            s["cur"].append(v["current"] if v.get("current") is not None else float("nan"))
            s["pos"].append(v["pos"] if v.get("pos") is not None else float("nan"))
            s["phase"].append(r.get("phase") or "?"); s["held"].append(bool(v.get("held")))

    out += ["## Per motor", "", "| motor | start C | end C | peak C | mean C/min | C/min holding still | C/min moving | "
            "mean abs load | mean current mA | heat vs load r | heat vs current r |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    ranking = []
    window_stats = {}
    for m, s in series.items():
        if len(s["t"]) < 3:
            continue
        temp = np.array(s["temp"])
        wins = heating_windows(s)
        window_stats[m] = wins
        rates = [w["rate"] for w in wins]
        still = [w["rate"] for w in wins if w["still"] is True]
        moving = [w["rate"] for w in wins if w["still"] is False]
        r = correlation([w["load"] for w in wins], rates)
        current_r = correlation([w["cur"] for w in wins], rates)
        fmt = lambda x: "-" if x is None or (isinstance(x, list) and not x) else f"{np.mean(x):.2f}" if isinstance(x, list) else f"{x:.2f}"  # noqa: E731
        out.append(f"| {m} | {temp[0]} | {temp[-1]} | {temp.max()} | {fmt(rates)} | {fmt(still)} | {fmt(moving)} | "
                    f"{fmt(mean_valid(s['load']))} | {fmt(mean_valid([c * 6.5 for c in s['cur']]))} | {fmt(r)} | {fmt(current_r)} |")
        ranking.append((float(temp.max()), mean_valid(rates), m, still, moving, r,
                        mean_valid(s["load"]), current_r))

    if not any(window_stats.values()):
        out += ["", "Insufficient continuous coverage for 60 s windows (minimum 54 s). No heating-rate, phase, holding/moving or correlation conclusion is supported."]

    ph = sorted({w["phase"] for ws in window_stats.values() for w in ws})
    if ph:
        out += ["", "## Heating by phase (mean C/min over windows)", "", "| motor | " + " | ".join(ph) + " |",
                "|---|" + "---|" * len(ph)]
        for m, ws in window_stats.items():
            cells = []
            for p in ph:
                v = [w["rate"] for w in ws if w["phase"] == p]
                cells.append(f"{np.mean(v):.2f} ({len(v)})" if v else "-")
            out.append(f"| {m} | " + " | ".join(cells) + " |")

    if "shoulder_lift" in series and series["shoulder_lift"]["t"]:
        s = series["shoulder_lift"]
        bins = defaultdict(list)
        for p, l in zip(s["pos"], s["load"]):
            if np.isfinite(p) and np.isfinite(l):
                bins[int(p // 20) * 20].append(l)
        out += ["", "## Gravity: shoulder_lift abs load by angle", "", "| angle (deg) | mean abs load | samples |", "|---|---|---|"]
        out += [f"| {b} to {b + 20} | {np.mean(v):.0f} | {len(v)} |" for b, v in sorted(bins.items())]

    cooling = [r for r in rows if r.get("kind") in ("cooling", "idle") and r.get("temps")]
    if len(cooling) >= 3:
        out += ["", "## Cooling / idle (torque state not inferred)", ""]
        tt = [r["t"] for r in cooling]
        for key in cooling[0]["temps"]:
            vals = [r["temps"].get(key) for r in cooling]
            if None not in vals:
                rate = slope_per_min(tt, vals)
                out.append(f"- motor {key}: {vals[0]} to {vals[-1]} C, {rate:.2f} C/min" if rate is not None else f"- {key}: -")

    events = [r for r in rows if r.get("kind") == "event"]
    if events:
        counts = defaultdict(int)
        for e in events:
            counts[(e.get("event"), e.get("motor"))] += 1
        out += ["", "## Guard events", ""] + [f"- {ev}{' ' + mo if mo else ''}: {n}" for (ev, mo), n in sorted(counts.items())]

    out += ["", "## Motor ranking (peak temperature, then heating rate; associations only)", ""]
    for peak, rate, m, still, moving, r, load, current_r in sorted(
            ranking, key=lambda x: (x[0], x[1] if x[1] is not None else -float("inf"), x[2]), reverse=True):
        why = []
        if still and moving and np.mean(still) > np.mean(moving) + 0.1:
            why.append("heats faster holding still than moving; check holding torque, starting temperature and thermal lag")
        if r is not None and r > 0.5:
            why.append(f"heating tracks load (r={r:.2f}): mechanical load or a blocked joint")
        if current_r is not None and current_r > 0.5:
            why.append(f"heating tracks reported current (r={current_r:.2f})")
        if m == "gripper" and load is not None and load > 200:
            why.append("gripper loaded on average: closing past the object or on itself")
        if m in ("shoulder_lift", "elbow_flex") and load is not None and load > 200:
            why.append("big gravity joint carrying load: rest it folded, counterbalance, or lower holding time")
        if not why:
            why.append("insufficient varying windows to assess load/current" if r is None and current_r is None
                       else "no strong contemporaneous load/current link; not evidence of a particular heat source")
        out.append(f"1. **{m}**: peak {peak:.0f} C, {fmt(rate)} C/min. " + "; ".join(why))
    return "\n".join(out) + "\n"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--session")
    p.add_argument("--hours", type=float)
    p.add_argument("--local", action="store_true")
    p.add_argument("--out")
    a = p.parse_args()
    report = analyze(load_rows(a))
    if a.out:
        Path(a.out).write_text(report)
        print(f"wrote {a.out}")
    else:
        print(report)


if __name__ == "__main__":
    main()
