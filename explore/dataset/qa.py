#!/usr/bin/env python
"""Demo QA checker for Scrub LeRobot (v3) datasets. Read-only on the dataset.

  .venv/bin/python -m explore.dataset.qa --root <dataset> [--out report.html]
"""
import argparse, base64, glob, html, json, os, sys, tempfile
import cv2
import numpy as np
import pandas as pd

# ---- thresholds (tune here) -------------------------------------------------
LEN_SHORT_FRAC = 0.5       # WARN if length < this * median length
LEN_LONG_FRAC = 1.8        # WARN if length > this * median length
LEN_MIN_S = 2.0            # FAIL if shorter than this many seconds
FROZEN_RANGE_DEG = 5.0     # FAIL if max joint range (excluding gripper) below this
GRIPPER_CLOSE_DROP = 15.0  # grasp = gripper falls this far below its starting/open level (0..100)
GRIPPER_REOPEN_RISE = 10.0 # release = gripper rises this much after its minimum
JUMP_DEG = 20.0            # per-frame state jump above this (deg) is a glitch
JUMP_WARN_COUNT = 1        # WARN at this many jumps
JUMP_FAIL_COUNT = 5        # FAIL at this many
TS_GAP_FRAC = 1.5          # frame dt > this * (1/fps) counts as a gap/drop
TS_WARN_COUNT = 1
TS_FAIL_COUNT = 5
BLUR_WARN = 30.0           # variance of Laplacian below this = blurry (median of samples)
BLUR_FAIL = 10.0
DARK_WARN = 40.0           # mean gray brightness (0..255)
DARK_FAIL = 20.0
BRIGHT_WARN = 220.0
BRIGHT_FAIL = 240.0
FROZEN_CAM_DIFF = 0.05     # mean abs gray diff (0..255) between consecutive frames counted as identical
FROZEN_CAM_WARN_FRAC = 0.65  # WARN if this fraction of pairs identical (side cam ~50% is normal 15fps duplication)
FROZEN_CAM_RUN_S = 1.0     # WARN if a run of identical frames lasts this long (camera stall)
FROZEN_CAM_FAIL_FRAC = 0.90  # FAIL (camera dead)
LAG_WARN_DEG = 12.0        # RMS action vs state gap at best lag (deg, excl. gripper)
LAG_FAIL_DEG = 25.0
LAG_MAX_FRAMES = 15        # lag search window; best lag above LAG_WARN_FRAMES warns
LAG_WARN_FRAMES = 8
THUMB_W = 240              # report thumbnail width
MAX_SAMPLED_FRAMES = 40    # frames per camera per episode for blur/brightness
# -----------------------------------------------------------------------------

LEVEL = {"PASS": 0, "WARN": 1, "FAIL": 2}


def load_meta(root):
    info = json.load(open(os.path.join(root, "meta/info.json")))
    eps = pd.concat([pd.read_parquet(f) for f in
                     sorted(glob.glob(os.path.join(root, "meta/episodes/**/*.parquet"), recursive=True))])
    data = pd.concat([pd.read_parquet(f) for f in
                      sorted(glob.glob(os.path.join(root, "data/**/*.parquet"), recursive=True))])
    return info, eps.sort_values("episode_index").reset_index(drop=True), data


def read_video_segment(path, start_frame, n, fps):
    """Read n frames starting at start_frame; return list of BGR frames."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return None
    if start_frame:
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    frames = []
    for _ in range(n):
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    cap.release()
    return frames


def cam_metrics(frames):
    small = [cv2.cvtColor(cv2.resize(f, (160, 120)), cv2.COLOR_BGR2GRAY).astype(np.float32) for f in frames]
    diffs = [float(np.abs(small[i + 1] - small[i]).mean()) for i in range(len(small) - 1)]
    frozen_frac = float(np.mean([d < FROZEN_CAM_DIFF for d in diffs])) if diffs else 0.0
    idx = np.linspace(0, len(frames) - 1, min(MAX_SAMPLED_FRAMES, len(frames))).astype(int)
    blur, bright = [], []
    for i in idx:
        g = cv2.cvtColor(frames[i], cv2.COLOR_BGR2GRAY)
        blur.append(float(cv2.Laplacian(g, cv2.CV_64F).var()))
        bright.append(float(g.mean()))
    run = best = 0
    for d in diffs:
        run = run + 1 if d < FROZEN_CAM_DIFF else 0
        best = max(best, run)
    return dict(blur=float(np.median(blur)), bright=float(np.median(bright)), frozen_frac=frozen_frac, run=best)


def thumb_b64(frame):
    h = int(frame.shape[0] * THUMB_W / frame.shape[1])
    ok, buf = cv2.imencode(".jpg", cv2.resize(frame, (THUMB_W, h)), [cv2.IMWRITE_JPEG_QUALITY, 70])
    return base64.b64encode(buf.tobytes()).decode()


def best_lag(a, s):
    """Lag (frames) of state behind action minimising RMS gap, plus that RMS (excl. gripper)."""
    best = (0, 1e9)
    for lag in range(0, LAG_MAX_FRAMES + 1):
        if len(a) - lag < 5:
            break
        d = a[:len(a) - lag, :5] - s[lag:, :5]
        r = float(np.sqrt((d ** 2).mean()))
        if r < best[1]:
            best = (lag, r)
    return best


def check_episode(root, info, row, df, cams):
    fps = info["fps"]
    flags = []  # (level, text)
    def add(l, t): flags.append((l, t))

    ts = df["timestamp"].to_numpy()
    st = np.stack(df["observation.state"].to_numpy()).astype(float)
    ac = np.stack(df["action"].to_numpy()).astype(float)
    n = len(df)
    m = dict(frames=n, dur=n / fps)

    # motion
    rng = st[:, :5].max(0) - st[:, :5].min(0)
    m["range"] = float(rng.max())
    if rng.max() < FROZEN_RANGE_DEG:
        add("FAIL", f"frozen: max joint range {rng.max():.1f} deg")

    # gripper
    g = st[:, 5]
    gmin_i = int(g.argmin())
    start_level = float(np.percentile(g[:max(5, n // 10)], 90))
    closed = start_level - g.min() >= GRIPPER_CLOSE_DROP
    m["grip"] = (start_level, float(g.min()), float(g[-1]))
    if not closed:
        add("FAIL", f"gripper never closes (open {start_level:.0f} -> min {g.min():.0f})")
    elif g[gmin_i:].max() - g.min() < GRIPPER_REOPEN_RISE:
        add("WARN", f"gripper never reopens after grasp (min {g.min():.0f}, end {g[-1]:.0f})")

    # jumps
    jumps = np.abs(np.diff(st, axis=0))[:, :5].max(1) if n > 1 else np.zeros(0)
    nj = int((jumps > JUMP_DEG).sum())
    m["jumps"] = nj
    m["max_jump"] = float(jumps.max()) if len(jumps) else 0.0
    if nj >= JUMP_FAIL_COUNT:
        add("FAIL", f"{nj} joint jumps > {JUMP_DEG:.0f} deg (max {m['max_jump']:.0f})")
    elif nj >= JUMP_WARN_COUNT:
        add("WARN", f"{nj} joint jump(s) > {JUMP_DEG:.0f} deg (max {m['max_jump']:.0f})")

    # timestamps
    dt = np.diff(ts)
    ng = int((dt > TS_GAP_FRAC / fps).sum()) + int((dt <= 0).sum())
    m["gaps"] = ng
    if ng >= TS_FAIL_COUNT:
        add("FAIL", f"{ng} timestamp gaps/drops (max dt {dt.max()*1000:.0f} ms)")
    elif ng >= TS_WARN_COUNT:
        add("WARN", f"{ng} timestamp gap(s) (max dt {dt.max()*1000:.0f} ms)")

    # action vs state
    lag, rms = best_lag(ac, st)
    m["lag"], m["rms"] = lag, rms
    if rms > LAG_FAIL_DEG:
        add("FAIL", f"action/state divergence RMS {rms:.1f} deg (lag {lag}f)")
    elif rms > LAG_WARN_DEG:
        add("WARN", f"action/state divergence RMS {rms:.1f} deg (lag {lag}f)")
    elif lag > LAG_WARN_FRAMES:
        add("WARN", f"state lags action by {lag} frames")

    # cameras
    thumbs, cam_m = {}, {}
    for cam in cams:
        key = f"observation.images.{cam}"
        fi = int(row[f"videos/{key}/file_index"]); ci = int(row[f"videos/{key}/chunk_index"])
        p = os.path.join(root, info["video_path"].format(video_key=key, chunk_index=ci, file_index=fi))
        start = int(round(float(row[f"videos/{key}/from_timestamp"]) * fps))
        frames = read_video_segment(p, start, n, fps) if os.path.exists(p) else None
        if not frames:
            add("FAIL", f"{cam}: video unreadable")
            continue
        if len(frames) < n * 0.98:
            add("WARN", f"{cam}: only {len(frames)}/{n} video frames")
        cm = cam_metrics(frames)
        cam_m[cam] = cm
        thumbs[cam] = thumb_b64(frames[len(frames) // 2])
        b, br, fz = cm["blur"], cm["bright"], cm["frozen_frac"]
        if b < BLUR_FAIL: add("FAIL", f"{cam}: very blurry (lapvar {b:.0f})")
        elif b < BLUR_WARN: add("WARN", f"{cam}: blurry (lapvar {b:.0f})")
        if br < DARK_FAIL: add("FAIL", f"{cam}: too dark ({br:.0f})")
        elif br < DARK_WARN: add("WARN", f"{cam}: dark ({br:.0f})")
        if br > BRIGHT_FAIL: add("FAIL", f"{cam}: blown out ({br:.0f})")
        elif br > BRIGHT_WARN: add("WARN", f"{cam}: bright ({br:.0f})")
        if fz >= FROZEN_CAM_FAIL_FRAC: add("FAIL", f"{cam}: frozen camera ({fz:.0%} identical frames)")
        elif fz >= FROZEN_CAM_WARN_FRAC: add("WARN", f"{cam}: {fz:.0%} identical consecutive frames")
        elif cm["run"] >= FROZEN_CAM_RUN_S * fps: add("WARN", f"{cam}: stalled {cm['run']/fps:.1f} s of identical frames")
    m["cams"] = cam_m
    return m, flags, thumbs, st, ac


def svg_traces(st, ac, w=420, h=110):
    names = ["pan", "lift", "elbow", "wflex", "wroll", "grip"]
    cols = ["#1f4e79", "#7a3b00", "#2e6b3a", "#6b2e6b", "#555555", "#b00020"]
    n = len(st)
    lo, hi = min(st.min(), ac.min()), max(st.max(), ac.max())
    sp = (hi - lo) or 1.0
    def pts(v):
        return " ".join(f"{i / max(n - 1, 1) * w:.1f},{h - (x - lo) / sp * (h - 4) - 2:.1f}"
                        for i, x in list(enumerate(v))[::max(1, n // 300)])
    out = [f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" class="tr">',
           f'<rect width="{w}" height="{h}" fill="none" stroke="#999"/>']
    for j in range(6):
        out.append(f'<polyline fill="none" stroke="{cols[j]}" stroke-width="1" points="{pts(st[:, j])}"><title>{names[j]}</title></polyline>')
    out.append("</svg>")
    return "".join(out)


CSS = """body{font-family:'IBM Plex Sans',sans-serif;background:#e8e8e4;color:#111;margin:0;padding:16px 20px}
h1{font:600 18px 'IBM Plex Mono',monospace;margin:0 0 4px;text-transform:uppercase;letter-spacing:.08em}
.sub,.m{font:12px 'IBM Plex Mono',monospace;color:#444}
.sum{margin:12px 0;display:flex;gap:8px}.sum div{border:1px solid #222;padding:6px 14px;background:#f6f6f2;font:600 13px 'IBM Plex Mono',monospace}
.ep{border:1px solid #222;background:#f6f6f2;margin:10px 0;padding:10px;display:grid;grid-template-columns:90px 500px 1fr;gap:12px}
.tag{font:700 13px 'IBM Plex Mono',monospace;padding:4px 8px;border:1px solid #222;display:inline-block;text-align:center}
.PASS{background:#cfe3cf}.WARN{background:#f2dc8c}.FAIL{background:#e8a09a}
.th img{width:240px;border:1px solid #222;margin-right:4px;display:block;margin-bottom:4px}
.th{display:flex;gap:4px;flex-wrap:wrap}ul{margin:4px 0;padding-left:18px;font:12px 'IBM Plex Mono',monospace}
.tr{display:block;margin-top:4px;background:#fff}
@media(max-width:1000px){.ep{grid-template-columns:1fr}}"""


def write_html(path, root, results, counts):
    p = ['<!doctype html><meta charset="utf-8"><title>Scrub Demo QA</title>',
         '<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono&family=IBM+Plex+Sans:wght@400;600&display=swap" rel="stylesheet">',
         f"<style>{CSS}</style><h1>Scrub demo QA</h1><div class='sub'>{html.escape(root)}</div>",
         "<div class='sum'>" + "".join(f"<div class='{k}'>{k} {v}</div>" for k, v in counts.items()) + "</div>"]
    for r in results:
        lines = "".join(f"<li>{l} {html.escape(t)}</li>" for l, t in r["flags"]) or "<li>no flags</li>"
        th = "".join(f"<div><div class='m'>{c}</div><img src='data:image/jpeg;base64,{b}'></div>" for c, b in r["thumbs"].items())
        m = r["m"]
        p.append(f"<div class='ep'><div><div class='tag {r['status']}'>{r['status']}</div><div class='m'>ep {r['ep']}<br>{m['dur']:.1f} s<br>{m['frames']} fr</div></div>"
                 f"<div class='th'>{th}</div><div><ul>{lines}</ul>{r['svg']}<div class='m'>state joints, pan lift elbow wflex wroll grip</div></div></div>")
    open(path, "w").write("\n".join(p))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", default=os.path.join(tempfile.gettempdir(), "qa_report.html"))
    a = ap.parse_args(argv)
    root = os.path.abspath(a.root)
    if os.path.commonpath([root, os.path.abspath(a.out)]) == root:
        sys.exit("--out must not be inside the dataset")
    info, eps, data = load_meta(root)
    cams = [k.split(".")[-1] for k, v in info["features"].items() if v["dtype"] == "video"]
    med = float(eps["length"].median())
    results = []
    for _, row in eps.iterrows():
        e = int(row["episode_index"])
        df = data[data["episode_index"] == e].sort_values("frame_index")
        m, flags, thumbs, st, ac = check_episode(root, info, row, df, cams)
        n = m["frames"]
        if n < LEN_MIN_S * info["fps"]:
            flags.append(("FAIL", f"too short: {m['dur']:.1f} s"))
        elif n < LEN_SHORT_FRAC * med:
            flags.append(("WARN", f"short vs median ({n} vs {med:.0f} frames)"))
        elif n > LEN_LONG_FRAC * med:
            flags.append(("WARN", f"long vs median ({n} vs {med:.0f} frames)"))
        status = max((l for l, _ in flags), key=LEVEL.get, default="PASS")
        results.append(dict(ep=e, m=m, flags=flags, status=status, thumbs=thumbs, svg=svg_traces(st, ac)))
    counts = {k: sum(r["status"] == k for r in results) for k in LEVEL}
    print(f"{'EP':>3} {'LEN s':>6} {'STATUS':<6} REASON")
    for r in results:
        why = "; ".join(t for _, t in r["flags"]) or "-"
        print(f"{r['ep']:>3} {r['m']['dur']:>6.1f} {r['status']:<6} {why}")
    print(f"\n{counts['PASS']} pass, {counts['WARN']} warn, {counts['FAIL']} fail of {len(results)}")
    write_html(a.out, root, results, counts)
    print("report:", a.out)


if __name__ == "__main__":
    main()
