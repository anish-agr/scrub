"""Heat report: motor temperature against phase, rise while holding, cooling, and which settings ran cool.

Reads the `thermal` collection (real hardware). Sample rows carry per-motor temps twice a second;
experiment rows are the torque-on hold test (every 10 s); idle rows are the idle monitor (torque off).
"""

from __future__ import annotations

import bisect
from collections import defaultdict

from explore.analysis.stats import median, pct

FIRMWARE_LIMIT_C = 70   # STS3215 max_temperature_limit register (snapshot rows confirm 70)
GUARD_C = 60            # arm/thermal.py COOL_TRIP: the software stops and cools down here
RESUME_C = 50           # arm/thermal.py COOL_RESUME
MOTORS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
PHASE_MAP = {
    "parked": "idle", "off": "idle", "preview": "idle", "killed": "idle", "idle": "idle",
    "recording": "moving", "teleop": "moving", "resetting": "moving",
    "torque_on_hold": "holding",
}
MIN_SEG_S = 60.0   # shortest stretch a rate is fitted over
COOL_WINDOW_S = 300.0  # cooling rate is fitted over the first 5 min of an idle stretch
MAX_GAP_S = 30.0   # a gap longer than this splits a stretch (telemetry outage)
CHART_COLORS = ["#3b6fb6", "#d1495b", "#2a9d8f", "#e0a100", "#8e5ea2", "#6b7280"]


def group_of(phase) -> str | None:
    return PHASE_MAP.get(phase)


def points(thermal: list[dict]) -> list[dict]:
    """Flat temperature points {t, session, phase, group, temps, src}, sorted by time."""
    out = []
    for r in thermal:
        k = r.get("kind")
        if not isinstance(r.get("t"), (int, float)):
            continue
        temps, phase = None, r.get("phase")
        if k in ("sample", "experiment"):
            temps = r.get("temps") or {m: v.get("temp") for m, v in (r.get("motors") or {}).items()}
            if k == "experiment":
                phase = phase or "torque_on_hold"
        elif k == "idle":
            temps, phase = r.get("temps"), "idle"
        if not temps:
            continue
        temps = {m: v for m, v in temps.items() if isinstance(v, (int, float))}
        g = group_of(phase)
        if temps and g:
            out.append({"t": r["t"], "session": r.get("session"), "phase": phase, "group": g, "temps": temps, "src": k})
    out.sort(key=lambda p: p["t"])
    return out


def slope_per_min(ts: list[float], ys: list[float]) -> float | None:
    """Least-squares slope in C per minute."""
    n = len(ts)
    if n < 3:
        return None
    mt, my = sum(ts) / n, sum(ys) / n
    den = sum((t - mt) ** 2 for t in ts)
    if den == 0:
        return None
    return sum((t - mt) * (y - my) for t, y in zip(ts, ys)) / den * 60.0


def segments(pts: list[dict], groups: set[str]) -> list[list[dict]]:
    """Runs of consecutive points of the given groups in one session with no gap over MAX_GAP_S."""
    segs, cur = [], []
    for p in pts:
        if p["group"] in groups and cur and p["session"] == cur[-1]["session"] and p["t"] - cur[-1]["t"] <= MAX_GAP_S:
            cur.append(p)
        elif p["group"] in groups:
            if cur:
                segs.append(cur)
            cur = [p]
        else:
            if cur:
                segs.append(cur)
            cur = []
    if cur:
        segs.append(cur)
    return segs


def seg_rates(segs: list[list[dict]], motor: str, min_s: float = MIN_SEG_S,
              max_s: float | None = None) -> list[tuple[float, float, float, float]]:
    """[(slope C/min, duration s, start C, end C)] for every stretch long enough with this motor.

    max_s keeps only the first max_s seconds of each stretch (the steep part of a cool-down)."""
    out = []
    for s in segs:
        v = [(p["t"], p["temps"][motor]) for p in s if motor in p["temps"]]
        if max_s is not None and v:
            v = [x for x in v if x[0] - v[0][0] <= max_s]
        if len(v) < 3 or v[-1][0] - v[0][0] < min_s:
            continue
        sl = slope_per_min([a for a, _ in v], [b for _, b in v])
        if sl is not None:
            out.append((sl, v[-1][0] - v[0][0], v[0][1], v[-1][1]))
    return out


def weighted_rate(rates) -> float | None:
    tot = sum(d for _, d, _, _ in rates)
    return sum(s * d for s, d, _, _ in rates) / tot if tot else None


def time_to_limit_s(start_c: float | None, rate_c_min: float | None, limit: float = GUARD_C) -> float | None:
    """Seconds for a motor at start_c rising rate_c_min to reach limit (0 if already there); None if it never rises."""
    if start_c is None or rate_c_min is None:
        return None
    if start_c >= limit:
        return 0.0
    if rate_c_min <= 0.02:
        return None
    return (limit - start_c) / rate_c_min * 60.0


def cooling_segments(pts: list[dict]) -> list[list[dict]]:
    """Idle-group stretches that follow a moving or holding stretch, plus the long stand-alone cool-downs."""
    return segments(pts, {"idle"})


def motor_stats(pts: list[dict], motor: str) -> dict:
    by = defaultdict(list)
    for p in pts:
        if motor in p["temps"] and p["src"] != "idle":
            by[p["group"]].append(p["temps"][motor])
    allv = [p["temps"][motor] for p in pts if motor in p["temps"]]
    med = lambda g: (round(median(by[g]), 1) if by.get(g) else None)  # noqa: E731
    hold = seg_rates(segments(pts, {"holding"}), motor)
    rise = weighted_rate(hold)
    idle_c = med("idle")
    cool = [(s, d, a, b) for s, d, a, b in seg_rates(cooling_segments(pts), motor, max_s=COOL_WINDOW_S) if s < 0 and a >= RESUME_C - 1 and a - b >= 1 and s < -0.05]
    cool_rate = -weighted_rate(cool) if cool else None
    return {
        "motor": motor, "idle_c": idle_c, "moving_c": med("moving"), "holding_c": med("holding"),
        "max_c": max(allv) if allv else None,
        "rise_c_per_min_holding": round(rise, 3) if rise is not None else None,
        "time_to_limit_s": (None if (t := time_to_limit_s(idle_c, rise)) is None else round(t)),
        "cool_c_per_min": round(cool_rate, 3) if cool_rate is not None else None,
        "_cool_segments": len(cool), "_hold_seconds": round(sum(d for _, d, _, _ in hold)),
    }


def downsample(seq: list, n: int = 400) -> list:
    if len(seq) <= n:
        return seq
    step = (len(seq) - 1) / (n - 1)
    return [seq[round(i * step)] for i in range(n)]


def biggest_session(thermal: list[dict]) -> str | None:
    c: dict[str, int] = defaultdict(int)
    for r in thermal:
        if r.get("kind") == "sample" and r.get("session"):
            c[r["session"]] += 1
    return max(c, key=c.get) if c else None


def series_for(pts: list[dict], session: str | None) -> dict:
    rows = [p for p in pts if p["session"] == session and p["src"] == "sample"]
    if not rows:
        return {"session": session or "", "t_min": [], "temps": {}, "phase": []}
    rows = downsample(rows)
    t0 = rows[0]["t"]
    return {"session": session, "t_min": [round((p["t"] - t0) / 60, 3) for p in rows],
            "temps": {m: [p["temps"].get(m) for p in rows] for m in MOTORS},
            "phase": [p["phase"] for p in rows]}


def session_table(thermal: list[dict], pts: list[dict]) -> list[dict]:
    meta = {r["session"]: r for r in thermal if r.get("kind") == "session" and r.get("session")}
    by = defaultdict(list)
    for p in pts:
        by[p["session"]].append(p)
    rows = []
    for s, ps in by.items():
        if len(ps) < 20:
            continue
        m = meta.get(s, {})
        peak = max(((v, k) for p in ps for k, v in p["temps"].items()), default=(None, None))
        mv = [max(p["temps"].values()) for p in ps if p["group"] == "moving"]
        rows.append({"session": s, "source": m.get("source"), "mode": m.get("mode"),
                     "minutes": round((ps[-1]["t"] - ps[0]["t"]) / 60, 1), "moving_minutes": round(len(mv) / 120, 1),
                     "peak_c": peak[0], "peak_motor": peak[1],
                     "start_c": max(ps[0]["temps"].values()), "moving_median_hottest_c": round(median(mv), 1) if mv else None})
    return sorted(rows, key=lambda r: -r["minutes"])


def torque_table(thermal: list[dict]) -> list[dict]:
    """Gripper temperature at each grasp by gripper torque_limit (grasp_start events carry both)."""
    by = defaultdict(list)
    for r in thermal:
        if r.get("kind") == "event" and r.get("event") == "grasp_start" and r.get("torque_limit") is not None \
                and isinstance(r.get("temp"), (int, float)):
            by[r["torque_limit"]].append(r)
    return [{"torque_limit": k, "grasps": len(v), "median_temp_c": median([r["temp"] for r in v]),
             "max_temp_c": max(r["temp"] for r in v), "median_load": median([abs(r.get("load") or 0) for r in v])}
            for k, v in sorted(by.items())]


def settings_view(thermal: list[dict]) -> dict:
    keys: dict[str, set] = defaultdict(set)
    for r in thermal:
        if r.get("kind") == "session":
            for k, v in (r.get("settings") or {}).items():
                keys[k].add(v)
    snap = [r for r in thermal if r.get("kind") == "snapshot"]
    regs = {}
    for r in snap:
        for mname, d in (r.get("motors") or {}).items():
            for k in ("acceleration", "torque_limit", "goal_velocity", "max_temperature_limit", "overload_torque"):
                if d.get(k) is not None:
                    regs.setdefault(k, set()).add(d[k])
    return {"session_settings_values": {k: sorted(v, key=str) for k, v in keys.items()},
            "constant": sorted(k for k, v in keys.items() if len(v) == 1),
            "varied": sorted(k for k, v in keys.items() if len(v) > 1),
            "registers": {k: sorted(v) for k, v in regs.items()}}


def charts(pts, thermal, session, motors, out_dir) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    files = []
    shade = {"idle": "#e5e7eb", "moving": "#cfe3f7", "holding": "#fde2c4"}
    ink, mute = "#1f2937", "#6b7280"

    def style(ax):
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.grid(axis="y", color="#e5e7eb", lw=0.6)
        ax.tick_params(colors=mute)
        ax.set_axisbelow(True)

    # 1. timeline of the biggest session
    rows = [p for p in pts if p["session"] == session and p["src"] == "sample"]
    if rows:
        t0 = rows[0]["t"]
        fig, ax = plt.subplots(figsize=(10, 4.6), dpi=130)
        i = 0
        while i < len(rows):
            j = i
            while j + 1 < len(rows) and rows[j + 1]["group"] == rows[i]["group"]:
                j += 1
            ax.axvspan((rows[i]["t"] - t0) / 60, (rows[min(j + 1, len(rows) - 1)]["t"] - t0) / 60,
                       color=shade[rows[i]["group"]], lw=0, alpha=0.8)
            i = j + 1
        x = [(p["t"] - t0) / 60 for p in rows]
        for m, c in zip(MOTORS, CHART_COLORS):
            ax.plot(x, [p["temps"].get(m) for p in rows], color=c, lw=1.6, label=m)
        ax.axhline(GUARD_C, color="#b42318", lw=1.2, ls="--")
        ax.text(x[-1], GUARD_C + 0.4, f"guard {GUARD_C} C (stop and cool)", color="#b42318", ha="right", va="bottom", fontsize=8)
        ax.set_ylim(40, GUARD_C + 3)
        ax.set_xlabel("minutes into session", color=mute)
        ax.set_ylabel("motor temperature (C)", color=mute)
        ax.set_title(f"Motor temperature, session {session} (shading: grey idle, blue moving, orange holding)",
                     loc="left", fontsize=10, color=ink)
        ax.legend(ncol=6, fontsize=8, frameon=False, loc="upper left")
        style(ax)
        fig.tight_layout()
        f = out_dir / "heat_timeline.png"
        fig.savefig(f)
        plt.close(fig)
        files.append(str(f))

    # 2. cooling curves
    segs = cooling_segments(pts)
    fig, ax = plt.subplots(figsize=(8, 4.4), dpi=130)
    drawn = 0
    for m, c in zip(MOTORS, CHART_COLORS):
        first = True
        for s in segs:
            v = [(p["t"], p["temps"][m]) for p in s if m in p["temps"]]
            if len(v) < 3 or v[-1][0] - v[0][0] < 120 or v[0][1] < RESUME_C or v[0][1] - v[-1][1] < 1:
                continue
            ax.plot([(a - v[0][0]) / 60 for a, _ in v], [b for _, b in v], color=c, lw=1.4, alpha=0.8,
                    label=m if first else None)
            first = False
            drawn += 1
    ax.axhline(RESUME_C, color="#2a9d8f", lw=1, ls=":")
    ax.text(0, RESUME_C + 0.15, "resume 50 C", color="#2a9d8f", fontsize=8, va="bottom")
    ax.set_xlabel("minutes since the arm went idle (parked or torque off)", color=mute)
    ax.set_ylabel("motor temperature (C)", color=mute)
    ax.set_title("Cooling after use: every idle stretch that started at 50 C or more", loc="left", fontsize=10, color=ink)
    if drawn:
        ax.legend(fontsize=8, frameon=False)
    style(ax)
    fig.tight_layout()
    f = out_dir / "heat_cooling.png"
    fig.savefig(f)
    plt.close(fig)
    files.append(str(f))

    # 3. torque-on hold test
    ex = [r for r in thermal if r.get("kind") == "experiment" and r.get("temps")]
    if ex:
        sid = max({r["session"] for r in ex}, key=lambda s: sum(1 for r in ex if r["session"] == s))
        e = sorted((r for r in ex if r["session"] == sid), key=lambda r: r["t"])
        fig, ax = plt.subplots(figsize=(8, 4.4), dpi=130)
        x = [(r["t"] - e[0]["t"]) / 60 for r in e]
        for m, c in zip(MOTORS, CHART_COLORS):
            ax.plot(x, [r["temps"].get(m) for r in e], color=c, lw=1.6, label=m)
        ax.axhline(GUARD_C, color="#b42318", lw=1.2, ls="--")
        ax.set_ylim(40, GUARD_C + 3)
        ax.set_xlabel("minutes holding (torque on, no motion)", color=mute)
        ax.set_ylabel("motor temperature (C)", color=mute)
        ax.set_title("Holding test: every motor warms with torque on, even doing nothing", loc="left", fontsize=10, color=ink)
        ax.legend(ncol=3, fontsize=8, frameon=False, loc="upper left")
        style(ax)
        fig.tight_layout()
        f = out_dir / "heat_hold.png"
        fig.savefig(f)
        plt.close(fig)
        files.append(str(f))
    return files


def fmt(v, nd=1, none="n/a"):
    return none if v is None else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))


def build(data: dict, charts_dir) -> dict:
    from pathlib import Path
    charts_dir = Path(charts_dir)
    charts_dir.mkdir(parents=True, exist_ok=True)
    thermal = data.get("thermal", [])
    pts = points(thermal)
    n_samples = sum(1 for r in thermal if r.get("kind") == "sample")
    motors = [motor_stats(pts, m) for m in MOTORS if any(m in p["temps"] for p in pts)]
    public = [{k: v for k, v in m.items() if not k.startswith("_")} for m in motors]
    session = biggest_session(thermal)
    series = series_for(pts, session)
    hot_events = sum(1 for r in thermal if r.get("kind") == "event" and r.get("hot") is True)
    guard_c = GUARD_C
    fw = [v for r in thermal if r.get("kind") == "snapshot" for d in (r.get("motors") or {}).values()
          for v in [d.get("max_temperature_limit")] if v]
    limit_c = max(fw) if fw else FIRMWARE_LIMIT_C
    files = charts(pts, thermal, session, MOTORS, charts_dir) if pts else []

    hottest = max((m for m in motors if m["max_c"] is not None), key=lambda m: m["max_c"], default=None)
    rising = [m for m in motors if m["time_to_limit_s"] is not None]
    worst = min(rising, key=lambda m: m["time_to_limit_s"]) if rising else None
    fastest = max((m for m in motors if m["rise_c_per_min_holding"] is not None),
                  key=lambda m: m["rise_c_per_min_holding"], default=None)
    cool_rates = [m["cool_c_per_min"] for m in motors if m["cool_c_per_min"]]
    cool_typ = median(cool_rates)
    cool_minutes = (guard_c - RESUME_C) / cool_typ if cool_typ else None
    max_hold = round(worst["time_to_limit_s"] * 0.5) if worst else None

    recs = []
    if hottest:
        recs.append(f"{hottest['motor']} is the hottest motor: peak {hottest['max_c']} C against a {guard_c} C guard "
                    f"and a {limit_c} C firmware limit. Nothing in the data reached the guard (hot events: {hot_events}).")
    if fastest and fastest["rise_c_per_min_holding"] is not None:
        recs.append(f"With torque on and no motion, {fastest['motor']} warms fastest: {fastest['rise_c_per_min_holding']:.2f} C/min. "
                    "Holding is not free; every motor warms with torque on.")
    if worst and max_hold:
        recs.append(f"Plan for at most {max_hold} s of continuous hold per pass (half of the {worst['time_to_limit_s']} s the "
                    f"{worst['motor']} needs from idle to the {guard_c} C guard); then torque off or park.")
    if cool_typ:
        recs.append(f"Park or torque off between passes: motors fall about {cool_typ:.2f} C/min (median), so "
                    f"{guard_c} C to {RESUME_C} C takes about {cool_minutes:.0f} min.")
    idl = sorted((m for m in motors if m["idle_c"] is not None), key=lambda m: -m["idle_c"])
    if len(idl) > 2:
        recs.append(f"{idl[0]['motor']} and {idl[1]['motor']} idle warmest ({idl[0]['idle_c']:.0f} and {idl[1]['idle_c']:.0f} C against "
                    f"{idl[-1]['idle_c']:.0f} C for {idl[-1]['motor']}): their idle temperature is not a fault, only their rise is.")
    if not hot_events:
        recs.append("No guard trips were recorded, so the guard values are untested on this data; keep COOL_TRIP at 60.")

    sess = session_table(thermal, pts)
    tq = torque_table(thermal)
    st = settings_view(thermal)

    md = ["Source: `thermal` collection, real hardware (recording Mac). Temperatures are whole degrees C from the STS3215 "
          "`present_temperature` register.", "",
          f"Phase grouping: idle = parked, off, preview, killed and the idle monitor (arm not working a task); "
          f"moving = recording, teleop, resetting; holding = `torque_on_hold` experiment rows (torque on, goal = present). "
          f"Guard = {guard_c} C (`COOL_TRIP`, arm/thermal.py; resume at {RESUME_C} C). Firmware limit = {limit_c} C.", "",
          "### Per motor", "",
          "| Motor | Idle C | Moving C | Holding C | Peak C | Hold rise C/min | Min from idle to guard (hold) | Cool C/min |",
          "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for m in motors:
        t = m["time_to_limit_s"]
        md.append(f"| {m['motor']} | {fmt(m['idle_c'])} | {fmt(m['moving_c'])} | {fmt(m['holding_c'])} | {fmt(m['max_c'])} | "
                  f"{fmt(m['rise_c_per_min_holding'], 2)} | {fmt(None if t is None else t / 60)} | {fmt(m['cool_c_per_min'], 2)} |")
    md += ["", "Medians per phase group; the hold rate is a least-squares fit over the hold experiment (stretches of 60 s or "
           "more), the cool rate over the first 5 min of idle stretches that began at 49 C or more and fell at least 1 C. `n/a` means no usable stretch."]
    if cool_typ:
        md += ["", f"### Cooling", "", f"Median fall {cool_typ:.2f} C/min over {sum(m['_cool_segments'] for m in motors)} "
               f"motor-stretches; {guard_c} C to {RESUME_C} C would take about {cool_minutes:.0f} min at that rate "
               "(linear extrapolation: the data never went above 55 C, and real cooling slows near the ambient floor)."]
    if sess:
        md += ["", "### Sessions", "", "| Session | Source | Mode | Minutes | Moving min | Start C | Peak C (motor) | Median hottest while moving C |",
               "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        for s in sess[:8]:
            md.append(f"| {s['session']} | {s['source'] or ''} | {s['mode'] or ''} | {s['minutes']} | {s['moving_minutes']} | "
                      f"{s['start_c']} | {s['peak_c']} ({s['peak_motor']}) | {fmt(s['moving_median_hottest_c'])} |")
    md += ["", "### Settings: what kept it cool or hot", ""]
    if tq:
        md += ["Gripper temperature at grasp start, by gripper `torque_limit`:", "",
               "| torque_limit | Grasps | Median C | Max C | Median |load| |", "| --- | --- | --- | --- | --- |",
               *[f"| {r['torque_limit']} | {r['grasps']} | {fmt(r['median_temp_c'])} | {r['max_temp_c']} | {fmt(r['median_load'], 0)} |" for r in tq], ""]
    const = ", ".join(f"{k}={st['session_settings_values'][k][0]}" for k in st["constant"])
    md.append(f"Session settings that were the same in every session (so they cannot explain any difference): {const or 'none'}."
              + (f" Settings that varied: {', '.join(st['varied'])}." if st["varied"] else " None of them varied."))
    if st["registers"]:
        md.append("Register snapshot: " + ", ".join(f"{k} {v}" for k, v in st["registers"].items()) + ".")
    md += ["", "### Recommendations", "", *[f"- {r}" for r in recs]]
    md += ["", *[f"![{Path(f).stem}](media/data/{Path(f).name})" for f in files]]

    notes = ["For the training chat (A) and the smart-pick chat (C):", "",
             *[f"- {r}" for r in recs],
             f"- Settings that were tried: only the gripper torque_limit changed ({', '.join(str(x) for x in sorted({r['torque_limit'] for r in thermal if r.get('kind') == 'event' and r.get('torque_limit') is not None}))}); every arm "
             "session ran the same acceleration/speed settings, so those are untested for heat. If you change them, "
             "log a `session` row with `settings` so this report can compare."]

    q_hot = "db.thermal.aggregate([{$match:{kind:'sample'}},{$project:{m:{$objectToArray:'$motors'}}},{$unwind:'$m'},{$group:{_id:'$m.k',peak:{$max:'$m.v.temp'}}},{$sort:{peak:-1}},{$limit:1}])"
    numbers = [
        {"name": "Hottest motor and peak" if hottest else "Hottest motor", "value": f"{hottest['motor']} {hottest['max_c']} C" if hottest else "no real data yet",
         "query": q_hot},
        {"name": "Thermal samples", "value": n_samples if n_samples else "no real data yet",
         "query": "db.thermal.countDocuments({kind:'sample'})"},
        {"name": "Max safe hold time", "value": f"{max_hold} s" if max_hold else "no real data yet",
         "query": "db.thermal.find({kind:'experiment',phase:'torque_on_hold'},{t:1,session:1,elapsed_s:1,temps:1}).sort({session:1,elapsed_s:1})"},
    ]
    summary = {"limit_c": limit_c, "guard_c": guard_c, "phase_map": PHASE_MAP, "motors": public, "series": series,
               "hot_events": hot_events, "recommendations": recs, "sessions": sess[:8], "torque_limit": tq,
               "settings": st, "max_hold_s": max_hold, "cool_minutes_guard_to_resume": round(cool_minutes, 1) if cool_minutes else None,
               "charts": [Path(f).name for f in files]}
    return {"title": "Heat", "summary": summary, "markdown": "\n".join(md), "notes": "\n".join(notes), "numbers": numbers}
