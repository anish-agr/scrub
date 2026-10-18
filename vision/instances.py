"""Pure candidate validation shared by locate and the controller (no camera/arm imports).

The overhead image is mounted with the surgeon at its bottom: image-left is
surgeon-left, and larger image y is closer. Slots are 1-based, left-to-right
then top-to-bottom unless the producer supplies a stable integer slot.
"""
import math


def box_ok(box):
    return (isinstance(box, (list, tuple)) and len(box) == 4
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in box)
            and box[2] > box[0] and box[3] > box[1])


def candidates(rows, item):
    """(validated candidates, unsafe metadata). Never turn conflicting rows into one arbitrary object."""
    out, unsafe = [], False
    for row in rows:
        if not isinstance(row, dict) or row.get("item", item) != item or row.get("present") is False:
            continue
        inst = row.get("instance") or {}
        if not isinstance(inst, dict):
            unsafe = True
            continue
        c = {"item": item}
        if any(key in row and key in inst and row[key] != inst[key] for key in ("variant", "side", "slot")):
            unsafe = True
            continue
        for key in ("variant", "side", "slot"):
            val = row.get(key, inst.get(key))
            if val is not None:
                c[key] = val
        if ("slot" in c and (type(c["slot"]) is not int or c["slot"] < 1)
                or "variant" in c and not isinstance(c["variant"], str)
                or "side" in c and c["side"] not in ("left", "right", "closest")):
            unsafe = True
            continue
        box = row.get("box")
        if box is not None:
            if not box_ok(box):
                unsafe = True
                continue
            c["box"] = list(box)
        if row.get("id"):
            c["id"] = str(row["id"])
        if row.get("label"):
            c["label"] = str(row["label"])
        if "slot" in c:
            c["slot_source"] = row.get("slot_source", "explicit")
        out.append(c)
    if out and all(c.get("box") for c in out):
        out.sort(key=lambda c: ((c["box"][0] + c["box"][2]) / 2, (c["box"][1] + c["box"][3]) / 2))
        for n, c in enumerate(out, 1):
            if "slot" not in c:
                c["slot_source"] = "generated"
            c.setdefault("slot", n)
        xs = [(c["box"][0] + c["box"][2]) / 2 for c in out]
        ys = [(c["box"][1] + c["box"][3]) / 2 for c in out]
        for i, c in enumerate(out):
            # Only unique extrema earn a relative name. A tied answer must clarify.
            if len(out) == 2 and xs.count(xs[i]) == 1:
                side = "left" if xs[i] == min(xs) else "right"
                if c.get("side", side) != side:
                    unsafe = True
                c["side"] = side
            elif len(out) > 2 and ys[i] == max(ys) and ys.count(ys[i]) == 1:
                if c.get("side", "closest") != "closest":
                    unsafe = True
                c.setdefault("side", "closest")
            elif len(out) > 2 and c.get("side") == "closest":
                unsafe = True
    slots = [c["slot"] for c in out if "slot" in c]
    ids = [c["id"] for c in out if "id" in c]
    if len(slots) != len(set(slots)) or len(ids) != len(set(ids)):
        unsafe = True
    boxes = [tuple(c["box"]) for c in out if c.get("box")]
    if len(boxes) != len(set(boxes)):
        unsafe = True
    for i, c in enumerate(out):
        for other in out[i + 1:]:
            a, b = c.get("box"), other.get("box")
            if a and b and min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1]):
                unsafe = True  # overlapping instances cannot safely identify a physical grasp target
    for c in out:
        c["instance"] = {k: c[k] for k in ("variant", "side", "slot") if k in c}
        label = c.get("variant")
        if label and sum(o.get("variant") == label for o in out) > 1:
            label += " " + (c.get("side") or (f"slot {c['slot']}" if "slot" in c else "(position unknown)"))
        c.setdefault("label", label or c.get("side") or (f"slot {c['slot']}" if "slot" in c else item.replace("_", " ")))
    return out, unsafe


def stabilize(current, previous):
    """Keep generated physical slot identities when another object disappears; no nearest-object guess."""
    out, used = [], set()
    for raw in current:
        c = dict(raw)
        old = [p for p in previous if p.get("item") == c.get("item") and p.get("box") and c.get("box")
               and min(p["box"][2], c["box"][2]) > max(p["box"][0], c["box"][0])
               and min(p["box"][3], c["box"][3]) > max(p["box"][1], c["box"][1])]
        if c.get("slot_source") == "generated":
            if len(old) > 1 or len(old) == 1 and (c["item"], old[0].get("slot")) in used:
                c["identity_ambiguous"] = True
            if len(old) == 1 and old[0].get("slot") is not None and (c["item"], old[0]["slot"]) not in used:
                c["slot"] = old[0]["slot"]
                if not c.get("side") and old[0].get("side"):
                    c["side"] = old[0]["side"]
                    c["instance"] = {**c.get("instance", {}), "side": c["side"]}
            elif previous:
                # An unmatched detection is a new identity, not a missing object's recycled number.
                c["slot"] = 1 + max([p.get("slot", 0) for p in previous + out if p.get("item") == c["item"]] or [0])
        if c.get("slot") is not None:
            used.add((c["item"], c["slot"]))
            c.setdefault("id", f"{c['item']}:slot:{c['slot']}")
            c["instance"] = {**c.get("instance", {}), "slot": c["slot"]}
            if str(c.get("label", "")).startswith("slot "):
                c["label"] = f"slot {c['slot']}"
        out.append(c)
    return out


def select(options, hint):
    """Exactly one match, never the first of several. All supplied hints must agree."""
    if not isinstance(hint, dict) or not hint or any(k not in ("variant", "side", "slot") for k in hint):
        return None
    def match_field(c, key, value):
        actual = c.get(key, (c.get("instance") or {}).get(key))
        if key == "variant" and isinstance(actual, str) and isinstance(value, str):
            return actual.casefold() == value.casefold()
        return actual == value
    matches = [c for c in options if all(match_field(c, k, v) for k, v in hint.items() if v is not None)]
    return matches[0] if len(matches) == 1 else None
