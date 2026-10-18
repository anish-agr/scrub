"""Append docs/DATA-LOG.md rows for saved episodes, from dataset metadata only.

  python -m arm.datalog sync --root ~/scrub-dataset [--lighting normal] [--dry-run]

Reads meta/info.json, the episode metadata (meta/episodes.jsonl or meta/episodes/**/*.parquet)
and <root>-cadence.json. Never opens frames or videos and never writes into the dataset.
One row per batch: a run of consecutive episodes with the same task and lighting. Rows
carry "<root name> ep A-B" in the notes, so a rerun only adds episodes not logged yet.
Lighting comes from a cadence entry's "lighting" field, else --lighting, else "unknown".
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re

from ledger.logbook import append_row, format_row

ROOT = Path(__file__).resolve().parents[1]
DATA_LOG = ROOT / "docs" / "DATA-LOG.md"
SETTINGS = ROOT / "settings"


def episodes(root: Path) -> list[dict]:
    """[{episode_index, task, length}] for every saved episode whose metadata reads."""
    info = json.loads((root / "meta/info.json").read_text())
    rows = []
    if str(info.get("codebase_version", "")).startswith("v2"):
        tasks = {}
        tasks_path = root / "meta/tasks.jsonl"
        if tasks_path.exists():
            for line in tasks_path.read_text().splitlines():
                if line.strip():
                    entry = json.loads(line)
                    tasks[entry.get("task_index")] = entry.get("task")
        for line in (root / "meta/episodes.jsonl").read_text().splitlines():
            if line.strip():
                rows.append(json.loads(line))
    else:
        import pyarrow.parquet as pq
        for path in sorted((root / "meta/episodes").rglob("*.parquet")):
            try:
                rows += pq.ParquetFile(path).read(columns=["episode_index", "tasks", "length"]).to_pylist()
            except Exception:  # noqa: BLE001 - a file still being written is skipped
                print(f"skipping {path.relative_to(root)} (still being written?)")
    out = []
    for row in rows:
        task = row.get("tasks")
        if isinstance(task, (list, tuple)):
            task = " + ".join(str(t) for t in task)
        out.append({"episode_index": int(row["episode_index"]), "task": str(task or "unknown"),
                    "length": int(row.get("length") or 0)})
    return sorted(out, key=lambda e: e["episode_index"])


def cadence(path: Path) -> dict[int, dict]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    return {int(e["episode_index"]): e for e in data.get("episodes", []) if "episode_index" in e}


def describe(task: str, settings: Path = SETTINGS) -> tuple[str, str, str, bool]:
    """(setting label, item name, direction, known) for an instruction."""
    for path in sorted(settings.glob("*.json")):
        try:
            setting = json.loads(path.read_text())
        except ValueError:
            continue
        for item in setting.get("items") or []:
            for key, direction in (("pick_instruction", "hand-out"), ("return_instruction", "put-back")):
                if item.get(key, "").strip().lower() == task.strip().lower():
                    return (setting.get("label") or setting.get("id", path.stem),
                            item.get("name") or item["id"], direction, True)
    words = task.strip().lower().split()
    direction = {"pick": "hand-out", "return": "put-back"}.get(words[0] if words else "", "unknown")
    noun = " ".join(words[2:] if len(words) > 2 and words[1] == "the" else words[1:]) or task
    return "unknown", noun, direction, False


def logged(log_text: str, name: str) -> set[int]:
    """Episode indexes already logged for this dataset name."""
    done = set()
    for start, end in re.findall(rf"(?<![\w.-]){re.escape(name)} ep (\d+)-(\d+)", log_text):
        done.update(range(int(start), int(end) + 1))
    return done


def span(values, fmt="{:.2f}"):
    values = [v for v in values if isinstance(v, (int, float))]
    if not values:
        return None
    low, high = min(values), max(values)
    return fmt.format(low) if low == high else f"{fmt.format(low)}-{fmt.format(high)}"


def notes(name: str, batch: list[dict], timing: dict[int, dict], task: str, known: bool) -> str:
    first, last = batch[0]["episode_index"], batch[-1]["episode_index"]
    parts = [f"{name} ep {first}-{last}"]
    if not known:
        parts.append(f"task '{task}' not in settings")
    entries = [timing[e["episode_index"]] for e in batch if e["episode_index"] in timing]
    missing = [e["episode_index"] for e in batch if e["episode_index"] not in timing]
    loop = span([t.get("measured_fps") for t in entries])
    if loop:
        out_of_range = [e for e, t in ((e["episode_index"], timing.get(e["episode_index"])) for e in batch)
                        if t and not 29 <= t.get("measured_fps", 0) <= 31]
        parts.append(f"loop {loop} Hz" + (f" (outside 29-31 on ep {out_of_range})" if out_of_range else ""))
    for cam in ("side", "wrist"):
        fps = span([t.get("camera_fps", {}).get(cam) for t in entries], "{:.1f}")
        if fps:
            parts.append(f"{cam} cam {fps} fps")
    stalls = {e: t.get("camera_stalls") for e, t in ((e["episode_index"], timing.get(e["episode_index"])) for e in batch)
              if t and t.get("camera_stalls")}
    if stalls:
        parts.append("stalls " + ", ".join(f"ep {e} {s}" for e, s in stalls.items()))
    seconds = span([t.get("seconds") for t in entries], "{:.0f}")
    if seconds:
        parts.append(f"{seconds} s")
    if missing:
        parts.append(f"no cadence for ep {missing}")
    return "; ".join(parts)


def plan(root: Path, timing: dict[int, dict], log_text: str, lighting: str, dataset: str,
         settings: Path = SETTINGS) -> list[str]:
    name = root.name
    done = logged(log_text, name)
    fresh = [e for e in episodes(root) if e["episode_index"] not in done]
    batches = []
    for episode in fresh:
        light = timing.get(episode["episode_index"], {}).get("lighting") or lighting
        key = (episode["task"], light)
        previous = batches[-1] if batches else None
        if previous and previous[0] == key and previous[1][-1]["episode_index"] + 1 == episode["episode_index"]:
            previous[1].append(episode)
        else:
            batches.append((key, [episode]))
    rows = []
    for (task, light), batch in batches:
        label, item, direction, known = describe(task, settings)
        stamp = timing.get(batch[0]["episode_index"], {}).get("recorded_at")
        try:
            when = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S%z").strftime("%Y-%m-%d %H:%M")
        except (TypeError, ValueError):
            when = datetime.now().strftime("%Y-%m-%d %H:%M")
        rows.append(format_row(when, label, item, direction, light, len(batch), dataset,
                               notes(name, batch, timing, task, known)))
    return rows


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m arm.datalog", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    sync = sub.add_parser("sync", help="append rows for episodes not in the log yet")
    sync.add_argument("--root", required=True, help="dataset root, e.g. ~/scrub-dataset")
    sync.add_argument("--cadence", help="default <root>-cadence.json")
    sync.add_argument("--log", default=str(DATA_LOG))
    sync.add_argument("--lighting", default="unknown", help="bright, normal or dim for new rows (default unknown)")
    sync.add_argument("--dataset", default="local", help="Hub name, or local")
    sync.add_argument("--dry-run", action="store_true", help="print rows, change nothing")
    a = p.parse_args(argv)
    root = Path(a.root).expanduser().resolve()
    timing = cadence(Path(a.cadence).expanduser() if a.cadence else Path(f"{root}-cadence.json"))
    log = Path(a.log)
    text = log.read_text(encoding="utf-8") if log.exists() else ""
    rows = plan(root, timing, text, a.lighting, a.dataset)
    for row in rows:
        print(row)
        if not a.dry_run:
            append_row(log, row)
    if not rows:
        print("nothing new to log")
    elif not a.dry_run:
        print(f"appended {len(rows)} row(s) to {log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
