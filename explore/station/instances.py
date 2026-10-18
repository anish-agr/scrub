"""Station instance selectors. Image is unmirrored; surgeon faces the camera across the tray."""
from __future__ import annotations

import math

ORIENTATION = "Surgeon opposite the side camera: your left = image right; closest = image top."
CLARIFY_TIMEOUT_S = 15.0


def parse_instance(value):
    if value is None:
        return {}
    if not isinstance(value, dict) or set(value) - {"variant", "side", "slot"}:
        raise ValueError("instance must contain only variant, side and/or slot")
    out = dict(value)
    if "side" in out and out["side"] not in ("left", "right", "closest"):
        raise ValueError("instance.side must be left, right or closest")
    if "slot" in out and (type(out["slot"]) is not int or out["slot"] < 1):
        raise ValueError("instance.slot must be a positive integer (1 = surgeon-leftmost)")
    if "variant" in out:
        if not isinstance(out["variant"], str) or not out["variant"].strip():
            raise ValueError("instance.variant must be a non-empty string")
        out["variant"] = out["variant"].strip().lower()
    return out


def unique_hits(hits, distance_px=3.0):
    """Overlapping category boxes/votes of one physical rod must not create a question."""
    out = []
    for hit in hits:
        if not any(math.dist(hit[:2], old[:2]) <= distance_px for old in out):
            out.append(hit)
    return out


def candidates(hits):
    # Slots are one-based, surgeon-left to right (reverse of unmirrored camera x).
    return [{"slot": i + 1, "pixel": [float(h[0]), float(h[1])], "hit": h,
             "variant": h[4] if len(h) > 4 else None}
            for i, h in enumerate(sorted(hits, key=lambda h: (-h[0], h[1])))]


def select(rows, instance):
    """None means still ambiguous. An unverified qualifier is refused, never silently dropped."""
    pool = rows
    if "variant" in instance:
        pool = [r for r in pool if r["variant"] == instance["variant"]]
        if not pool:
            raise ValueError("detector cannot verify that instance.variant")
    side = instance.get("side")
    if side:
        key = {"left": lambda r: -r["pixel"][0], "right": lambda r: r["pixel"][0],
               "closest": lambda r: r["pixel"][1]}[side]
        chosen = min(pool, key=key)
        if "slot" in instance and chosen["slot"] != instance["slot"]:
            raise ValueError("instance.slot and instance.side refer to different candidates")
        return chosen
    if "slot" in instance:
        pool = [r for r in pool if r["slot"] == instance["slot"]]
        if not pool:
            raise ValueError("instance.slot is not among the detected candidates")
    return pool[0] if len(pool) == 1 else None
