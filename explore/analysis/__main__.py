"""python -m explore.analysis [--fixture data.json] [--out DIR]"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib
import json
from pathlib import Path

from explore.analysis import REPORTS
from explore.analysis.source import ROOT, arm_kind, load, tag_start


def overview(data: dict) -> dict:
    start = tag_start(data["events"])
    kinds: dict[str, int] = {}
    for e in data["events"]:
        k = arm_kind(e, start)
        kinds[k] = kinds.get(k, 0) + 1
    hours = sum(ep.get("duration_s") or 0 for ep in data["episodes"]) / 3600
    return {"events": len(data["events"]), "episodes": len(data["episodes"]), "thermal": len(data["thermal"]),
            "events_by_arm": kinds, "tag_start": start, "hours_recorded": round(hours, 3)}


def stamp(t: float) -> str:
    return dt.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M")


def run(fixture: str | None, out: Path) -> dict:
    data = load(fixture)
    charts = out / "docs" / "media" / "data"
    charts.mkdir(parents=True, exist_ok=True)
    read_at = stamp(data["read_at"])
    ov = overview(data)
    sections = {}
    for name in REPORTS:
        mod = importlib.import_module(f"explore.analysis.{name}")
        sections[name] = mod.build(data, charts)
    numbers = [{**n, "read_at": read_at} for s in sections.values() for n in s.get("numbers", [])]
    result = {"read_at": data["read_at"], "read_at_text": read_at, "source": data["source"], "overview": ov,
              "numbers": numbers, **{k: s["summary"] for k, s in sections.items()}}

    start = f"{stamp(ov['tag_start'])}" if ov["tag_start"] else "never"
    kinds = ", ".join(f"{k} {v}" for k, v in sorted(ov["events_by_arm"].items()))
    head = [
        "# Data: what MongoDB says",
        "",
        f"Read {read_at} from `{data['source'] if data['source'] != 'mongo' else 'MongoDB Atlas, database scrub'}`. "
        "Regenerate with `.venv/bin/python -m explore.analysis`. Machine-readable copy: `data/analysis.json` "
        "(committed snapshot `docs/media/data/analysis.json`). Read-only: nothing here edits MongoDB.",
        "",
        f"- {ov['events']} events, {ov['episodes']} episodes ({ov['hours_recorded']:.2f} h recorded), {ov['thermal']} thermal rows",
        f"- Events by arm: {kinds}. Tags (`fake_arm`) started {start}; earlier rows are test data (`pretag`).",
        "",
        "## Pitch and Devpost numbers",
        "",
        "| Number | Value | Query | Read |",
        "| --- | --- | --- | --- |",
        *[f"| {n['name']} | {n['value']} | `{n['query']}` | {n['read_at']} |" for n in numbers],
        "",
    ]
    md = "\n".join(head + [f"## {s['title']}\n\n{s['markdown'].strip()}\n" for s in sections.values()])
    (out / "docs").mkdir(exist_ok=True)
    (out / "docs" / "DATA.md").write_text(md + "\n")
    blob = json.dumps(result, indent=1, default=str)
    (out / "data").mkdir(exist_ok=True)
    (out / "data" / "analysis.json").write_text(blob)
    (charts / "analysis.json").write_text(blob)
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fixture", help="JSON file with events, episodes, thermal (instead of MongoDB)")
    p.add_argument("--out", default=str(ROOT), help="root to write docs/ and data/ under (default: repo)")
    a = p.parse_args()
    r = run(a.fixture, Path(a.out))
    print(f"read {r['read_at_text']}: {r['overview']['events']} events, wrote docs/DATA.md, data/analysis.json")
    for n in r["numbers"]:
        print(f"  {n['name']}: {n['value']}")


if __name__ == "__main__":
    main()
