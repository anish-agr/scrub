"""Change the task text of some episodes in a LeRobot v3 dataset (the instruction the model trains on).

  .venv/bin/python explore/dataset/retask.py --from-episode 3 --task "pick the scalpel handle"   # dry run
  .venv/bin/python explore/dataset/retask.py --from-episode 3 --task "pick the scalpel handle" --apply

Run only while nothing has the dataset open (stop the recording station with Ctrl-C first).
--apply backs up meta/ and data/ to <root>.backup-<time>/ first, then:
  meta/tasks.parquet          adds the new task (new task_index) if it isn't there
  data/**/*.parquet           task_index of the chosen episodes' frames -> the new index
  meta/episodes/**/*.parquet  the `tasks` list of the chosen episodes -> [new task]
Videos and joint data are untouched. Afterwards it reloads the dataset with LeRobotDataset to check.
"""
from __future__ import annotations

import argparse
import glob
import os
import shutil
import subprocess
import sys
import time

import pandas as pd


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--root", default="~/scrub-dataset")
    p.add_argument("--from-episode", type=int, required=True)
    p.add_argument("--to-episode", type=int, help="inclusive; default: the last episode")
    p.add_argument("--task", required=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--no-recorder-check", action="store_true", help=argparse.SUPPRESS)  # tests on a copy
    a = p.parse_args()
    root = os.path.expanduser(a.root)
    if not a.no_recorder_check and subprocess.run(["pgrep", "-f", "station/station.py|arm_session.py|lerobot-record"], capture_output=True).stdout:
        sys.exit("a recorder has the dataset open: stop it (Ctrl-C) first")

    tasks = pd.read_parquet(os.path.join(root, "meta/tasks.parquet"))
    if a.task in tasks.index:
        new_idx = int(tasks.loc[a.task, "task_index"])
    else:
        new_idx = int(tasks["task_index"].max()) + 1
        tasks = pd.concat([tasks, pd.DataFrame({"task_index": [new_idx]}, index=pd.Index([a.task], name=tasks.index.name))])
    hi = a.to_episode if a.to_episode is not None else 10 ** 9
    pick = lambda s: (s >= a.from_episode) & (s <= hi)  # noqa: E731

    data_files = sorted(glob.glob(os.path.join(root, "data/**/*.parquet"), recursive=True))
    ep_files = sorted(glob.glob(os.path.join(root, "meta/episodes/**/*.parquet"), recursive=True))
    changes, frames = [], 0
    for f in data_files:
        d = pd.read_parquet(f)
        m = pick(d["episode_index"])
        if m.any():
            frames += int(m.sum())
            changes.append((f, "data", sorted(d.loc[m, "episode_index"].unique().tolist())))
    eps = []
    for f in ep_files:
        e = pd.read_parquet(f)
        m = pick(e["episode_index"])
        if m.any():
            eps += e.loc[m, "episode_index"].tolist()
            changes.append((f, "episodes", sorted(e.loc[m, "episode_index"].tolist())))
    print(f"task {a.task!r} -> task_index {new_idx}; episodes {sorted(set(eps))}; {frames} frames in {len(data_files)} data files")
    if not a.apply:
        print("dry run: add --apply to change the dataset (it backs up first)")
        return

    backup = f"{root}.backup-{time.strftime('%Y%m%d-%H%M%S')}"
    os.makedirs(backup)
    for sub in ("meta", "data"):
        shutil.copytree(os.path.join(root, sub), os.path.join(backup, sub))
    print("backup:", backup)
    tasks.to_parquet(os.path.join(root, "meta/tasks.parquet"))
    for f, kind, _ in changes:
        df = pd.read_parquet(f)
        m = pick(df["episode_index"])
        if kind == "data":
            df.loc[m, "task_index"] = new_idx
        else:
            df["tasks"] = [[a.task] if sel else t for t, sel in zip(df["tasks"], m)]
        df.to_parquet(f, index=False)
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    ds = LeRobotDataset("local/scrub", root=root)
    first = ds.meta.episodes[a.from_episode]["dataset_from_index"]
    print("check:", ds.meta.total_episodes, "episodes; tasks", list(ds.meta.tasks.index),
          f"; episode {a.from_episode} first frame task:", ds[int(first)]["task"])


if __name__ == "__main__":
    main()
