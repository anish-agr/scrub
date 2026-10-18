"""Load settings/<id>.json (built-in defaults until Evan's files land), with settings/<id>.local.json merged over it.

The .local.json overlay holds clinic-taught aliases ({"aliases": {"hemostat": ["clamp"]}}). Only add_alias writes it;
Evan's <id>.json is never written.
"""
import json
import os
import re
import tempfile
from pathlib import Path

SETTINGS_DIR = Path(__file__).resolve().parent.parent / "settings"
SETTING_IDS = ("surgical", "bench", "dental")  # surgical first, bench second; dental is hidden from pages but still loads

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
    else:
        data = _default(setting_id)
    return _merge(data, _overlay(setting_id))


def _overlay_path(setting_id: str) -> Path:
    return SETTINGS_DIR / f"{setting_id}.local.json"


_warned: set = set()


def _overlay(setting_id: str) -> dict:
    """{item_id: [alias, ...]} from settings/<id>.local.json. Missing or broken gives {} (broken is logged once)."""
    path = _overlay_path(setting_id)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text()).get("aliases") or {}
        return {str(k): [str(a) for a in v] for k, v in raw.items() if isinstance(v, list)}
    except Exception as e:  # noqa: BLE001 - a broken overlay never stops a tray loading
        if str(path) not in _warned:
            _warned.add(str(path))
            print(f"[settings] ignoring {path.name}: {e}")
        return {}


def _merge(data: dict, overlay: dict) -> dict:
    """Add overlay aliases (lowercase, deduped) to the matching items. Unknown item ids are ignored."""
    for it in data["items"]:
        extra = overlay.get(it["id"])
        if not extra:
            continue
        it["aliases"] = list(it.get("aliases") or [])
        have = {a.lower() for a in it["aliases"]}
        for a in map(norm, extra):
            if a and a not in have:
                have.add(a)
                it["aliases"].append(a)
    if overlay:
        data["_overlay"] = str(_overlay_path(data["id"]).relative_to(SETTINGS_DIR.parent))
    return data


def norm(word: str) -> str:
    """Lowercase, single spaces, no leading article: "The  Clamp" -> "clamp"."""
    w = re.sub(r"[^a-z0-9' -]", " ", str(word).lower())
    w = re.sub(r"\s+", " ", w).strip()
    return re.sub(r"^(the|a|an)( |$)", "", w)


def words_for(it: dict) -> set:
    """Every word that names this item: name, id, aliases."""
    return {norm(w) for w in [it["name"], it["id"].replace("_", " "), *(it.get("aliases") or [])]} - {""}


def add_alias(setting_id: str, item_id: str, alias: str) -> None:
    """Append alias to settings/<id>.local.json, atomically (temp file + rename). Never touches <id>.json."""
    path = _overlay_path(setting_id)
    try:
        data = json.loads(path.read_text()) if path.exists() else {}
        if not isinstance(data, dict) or not isinstance(data.get("aliases", {}), dict):
            raise ValueError("not an overlay")
    except Exception as e:  # noqa: BLE001 - a broken overlay is replaced rather than blocking teaching
        print(f"[settings] replacing broken {path.name}: {e}")
        data = {}
    aliases = data.setdefault("aliases", {})
    have = aliases.setdefault(item_id, [])
    if alias not in have:
        have.append(alias)
    fd, tmp = tempfile.mkstemp(dir=SETTINGS_DIR, prefix=f".{setting_id}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    _warned.discard(str(path))


def item(setting: dict, item_id: str) -> dict | None:
    return next((i for i in setting["items"] if i["id"] == item_id), None)
