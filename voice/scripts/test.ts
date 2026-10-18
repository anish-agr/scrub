// Offline checks for parsing and the case summary: `npm test`. No keys, no controller needed.
import assert from "node:assert/strict";
import { localParse } from "../src/parse.js";
import { caseFacts, newCase, recordEvent, templateSummary } from "../src/summary.js";
import type { Setting } from "../src/settings.js";

const bench: Setting = { id: "bench", label: "Robotics bench", items: [
  { id: "needle_nose_pliers", name: "needle-nose pliers", aliases: ["pliers"], sharp: false },
  { id: "wire_cutters", name: "wire cutters", aliases: ["snips"], sharp: false },
] };
assert.deepEqual(localParse("hand me the needle-nose pliers", bench), { action: "handover", item: "needle_nose_pliers" });
assert.deepEqual(localParse("needle nose pliers please", bench), { action: "handover", item: "needle_nose_pliers" });
assert.deepEqual(localParse("snips", bench), { action: "handover", item: "wire_cutters" });

let t = 0;
const ev = (type: string, extra: Record<string, unknown> = {}) => recordEvent({ type, t: ++t, ...extra } as any);
newCase();
// a: retried pick, then handed and released
ev("missed", { command_id: "a", item: "hemostat", retries: 1 });
ev("picked", { command_id: "a", item: "hemostat" });
ev("handed", { command_id: "a", item: "hemostat", request_to_hand_s: 6 });
ev("released", { command_id: "a", item: "hemostat", out: ["hemostat"] });
// b: handed, nobody pulled, set down (unplanned): not a pass, and not counted twice
ev("picked", { command_id: "b", item: "mayo_scissors" });
ev("handed", { command_id: "b", item: "mayo_scissors", request_to_hand_s: 8 });
ev("set_down", { command_id: "b", item: "mayo_scissors", out: ["hemostat", "mayo_scissors"] });
// c: scalpel to the safe spot (planned)
ev("picked", { command_id: "c", item: "scalpel" });
ev("set_down", { command_id: "c", item: "scalpel", request_to_hand_s: 5, out: ["hemostat", "mayo_scissors", "scalpel"] });
// d: not on the tray
ev("missed", { command_id: "d", item: "hemostat" });
ev("stopped", { out: ["hemostat", "mayo_scissors", "scalpel"] });
const f = caseFacts();
assert.deepEqual(f.passed, { hemostat: 1, scalpel: 1 });
assert.deepEqual(f.set_down_at_safe_spot, { mayo_scissors: 1 });
assert.equal(f.picks_retried, 1);
assert.equal(f.failed_requests, 1);
assert.equal(f.stops, 1);
assert.equal(f.median_request_to_hand_s, 6);  // 5, 6, 8
assert.deepEqual(f.still_out, ["hemostat", "mayo_scissors", "scalpel"]);
assert.match(templateSummary(f).split("\n")[0], /^Still out: hemostat, mayo scissors, scalpel/);
ev("handed", { command_id: "e", item: "hemostat", request_to_hand_s: 7 });
assert.equal(caseFacts().median_request_to_hand_s, 6.5);  // even count: mean of the middle two
console.log("voice tests passed");
