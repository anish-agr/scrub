#!/usr/bin/env python
"""Video QA for recorded LeRobot episodes before they go to training. Read-only on the dataset.

  .venv/bin/python -m explore.dataset.qa_video --dataset ~/scrub-dataset [--episodes N] [--report out.md]
      [--no-api] [--max-calls 30]

Per episode and camera it reads 3 frames (start, middle, end) and flags:
  dark           the camera's median luminance is under DARK_LUMA (local, no API)
  unreadable     the camera's video could not be read at those frames (local)
  grasp_failed   Perceptron says the gripper holds nothing at the end of a "pick" episode
  dropped        Perceptron says an instrument falls or is dropped during the episode
The API part is one chat completions call per episode on the brightest camera, capped by --max-calls.
Writes <report>.md and <report>.json, one row per episode.

Callable from other modules (writes no report; the dataset is only read):
  video_failures(root, episode=None, use_api=False, max_calls=30) -> list[str]
      one "episode N: camera: reason" string per problem; [] means clean. episode=None checks every episode, an
      int checks only that episode_index. Local checks only (dark, unreadable) unless use_api=True, which also
      needs PERCEPTRON_API_KEY in the repo .env and adds grasp_failed / dropped reasons.
      An unreadable dataset returns one "dataset: ..." reason instead of raising.
"""
from __future__ import annotations

import argparse
import base64
import glob
import json
import os
import re
import sys
import tempfile
import time

import cv2
import numpy as np

CHAT_COMPLETIONS_URL = "https://api.perceptron.inc/v1/chat/completions"
MODEL = "perceptron-mk1.5"
DARK_LUMA = 40.0          # mean gray (0..255) under this = dark; same as DARK_WARN in qa.py
API_TIMEOUT_S = 30.0
POSITIONS = ("start", "middle", "end")


# ---- dataset reading -----------------------------------------------------------------------------------------

def resolve_dataset(spec: str) -> str:
    """A local folder, or a Hugging Face dataset repo id downloaded (read-only) to the HF cache."""
    path = os.path.abspath(os.path.expanduser(spec))
    if os.path.isdir(path):
        return path
    if re.fullmatch(r"[\w.-]+/[\w.-]+", spec):
        from huggingface_hub import snapshot_download
        return snapshot_download(repo_id=spec, repo_type="dataset")
    raise SystemExit(f"no dataset at {spec}")


def load_episodes(root: str) -> tuple[dict, list[dict]]:
    """info.json and one dict per episode: episode_index, tasks, length, and per camera the video file and
    the episode's start/end in seconds inside it. Handles LeRobot v3 (episodes parquet, shared video files)
    and v2 (episodes.jsonl, one video per episode). A parquet still being written is skipped."""
    with open(os.path.join(root, "meta", "info.json")) as f:
        info = json.load(f)
    fps = float(info.get("fps") or 30)
    cams = [k for k, v in info["features"].items() if v.get("dtype") == "video"]
    episodes: list[dict] = []
    files = sorted(glob.glob(os.path.join(root, "meta", "episodes", "**", "*.parquet"), recursive=True))
    if files:
        import pandas as pd
        for f in files:
            try:
                df = pd.read_parquet(f)
            except Exception as e:  # noqa: BLE001
                print(f"skipping {os.path.relpath(f, root)} ({type(e).__name__}: still being written?)")
                continue
            for _, row in df.iterrows():
                ep = {"episode_index": int(row["episode_index"]), "tasks": list(row.get("tasks", []) or []),
                      "length": int(row["length"]), "videos": {}}
                for key in cams:
                    if f"videos/{key}/file_index" not in row:
                        continue
                    p = info["video_path"].format(video_key=key, chunk_index=int(row[f"videos/{key}/chunk_index"]),
                                                  file_index=int(row[f"videos/{key}/file_index"]))
                    ep["videos"][key] = {"path": os.path.join(root, p),
                                         "from_s": float(row[f"videos/{key}/from_timestamp"]),
                                         "to_s": float(row[f"videos/{key}/to_timestamp"])}
                episodes.append(ep)
    else:  # v2.x
        chunks = int(info.get("chunks_size") or 1000)
        with open(os.path.join(root, "meta", "episodes.jsonl")) as f:
            lines = f.read().splitlines()
        for line in lines:
            if not line.strip():
                continue
            row = json.loads(line)
            i, n = int(row["episode_index"]), int(row["length"])
            ep = {"episode_index": i, "tasks": list(row.get("tasks", [])), "length": n, "videos": {}}
            for key in cams:
                p = info["video_path"].format(episode_chunk=i // chunks, video_key=key, episode_index=i)
                ep["videos"][key] = {"path": os.path.join(root, p), "from_s": 0.0, "to_s": n / fps}
            episodes.append(ep)
    episodes.sort(key=lambda e: e["episode_index"])
    return info, episodes


def read_frames(video: dict, fps: float) -> dict[str, np.ndarray | None]:
    """The start, middle and end frames of one episode in one camera's video (None where unreadable)."""
    first = int(round(video["from_s"] * fps))
    last = max(first, int(round(video["to_s"] * fps)) - 1)
    want = {"start": first, "middle": (first + last) // 2, "end": last}
    out: dict[str, np.ndarray | None] = {k: None for k in want}
    if not os.path.isfile(video["path"]):
        return out
    cap = cv2.VideoCapture(video["path"])
    if not cap.isOpened():
        return out
    for name, idx in want.items():
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        out[name] = frame if ok else None
    cap.release()
    return out


# ---- local checks --------------------------------------------------------------------------------------------

def luminance(frame: np.ndarray) -> float:
    return float(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).mean())


def camera_check(frames: dict[str, np.ndarray | None], threshold: float = DARK_LUMA) -> dict:
    """{'luma': median luminance or None, 'dark': bool, 'unreadable': bool} for one camera's sampled frames."""
    lumas = [luminance(f) for f in frames.values() if f is not None]
    if not lumas:
        return {"luma": None, "dark": False, "unreadable": True}
    med = float(np.median(lumas))
    return {"luma": round(med, 1), "dark": med < threshold, "unreadable": len(lumas) < len(frames)}


# ---- Perceptron check ----------------------------------------------------------------------------------------

def build_qa_prompt(task: str) -> str:
    return (
        f"These are 3 frames (start, middle, end) of a robot arm demonstration. The operator's instruction was: "
        f"\"{task or 'unknown'}\". Look only at what the frames show; the demonstration may have failed.\n"
        "Answer in JSON only, with these keys:\n"
        '{"caption": "<one short sentence: what the arm does>", '
        '"holding_at_end": "yes" | "no" | "unclear" (is the gripper holding an instrument in the last frame?), '
        '"dropped": "yes" | "no" | "unclear" (does an instrument fall or get dropped?)}'
    )


def build_qa_payload(frames: list[tuple[int, bytes]], prompt: str) -> dict:
    """The frames as one video_frames part (timestamp_ms each, at least 2), then the question."""
    parts = [{"image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(j).decode("ascii")},
              "timestamp_ms": int(ms)} for ms, j in frames]
    return {
        "model": MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "video_frames", "video_frames": {"frames": parts}},
            {"type": "text", "text": prompt},
        ]}],
        "reasoning_effort": "low",
        "max_completion_tokens": 1024,
        "temperature": 0.0,
    }


def parse_answer(body: dict) -> dict | None:
    """caption / holding_at_end / dropped from the reply's JSON object, or None."""
    try:
        content = body["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return None
    content = re.sub(r"<think>.*?</think>", "", str(content), flags=re.S)
    m = re.search(r"\{.*\}", content, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    norm = lambda v: str(v).strip().lower() if str(v).strip().lower() in ("yes", "no") else "unclear"  # noqa: E731
    return {"caption": str(data.get("caption", "")).strip()[:200],
            "holding_at_end": norm(data.get("holding_at_end")), "dropped": norm(data.get("dropped"))}


def ask_perceptron(frames: list[tuple[int, bytes]], task: str, key: str, post=None) -> tuple[dict | None, int, str | None]:
    """(answer, latency_ms, error). `post` is httpx.post unless a test passes a fake."""
    if post is None:
        import httpx
        post = httpx.post
    started = time.perf_counter()
    try:
        resp = post(CHAT_COMPLETIONS_URL, json=build_qa_payload(frames, build_qa_prompt(task)),
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    timeout=API_TIMEOUT_S)
        ms = round((time.perf_counter() - started) * 1000)
        if resp.status_code != 200:
            return None, ms, f"HTTP {resp.status_code}"
        answer = parse_answer(resp.json())
        return answer, ms, None if answer else "no JSON in reply"
    except Exception as e:  # noqa: BLE001
        return None, round((time.perf_counter() - started) * 1000), type(e).__name__


def api_flags(answer: dict, task: str) -> list[tuple[str, str]]:
    flags = []
    if answer["holding_at_end"] == "no" and (task or "").lower().startswith("pick"):
        flags.append(("grasp_failed", "gripper empty in the last frame of a pick episode"))
    if answer["dropped"] == "yes":
        flags.append(("dropped", "an instrument falls or is dropped"))
    return flags


# ---- per-episode check and report -------------------------------------------------------------------------------

def jpeg(frame: np.ndarray) -> bytes:
    return cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()


def check_episode(ep: dict, fps: float, key: str | None, calls_left: int, post=None, reader=read_frames) -> dict:
    row = {"episode": ep["episode_index"], "task": (ep["tasks"] or [""])[0], "length_s": round(ep["length"] / fps, 1),
           "cameras": {}, "flags": [], "reasons": [], "caption": None, "api": None}
    sampled = {}
    for cam, video in ep["videos"].items():
        name = cam.split(".")[-1]
        frames = reader(video, fps)
        sampled[name] = (frames, video)
        c = camera_check(frames)
        row["cameras"][name] = c
        if c["unreadable"]:
            row["flags"].append("unreadable")
            row["reasons"].append(f"{name}: video unreadable at {sum(f is None for f in frames.values())}/3 frames")
        if c["dark"]:
            row["flags"].append("dark")
            row["reasons"].append(f"{name}: dark, luminance {c['luma']} < {DARK_LUMA:g}")
    if key and calls_left > 0:
        usable = [(n, s) for n, s in sampled.items() if all(f is not None for f in s[0].values())]
        if usable:
            # the brightest fully readable camera, preferring "side" on a tie
            name, (frames, video) = max(usable, key=lambda x: (row["cameras"][x[0]]["luma"], x[0] == "side"))
            span_ms = max(0.0, (video["to_s"] - video["from_s"]) * 1000 - 1000 / fps)
            stamps = {"start": 0, "middle": int(span_ms / 2), "end": int(span_ms)}
            answer, ms, err = ask_perceptron([(stamps[p], jpeg(frames[p])) for p in POSITIONS], row["task"], key, post)
            row["api"] = {"camera": name, "latency_ms": ms, "error": err, "answer": answer}
            if answer:
                row["caption"] = answer["caption"]
                for flag, reason in api_flags(answer, row["task"]):
                    row["flags"].append(flag)
                    row["reasons"].append(f"{name}: {reason}")
    row["flags"] = sorted(set(row["flags"]))
    return row


def summarize(rows: list[dict]) -> dict:
    out = {"episodes": len(rows), "flagged": [r["episode"] for r in rows if r["flags"]]}
    for flag in ("dark", "unreadable", "grasp_failed", "dropped"):
        out[flag] = [r["episode"] for r in rows if flag in r["flags"]]
    out["api_calls"] = sum(1 for r in rows if r["api"])
    lat = sorted(r["api"]["latency_ms"] for r in rows if r["api"])
    out["api_latency_ms_median"] = lat[len(lat) // 2] if lat else None
    return out


def write_report(path_md: str, dataset: str, rows: list[dict], summary: dict) -> str:
    """Write <path>.md and <path>.json; returns the json path."""
    path_json = os.path.splitext(path_md)[0] + ".json"
    cams = sorted({c for r in rows for c in r["cameras"]})
    lines = [f"# Video QA: {dataset}", "",
             f"{summary['episodes']} episodes, {len(summary['flagged'])} flagged. "
             f"Dark: {summary['dark'] or 'none'}. Unreadable: {summary['unreadable'] or 'none'}. "
             f"Grasp failed: {summary['grasp_failed'] or 'none'}. Dropped: {summary['dropped'] or 'none'}. "
             f"API calls: {summary['api_calls']}"
             + (f", median {summary['api_latency_ms_median']} ms." if summary["api_calls"] else "."),
             "", "| Episode | Task | Length (s) | " + " | ".join(f"{c} luma" for c in cams)
             + " | Flags | Reason | Caption |",
             "| --- | --- | --- | " + " | ".join("---" for _ in cams) + " | --- | --- | --- |"]
    esc = lambda s: str(s).replace("|", "\\|").replace("\n", " ")  # noqa: E731
    for r in rows:
        lumas = [str((r["cameras"].get(c) or {}).get("luma", "")) for c in cams]
        lines.append(f"| {r['episode']} | {esc(r['task'])} | {r['length_s']} | " + " | ".join(lumas)
                     + f" | {', '.join(r['flags']) or 'ok'} | {esc('; '.join(r['reasons']))} | {esc(r['caption'] or '')} |")
    with open(path_md, "w") as f:
        f.write("\n".join(lines) + "\n")
    with open(path_json, "w") as f:
        json.dump({"dataset": dataset, "summary": summary, "episodes": rows}, f, indent=2)
    return path_json


def video_failures(root: str, episode: int | None = None, use_api: bool = False, max_calls: int = 30) -> list[str]:
    """Plain entry point for `python -m arm.train preflight`; see the module docstring."""
    try:
        root = resolve_dataset(str(root))
        info, episodes = load_episodes(root)
        if episode is not None:
            episodes = [e for e in episodes if e["episode_index"] == int(episode)]
            if not episodes:
                return [f"dataset: no episode {episode}"]
        if not episodes:
            return ["dataset: no episodes"]
        key = None
        if use_api:
            from dotenv import load_dotenv
            load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env"))
            key = os.environ.get("PERCEPTRON_API_KEY", "").strip() or None
        fps = float(info.get("fps") or 30)
        out, calls = [], 0
        for ep in episodes:
            row = check_episode(ep, fps, key, max_calls - calls)
            calls += 1 if row["api"] else 0
            out += [f"episode {row['episode']}: {r}" for r in row["reasons"]]
        return out
    except SystemExit as e:
        return [f"dataset: {e.code}"]
    except Exception as e:  # noqa: BLE001 - missing meta, corrupt files
        return [f"dataset: cannot be read ({type(e).__name__}: {e})"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dataset", required=True, help="dataset folder or Hugging Face repo id")
    ap.add_argument("--episodes", type=int, default=None, help="only the first N episodes")
    ap.add_argument("--report", default=os.path.join(tempfile.gettempdir(), "qa_video.md"))
    ap.add_argument("--no-api", action="store_true", help="local checks only")
    ap.add_argument("--max-calls", type=int, default=30, help="Perceptron calls at most (one per episode)")
    a = ap.parse_args(argv)

    root = resolve_dataset(a.dataset)
    report = os.path.abspath(a.report)
    if os.path.commonpath([root, report]) == root:
        raise SystemExit("--report must be outside the dataset (this tool never writes to it)")
    key = None
    if not a.no_api:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env"))
        key = os.environ.get("PERCEPTRON_API_KEY", "").strip() or None
        if not key:
            print("PERCEPTRON_API_KEY unset: local checks only")
    info, episodes = load_episodes(root)
    if a.episodes:
        episodes = episodes[: a.episodes]
    fps = float(info.get("fps") or 30)
    rows, calls = [], 0
    for ep in episodes:
        row = check_episode(ep, fps, key, a.max_calls - calls)
        calls += 1 if row["api"] else 0
        rows.append(row)
        print(f"episode {row['episode']}: {', '.join(row['flags']) or 'ok'}"
              + (f"  [{row['api']['latency_ms']} ms] {row['caption'] or row['api']['error']}" if row["api"] else ""))
    summary = summarize(rows)
    path_json = write_report(report, a.dataset, rows, summary)
    print(f"wrote {report} and {path_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
