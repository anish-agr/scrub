// Explicit permission to choose is not permission to guess: prefer measured real success, then proximity.
import type { Candidate } from "./controller.js";

const finite = (x: unknown): x is number => typeof x === "number" && Number.isFinite(x);
const vector = (v: unknown): v is number[] => Array.isArray(v) && v.length >= 2 && v.every(finite);

function nearest(candidates: Candidate[]): Candidate | undefined {
  const metrics: ((c: Candidate) => number | undefined)[] = [
    (c) => finite(c.distance_m) && c.distance_m >= 0 ? c.distance_m : undefined,
    (c) => finite(c.distance) && c.distance >= 0 ? c.distance : undefined,
    (c) => vector(c.position) ? Math.hypot(...c.position) : undefined,
    (c) => vector(c.arm_xy) ? Math.hypot(...c.arm_xy) : undefined,
    // Same camera convention as vision/instances.py: the person is at the bottom of the image.
    (c) => vector(c.center_px) ? -c.center_px[1] : vector(c.box) && c.box.length === 4 ? -(c.box[1] + c.box[3]) / 2 : undefined,
  ];
  for (const metric of metrics) {
    const rows = candidates.map((c) => ({ c, distance: metric(c) }));
    if (rows.every((r) => r.distance !== undefined)) return rows.sort((a, b) => a.distance! - b.distance!)[0]?.c;
  }
  return candidates.find((c) => (c.instance?.side || c.side) === "closest") || candidates[0];
}

export function chooseCandidate(candidates: Candidate[], stats?: unknown): Candidate | undefined {
  const rates = new Map<string, number>();
  if (stats && typeof stats === "object") {
    const data = stats as { source?: unknown; by_item?: unknown };
    // The controller-memory fallback can include fake tries; the default ledger /stats excludes them.
    if (!String(data.source || "").includes("controller memory") && Array.isArray(data.by_item)) {
      for (const row of data.by_item) {
        if (!row || row.fake_arm || row.sim || row.test || !finite(row.attempts) || row.attempts <= 0) continue;
        const rate = finite(row.success_rate) ? row.success_rate : finite(row.successes) ? row.successes / row.attempts : null;
        if (typeof row.item === "string" && finite(rate) && rate >= 0 && rate <= 1) rates.set(row.item, rate);
      }
    }
  }
  const best = Math.max(-1, ...candidates.map((c) => rates.get(c.item || c.id || "") ?? -1));
  const ranked = best >= 0 ? candidates.filter((c) => rates.get(c.item || c.id || "") === best) : candidates;
  return nearest(ranked);
}
