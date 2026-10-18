"""Copy each recorded episode's joint data into MongoDB (scrub.episodes); videos stay on disk.

  .venv/bin/python explore/dataset/to_mongo.py                       # every readable episode in ~/scrub-dataset
  .venv/bin/python explore/dataset/to_mongo.py --root <ds> --episode 12
  .venv/bin/python explore/dataset/to_mongo.py --check               # what MongoDB has vs the dataset

One document per episode, upserted on (dataset, episode_index), so re-running is safe:
  dataset, episode_index, task, length, fps, duration_s, uploaded_at,
  joints (names), state [[6 floats] per frame] (follower), action [[6 floats] per frame] (leader commands),
  timestamp [per frame], video {camera: {file, from_s, to_s}} (paths relative to the dataset root),
  handoff (the episode_end telemetry for that episode, when the station logged it: grasps, lifted, pulled ...).
A parquet file a live recording is still writing is skipped; run again after the session ends.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import thermal_log  # noqa: E402

COLLECTION = "episodes"


def _read_all(pattern):
    frames = []
    for f in sorted(glob.glob(pattern, recursive=True)):
        try:
            frames.append(pd.read_parquet(f))
        except Exception:  # noqa: BLE001 - still being written by a live recording
            print(f"skipping {f} (still being written?)")
    return pd.concat(frames) if frames else pd.DataFrame()


def _coll():
    import pymongo
    uri = thermal_log._uri()
    if not uri:
        sys.exit("MONGODB_URI is not set in .env")
    c = pymongo.MongoClient(uri, serverSelectionTimeoutMS=8000).get_default_database(default="scrub")[COLLECTION]
    c.create_index([("dataset", 1), ("episode_index", 1)], unique=True)
    return c


def build_docs(root: str, only: int | None = None) -> list[dict]:
    root = os.path.expanduser(root)
    info = json.load(open(os.path.join(root, "meta/info.json")))
    names = info["features"]["action"]["names"]
    tasks = _read_all(os.path.join(root, "meta/tasks.parquet"))
    task_by_index = {}
    if not tasks.empty:
        tasks = tasks.reset_index()
        tcol = "task" if "task" in tasks.columns else tasks.columns[0]
        task_by_index = {int(r["task_index"]): str(r[tcol]) for _, r in tasks.iterrows()}
    eps = _read_all(os.path.join(root, "meta/episodes/**/*.parquet"))
    data = _read_all(os.path.join(root, "data/**/*.parquet"))
    if eps.empty or data.empty:
        return []
    docs = []
    for _, e in eps.sort_values("episode_index").iterrows():
        idx = int(e["episode_index"])
        if only is not None and idx != only:
            continue
        rows = data[data["episode_index"] == idx].sort_values("frame_index")
        if rows.empty:
            continue
        video = {}
        for cam in [k for k, v in info["features"].items() if v["dtype"] == "video"]:
            try:
                video[cam.split(".")[-1]] = {
                    "file": f"videos/{cam}/chunk-{int(e[f'videos/{cam}/chunk_index']):03d}/"
                            f"file-{int(e[f'videos/{cam}/file_index']):03d}.mp4",
                    "from_s": float(e[f"videos/{cam}/from_timestamp"]), "to_s": float(e[f"videos/{cam}/to_timestamp"])}
            except KeyError:
                pass
        task_idx = int(rows["task_index"].iloc[0]) if "task_index" in rows else None
        docs.append({
            "dataset": root, "episode_index": idx, "task": task_by_index.get(task_idx), "length": int(len(rows)),
            "fps": info["fps"], "duration_s": round(len(rows) / info["fps"], 2), "uploaded_at": time.time(),
            "joints": names,
            "state": [[round(float(x), 3) for x in v] for v in rows["observation.state"]],
            "action": [[round(float(x), 3) for x in v] for v in rows["action"]],
            "timestamp": [round(float(t), 4) for t in rows["timestamp"]],
            "video": video,
        })
    return docs


def _handoff(idx: int):
    """The station's episode_end summary for this dataset index, if it was logged."""
    try:
        r = thermal_log._collection().find_one({"kind": "event", "event": "episode_end", "episode": idx,
                                                "reason": "saved"}, {"_id": 0}, sort=[("t", -1)])
        return {k: r[k] for k in ("grasps", "lifted", "lift_m", "pulled", "released", "handoff_success",
                                  "duration_s", "peak_temps", "session") if k in r} if r else None
    except Exception:  # noqa: BLE001
        return None


def upload(root: str, only: int | None = None) -> int:
    c = _coll()
    n = 0
    for d in build_docs(root, only):
        d["handoff"] = _handoff(d["episode_index"])
        c.replace_one({"dataset": d["dataset"], "episode_index": d["episode_index"]}, d, upsert=True)
        n += 1
        print(f"episode {d['episode_index']:3d}: {d['length']} frames, {d['duration_s']} s"
              + (f", handoff {'SUCCESS' if d['handoff'].get('handoff_success') else 'no'}" if d["handoff"] else ""))
    return n


def upload_episode(root: str, idx: int, task, fps: int, names: list, state, action, timestamp) -> None:
    """From the station at save time (the data parquet stays open until the session ends). Never raises.
    Video locations are filled in by a later plain run of this script."""
    try:
        doc = {"dataset": os.path.expanduser(root), "episode_index": int(idx), "task": task, "length": len(state),
               "fps": fps, "duration_s": round(len(state) / fps, 2), "uploaded_at": time.time(), "joints": names,
               "state": [[round(float(x), 3) for x in v] for v in state],
               "action": [[round(float(x), 3) for x in v] for v in action],
               "timestamp": [round(float(t), 4) for t in timestamp], "video": {}, "handoff": _handoff(int(idx))}
        _coll().replace_one({"dataset": doc["dataset"], "episode_index": doc["episode_index"]}, doc, upsert=True)
    except BaseException as e:  # noqa: BLE001 - telemetry must never break recording
        print(f"to_mongo: episode {idx} not uploaded ({type(e).__name__}); run explore/dataset/to_mongo.py later")


def check(root: str) -> None:
    c = _coll()
    root = os.path.expanduser(root)
    info = json.load(open(os.path.join(root, "meta/info.json")))
    have = sorted(d["episode_index"] for d in c.find({"dataset": root}, {"episode_index": 1}))
    print(f"dataset {root}: {info['total_episodes']} episodes; MongoDB {COLLECTION}: {len(have)} -> {have}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--root", default="~/scrub-dataset")
    p.add_argument("--episode", type=int)
    p.add_argument("--check", action="store_true")
    a = p.parse_args()
    if a.check:
        check(a.root)
    else:
        print(f"uploaded {upload(a.root, a.episode)} episodes to MongoDB scrub.{COLLECTION}")


if __name__ == "__main__":
    main()
