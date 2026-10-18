"""Append one demo batch to docs/DATA-LOG.md.

The line matches the table explore prototype 51 imports, which is the line
arm/record.py should append when that script lands:

| Time | Setting | Item | Direction | Lighting | Demos | Dataset name | Notes |
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = ROOT / "docs" / "DATA-LOG.md"
HEADER = "| Time | Setting | Item | Direction | Lighting | Demos | Dataset name | Notes |"
SEPARATOR = "| --- | --- | --- | --- | --- | --- | --- | --- |"

DIRECTIONS = {
    "hand-out": "hand-out",
    "handover": "hand-out",
    "pick": "hand-out",
    "out": "hand-out",
    "put-back": "put-back",
    "putback": "put-back",
    "return": "put-back",
    "back": "put-back",
}
LIGHTS = ("bright", "normal", "dim")


def _cell(value: str) -> str:
    return str(value).replace("|", "/").replace("\n", " ").strip()


def load_setting(repo: Path, setting_id: str) -> dict:
    path = repo / "settings" / f"{setting_id}.json"
    if not path.exists():
        raise SystemExit(f"no settings/{setting_id}.json")
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_names(repo: Path, setting_id: str, item_id: str) -> tuple[str, str, str]:
    """Return (setting id, setting label, item name) from the tray file."""
    setting = load_setting(repo, setting_id)
    wanted = item_id.replace("-", " ").replace("_", " ").strip().lower()
    for item in setting.get("items") or []:
        names = [item.get("id", ""), item.get("name", "")]
        names.extend(item.get("aliases") or [])
        folded = [name.replace("-", " ").replace("_", " ").strip().lower() for name in names]
        if wanted in folded or item_id == item.get("id"):
            return setting["id"], setting.get("label") or setting["id"], item.get("name") or item["id"]
    known = ", ".join(item["id"] for item in setting.get("items") or [])
    raise SystemExit(f"{item_id!r} is not in {setting_id}. Items: {known}")


def format_row(
    when: str,
    setting_label: str,
    item_name: str,
    direction: str,
    lighting: str,
    demos: int,
    dataset: str,
    notes: str,
) -> str:
    cells = [
        _cell(when),
        _cell(setting_label),
        _cell(item_name),
        _cell(direction),
        _cell(lighting),
        str(int(demos)),
        _cell(dataset or "local"),
        _cell(notes),
    ]
    return "| " + " | ".join(cells) + " |"


def append_row(path: Path, row: str) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else "# Data log\n\n"
    if HEADER not in text:
        text = text.rstrip() + "\n\n" + HEADER + "\n" + SEPARATOR + "\n"
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text + row + "\n", encoding="utf-8")


def log_batch(
    setting: str,
    item: str,
    direction: str,
    lighting: str,
    demos: int,
    dataset: str = "local",
    notes: str = "",
    when: str | None = None,
    path: Path | None = None,
    repo: Path | None = None,
) -> str:
    folded = direction.strip().lower().replace("_", "-")
    if folded not in DIRECTIONS:
        raise SystemExit("direction must be hand-out or put-back")
    if lighting not in LIGHTS:
        raise SystemExit("lighting must be bright, normal, or dim")
    if demos < 1:
        raise SystemExit("demos must be at least 1")
    repo = repo or ROOT
    _setting_id, label, item_name = resolve_names(repo, setting, item)
    stamp = when or datetime.now().strftime("%Y-%m-%d %H:%M")
    row = format_row(stamp, label, item_name, DIRECTIONS[folded], lighting, demos, dataset, notes)
    append_row(path or LOG_PATH, row)
    return row


def log_cli(argv: list[str]) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Append one demo batch to docs/DATA-LOG.md")
    parser.add_argument("--setting", required=True, help="surgical, dental, or bench")
    parser.add_argument("--item", required=True, help="item id or name, such as hemostat or kelly")
    parser.add_argument("--direction", required=True, help="hand-out or put-back")
    parser.add_argument("--lighting", required=True, choices=list(LIGHTS))
    parser.add_argument("--demos", required=True, type=int)
    parser.add_argument("--dataset", default="local", help="Hub repo name, or local")
    parser.add_argument("--notes", default="")
    parser.add_argument("--log", help="path to the markdown log (default docs/DATA-LOG.md)")
    args = parser.parse_args(argv)
    row = log_batch(
        setting=args.setting,
        item=args.item,
        direction=args.direction,
        lighting=args.lighting,
        demos=args.demos,
        dataset=args.dataset,
        notes=args.notes,
        path=Path(args.log) if args.log else None,
    )
    print(row)
    print(f"appended to {args.log or LOG_PATH}")
