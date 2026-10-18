// Offline checks for parsing, the case summary and the custom-LLM endpoint: `npm test`.
// No keys (VOICE_NO_KEYS=1 ignores .env), no real controller: the server runs against a fake one here.
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
import { isStop, isTrayCheck, localParse } from "../src/parse.js";
import { caseFacts, clock, endCase, newCase, recordEvent, setCaller, templateSummary, textCaller } from "../src/summary.js";
import type { Setting } from "../src/settings.js";
import { CANT_CHECK, textTrayCheck, trayReadyText, voiceTrayCheck } from "../src/tray.js";
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
await logRestock(restocks[0], tmp, async () => { throw new Error("controller down"); });  // falls back to the file
assert.equal(JSON.parse(readFileSync(tmp, "utf8").trim()).item, "hemostat");
await logRestock(restocks[0], tmp, async () => ({ ok: true }));  // the ledger took it: nothing more in the file
assert.equal(readFileSync(tmp, "utf8").trim().split("\n").length, 1);

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
const r = await endCase(async (to, text) => { texted.push([to, text]); return true; }, async () => templateSummary(caseFacts()));
assert.equal(r.sent, true);
assert.equal(texted.length, 1);
assert.equal(texted[0][0], "+15555550123");
assert.match(texted[0][1], /^Still out: hemostat\. Check the count\.\nScrub case: surgical, started /);
assert.deepEqual(caseFacts().passed, {});  // a new case after the text
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
const ctl = http.createServer((req, res) => {
  hits.push(`${req.method} ${req.url}`);
  let raw = "";
  req.on("data", (d) => (raw += d));
  req.on("end", () => {
    res.setHeader("content-type", "application/json");
    if (req.url === "/setting") return res.end(JSON.stringify({ id: "surgical", label: "Operating room",
      items: [{ id: "hemostat", name: "hemostat", aliases: ["kelly"] }, { id: "scalpel", name: "scalpel", aliases: ["knife"], sharp: true }] }));
    if (req.url === "/tray_check") return res.end(JSON.stringify(trayAnswer));
    if (req.url === "/stop") { emit({ type: "stopped", say: "Stopped." }); return res.end('{"accepted":true}'); }
    if (req.url === "/command") {
      const c = JSON.parse(raw);
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
const wss = new WebSocketServer({ server: ctl });
const emit = (e: object) => wss.clients.forEach((c) => c.send(JSON.stringify({ t: Date.now() / 1000, ...e })));
await new Promise<void>((r) => ctl.listen(0, r));
const ctlPort = (ctl.address() as AddressInfo).port;
const voicePort = 3900 + Math.floor(Math.random() * 90);
const out: string[] = [];
const child = spawn(process.execPath, ["--import", "tsx", "src/server.ts"], { cwd: path.resolve(import.meta.dirname, ".."),
  env: { ...process.env, VOICE_NO_KEYS: "1", CONTROLLER_URL: `http://localhost:${ctlPort}`, VOICE_PORT: String(voicePort), VOICE_HOLD_S: "2" } });
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
  assert.equal(await turn("check the tray"), READY.say);
  assert.deepEqual(hits, ["GET /tray_check"]);  // no /setting, no Gemini, no /command
  for (let i = 0; i < 20 && !out.join("").includes("[photon] not sent"); i++) await new Promise((r) => setTimeout(r, 50));
  assert.ok(out.join("").includes("[photon] not sent"), out.join(""));  // the "tray ready" text was tried (no keys: not sent)
  trayAnswer = MISSING;
  assert.equal(await turn("is the tray ready"), "Missing the scalpel.");

  const health = await (await fetch(`${base}/health`)).json();
  assert.deepEqual(health, { ok: true, keys: { gemini: false, photon: false, llm_secret: false }, controller: true });
} finally {
  child.kill();
  wss.close();
  ctl.close();
}
console.log("voice tests passed");
