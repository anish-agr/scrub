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


LIFECYCLE = {"phase", "control", "episode_start", "episode_end", "episode_saved", "episode_discarded",
             "grasp_start", "grasp_end", "claw_closed_empty", "session_end"}


def episodes_section(rows: list[dict], motors: list) -> list[str]:
    """Per episode: duration, grasps, gripper load during grasps, temperature rise per motor."""
    ev = lambda name: [r for r in rows if r.get("kind") == "event" and r.get("event") == name]  # noqa: E731
    starts, ends, saved = ev("episode_start"), ev("episode_end"), ev("episode_saved")
    grasps, empties = ev("grasp_start"), ev("claw_closed_empty")
    if not (starts or grasps or empties):
        return []
    samples = [r for r in rows if r.get("kind") == "sample"]
    out = ["", "## Episodes and grasps", "", f"Total grasps: {len(grasps)}; claw closed on nothing: {len(empties)}", ""]
    if starts:
        out += ["| session | episode | outcome | handoff | lift cm | pulled out | duration s | grasps | mean grip load in grasps | peak grip load | "
                + " | ".join(f"{m} rise C" for m in motors) + " |", "|" + "---|" * (10 + len(motors))]
    for st in starts:
        sess = st.get("session")
        en = next((e for e in ends if e.get("session") == sess and e["t"] >= st["t"]), None)
        t_end = en["t"] if en else (samples[-1]["t"] if samples else st["t"])
        nxt = [s["t"] for s in starts if s.get("session") == sess and s["t"] > st["t"]]
        t_end = min(t_end, nxt[0]) if nxt else t_end
        sv = next((e for e in saved if e.get("session") == sess and st["t"] <= e["t"] <= t_end + 120
                   and e.get("episode") == st.get("episode")), None)
        outcome = ("saved" if sv else f"discarded ({en.get('reason')})" if en and en.get("reason") not in ("done", "stop", None)
                   else en.get("reason") if en else "open")
        gs = [g for g in grasps if g.get("session") == sess and st["t"] <= g["t"] <= t_end]
        ge = [g for g in ev("grasp_end") if g.get("session") == sess and st["t"] <= g["t"] <= t_end + 5]
        loads = []
        for g in gs:  # gripper samples between a grasp's start and its end
            e = next((x for x in ge if x["t"] >= g["t"]), None)
            loads += [abs((r["motors"].get("gripper") or {}).get("load") or 0) for r in samples
                      if r.get("session") == sess and g["t"] <= r["t"] <= (e["t"] if e else t_end)]
        peak = max([x.get("peak_load") or 0 for x in ge] + loads or [0])
        win = [r for r in samples if r.get("session") == sess and st["t"] <= r["t"] <= t_end]
        rises = []
        for m in motors:
            temps = [(r["motors"].get(m) or {}).get("temp") for r in win]
            temps = [x for x in temps if x is not None]
            rises.append(f"{temps[-1] - temps[0]:+d}" if len(temps) >= 2 else "-")
        dur = (en or {}).get("duration_s")
        e_ = en or {}
        handoff = "-" if "handoff_success" not in e_ else ("SUCCESS" if e_["handoff_success"] else
                  "no grab" if not e_.get("grasps") else "no lift" if not e_.get("lifted") else "not pulled")
        lift_cm = f"{e_['lift_m'] * 100:.0f}" if e_.get("lift_m") is not None else "-"
        out.append(f"| {sess} | {st.get('episode')} | {outcome} | {handoff} | {lift_cm} | {e_.get('pulled', '-')} | "
                   f"{dur if dur is not None else '-'} | "
                   f"{(en or {}).get('grasps', len(gs))} | {f'{np.mean(loads):.0f}' if loads else '-'} | "
                   f"{peak if (loads or ge) else '-'} | " + " | ".join(rises) + " |")
    ends_h = [e for e in ends if "handoff_success" in e]
    if ends_h:
        ok = sum(1 for e in ends_h if e["handoff_success"])
        out += ["", f"Handoffs (grab, lift >= 3 cm, pulled out by hand): {ok} of {len(ends_h)} episodes."]
    if grasps:
        durs = [g.get("duration_s") for g in ev("grasp_end") if g.get("duration_s") is not None]
        if durs:
            out += ["", f"Grasp duration: mean {np.mean(durs):.1f} s, longest {max(durs):.1f} s over {len(durs)} released grasps."]
    return out


def analyze(rows: list[dict]) -> str:
    samples = [r for r in rows if r.get("kind") == "sample"]
    out = [f"# Arm thermal report", "",
           f"{len(rows)} rows, {len(samples)} samples, sessions: {', '.join(sorted({r['session'] for r in rows}))}", ""]
    if not samples:
        return "\n".join(out + ["No samples yet: run the recorder (explore/arm_session.py) with MONGODB_URI set."])
    t0, t1 = samples[0]["t"], samples[-1]["t"]
    out += [f"Span {time.strftime('%H:%M', time.localtime(t0))} to {time.strftime('%H:%M', time.localtime(t1))} "
            f"({(t1 - t0) / 60:.1f} min)", ""]
    motors = list(samples[0]["motors"])
    series = {m: defaultdict(list) for m in motors}
    for r in samples:
        for m in motors:
            v = r["motors"].get(m) or {}
            if v.get("temp") is None:
                continue
            s = series[m]
            s["t"].append(r["t"]); s["temp"].append(v["temp"]); s["load"].append(abs(v.get("load") or 0))
            s["cur"].append(v.get("current") or 0); s["pos"].append(v.get("pos") or 0)
            s["phase"].append(r.get("phase") or "?"); s["held"].append(bool(v.get("held")))

    out += ["## Per motor", "", "| motor | start C | end C | peak C | mean C/min | C/min holding still | C/min moving | "
            "mean abs load | mean current mA | heat vs load r |", "|---|---|---|---|---|---|---|---|---|---|"]
    ranking = []
    window_stats = {}
    for m, s in series.items():
        if len(s["t"]) < 3:
            continue
        t, temp = np.array(s["t"]), np.array(s["temp"])
        wins = []
        k = 0
        while k < len(t):
            j = np.searchsorted(t, t[k] + WINDOW_S)
            if j - k >= 5:
                rate = slope_per_min(t[k:j], temp[k:j])
                if rate is not None:
                    moved = float(np.ptp(np.array(s["pos"][k:j])))
                    phases = s["phase"][k:j]
                    wins.append({"rate": rate, "load": float(np.mean(s["load"][k:j])),
                                 "cur": float(np.mean(s["cur"][k:j])) * 6.5, "still": moved < STILL_DEG,
                                 "phase": max(set(phases), key=phases.count), "t": float(t[k])})
            k = j if j > k else k + 1
        window_stats[m] = wins
        rates = [w["rate"] for w in wins]
        still = [w["rate"] for w in wins if w["still"]]
        moving = [w["rate"] for w in wins if not w["still"]]
        r = (float(np.corrcoef([w["load"] for w in wins], rates)[0, 1])
             if len(wins) >= 3 and np.std(rates) > 0 and np.std([w["load"] for w in wins]) > 0 else None)
        fmt = lambda x: "-" if x is None or (isinstance(x, list) and not x) else f"{np.mean(x):.2f}" if isinstance(x, list) else f"{x:.2f}"  # noqa: E731
        out.append(f"| {m} | {temp[0]} | {temp[-1]} | {temp.max()} | {fmt(rates)} | {fmt(still)} | {fmt(moving)} | "
                   f"{np.mean(s['load']):.0f} | {np.mean(s['cur']) * 6.5:.0f} | {fmt(r)} |")
        ranking.append((float(temp.max()), float(np.mean(rates)) if rates else 0.0, m, still, moving, r,
                        float(np.mean(s["load"]))))

    out += ["", "## Heating by phase (mean C/min over windows)", "", "| motor | " + " | ".join(
        ph := sorted({w["phase"] for ws in window_stats.values() for w in ws})) + " |", "|---|" + "---|" * len(ph)]
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
            bins[int(p // 20) * 20].append(l)
        out += ["", "## Gravity: shoulder_lift abs load by angle", "", "| angle (deg) | mean abs load | samples |", "|---|---|---|"]
        out += [f"| {b} to {b + 20} | {np.mean(v):.0f} | {len(v)} |" for b, v in sorted(bins.items())]

    cooling = [r for r in rows if r.get("kind") in ("cooling", "idle") and r.get("temps")]
    if len(cooling) >= 3:
        out += ["", "## Cooling with torque off", ""]
        tt = [r["t"] for r in cooling]
        for key in cooling[0]["temps"]:
            vals = [r["temps"].get(key) for r in cooling]
            if None not in vals:
                rate = slope_per_min(tt, vals)
                out.append(f"- motor {key}: {vals[0]} to {vals[-1]} C, {rate:.2f} C/min" if rate is not None else f"- {key}: -")

    out += episodes_section(rows, motors)

    events = [r for r in rows if r.get("kind") == "event" and r.get("event") not in LIFECYCLE]
    if events:
        counts = defaultdict(int)
        for e in events:
            counts[(e.get("event"), e.get("motor"))] += 1
        out += ["", "## Guard events", ""] + [f"- {ev}{' ' + mo if mo else ''}: {n}" for (ev, mo), n in sorted(counts.items())]

    out += ["", "## Likeliest heat sources (ranked by peak temperature, then heating rate)", ""]
    for peak, rate, m, still, moving, r, load in sorted(ranking, reverse=True):
        why = []
        if still and moving and np.mean(still) > np.mean(moving) + 0.1:
            why.append("heats faster holding still than moving: holding torque (gravity or pressing into a stop)")
        if r is not None and r > 0.5:
            why.append(f"heating tracks load (r={r:.2f}): mechanical load or a blocked joint")
        if m == "gripper" and load > 200:
            why.append("gripper loaded on average: closing past the object or on itself")
        if m in ("shoulder_lift", "elbow_flex") and load > 200:
            why.append("big gravity joint carrying load: rest it folded, counterbalance, or lower holding time")
        if not why:
            why.append("no strong load link: check idle self-heating (powered-idle motors sit near 45 C)")
        out.append(f"1. **{m}**: peak {peak:.0f} C, {rate:.2f} C/min. " + "; ".join(why))
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
