"""Heat graphs from the motor telemetry logs (~/scrub-logs/thermal/*.jsonl). Reads logs only; never opens the arm.

  .venv/bin/python explore/thermal_plot.py                      # every session, PNGs in ~/scrub-logs/thermal-plots
  .venv/bin/python explore/thermal_plot.py --since 20261018-04  # sessions whose name sorts at or after this

Writes:
  timeline.png        all six motor temps across every session (gaps where nothing logged), cooling trip and resume lines,
                      shaded while a run or recording was going, plus summed current and |load|
  peaks.png           hottest reading per motor, with the trip line
  sessions/<id>.png   one per session with samples: temps and the phase it was in
"""
import argparse
import glob
import json
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

MOTORS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
TRIP, RESUME = 60, 50  # station defaults; a session line overrides them
BUSY = {"recording", "running", "teleop", "resetting"}
GAP_S = 120  # break the line when samples are further apart than this


def load(root, since):
    sessions = []
    for f in sorted(glob.glob(str(Path(root).expanduser() / "*.jsonl"))):
        if since and Path(f).stem < since:
            continue
        rows, meta = [], {}
        for line in open(f):
            try:
                d = json.loads(line)
            except ValueError:
                continue  # a log cut off mid-line when its process was killed
            if d.get("kind") == "session":
                meta = d
            elif d.get("kind") == "sample":
                # older logs keep temp only under motors.<name>.temp
                d["temps"] = d.get("temps") or {m: v["temp"] for m, v in (d.get("motors") or {}).items() if "temp" in v}
                if d["temps"]:
                    rows.append(d)
        if rows:
            sessions.append({"id": Path(f).stem, "meta": meta, "rows": rows})
    return sessions


def series(rows, get):
    """(times, values) with None inserted across gaps so lines don't bridge them."""
    ts, vs, last = [], [], None
    for r in rows:
        v = get(r)
        if v is None:
            continue
        if last is not None and r["t"] - last > GAP_S:
            ts.append(datetime.fromtimestamp(last + 1))
            vs.append(None)
        ts.append(datetime.fromtimestamp(r["t"]))
        vs.append(v)
        last = r["t"]
    return ts, vs


def shade_busy(ax, rows):
    start = None
    for a, b in zip(rows, rows[1:] + [None]):
        busy = a.get("phase") in BUSY
        if busy and start is None:
            start = a["t"]
        if start is not None and (b is None or b.get("phase") not in BUSY or b["t"] - a["t"] > GAP_S):
            ax.axvspan(datetime.fromtimestamp(start), datetime.fromtimestamp(a["t"]), color="0.85", lw=0)
            start = None


def temp_axes(ax, rows, trip, resume):
    shade_busy(ax, rows)
    for m in MOTORS:
        ax.plot(*series(rows, lambda r, m=m: r["temps"].get(m)), lw=1.2, label=m)
    ax.axhline(trip, color="tab:red", ls="--", lw=1, label=f"cool trip {trip} C")
    ax.axhline(resume, color="tab:blue", ls=":", lw=1, label=f"resume {resume} C")
    ax.set_ylabel("motor temp (C)")
    ax.grid(alpha=0.3)


def sum_motor(r, key, absval=False):
    vals = [(r.get("motors") or {}).get(m, {}).get(key) for m in MOTORS]
    vals = [abs(v) if absval else v for v in vals if v is not None]
    return sum(vals) if vals else None


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--logs", default="~/scrub-logs/thermal")
    p.add_argument("--out", default="~/scrub-logs/thermal-plots")
    p.add_argument("--since", default="", help="first session name to include, e.g. 20261018-04")
    a = p.parse_args()
    out = Path(a.out).expanduser()
    (out / "sessions").mkdir(parents=True, exist_ok=True)
    sessions = load(a.logs, a.since)
    if not sessions:
        raise SystemExit(f"no samples in {a.logs}")
    settings = sessions[-1]["meta"].get("settings") or {}
    trip, resume = settings.get("COOL_TRIP", TRIP), settings.get("COOL_RESUME", RESUME)
    rows = sorted((r for s in sessions for r in s["rows"]), key=lambda r: r["t"])
    fmt = mdates.DateFormatter("%H:%M")

    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(16, 9), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    temp_axes(ax, rows, trip, resume)
    ax.set_title(f"Scrub arm motor temperatures, {len(sessions)} sessions, {len(rows)} samples (grey: run, teleop or recording)")
    ax.legend(loc="upper left", ncol=4, fontsize=8)
    ax2.plot(*series(rows, lambda r: sum_motor(r, "current")), lw=1, color="tab:purple", label="current, sum of 6 (raw)")
    ax2b = ax2.twinx()
    ax2b.plot(*series(rows, lambda r: sum_motor(r, "load", True)), lw=1, color="tab:orange", alpha=0.7, label="|load|, sum of 6 (raw)")
    ax2.set_ylabel("current (raw)")
    ax2b.set_ylabel("|load| (raw)")
    ax2.legend(loc="upper left", fontsize=8)
    ax2b.legend(loc="upper right", fontsize=8)
    ax2.grid(alpha=0.3)
    ax2.xaxis.set_major_formatter(fmt)
    fig.tight_layout()
    fig.savefig(out / "timeline.png", dpi=130)
    plt.close(fig)

    peaks = {m: max((r["temps"].get(m) or 0) for r in rows) for m in MOTORS}
    fig, ax = plt.subplots(figsize=(8, 4.5))
    bars = ax.bar(MOTORS, [peaks[m] for m in MOTORS], color="tab:orange")
    ax.bar_label(bars, fmt="%d C")
    ax.axhline(trip, color="tab:red", ls="--", lw=1, label=f"cool trip {trip} C")
    ax.set_ylim(0, max(trip, *peaks.values()) + 8)
    ax.set_ylabel("hottest reading (C)")
    ax.set_title("Peak motor temperature, all sessions")
    ax.legend()
    plt.setp(ax.get_xticklabels(), rotation=20)
    fig.tight_layout()
    fig.savefig(out / "peaks.png", dpi=130)
    plt.close(fig)

    for s in sessions:
        r = s["rows"]
        fig, ax = plt.subplots(figsize=(11, 4.5))
        temp_axes(ax, r, trip, resume)
        src = s["meta"].get("source") or "?"
        mins = (r[-1]["t"] - r[0]["t"]) / 60
        ax.set_title(f"{s['id']} ({src}, {mins:.1f} min, peak {max(max(v for v in x['temps'].values() if v is not None) for x in r)} C)")
        ax.legend(loc="upper left", ncol=4, fontsize=7)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        fig.tight_layout()
        fig.savefig(out / "sessions" / f"{s['id']}.png", dpi=110)
        plt.close(fig)

    print(f"{len(sessions)} sessions, {len(rows)} samples, "
          f"{datetime.fromtimestamp(rows[0]['t']):%m-%d %H:%M} to {datetime.fromtimestamp(rows[-1]['t']):%m-%d %H:%M}")
    print("peak C: " + ", ".join(f"{m} {peaks[m]}" for m in MOTORS) + f" (trip {trip})")
    print(f"wrote {out}/timeline.png, peaks.png, sessions/ ({len(sessions)} files)")


if __name__ == "__main__":
    main()
