// Offline checks for parsing and the case summary: `npm test`. No keys, no controller needed.
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import type { State } from "../src/controller.js";
import { localParse } from "../src/parse.js";
import { caseFacts, newCase, recordEvent, templateSummary } from "../src/summary.js";
import type { Setting } from "../src/settings.js";
import { HELP, countReply, handleText, localText, logRestock, runTexts, type InMessage, type InSpace, type Restock } from "../src/texts.js";

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

// Texts in (F3): fake message stream, fake controller state, local parse only (never Gemini or Photon).
const surgical: Setting = { id: "surgical", label: "Operating room", items: [
  { id: "scalpel", name: "scalpel", aliases: ["knife"], sharp: true },
  { id: "hemostat", name: "hemostat", aliases: ["kelly", "clamp"], sharp: false },
  { id: "mayo_scissors", name: "mayo scissors", aliases: ["mayo"], sharp: false },
] };
assert.deepEqual(localText("add a second hemostat to the surgical tray", surgical), { kind: "restock", item: "hemostat", qty: 1, setting: "surgical" });
assert.deepEqual(localText("Added 2 kellys", surgical), { kind: "restock", item: "hemostat", qty: 2, setting: null });
assert.equal(localText("what's out?", surgical).kind, "count");
assert.equal(localText("end of case", surgical).kind, "summary");
assert.equal(localText("Summary please", surgical).kind, "summary");
assert.equal(localText("hello", surgical).kind, "help");

const restocks: Restock[] = [];
const sent: string[] = [];
let summaries = 0;
const deps = {
  state: async (): Promise<State> => ({ step: "idle", out: ["hemostat", "scalpel"], out_camera: ["hemostat"], setting: "surgical", case_id: "surgical-1760731200", t: 1 }),
  setting: async () => surgical,
  parse: async (s: string, st: Setting) => localText(s, st),
  log: (r: Restock) => { restocks.push(r); },
  summary: async () => { summaries++; return "Count: everything is back on the tray."; },
};
const msg = (text: string, direction = "inbound"): [InSpace, InMessage] =>
  [{ send: async (t: string) => { sent.push(t); } }, { direction, content: { type: "text", text }, sender: { id: "+15555550123" } }];
async function* stream() {
  yield msg("add a second hemostat to the surgical tray");
  yield msg("what's out?");
  yield msg("our own reply", "outbound");  // skipped
  yield msg("end of case");
  yield msg("hello?");
}
await runTexts(stream(), deps);
assert.deepEqual(sent, [
  "Logged: +1 hemostat on the surgical tray.",
  "Out (2): hemostat, scalpel. The camera sees out: hemostat.",
  "Count: everything is back on the tray.",
  HELP,
]);
assert.equal(summaries, 1);
assert.equal(restocks.length, 1);
assert.deepEqual({ ...restocks[0], t: 0 }, { type: "restock", item: "hemostat", qty: 1, setting: "surgical", from: "+15555550123",
  heard: "add a second hemostat to the surgical tray", case_id: "surgical-1760731200", t: 0 });
assert.equal(await handleText("what's out", null, { ...deps, state: async () => { throw new Error("down"); } }), "I can't reach the arm controller.");
assert.equal(countReply({ step: "idle", out: [], setting: "surgical", t: 1 }), "Count: everything is back on the tray.");
assert.match(await handleText("add another one", null, deps), /^Which instrument\?/);
// The restock file writer, on a scratch file.
const tmp = path.join(mkdtempSync(path.join(tmpdir(), "scrub-")), "restocks.jsonl");
logRestock(restocks[0], tmp);
assert.equal(JSON.parse(readFileSync(tmp, "utf8").trim()).item, "hemostat");
console.log("voice tests passed");
