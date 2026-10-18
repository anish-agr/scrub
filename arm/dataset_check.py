"""Local preflight, not a replacement for replay or Perceptron's validator.

Only reads a dataset when the operator explicitly supplies its root to the CLI.
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
    lengths = {}
    for episode in episodes:
        index, length = episode.get("episode_index"), episode.get("length")
        if type(index) is not int or type(length) is not int or length < 2 or index in lengths:
            raise ValueError("Invalid, empty or duplicate episode metadata")
        lengths[index] = length
    if set(lengths) != set(range(count)):
        raise ValueError("Episode metadata count/indexes do not match info.json")

    data_files = sorted((root / "data").rglob("*.parquet"))
    if not data_files:
        raise ValueError("No local data parquet files")
    seen = {index: [] for index in lengths}
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
                seen[index].append(frame)
    if any(sorted(frames) != list(range(lengths[index])) for index, frames in seen.items()):
        raise ValueError("Missing, duplicated or incomplete episode frames")
    if sum(lengths.values()) != info.get("total_frames"):
        raise ValueError("Episode lengths disagree with total_frames")

    cadence_path = Path(cadence_report)
    cadence = json.loads(cadence_path.read_text())
    measured = {}
    for entry in cadence.get("episodes", []):
        index, hz = entry.get("episode_index"), entry.get("measured_fps")
        if type(index) is not int or index in measured or not isinstance(hz, (int, float)) or not math.isfinite(hz) or not 29 <= hz <= 31:
            raise ValueError("Recording cadence must be measured at about 30 Hz (29..31) for every episode")
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
    return {"episodes": count, "frames": sum(lengths.values()), "fps": 30,
            "measured_fps_min": min(measured.values()), "measured_fps_max": max(measured.values()),
            "fingerprint": digest.hexdigest(),
            "note": "Media dimensions are checked from metadata, not decoded. Replay and service validation are still required."}
