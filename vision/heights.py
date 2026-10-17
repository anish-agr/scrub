"""Saved hand height per clinician. The palm target uses the active one."""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_HEIGHT_M = 0.18


def load_heights(path: Path) -> dict:
    if not path.exists():
        return {"default_m": DEFAULT_HEIGHT_M, "clinicians": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("default_m", DEFAULT_HEIGHT_M)
    data.setdefault("clinicians", {})
    return data


def save_heights(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def height_for(data: dict, clinician: str | None) -> float:
    if clinician and clinician in (data.get("clinicians") or {}):
        return float(data["clinicians"][clinician])
    return float(data.get("default_m", DEFAULT_HEIGHT_M))


def set_clinician(data: dict, name: str, hand_height_m: float) -> dict:
    data.setdefault("clinicians", {})[name] = float(hand_height_m)
    return data
