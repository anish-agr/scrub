"""Load settings/<id>.json. Falls back to built-in defaults until Evan's files land."""
import json
from pathlib import Path

SETTINGS_DIR = Path(__file__).resolve().parent.parent / "settings"
SETTING_IDS = ("surgical", "dental", "bench")

_DEFAULTS = {
    "surgical": ("Operating room", [
        ("scalpel", "scalpel", ["blade", "knife", "ten blade", "number ten"], True),
        ("hemostat", "hemostat", ["kelly", "clamp", "hemo"], False),
        ("mayo_scissors", "Mayo scissors", ["mayo", "scissors"], False),
    ]),
    "dental": ("Dental office", [
        ("mouth_mirror", "mouth mirror", ["mirror"], False),
        ("explorer", "explorer", ["probe", "pick"], False),
        ("cotton_pliers", "cotton pliers", ["pliers", "tweezers", "cotton forceps"], False),
    ]),
    "bench": ("Robotics bench", [
        ("needle_nose_pliers", "needle-nose pliers", ["needle nose", "pliers"], False),
        ("wire_cutters", "wire cutters", ["cutters", "snips", "flush cutters"], False),
        ("hex_key", "hex key", ["allen key", "allen wrench", "hex"], False),
    ]),
}


def _default(setting_id: str) -> dict:
    label, items = _DEFAULTS[setting_id]
    return {
        "id": setting_id,
        "label": label,
        "items": [
            {
                "id": i, "name": n, "aliases": a, "sharp": s, "slot": None,
                "pick_instruction": f"pick the {n.lower()}",
                "return_instruction": f"return the {n.lower()}",
            }
            for i, n, a, s in items
        ],
        "return_spot": None,
        "_source": "built-in default",
    }


def load(setting_id: str) -> dict:
    if setting_id not in SETTING_IDS:
        raise KeyError(setting_id)
    path = SETTINGS_DIR / f"{setting_id}.json"
    if path.exists():
        data = json.loads(path.read_text())
        data["_source"] = str(path.relative_to(SETTINGS_DIR.parent))
        return data
    return _default(setting_id)


def item(setting: dict, item_id: str) -> dict | None:
    return next((i for i in setting["items"] if i["id"] == item_id), None)
