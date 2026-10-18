"""Shared reading of LeRobot v3 (meta/episodes parquet) and v2.x (meta/episodes.jsonl, meta/tasks.jsonl) metadata.

  is_v2(root)                   True when the v3 episodes parquet tree is absent and meta/episodes.jsonl exists
  v2_episodes_df(root, info)    a DataFrame shaped like the v3 episodes table (episode_index, length, tasks, and
                                data/* and videos/<key>/* columns; one video file per episode, from_timestamp 0)
  v2_tasks(root)                {task_index: task}
  video_file(root, info, key, row)   the video path of one episode row for either version
"""
import glob
import json
import os

import pandas as pd


def read_jsonl(path):
    out = []
    with open(path) as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out


def is_v2(root):
    root = str(root)
    return (not glob.glob(os.path.join(root, "meta", "episodes", "**", "*.parquet"), recursive=True)
            and os.path.exists(os.path.join(root, "meta", "episodes.jsonl")))


def v2_tasks(root):
    p = os.path.join(str(root), "meta", "tasks.jsonl")
    return {int(r["task_index"]): str(r["task"]) for r in read_jsonl(p)} if os.path.exists(p) else {}


def v2_episodes_df(root, info):
    chunks = int(info.get("chunks_size") or 1000)
    cams = [k for k, v in info.get("features", {}).items() if v.get("dtype") == "video"]
    fps = float(info.get("fps") or 30)
    rows = []
    for r in read_jsonl(os.path.join(str(root), "meta", "episodes.jsonl")):
        i, n = int(r["episode_index"]), int(r["length"])
        tasks = r.get("tasks", [])
        row = {"episode_index": i, "length": n, "tasks": [tasks] if isinstance(tasks, str) else list(tasks),
               "data/chunk_index": i // chunks, "data/file_index": i}
        for k in cams:
            row.update({f"videos/{k}/chunk_index": i // chunks, f"videos/{k}/file_index": i,
                        f"videos/{k}/from_timestamp": 0.0, f"videos/{k}/to_timestamp": n / fps})
        rows.append(row)
    return pd.DataFrame(rows)


def data_file(root, info, row):
    c, f = int(row["data/chunk_index"]), int(row["data/file_index"])
    tpl = info["data_path"]
    if "{episode_index" in tpl:  # v2
        return os.path.join(str(root), tpl.format(episode_chunk=c, episode_index=int(row["episode_index"])))
    return os.path.join(str(root), tpl.format(chunk_index=c, file_index=f))


def video_file(root, info, key, row):
    c = int(row[f"videos/{key}/chunk_index"])
    f = int(row[f"videos/{key}/file_index"])
    tpl = info["video_path"]
    if "{episode_index" in tpl:  # v2
        return os.path.join(str(root), tpl.format(episode_chunk=c, video_key=key,
                                                  episode_index=int(row["episode_index"])))
    return os.path.join(str(root), tpl.format(video_key=key, chunk_index=c, file_index=f))
