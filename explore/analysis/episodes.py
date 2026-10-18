"""Training-data report: are the recorded episodes good enough to train the policy (Chat A)?

Reads the `episodes` collection (and, if present, ~/scrub-dataset/meta/info.json to compare counts).
Nothing is written to MongoDB or to the local dataset.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from explore.analysis.stats import median

TITLE = "Training data: episodes"
LOCAL_DATASET = Path.home() / "scrub-dataset"
RECOMMENDED_EPISODES = 50  # ACT: roughly 50 demos per task
MOVE_DEG_S = 5.0           # fastest joint above this = arm is moving
IDLE_TRIM_S = 2.0          # head/tail idle longer than this should be trimmed
STALL_S = 1.5              # mid-episode no-motion run
JERK_DEG = 8.0             # one-frame jump (deg) that counts as jerky
GRIP_OPEN_DEG = 8.0        # gripper this far above its start value = open
GRIP_CLOSE_DEG = 5.0       # drop this far from the open peak = closed on something
LONG_S = 60.0
WRIST_FPS_MIN = 25.0
CAMERA_FPS_NOTE = "git history: side and wrist 29-31 fps; wrist 18.7-22.6 fps on the spatula episodes"


def _runs(mask: np.ndarray, t: np.ndarray) -> list[tuple[float, float]]:
    """(start_s, end_s) of each run of True in mask (mask has one entry per frame)."""
    out, i, n = [], 0, len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j + 1 < n and mask[j + 1]:
                j += 1
            out.append((float(t[i]), float(t[j])))
            i = j + 1
        else:
            i += 1
    return out


def analyze(ep: dict) -> dict:
    """Metrics and verdict for one episode document."""
    joints = ep.get("joints") or [f"j{i}" for i in range(6)]
    s = np.asarray(ep.get("state") or [], dtype=float)
    t = np.asarray(ep.get("timestamp") or [], dtype=float)
    base = {"episode_index": ep.get("episode_index"), "task": ep.get("task"), "length": ep.get("length"),
            "duration_s": ep.get("duration_s"), "fps": ep.get("fps"), "handoff": ep.get("handoff")}
    if s.ndim != 2 or len(s) < 3 or len(t) != len(s):
        return {**base, "joints": {}, "idle_start_s": None, "idle_end_s": None, "gripper_open_s": None,
                "gripper_close_s": None, "stalls": [], "jerky_frames": 0, "start_pose": [],
                "verdict": "drop", "reason": "no usable state/timestamp data"}
    dur = float(t[-1] - t[0])
    dt = np.diff(t)
    dt[dt <= 0] = np.nan
    step = np.diff(s, axis=0)
    speed = np.abs(step) / dt[:, None]  # deg/s per joint, one row per frame gap
    speed = np.nan_to_num(speed)
    tm = t[1:]
    arm = speed[:, :5] if s.shape[1] > 5 else speed  # arm joints; the gripper is judged separately
    moving = arm.max(axis=1) > MOVE_DEG_S
    stats = {}
    for k, name in enumerate(joints[: s.shape[1]]):
        stats[name] = {"min": float(s[:, k].min()), "max": float(s[:, k].max()),
                       "range": float(s[:, k].max() - s[:, k].min()),
                       "peak_speed": float(speed[:, k].max()), "mean_speed": float(speed[:, k].mean())}
    if moving.any():
        first, last = float(tm[np.argmax(moving)]), float(tm[len(moving) - 1 - np.argmax(moving[::-1])])
        idle_start, idle_end = first - float(t[0]), float(t[-1]) - last
        quiet = _runs(~moving & (tm > first) & (tm < last), tm)
        stalls = [(a, b) for a, b in quiet if b - a >= STALL_S]
    else:
        idle_start, idle_end, stalls = dur, dur, []
    jerky = int((np.abs(step[:, :5]).max(axis=1) > JERK_DEG).sum()) if len(step) else 0

    g = s[:, -1]
    g0 = g[0]
    open_s = close_s = None
    open_idx = np.nonzero(g > g0 + GRIP_OPEN_DEG)[0]
    if len(open_idx):
        i0 = int(open_idx[0])
        open_s = float(t[i0] - t[0])
        run_max = np.maximum.accumulate(g[i0:])
        closed = np.nonzero(g[i0:] < run_max - GRIP_CLOSE_DEG)[0]
        if len(closed):
            close_s = float(t[i0 + int(closed[0])] - t[0])

    fixed = bool(moving.mean() < 0.005)
    reasons, verdict = [], "keep"
    if fixed:
        verdict, reasons = "drop", ["the arm never moves"]
    elif open_s is None:
        verdict, reasons = "drop", ["the gripper never opens, so there is no grasp to learn"]
    elif close_s is None:
        verdict, reasons = "re-record", ["the gripper opens but never closes on the spatula"]
    if verdict == "keep" and dur > LONG_S:
        verdict, reasons = "re-record", [f"{dur:.0f} s long with the arm moving only {moving.mean() * 100:.0f}% of the time"]
    if verdict == "keep" and stalls and sum(b - a for a, b in stalls) > 0.4 * dur:
        verdict, reasons = "re-record", ["arm stalls for most of the episode"]
    if verdict == "keep":
        if idle_start > IDLE_TRIM_S:
            reasons.append(f"trim {idle_start:.1f} s idle at the start")
        if idle_end > IDLE_TRIM_S:
            reasons.append(f"trim {idle_end:.1f} s idle at the end")
        if stalls:
            reasons.append(f"{len(stalls)} stall(s) over {STALL_S} s mid-episode")
        if jerky:
            reasons.append(f"{jerky} jerky frame(s)")
        if not reasons:
            reasons = ["clean: gripper opens and closes, little idle time"]
    return {**base, "joints": stats, "idle_start_s": round(idle_start, 2), "idle_end_s": round(idle_end, 2),
            "gripper_open_s": None if open_s is None else round(open_s, 2),
            "gripper_close_s": None if close_s is None else round(close_s, 2),
            "stalls": [(round(a, 1), round(b, 1)) for a, b in stalls], "jerky_frames": jerky,
            "moving_frac": round(float(moving.mean()), 3), "start_pose": s[0].tolist(),
            "verdict": verdict, "reason": "; ".join(reasons)}


def start_spread(rows: list[dict]) -> float | None:
    """Mean over joints of the standard deviation of first-frame values (degrees); None under 2 episodes."""
    poses = [r["start_pose"] for r in rows if r.get("start_pose")]
    if len(poses) < 2:
        return None
    return float(np.mean(np.std(np.asarray(poses), axis=0)))


def local_dataset(root: Path = LOCAL_DATASET) -> dict:
    try:
        info = json.loads((Path(root) / "meta" / "info.json").read_text())
        return {"episodes": int(info["total_episodes"]), "frames": int(info["total_frames"])}
    except (OSError, ValueError, KeyError):
        return {"episodes": None, "frames": None}


def _chart(rows: list[dict], charts_dir: Path) -> str | None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    charts_dir = Path(charts_dir)
    charts_dir.mkdir(parents=True, exist_ok=True)
    rows = [r for r in rows if r.get("duration_s")]
    if not rows:
        return None
    colors = {"keep": "#2a7f62", "re-record": "#c98a00", "drop": "#b23a48"}
    fig, ax = plt.subplots(figsize=(6, 0.55 * len(rows) + 1.6), facecolor="white")
    for y, r in enumerate(rows):
        d = r["duration_s"]
        a, b = r["idle_start_s"] or 0, r["idle_end_s"] or 0
        ax.barh(y, d, color=colors[r["verdict"]], height=0.55, alpha=0.9)
        ax.barh(y, a, color="white", alpha=0.6, height=0.55, hatch="///", edgecolor="#888", lw=0)
        ax.barh(y, b, left=d - b, color="white", alpha=0.6, height=0.55, hatch="///", edgecolor="#888", lw=0)
        if r.get("gripper_close_s") is not None:
            ax.plot(r["gripper_close_s"], y, marker="v", color="black", ms=7)
    ax.set_yticks(range(len(rows)), [f"ep {r['episode_index']} ({r['verdict']})" for r in rows])
    ax.invert_yaxis()
    ax.set_xlabel("seconds into episode (hatched = idle, triangle = gripper closes)")
    ax.set_title("Each recorded episode: length, idle time, grasp", loc="left", fontsize=11)
    ax.set_xscale("symlog", linthresh=20)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_facecolor("white")
    fig.tight_layout()
    fig.savefig(charts_dir / "episodes.png", dpi=130)
    plt.close(fig)
    return "episodes.png"


def _f(x, nd=1):
    return "-" if x is None else f"{x:.{nd}f}"


def build(data: dict, charts_dir) -> dict:
    eps = sorted(data.get("episodes") or [], key=lambda e: (e.get("episode_index") is None, e.get("episode_index")))
    rows = [analyze(e) for e in eps]
    local = local_dataset()
    tasks: dict[str, list[dict]] = {}
    for r in rows:
        tasks.setdefault(r["task"] or "(no task)", []).append(r)
    task_rows = [{"task": k, "count": len(v), "start_spread_deg": None if start_spread(v) is None else round(start_spread(v), 1)}
                 for k, v in tasks.items()]
    n = len(rows)
    kept = [r for r in rows if r["verdict"] == "keep"]
    flags: list[str] = []
    if n < RECOMMENDED_EPISODES:
        flags.append(f"Only {n} episodes ({len(kept)} usable); ACT usually needs {RECOMMENDED_EPISODES}+ per task. A training job now will overfit.")
    nogrip = [r["episode_index"] for r in rows if r["gripper_open_s"] is None]
    if nogrip:
        flags.append(f"Gripper never opens in episodes {nogrip}.")
    noclose = [r["episode_index"] for r in rows if r["gripper_open_s"] is not None and r["gripper_close_s"] is None]
    if noclose:
        flags.append(f"Gripper opens but never closes in episodes {noclose}.")
    for k, v in tasks.items():
        sp = start_spread(v)
        if sp is not None and sp < 0.5:
            flags.append(f"Task '{k}': every episode starts from the same pose (spread {sp:.2f} deg); the policy will not learn varied starts.")
    trim = [r["episode_index"] for r in rows if (r["idle_start_s"] or 0) > IDLE_TRIM_S or (r["idle_end_s"] or 0) > IDLE_TRIM_S]
    if trim:
        flags.append(f"Idle head or tail over {IDLE_TRIM_S:.0f} s in episodes {trim}; trim before training.")
    longs = [r["episode_index"] for r in rows if (r["duration_s"] or 0) > LONG_S]
    if longs:
        flags.append(f"Episodes {longs} run over {LONG_S:.0f} s; a pick should take well under a minute.")
    if local["episodes"] is not None and local["episodes"] != n:
        flags.append(f"MongoDB has {n} episodes but the local dataset says {local['episodes']} ({local['frames']} frames); "
                     "the extra episodes were never uploaded or were recorded after the upload.")
    flags.append("No lighting field on any episode, so lighting variety cannot be checked.")
    flags.append(f"Wrist camera frame rate is not stored per episode. {CAMERA_FPS_NOTE}; below {WRIST_FPS_MIN:.0f} fps is a training concern.")
    if any(r["handoff"] is None for r in rows):
        flags.append(f"{sum(r['handoff'] is None for r in rows)} of {n} episodes have no handoff outcome attached.")

    hours = sum(r["duration_s"] or 0 for r in rows) / 3600
    drop = [r for r in rows if r["verdict"] == "drop"]
    rerec = [r for r in rows if r["verdict"] == "re-record"]
    chart = _chart(rows, Path(charts_dir))

    md = [f"{n} episodes in MongoDB ({hours * 60:.1f} min recorded), {len(kept)} usable as they are.", ""]
    md += ["| Ep | Task | Length (frames) | Duration s | FPS | Idle start s | Idle end s | Gripper opens s | Gripper closes s | Verdict | Why |",
           "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        md.append(f"| {r['episode_index']} | {r['task']} | {r['length']} | {_f(r['duration_s'])} | {r['fps']} | {_f(r['idle_start_s'])} | "
                  f"{_f(r['idle_end_s'])} | {_f(r['gripper_open_s'])} | {_f(r['gripper_close_s'])} | **{r['verdict']}** | {r['reason']} |")
    if chart:
        md += ["", f"![Episode timeline](media/data/{chart})"]
    md += ["", "### Joint motion (deg and deg/s, from `state` and `timestamp`)", "",
           "| Ep | Joint | Range deg | Peak speed | Mean speed |", "| --- | --- | --- | --- | --- |"]
    for r in rows:
        for name, j in r["joints"].items():
            md.append(f"| {r['episode_index']} | {name} | {j['range']:.1f} | {j['peak_speed']:.0f} | {j['mean_speed']:.1f} |")
    md += ["", "### Per task", "", "| Task | Episodes | Start-pose spread (deg) | Lighting |", "| --- | --- | --- | --- |"]
    for t in task_rows:
        md.append(f"| {t['task']} | {t['count']} | {_f(t['start_spread_deg'])} | not recorded (no lighting field) |")
    md += ["", f"Local dataset `~/scrub-dataset`: {local['episodes'] if local['episodes'] is not None else 'not found'} episodes, "
               f"{local['frames'] if local['frames'] is not None else '-'} frames. Camera fps: dataset says 30; {CAMERA_FPS_NOTE}.",
           "", "### Flags", ""] + [f"- {f}" for f in flags]

    notes = [f"Chat A: do not start a real training job yet. MongoDB holds {n} episodes ({len(kept)} usable); ACT wants {RECOMMENDED_EPISODES}+.", ""]
    notes.append("Drop (exclude from training): " + ("; ".join(f"episode {r['episode_index']} ({r['reason']})" for r in drop) or "none"))
    notes.append("Re-record: " + ("; ".join(f"episode {r['episode_index']} ({r['reason']})" for r in rerec) or "none"))
    notes.append("Keep: " + (", ".join(str(r["episode_index"]) for r in kept) or "none")
                 + ("; trim idle head and tail where noted in docs/DATA.md." if kept else ""))
    notes.append("Check the wrist camera frame rate before recording more; under 25 fps hurts the policy.")

    numbers = [
        {"name": "Episodes recorded (MongoDB)", "value": str(n), "query": "db.episodes.countDocuments({})"},
        {"name": "Hours of demonstrations recorded", "value": f"{hours:.2f}",
         "query": 'db.episodes.aggregate([{$group:{_id:null,s:{$sum:"$duration_s"}}}])'},
        {"name": "Episodes usable for training", "value": f"{len(kept)} of {n}",
         "query": 'db.episodes.find({}, {episode_index:1, task:1, duration_s:1, handoff:1})'},
        {"name": "Episodes with a handoff outcome", "value": str(sum(r["handoff"] is not None for r in rows)),
         "query": "db.episodes.countDocuments({handoff: {$ne: null}})"},
    ]
    summary = {
        "episodes": [{k: r[k] for k in ("episode_index", "task", "length", "duration_s", "fps", "idle_start_s", "idle_end_s",
                                         "gripper_close_s", "verdict", "reason")} for r in rows],
        "tasks": task_rows, "local_dataset": local, "flags": flags}
    return {"title": TITLE, "summary": summary, "markdown": "\n".join(md), "notes": "\n".join(notes), "numbers": numbers}
