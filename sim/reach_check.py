"""python -m sim.reach_check : reachability of every point in layout.json (for A3 tape positions)."""
import numpy as np

from sim import ik, scene
from sim.sim_arm import ABOVE_Z, PICK_Z


def main():
    L = scene.load_layout()
    pts = []
    items = L["setting_items"][L["setting"]]
    for i, (x, y) in enumerate(L["slots"]):
        pts += [(f"slot {i} ({items[i]}) above", (x, y, ABOVE_Z)), (f"slot {i} ({items[i]}) pick", (x, y, PICK_Z))]
    for name in ("return_spot", "safe_spot"):
        x, y = L[name]
        pts += [(f"{name} above", (x, y, ABOVE_Z)), (f"{name} down", (x, y, PICK_Z + 0.01))]
    r = L["handoff_region"]
    lo, hi = np.array(r["min"]), np.array(r["max"])
    pts.append(("hand zone", tuple(L["hand_zone"])))
    for n, f in (("region center", (lo + hi) / 2), ("region min corner", lo), ("region max corner", hi)):
        pts.append((n, tuple(f)))
    bad = 0
    for name, p in pts:
        ok, err, _ = ik.reachable(p)
        bad += not ok
        print(f"{'OK  ' if ok else 'FAIL'} {name:34s} xyz=({p[0]:.2f},{p[1]:.2f},{p[2]:.2f})  error={err * 1000:.1f} mm")
    print(f"{len(pts) - bad}/{len(pts)} reachable")


main()
