"""Local preflight, not a replacement for replay or Perceptron's validator.

Only reads a dataset when the operator explicitly supplies its root:
  python -m arm.dataset_check ~/scrub-dataset [--cadence-report ~/scrub-dataset-cadence.json]
Cadence must come from the recording clock, never frame-index timestamps.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np

from .kinematics import FEATURES

CAMERAS = ("observation.images.side", "observation.images.wrist")
SETTINGS = Path(__file__).resolve().parents[1] / "settings"
MIN_EPISODES_PER_TASK = 10  # the service splits ~90/10 by whole episode, stratified by task
SHOULDER_LIFT = 1           # state index; this arm rests near -100 deg, so degrees leave -10..10
RADIANS_BAND = 10.0


def instructions(settings=SETTINGS):
    """Exact pick/return strings from settings/*.json (the words the model is told later)."""
    allowed = set()
    for path in sorted(Path(settings).glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except ValueError:
            continue
        for item in data.get("items") or []:
            allowed.update(item[k] for k in ("pick_instruction", "return_instruction") if item.get(k))
    return allowed


def local_check(root, cadence_report):
    import pyarrow.parquet as pq

    root = Path(root).resolve()
    info_path = root / "meta/info.json"
    info = json.loads(info_path.read_text())
    if info.get("codebase_version") not in {"v2.0", "v2.1", "v3.0"}:
        raise ValueError("Expected LeRobot dataset v2.0, v2.1 or v3.0")
    if info.get("fps") != 30:
        raise ValueError("Dataset fps must be exactly 30")
    count = info.get("total_episodes")
    if type(count) is not int or count < 2:
        raise ValueError("At least two whole episodes are needed for train/validation")
    features = info.get("features", {})
    images = {name for name, feature in features.items() if feature.get("dtype") in {"video", "image"}}
    if images != set(CAMERAS):
        raise ValueError("Expected exactly side and wrist image streams")
    for name in CAMERAS:
        feature = features[name]
        if feature.get("shape") != [480, 640, 3]:
            raise ValueError(f"{name} must be RGB 640x480")
    for name in ("observation.state", "action"):
        feature = features.get(name, {})
        names = feature.get("names")
        if isinstance(names, dict):
            names = names.get("motors")  # older LeRobot metadata
        if feature.get("dtype") != "float32" or feature.get("shape") != [6] or names != list(FEATURES):
            raise ValueError(f"{name} must contain the six named float32 joints in contract order")

    episode_path = root / "meta/episodes.jsonl"
    if info["codebase_version"].startswith("v2"):
        episodes = [json.loads(line) for line in episode_path.read_text().splitlines() if line.strip()]
        metadata_files = [episode_path]
    else:
        metadata_files = sorted((root / "meta/episodes").rglob("*.parquet"))
        episodes = [row for path in metadata_files for row in pq.ParquetFile(path).read().to_pylist()]
    allowed = instructions()
    lengths = {}
    task_counts = {}
    for episode in episodes:
        tasks = episode.get("tasks")
        tasks = [tasks] if isinstance(tasks, str) else list(tasks or [])
        wrong = [t for t in tasks if t not in allowed]
        if not tasks or wrong:
            raise ValueError(f"Episode {episode.get('episode_index')} task {wrong or tasks!r} is not an exact "
                             "pick/return instruction from settings/*.json")
        index, length = episode.get("episode_index"), episode.get("length")
        if type(index) is not int or type(length) is not int or length < 2 or index in lengths:
            raise ValueError("Invalid, empty or duplicate episode metadata")
        lengths[index] = length
        for task in set(tasks):
            task_counts[task] = task_counts.get(task, 0) + 1
    if set(lengths) != set(range(count)):
        raise ValueError("Episode metadata count/indexes do not match info.json")
    few = {task: n for task, n in sorted(task_counts.items()) if n < MIN_EPISODES_PER_TASK}
    if few:
        raise ValueError(f"Need at least {MIN_EPISODES_PER_TASK} episodes per task (the service splits ~90/10 "
                         f"stratified by task); too few: " + ", ".join(f"{t!r}={n}" for t, n in few.items()))

    data_files = sorted((root / "data").rglob("*.parquet"))
    if not data_files:
        raise ValueError("No local data parquet files")
    seen = {index: [] for index in lengths}
    lift_peak = 0.0  # largest |shoulder_lift| in observation.state over the whole dataset
    for path in data_files:
        for batch in pq.ParquetFile(path).iter_batches(columns=["episode_index", "frame_index", "timestamp", "observation.state", "action"]):
            for row in batch.to_pylist():
                index, frame, stamp = row["episode_index"], row["frame_index"], row["timestamp"]
                if index not in seen or type(frame) is not int or frame < 0 or not math.isfinite(stamp):
                    raise ValueError("Invalid episode/frame/timestamp in data")
                if abs(stamp - frame / 30) > .002:
                    raise ValueError("Data timestamps disagree with frame indices at 30 FPS")
                for name in ("observation.state", "action"):
                    values = np.asarray(row[name], dtype=float)
                    if values.shape != (6,) or not np.isfinite(values).all() or not 0 <= values[5] <= 100:
                        raise ValueError("Invalid six-value state/action or gripper range")
                    if name == "observation.state":
                        lift_peak = max(lift_peak, abs(float(values[SHOULDER_LIFT])))
                seen[index].append(frame)
    if any(sorted(frames) != list(range(lengths[index])) for index, frames in seen.items()):
        raise ValueError("Missing, duplicated or incomplete episode frames")
    if sum(lengths.values()) != info.get("total_frames"):
        raise ValueError("Episode lengths disagree with total_frames")
    if lift_peak <= RADIANS_BAND:
        raise ValueError(f"Every shoulder_lift state sample stays within -{RADIANS_BAND:g}..{RADIANS_BAND:g}: "
                         "this looks like radians or a non-degree recording (the arm rests near -100 deg). "
                         "Re-record with --robot.use_degrees=true --teleop.use_degrees=true")

    cadence_path = Path(cadence_report)
    cadence = json.loads(cadence_path.read_text())
    measured = {}
    for entry in cadence.get("episodes", []):
        index, hz = entry.get("episode_index"), entry.get("measured_fps")
        if type(index) is not int or index in measured or not isinstance(hz, (int, float)) or not math.isfinite(hz) or not 29 <= hz <= 31:
            raise ValueError("Recording cadence must be measured at about 30 Hz (29..31) for every episode")
        cams = entry.get("camera_fps") or {}
        for cam in ("side", "wrist"):
            fps = cams.get(cam)
            if not isinstance(fps, (int, float)) or not math.isfinite(fps) or not 29 <= fps <= 31:
                raise ValueError(f"Episode {index} {cam} camera ran at {fps} fps; every episode needs "
                                 "camera_fps side and wrist measured at 29..31 (re-record it)")
        if entry.get("use_degrees") is not True:
            raise ValueError(f"Episode {index} cadence entry lacks \"use_degrees\": true; the recorder must "
                             "write it only when --robot.use_degrees=true and --teleop.use_degrees=true were passed")
        measured[index] = hz
    if set(measured) != set(lengths):
        raise ValueError("Cadence evidence must cover every recorded episode")

    # Pin a local snapshot for safe resumption. Include media bytes, not just
    # frame metadata: editing a video must invalidate the pipeline state.
    digest = hashlib.sha256()
    paths = sorted(set([info_path, *metadata_files, *data_files,
                        *(root / "videos").rglob("*"), *(root / "images").rglob("*")]))
    for path in paths:
        if path.is_symlink():
            raise ValueError("Dataset symlinks are not supported")
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode())
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024**2), b""):
                    digest.update(block)
    digest.update(cadence_path.read_bytes())
    return {"episodes": count, "frames": sum(lengths.values()), "fps": 30, "tasks": dict(sorted(task_counts.items())),
            "measured_fps_min": min(measured.values()), "measured_fps_max": max(measured.values()),
            "fingerprint": digest.hexdigest(),
            "note": "Media dimensions are checked from metadata, not decoded. Replay and service validation are still required."}


def main(argv=None) -> int:
    """python -m arm.dataset_check ~/scrub-dataset [--cadence-report ~/scrub-dataset-cadence.json]"""
    import argparse
    p = argparse.ArgumentParser(prog="python -m arm.dataset_check",
                                description="Local preflight of a LeRobot dataset before upload: 30 fps metadata, "
                                            "side and wrist streams, six joints, whole episodes, and a recording "
                                            "cadence of 29-31 Hz for every episode. Reads only the root you pass.")
    p.add_argument("root", help="dataset root, e.g. ~/scrub-dataset")
    p.add_argument("--cadence-report", help="per-episode loop rate JSON (default <root>-cadence.json, "
                                            "written by explore/arm_session.py)")
    a = p.parse_args(argv)
    root = Path(a.root).expanduser()
    cadence = Path(a.cadence_report).expanduser() if a.cadence_report else Path(f"{root}-cadence.json")
    try:
        report = local_check(root, cadence)
    except (ValueError, OSError, KeyError) as e:
        print(f"NOT READY: {e}")
        return 1
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
