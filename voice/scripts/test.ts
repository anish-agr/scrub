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
import { isStop, isTrayCheck, localParse, parseAlias } from "../src/parse.js";
import { caseFacts, caseLink, clock, closeCaseWithLink, endCase, newCase, recordEvent, setCaller, templateSummary, textCaller } from "../src/summary.js";
import type { Setting } from "../src/settings.js";
import { CANT_CHECK, textTrayCheck, trayReadyText, voiceTrayCheck } from "../src/tray.js";
import { BUSY, settingAsked, switchSetting } from "../src/cases.js";
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
assert.deepEqual(localText("start a dental case", surgical), { kind: "setting", item: null, qty: 1, setting: "dental" });
assert.equal(localText("Switch to the bench tray", surgical).setting, "bench");
assert.equal(localText("surgical case", surgical).kind, "setting");
assert.equal(localText("add a second hemostat to the surgical tray", surgical).kind, "restock");  // not a switch
assert.equal(settingAsked("grab me the kelly"), null);
assert.equal(settingAsked("the dental mirror"), null);
const dentalFile = { id: "dental", label: "Dental office", items: [{ id: "mouth_mirror", name: "mouth mirror" },
  { id: "explorer", name: "explorer" }, { id: "cotton_pliers", name: "cotton pliers" }] };
const posted: string[] = [];
const fakePost = (status: number) => async (id: string) => { posted.push(id); return { status, setting: status === 200 ? dentalFile : null }; };
assert.equal(await switchSetting("dental", fakePost(200)), "Dental case started: mouth mirror, explorer, cotton pliers.");
assert.equal(await switchSetting("dental", fakePost(409)), BUSY);
assert.equal(await switchSetting("dental", fakePost(404)), "I don't have a dental tray.");
assert.equal(await switchSetting("dental", async () => { throw new Error("down"); }), "I can't reach the arm controller.");
assert.deepEqual(posted, ["dental", "dental", "dental"]);
const switched: string[] = [];
const switchDeps = { ...deps, switchTo: async (id: string) => { switched.push(id); return switchSetting(id, fakePost(200)); } };
summaries = 0;
assert.equal(await handleText("start a dental case", "+15555550123", switchDeps), "Dental case started: mouth mirror, explorer, cotton pliers.");
assert.deepEqual(switched, ["dental"]);
assert.equal(summaries, 0);  // the previous case's summary is not sent on a switch
assert.equal(await handleText("switch to the bench tray", null, { ...deps, switchTo: (id: string) => switchSetting(id, fakePost(409)) }), BUSY);

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
    if (req.method === "POST" && req.url === "/setting") return res.end(JSON.stringify(dentalFile));
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
  assert.equal(await turn("start a dental case"), "Dental case started: mouth mirror, explorer, cotton pliers.");
  assert.deepEqual(hits, ["POST /setting"]);  // a phrase match: no Gemini, no /command

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

  const health = await (await fetch(`${base}/health`)).json();
  assert.deepEqual(health, { ok: true, keys: { gemini: false, photon: false, llm_secret: false }, controller: true });
} finally {
  child.kill();
  wss.close();
  ctl.close();
}
console.log("voice tests passed");
