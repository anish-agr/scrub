// Offline checks for parsing, the case summary and the custom-LLM endpoint: `npm test`.
// No keys (VOICE_NO_KEYS=1 ignores .env), no real controller: the server runs against a fake one here.
import "./test-env.js";  // first: VOICE_NO_KEYS and a dead CONTROLLER_URL before config.ts loads
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import type { State } from "../src/controller.js";
import { spawn } from "node:child_process";
import http from "node:http";
import type { AddressInfo } from "node:net";
import { WebSocketServer } from "ws";
import { callerFrom, heardFrom } from "../src/chat.js";
import { isGotIt, isStop, isTrayCheck, localParse, parseAlias } from "../src/parse.js";
import { caseFacts, caseLink, clock, closeCaseWithLink, endCase, newCase, recordEvent, setCaller, templateSummary, textCaller, withTimeout } from "../src/summary.js";
import type { Setting } from "../src/settings.js";
import { CANT_CHECK, textTrayCheck, trayReadyText, voiceTrayCheck } from "../src/tray.js";
import { BUSY, JUDGE, notSetUp, settingAsked, switchSetting } from "../src/cases.js";
import { forgetJudge, judgeMode, noteJudge } from "../src/controller.js";
import { teach } from "../src/settings.js";
import { handleTurn, io, speak } from "../src/turn.js";
import { HELP, countReply, handleText, localText, logRestock, runTexts, type InMessage, type InSpace, type Restock } from "../src/texts.js";

const bench: Setting = { id: "bench", label: "Robotics bench", items: [
  { id: "needle_nose_pliers", name: "needle-nose pliers", aliases: ["pliers"], sharp: false },
  { id: "wire_cutters", name: "wire cutters", aliases: ["snips"], sharp: false },
] };
assert.deepEqual(localParse("hand me the needle-nose pliers", bench), { action: "handover", item: "needle_nose_pliers" });
assert.deepEqual(localParse("needle nose pliers please", bench), { action: "handover", item: "needle_nose_pliers" });
assert.deepEqual(localParse("snips", bench), { action: "handover", item: "wire_cutters" });
// Bug: an empty alias (a taught word that was all punctuation) matched any " s " through the plural test.
const blank: Setting = { id: "bench", label: "Robotics bench", items: [{ id: "hex_key", name: "hex key", aliases: [""], sharp: false }] };
assert.deepEqual(localParse("let's go", blank), { action: "unknown", item: null });
// M4: common phrasings the local match missed when Gemini is off or slow.
for (const g of ["thanks got it", "thanks, got it", "okay got it", "ok, I've got it", "thank you", "got it.", "release"]) assert.ok(isGotIt(g), g);
for (const g of ["got it hemostat", "thanks for the scalpel", "give me the thing"]) assert.ok(!isGotIt(g), g);
const scissors: Setting = { id: "surgical", label: "Operating room", items: [{ id: "mayo_scissors", name: "mayo scissors", aliases: [], sharp: false }] };
assert.deepEqual(localParse("take back the mayo scissors", scissors), { action: "return", item: null });
assert.deepEqual(localParse("take it back", scissors), { action: "return", item: null });
assert.deepEqual(localParse("take the mayo scissors", scissors), { action: "handover", item: "mayo_scissors" });

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
// Errors from the arm's robot model (401/409/503 with a say line) are not failed requests.
ev("error", { command_id: "h", item: "hemostat", code: 409, say: "The arm's model is busy.", error: "409" });
ev("error", { command_id: null, code: 503, say: "The arm's model is offline." });
ev("error", { command_id: "e", code: 401, say: "The arm's model key was refused." });
assert.equal(caseFacts().failed_requests, 1);
assert.equal(caseFacts().stops, 1);

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

// X6 clinic words: local pattern, spoken or texted.
const mayo = { item: "mayo_scissors" };
assert.deepEqual(parseAlias("call the hemostat a clamp", surgical), { item: "hemostat", alias: "clamp" });
assert.deepEqual(parseAlias("Call the hemostat a snap.", surgical), { item: "hemostat", alias: "snap" });
assert.deepEqual(parseAlias("the crile means the hemostat", surgical), { item: "hemostat", alias: "crile" });
assert.deepEqual(parseAlias("When I say crile, I mean the hemostat", surgical), { item: "hemostat", alias: "crile" });
assert.deepEqual(parseAlias("crile means kelly", surgical), { item: "hemostat", alias: "crile" });
assert.deepEqual(parseAlias("let's call the mayo scissors shears", surgical), { ...mayo, alias: "shears" });
assert.deepEqual(parseAlias("call the mayo scissors the big scissors", surgical), { ...mayo, alias: "big scissors" });
for (const no of ["grab me the kelly", "the kelly is ready", "next up is the hemostat", "my next one is the scalpel", "the crile is the hemostat", "what is the hemostat", "that is the hemostat", "call it", "call the bovie a pen", "stop"])
  assert.equal(parseAlias(no, surgical), null, no);
assert.deepEqual(localText("call the hemostat a clamp", surgical), { kind: "alias", item: "hemostat", qty: 1, setting: null, alias: "clamp" });
const taught: string[] = [];
const teachDeps = {
  state: async (): Promise<State> => ({ step: "idle", out: [], setting: "surgical", t: 1 }),
  setting: async () => surgical, parse: async (s: string, st: Setting) => localText(s, st),
  teach: async (item: string, alias: string) => { taught.push(`${alias}=${item}`); return { ok: true, say: `Got it: ${alias} means the ${item}.` }; },
};
assert.equal(await handleText("when I say crile I mean the hemostat", null, teachDeps), "Got it: crile means the hemostat.");
assert.deepEqual(taught, ["crile=hemostat"]);
assert.equal(await handleText("call the hemostat a crile", null, { ...teachDeps, teach: async () => { throw new Error("down"); } }), "I can't reach the arm controller.");
assert.match(await handleText("x", null, { ...teachDeps, parse: async () => ({ kind: "alias" as const, item: null, qty: 1, setting: null }) }), /^Say it like: call the scalpel a clamp/);

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
await logRestock(restocks[0], tmp, async () => { throw new Error("controller down"); });  // falls back to the file
assert.equal(JSON.parse(readFileSync(tmp, "utf8").trim()).item, "hemostat");
await logRestock(restocks[0], tmp, async () => ({ ok: true }));  // the ledger took it: nothing more in the file
assert.equal(readFileSync(tmp, "utf8").trim().split("\n").length, 1);

// Switching trays by text (X5): local match, fake POST /setting (ok, 409 busy, 404 unknown, down).
assert.deepEqual(localText("start a bench case", surgical), { kind: "setting", item: null, qty: 1, setting: "bench" });
assert.equal(localText("Switch to the bench tray", surgical).setting, "bench");
assert.equal(settingAsked("start a robotics case"), "bench");
assert.equal(settingAsked("switch to the operating room tray"), "surgical");
assert.equal(settingAsked("start a dental case"), "dental");  // recognised, only to say it isn't set up
assert.ok(!HELP.includes("dental") && HELP.includes("bench"));
assert.equal(localText("surgical case", surgical).kind, "setting");
assert.equal(localText("add a second hemostat to the surgical tray", surgical).kind, "restock");  // not a switch
assert.equal(settingAsked("grab me the kelly"), null);
assert.equal(settingAsked("the dental mirror"), null);
// Bug: any switch word anywhere made a tray switch, and a switch clears the count. These stay handovers.
for (const no of ["go grab the kelly off the surgical tray", "can you go get the scissors from the surgical tray", "move the pliers back to the bench"])
  assert.equal(settingAsked(no), null, no);
for (const [yes, id] of [["go to the bench tray", "bench"], ["switch trays to bench", "bench"], ["let's switch over to the surgical tray", "surgical"], ["start a new surgical case", "surgical"]])
  assert.equal(settingAsked(yes), id, yes);
// A restock naming the hidden tray is not logged and the reply doesn't name it.
assert.equal(await handleText("x", null, { ...deps, parse: async () => ({ kind: "restock" as const, item: "hemostat", qty: 1, setting: "dental" }) }), notSetUp("dental"));
const benchFile = { id: "bench", label: "Robotics bench", items: [{ id: "needle_nose_pliers", name: "needle-nose pliers" },
  { id: "wire_cutters", name: "wire cutters" }, { id: "hex_key", name: "hex key" }] };
const BENCH_LINE = "Bench case started: needle-nose pliers, wire cutters, hex key.";
const posted: string[] = [];
const fakePost = (status: number) => async (id: string) => { posted.push(id); return { status, setting: status === 200 ? benchFile : null }; };
assert.equal(await switchSetting("bench", fakePost(200)), BENCH_LINE);
// A switch clears the controller's count: anything still out is named so it isn't forgotten.
assert.equal(await switchSetting("bench", fakePost(200), async () => ({ out: ["mayo_scissors"] })),
  `${BENCH_LINE} Still out from the last tray: mayo scissors.`);
assert.equal(await switchSetting("bench", fakePost(409)), BUSY);
assert.equal(await switchSetting("bench", fakePost(404)), "I don't have a bench tray.");
assert.equal(await switchSetting("bench", fakePost(403)), JUDGE);  // the controller refused it in judge mode
assert.equal(await switchSetting("bench", async () => { throw new Error("down"); }), "I can't reach the arm controller.");
assert.equal(await switchSetting("dental", fakePost(200)), notSetUp("dental"));  // never posted
assert.ok(!/dental/i.test(notSetUp("dental")) && /surgical and bench/.test(notSetUp("dental")));  // never names the hidden tray
assert.deepEqual(posted, ["bench", "bench", "bench", "bench", "bench"]);
const switched: string[] = [];
const switchDeps = { ...deps, switchTo: async (id: string) => { switched.push(id); return switchSetting(id, fakePost(200)); } };
summaries = 0;
assert.equal(await handleText("start a bench case", "+15555550123", switchDeps), BENCH_LINE);
assert.equal(await handleText("start a dental case", "+15555550123", switchDeps), notSetUp("dental"));
assert.deepEqual(switched, ["bench", "dental"]);
assert.equal(posted.length, 6);  // dental never reached POST /setting
assert.equal(summaries, 0);  // the previous case's summary is not sent on a switch
assert.equal(await handleText("which tray", null, { ...deps, parse: async () => ({ kind: "setting" as const, item: null, qty: 1, setting: null }) }),
  "Which tray? surgical, bench.");

// Judge mode by text: state.judge true -> no POST /setting, /alias or /restock; count still works.
const judgeState = async (): Promise<State> => ({ step: "idle", out: ["hemostat"], setting: "surgical", judge: true, t: 1 });
const judged: string[] = [];
const judgeDeps = { ...deps, state: judgeState, switchTo: async (id: string) => { judged.push(`setting ${id}`); return "x"; },
  teach: async (i: string, a: string) => { judged.push(`alias ${a}`); return { ok: true, say: "x" }; },
  log: (r: Restock) => { judged.push(`restock ${r.item}`); } };
assert.equal(await handleText("switch to the bench tray", null, judgeDeps), JUDGE);
assert.equal(await handleText("call the hemostat a snap", null, judgeDeps), JUDGE);
assert.equal(await handleText("added 2 kellys", null, judgeDeps), JUDGE);
assert.equal(await handleText("what's out?", null, judgeDeps), "Out (1): hemostat.");
assert.deepEqual(judged, []);
assert.equal(JUDGE, "In judge mode I can hand you an instrument, read the count, or stop.");
// The judge flag is cached for a short while (a fake clock and a fake GET /state).
let stateGets = 0, now = 1000;
const getJ = (on: boolean) => async (): Promise<State> => { stateGets++; return { step: "idle", out: [], setting: "surgical", judge: on, t: 1 }; };
forgetJudge();
assert.equal(await judgeMode(getJ(true), 3000, () => now), true);
now += 2000;
assert.equal(await judgeMode(getJ(false), 3000, () => now), true);  // cached
assert.equal(stateGets, 1);
now += 1500;
assert.equal(await judgeMode(getJ(false), 3000, () => now), false);  // expired: asked again
assert.equal(stateGets, 2);
forgetJudge();
assert.equal(await judgeMode(async () => { throw new Error("down"); }, 3000, () => now), false);  // controller down: not judge
noteJudge(true, () => now);  // an event said judge: true, no GET /state needed
assert.equal(await judgeMode(getJ(false), 3000, () => now), true);
assert.equal(stateGets, 2);
forgetJudge();
// POST /alias refused with a 403 (judge mode turned on since the cache): the judge line, not "can't reach".
assert.equal((await teach("hemostat", "snap", async () => { throw new Error("POST /alias -> 403"); })).say, JUDGE);
await assert.rejects(teach("hemostat", "snap", async () => { throw new Error("POST /alias -> 500"); }));
assert.equal(await handleText("switch to the bench tray", null, { ...deps, switchTo: (id: string) => switchSetting(id, fakePost(409)) }), BUSY);

// The stop path never waits on Gemini, the setting or judge mode (in-process, every call faked; never the real controller).
const never = () => new Promise<never>(() => {});
const calls: string[] = [];
Object.assign(io, {
  parse: () => { calls.push("parse"); return never(); }, currentSetting: () => { calls.push("setting"); return never(); },
  judgeMode: () => { calls.push("judge"); return never(); },
  postStop: async () => { calls.push("stop"); return { accepted: true }; },
  postCommand: async () => { calls.push("command"); return { accepted: true, reason: null, say: null }; },
});
let t0 = Date.now();
await handleTurn("stop", () => {});
assert.deepEqual(calls, ["stop"]);
assert.ok(Date.now() - t0 < 2500);
// Gemini hearing a stop the local words missed goes to POST /stop, not the /command queue.
calls.length = 0;
Object.assign(io, { currentSetting: async () => surgical, parse: async () => ({ action: "stop" as const, item: null, via: "gemini" as const }) });
await handleTurn("hang on a second", () => {});
assert.deepEqual(calls, ["stop"]);

// H1: lines said with no turn open wait for the next turn, but only the last 2 and only if under 10 s old.
const realNow = Date.now;
Date.now = () => realNow() - 11_000;
speak("Reset. Ready.");  // 11 s old by the next turn: dropped
Date.now = realNow;
for (const l of ["Hemostat coming.", "Hemostat in your hand.", "Scalpel down."]) speak(l);
const heardBack: string[] = [];
await handleTurn("stop", (l) => heardBack.push(l));
assert.deepEqual(heardBack, ["Hemostat in your hand.", "Scalpel down."]);
heardBack.length = 0;
await handleTurn("stop", (l) => heardBack.push(l));
assert.deepEqual(heardBack, []);  // flushed once, not again

// Call-to-text memory (F4): events grouped by case_id, the text names the case, goes to the caller. Fake sender, no Gemini.
const start = Math.floor(Date.now() / 1000) - 600;
ev("released", { command_id: "z", item: "scalpel", case_id: `surgical-${start - 900}`, setting: "surgical" });  // an older case
ev("picked", { command_id: "y", item: "hemostat", case_id: `surgical-${start}`, setting: "surgical" });
ev("handed", { command_id: "y", item: "hemostat", request_to_hand_s: 4, case_id: `surgical-${start}`, setting: "surgical" });
ev("released", { command_id: "y", item: "hemostat", case_id: `surgical-${start}`, setting: "surgical", out: ["hemostat"] });
const g = caseFacts();
assert.equal(g.case_id, `surgical-${start}`);
assert.equal(g.setting, "surgical");
assert.deepEqual(g.passed, { hemostat: 1 });  // the older case's scalpel is not in this one
assert.deepEqual(g.used, ["hemostat"]);
assert.equal(g.started, clock(start));
assert.match(g.started, /^\d{1,2}:\d{2} [AP]M$/);
assert.equal(g.minutes, 10);
const lines = templateSummary(g).split("\n");
assert.equal(lines[0], "Still out: hemostat. Check the count.");  // count first
assert.equal(lines[1], `Scrub case: surgical, started ${clock(start)} (10 min)`);
assert.equal(lines[2], "Used: hemostat");
assert.match(templateSummary(g), /Median request to hand: 4\.0 s/);
setCaller("+15555550123");
const texted: [string, string][] = [];
const r = await endCase(async (to, text) => { texted.push([to, text]); return true; }, async () => templateSummary(caseFacts()), "");
assert.equal(r.sent, true);
assert.equal(texted.length, 1);  // no SCRUB_PUBLIC_URL: no case link text
assert.equal(texted[0][0], "+15555550123");
assert.match(texted[0][1], /^Still out: hemostat\. Check the count\.\nScrub case: surgical, started /);
assert.deepEqual(caseFacts().passed, {});  // a new case after the text
// Bug: a second summary before any new event said "everything is back on the tray" with the hemostat still out.
assert.deepEqual(caseFacts().still_out, ["hemostat"]);
// Case link (X5): a second short text only when SCRUB_PUBLIC_URL is set and the case has a case_id.
const linked: [string, string][] = [];
const r2 = await endCase(async (to, text) => { linked.push([to, text]); return true; }, async () => "Count: everything is back on the tray.", "https://scrub.example/");
assert.equal(linked.length, 2);
assert.deepEqual(linked[1], ["+15555550123", `Case replay: https://scrub.example/case.html?id=surgical-${start}`]);
assert.equal(r2.link, linked[1][1]);
assert.equal(caseLink(null, "https://scrub.example"), null);
assert.equal(caseLink(`surgical-${start}`, ""), null);
const notSent: string[] = [];
await endCase(async (_to, text) => { notSent.push(text); throw new Error("photon down"); }, async () => "x", "https://scrub.example");
assert.deepEqual(notSent, ["x"]);  // the summary failed: no link text after it
// A Photon call that never answers fails instead of hanging the summary.
await assert.rejects(withTimeout(new Promise(() => {}), 50, "Photon send"), /timed out/);
const hung = await endCase(async (_to, text) => withTimeout(new Promise<boolean>(() => {}), 50, `send ${text}`), async () => "y", "");
assert.equal(hung.sent, false);
assert.match(hung.error ?? "", /timed out/);
// A "summary" text gets the link on its own line after the summary.
assert.equal(await closeCaseWithLink(async () => "Count: everything is back on the tray.", "https://scrub.example"),
  `Count: everything is back on the tray.\n\nCase replay: https://scrub.example/case.html?id=surgical-${start}`);
assert.equal(await closeCaseWithLink(async () => "Count: everything is back on the tray.", ""), "Count: everything is back on the tray.");
// No case_id on events: the current behaviour, one case until "end of case".
newCase();
ev("released", { command_id: "x", item: "hemostat" });
assert.equal(caseFacts().case_id, `surgical-${start}`);  // still the controller's last case
assert.deepEqual(caseFacts().passed, { hemostat: 1 });
// Tray check (X3): local phrase match, fake controller replies, fake sender (never Photon).
for (const s of ["check the tray", "Can you check the tray?", "is the tray ready", "Tray check", "tray ready?", "is my tray set up"])
  assert.ok(isTrayCheck(s) && !isStop(s), s);
for (const s of ["grab me the kelly", "what's out", "Tray ready: Operating room, all 3 instruments in place.", "end of case"])
  assert.ok(!isTrayCheck(s), s);
const READY = { ok: true, say: "Tray's ready: scalpel, hemostat, mayo scissors.", setting: "surgical", label: "Operating room",
  items: ["scalpel", "hemostat", "mayo scissors"], missing: [], wrong_slot: [], extra: [], stale: false };
const MISSING = { ...READY, ok: false, say: "Missing the scalpel.", missing: ["scalpel"] };
assert.equal(trayReadyText(READY), "Tray ready: Operating room, all 3 instruments in place.");
const notes: string[] = [];
const notify = async (t: string) => { notes.push(t); };
assert.equal(await voiceTrayCheck(async () => READY, notify), READY.say);
await new Promise((r) => setTimeout(r, 0));
assert.deepEqual(notes, ["Tray ready: Operating room, all 3 instruments in place."]);  // passing by voice: also a text
assert.equal(await voiceTrayCheck(async () => MISSING, notify), "Missing the scalpel.");
assert.equal(await voiceTrayCheck(async () => { throw new Error("GET /tray_check -> 404"); }, notify), CANT_CHECK);
assert.equal(notes.length, 1);  // no text unless it passed
assert.equal(await textTrayCheck(async () => READY), "Tray ready: Operating room, all 3 instruments in place.");
assert.equal(await textTrayCheck(async () => MISSING), "Missing the scalpel.");
assert.equal(await textTrayCheck(async () => { throw new Error("down"); }), CANT_CHECK);
assert.equal(await handleText("is the tray ready?", null, { ...deps, parse: async () => { throw new Error("no parse for tray checks"); },
  trayCheck: async () => "Tray ready: Operating room, all 3 instruments in place." }), "Tray ready: Operating room, all 3 instruments in place.");
const trayTexts: [string, string][] = [];
assert.equal(await textCaller("Tray ready: x", async (to, t) => { trayTexts.push([to, t]); return true; }), true);
assert.deepEqual(trayTexts, [["+15555550123", "Tray ready: x"]]);  // the caller's thread, same sender as the summary

// What ElevenLabs sends: caller id from the system prompt, act only on a trailing user message.
const sys = (c: string) => ({ role: "system", content: c });
assert.equal(callerFrom([sys("You are Scrub.\nCaller: +1 (555) 555-0123")]), "+15555550123");
assert.equal(callerFrom([sys("Caller: {{system__caller_id}}")]), "");
assert.equal(callerFrom([sys("Caller: ")]), "");
assert.equal(heardFrom([sys("x"), { role: "user", content: [{ type: "text", text: "knife please" }] }]), "knife please");
assert.equal(heardFrom([sys("x"), { role: "user", content: "kelly" }, { role: "assistant", content: "Hemostat coming." }]), "");

// The real server against a fake controller: SSE chunk shape, stop skips Gemini and /command, caller id.
const hits: string[] = [];
const clinic: string[] = [];  // aliases taught through the fake controller's POST /alias
const ctl = http.createServer((req, res) => {
  hits.push(`${req.method} ${req.url}`);
  let raw = "";
  req.on("data", (d) => (raw += d));
  req.on("end", () => {
    res.setHeader("content-type", "application/json");
    if (req.method === "POST" && req.url === "/setting") return res.end(JSON.stringify(benchFile));
    if (req.url === "/state") return res.end(JSON.stringify({ step: "idle", out: [], setting: "surgical", judge: judgeOn, t: 1 }));
    if (req.url === "/setting") return res.end(JSON.stringify({ id: "surgical", label: "Operating room",
      items: [{ id: "hemostat", name: "hemostat", aliases: ["kelly", ...clinic] }, { id: "scalpel", name: "scalpel", aliases: ["knife"], sharp: true }] }));
    if (req.url === "/tray_check") return res.end(JSON.stringify(trayAnswer));
    if (req.url === "/alias") {
      const a = JSON.parse(raw);
      if (a.alias === "knife") return res.end(JSON.stringify({ ok: false, say: "Knife already means the scalpel.", reason: "already scalpel" }));
      clinic.push(a.alias);
      return res.end(JSON.stringify({ ok: true, say: `Got it: ${a.alias} means the ${a.item}.`, reason: null }));
    }
    if (req.url === "/stop") { emit({ type: "stopped", say: "Stopped." }); return res.end('{"accepted":true}'); }
    if (req.url === "/command") {
      const c = JSON.parse(raw);
      const reply = () => res.end(JSON.stringify({ accepted: true, reason: null, say: null }));
      // Like the controller: count (and an early robot-model error) are emitted while it answers the POST.
      if (c.action === "count") { emit({ type: "count", command_id: c.id, say: "Out: hemostat." }); return setTimeout(reply, 50); }
      if (c.item === "scalpel") {
        emit({ type: "error", command_id: c.id, item: c.item, code: 409, say: "The arm's model is busy. Try again.", error: "409" });
        return setTimeout(reply, 50);
      }
      if (c.action === "got_it") {  // the released event carries the handover's command_id
        setTimeout(() => emit({ type: "released", command_id: "the-handover", item: "hemostat" }), 50);
        return reply();
      }
      if (preopenError) {  // a pre-open session error mid-handover: spoken, but the handover goes on
        setTimeout(() => emit({ type: "error", command_id: null, step: "idle", code: 503, say: "The robot model is down right now." }), 30);
        setTimeout(() => emit({ type: "handed", command_id: c.id, item: c.item, say: "Hemostat in your hand." }), 400);
        return reply();
      }
      if (errorLater) { setTimeout(() => emit({ type: "error", command_id: c.id, code: 503, say: "The arm's model is offline. Reset the arm." }), 100); return reply(); }
      if (c.action === "handover") setTimeout(() => {
        emit({ type: "command", command_id: c.id, item: c.item, say: "Hemostat coming." });
        emit({ type: "handed", command_id: c.id, item: c.item });
      }, 20);
      return res.end(JSON.stringify({ accepted: true, reason: null, say: null }));
    }
    res.end("{}");
  });
});
let trayAnswer: object = READY;
let judgeOn = false, errorLater = false, preopenError = false;
const wss = new WebSocketServer({ server: ctl });
const emit = (e: object) => wss.clients.forEach((c) => c.send(JSON.stringify({ t: Date.now() / 1000, ...e })));
// Test ports 8260-8268 and 3260-3268 (the live controller and voice server stay on 8000 and 3000). npm test points
// in-process code at 8269, where nothing listens, so a call a test forgot to fake never reaches the real arm.
const offset = Math.floor(Math.random() * 9);
await new Promise<void>((r) => ctl.listen(8260 + offset, r));
const ctlPort = (ctl.address() as AddressInfo).port;
const voicePort = 3260 + offset;
const out: string[] = [];
const child = spawn(process.execPath, ["--import", "tsx", "src/server.ts"], { cwd: path.resolve(import.meta.dirname, ".."),
  env: { ...process.env, VOICE_NO_KEYS: "1", CONTROLLER_URL: `http://localhost:${ctlPort}`, VOICE_PORT: String(voicePort), VOICE_HOLD_S: "2", VOICE_JUDGE_TTL_MS: "0" } });
child.stdout.on("data", (d) => out.push(String(d)));
child.stderr.on("data", (d) => out.push(String(d)));
const base = `http://localhost:${voicePort}`;
try {
  for (let i = 0; i < 100 && !out.join("").includes("[events] connected"); i++) await new Promise((r) => setTimeout(r, 100));
  assert.ok(out.join("").includes("[events] connected"), out.join(""));

  const turn = async (heard: string) => {
    const res = await fetch(`${base}/v1/chat/completions`, { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ model: "scrub", stream: true, temperature: 0.5, max_tokens: 5000, tools: [], elevenlabs_extra_body: {},
        messages: [sys("You are Scrub.\nCaller: +15555550123"), { role: "assistant", content: "Scrub here." }, { role: "user", content: heard }] }) });
    assert.match(res.headers.get("content-type") || "", /text\/event-stream/);
    const raw = await res.text();
    assert.ok(raw.endsWith("data: [DONE]\n\n"), raw);
    const chunks = raw.split("\n\n").filter((l) => l.startsWith("data: {")).map((l) => JSON.parse(l.slice(6)));
    for (const c of chunks) {
      assert.equal(c.object, "chat.completion.chunk");
      assert.equal(c.choices.length, 1);
      assert.equal(c.choices[0].index, 0);
    }
    assert.deepEqual(chunks[0].choices[0].delta, { role: "assistant", content: "" });
    assert.equal(chunks.at(-1).choices[0].finish_reason, "stop");
    return chunks.map((c) => c.choices[0].delta.content || "").join("");
  };

  assert.equal(await turn("grab me the kelly"), "Hemostat coming.");
  assert.ok(hits.includes("POST /command"));
  assert.ok(out.join("").includes("[case] caller +15555550123"));
  hits.length = 0;
  assert.equal(await turn("stop"), "Stopped.");
  assert.deepEqual(hits, ["POST /stop"]);  // no GET /setting, no Gemini, no /command
  assert.ok(!out.join("").includes("[gemini]"));
  hits.length = 0;
  assert.equal(await turn("start a bench case"), BENCH_LINE);
  assert.deepEqual(hits, ["GET /state", "GET /state", "POST /setting"]);  // judge mode, then what is out, then the switch: no Gemini, no /command
  hits.length = 0;
  assert.equal(await turn("start a dental case"), notSetUp("dental"));
  assert.equal(hits.length, 0, hits.join());  // dental is never posted

  // Bug: count (and stop) events arrive while the controller answers the POST, before the hold starts:
  // the reply used to stay open the full VOICE_HOLD_S (2 s here). Now it ends right after the line.
  let t1 = Date.now();
  assert.equal(await turn("what's out"), "Out: hemostat.");
  assert.ok(Date.now() - t1 < 1200, `count turn took ${Date.now() - t1} ms`);
  // Robot-model errors (code 401/409/503 with a say line) are spoken: during the POST, and in the hold window.
  t1 = Date.now();
  assert.equal(await turn("knife please"), "The arm's model is busy. Try again.");
  assert.ok(Date.now() - t1 < 1200, `error turn took ${Date.now() - t1} ms`);
  // Bug: "got it" held the reply open the full VOICE_HOLD_S (the release names the handover, not got_it).
  t1 = Date.now();
  assert.equal(await turn("got it"), "");
  assert.ok(Date.now() - t1 < 1200, `got it turn took ${Date.now() - t1} ms`);
  // Bug: asking again within 3 s got silence (the same line was muted as a repeat, though it's a new command).
  assert.equal(await turn("knife please"), "The arm's model is busy. Try again.");
  errorLater = true;
  assert.equal(await turn("grab me the kelly"), "The arm's model is offline. Reset the arm.");
  errorLater = false;
  preopenError = true;
  assert.equal(await turn("grab me the kelly"), "The robot model is down right now. Hemostat in your hand.");
  preopenError = false;

  hits.length = 0;
  assert.equal(await turn("check the tray"), READY.say);
  assert.deepEqual(hits, ["GET /tray_check"]);  // no /setting, no Gemini, no /command
  for (let i = 0; i < 20 && !out.join("").includes("[photon] not sent"); i++) await new Promise((r) => setTimeout(r, 50));
  assert.ok(out.join("").includes("[photon] not sent"), out.join(""));  // the "tray ready" text was tried (no keys: not sent)
  trayAnswer = MISSING;
  assert.equal(await turn("is the tray ready"), "Missing the scalpel.");

  // X6: teach a word on the call, before Gemini, and the next turn sees it (the 30 s setting cache is dropped).
  hits.length = 0;
  assert.equal(await turn("grab me the crile"), "");  // not a word yet: unknown (the fake controller says nothing)
  hits.length = 0;  // the tray switch above dropped the cache; this turn refilled it
  assert.equal(await turn("call the hemostat a knife"), "Knife already means the scalpel.");  // refused: cache kept
  assert.equal(await turn("call the hemostat a crile"), "Got it: crile means the hemostat.");
  assert.ok(hits.includes("POST /alias") && !hits.includes("GET /setting"), hits.join());
  hits.length = 0;
  const before = out.join("").length;
  assert.equal(await turn("grab me the crile"), "Hemostat coming.");
  assert.equal(hits[0], "GET /setting");
  assert.match(out.join("").slice(before), /\[command\] handover hemostat/);

  // Judge mode (GET /state judge: true): no POST /setting or /alias by voice; stop still goes straight to POST /stop.
  judgeOn = true;
  hits.length = 0;
  assert.equal(await turn("switch to the bench tray"), JUDGE);
  assert.deepEqual(hits, ["GET /state"]);
  hits.length = 0;
  assert.equal(await turn("call the hemostat a snap"), JUDGE);  // bug: the same line twice in 3 s was dropped
  assert.ok(!hits.includes("POST /alias"), hits.join());
  hits.length = 0;
  assert.equal(await turn("stop"), "Stopped.");
  assert.deepEqual(hits, ["POST /stop"]);  // no GET /state before a stop
  hits.length = 0;
  assert.equal(await turn("what's out"), "Out: hemostat.");  // count still goes to the controller
  assert.ok(hits.includes("POST /command"), hits.join());
  judgeOn = false;

  const health = await (await fetch(`${base}/health`)).json();
  assert.deepEqual(health, { ok: true, keys: { gemini: false, photon: false, llm_secret: false }, controller: true });
} finally {
  child.kill();
  wss.close();
  ctl.close();
}
console.log("voice tests passed");
