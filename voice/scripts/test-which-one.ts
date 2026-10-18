// All fake inputs and blank keys. Also runnable on its own: npx tsx scripts/test-which-one.ts.
import "./test-env.js";
import assert from "node:assert/strict";
import http from "node:http";
import { spawn } from "node:child_process";
import path from "node:path";
import { readFileSync } from "node:fs";
import { WebSocketServer } from "ws";
import { Dialogue, dialogue, QUESTION_MS } from "../src/dialogue.js";
import { localParse, parse, validateGemini } from "../src/parse.js";
import { handleText, type TextDeps } from "../src/texts.js";
import { handleTurn, io, receiveEvent } from "../src/turn.js";
import type { Candidate, ClarifyLog, Command, ScrubEvent, State } from "../src/controller.js";
import type { Setting } from "../src/settings.js";

const setting: Setting = { id: "surgical", label: "Surgical", items: [
  { id: "mayo_straight", name: "straight Mayo scissors", group: "scissors", variant: "straight", aliases: ["scissors", "mayo"], sharp: false },
  { id: "mayo_curved", name: "curved Mayo scissors", group: "scissors", variant: "curved", aliases: ["scissors", "mayo"], sharp: false },
  { id: "hemostat", name: "hemostat", aliases: ["kelly"], sharp: false },
] };
const parsed = localParse("scissors", setting);
assert.equal(parsed.item, null);
assert.deepEqual(parsed.clarify?.candidates.map((c) => c.item), ["mayo_straight", "mayo_curved"]);
assert.equal(parsed.clarify!.say, "Which scissors: straight or curved?");
const actualBench: Setting = JSON.parse(readFileSync(new URL("../../settings/bench.json", import.meta.url), "utf8"));
assert.equal(localParse("screwdriver", actualBench).clarify?.say, "Which screwdriver: flathead or Phillips?");
assert.equal((await parse("screwdriver", actualBench)).clarify?.say, "Which screwdriver: flathead or Phillips?");
assert.equal(validateGemini({ action: "clarify", item: "none", candidates: ["flathead_screwdriver", "phillips_screwdriver"] }, actualBench).clarify?.say,
  "Which screwdriver: flathead or Phillips?");
assert.equal((await parse("scissors", setting)).via, "local");
assert.equal(localParse("curved scissors", setting).item, "mayo_curved");
assert.equal(localParse("straight Mayo scissors please", setting).item, "mayo_straight");
assert.equal(localParse("the left kelly", setting).instance?.side, "left");
assert.equal(localParse("stop, curved scissors", setting).action, "stop");
assert.equal(localParse("scissors or hemostat", setting).clarify?.candidates.length, 3);
assert.equal(validateGemini({ action: "handover", item: "invented" }, setting).action, "unknown");
assert.equal(validateGemini({ action: "handover", candidates: ["mayo_straight", "mayo_curved", "invented"] }, setting).clarify?.candidates.length, 2);
assert.equal(validateGemini({ action: "handover", item: "hemostat", confidence: 0.6 }, setting).confirm, true);

let now = 100;
const telemetry: ClarifyLog[] = [];
const d = new Dialogue(() => now, async (row) => { telemetry.push(row); });
const question = parsed.clarify!;
for (const [answer, item] of [["curved", "mayo_curved"], ["the curved one", "mayo_curved"], ["curved Mayo scissors", "mayo_curved"], ["straight", "mayo_straight"],
  ["first", "mayo_straight"], ["second", "mayo_curved"], ["either", "mayo_straight"], ["any", "mayo_straight"], ["you pick", "mayo_straight"]]) {
  d.ask("call:a", question, setting);
  now += 50;
  const answerResult = d.answer("call:a", answer, setting);
  assert.ok(answerResult && "parsed" in answerResult, answer);
  assert.equal(answerResult.parsed.item, item, answer);
}
for (const cancel of ["cancel", "never mind"]) {
  d.ask("call:a", question, setting);
  assert.match((d.answer("call:a", cancel, setting) as { say: string }).say, /Cancelled/);
  assert.ok(!d.pending("call:a"));
}
d.ask("call:a", question, setting);
assert.equal(d.answer("call:b", "curved", setting), null);
assert.equal(d.answer("text:a", "curved", setting), null);
assert.ok(d.pending("call:a"));
assert.match((d.answer("call:a", "banana", setting) as { say: string }).say, /Which scissors/);
now += QUESTION_MS;
assert.match((d.answer("call:a", "curved", setting) as { say: string }).say, /timed out/);
assert.ok(!d.pending("call:a"));
assert.ok(telemetry.some((r) => r.type === "clarify_answer" && r.answer_ms === 50));
assert.ok(telemetry.every((r) => !!r.question_id && r.context === "call:a"));

const visible: Candidate[] = [{ item: "hemostat", label: "left hemostat", side: "left", slot: 0 }, { item: "hemostat", label: "right hemostat", instance: { side: "right", slot: 1 } }];
for (const [word, expected] of [["left", { side: "left", slot: 0 }], ["right", { side: "right", slot: 1 }], ["closest", { side: "closest" }]] as const) {
  d.ask("sight", { say: "Left or right?", item: "hemostat", candidates: visible }, setting);
  const r = d.answer("sight", word, setting);
  assert.ok(r && "parsed" in r);
  assert.deepEqual(r.parsed.instance, expected);
}
d.askParsed("confirm", { action: "handover", item: "hemostat", confirm: true }, setting);
assert.ok(d.pending("confirm"));
assert.match((d.answer("confirm", "no", setting) as { say: string }).say, /Cancelled/);
d.askParsed("confirm", { action: "handover", item: "hemostat", confirm: true }, setting);
assert.equal((d.answer("confirm", "yes", setting) as { parsed: { item: string } }).parsed.item, "hemostat");
for (const confusing of ["straight or curved", "first or second", "left or right"]) {
  d.ask("confusing", question, setting);
  assert.ok("say" in d.answer("confusing", confusing, setting)!, confusing);
}

// Follow-ups use handed events from this person only, not the controller's global last-out list.
const handover: Command = { id: "handed-a", action: "handover", item: "mayo_curved", source: "voice", heard: "curved", t: 1, instance: { variant: "curved", slot: 3 } };
d.track("person:a", handover, setting);
d.event({ type: "handed", t: 1, command_id: handover.id, item: handover.item });
for (const phrase of ["another", "another one", "same again", "one more", "give me another one please"]) {
  const r = d.answer("person:a", phrase, setting);
  assert.ok(r && "parsed" in r, phrase);
  assert.equal(r.parsed.item, "mayo_curved");
  assert.deepEqual(r.parsed.instance, { variant: "curved" }); // another isn't the already-out physical slot
}
for (const phrase of ["put it back", "take it back", "return that"]) {
  const r = d.answer("person:a", phrase, setting);
  assert.ok(r && "parsed" in r, phrase);
  assert.equal(r.parsed.action, "return");
  assert.equal(r.parsed.item, "mayo_curved");
  assert.deepEqual(r.parsed.instance, { variant: "curved", slot: 3 });
}
assert.ok("say" in d.answer("person:b", "take it back", setting)!);
assert.ok("say" in d.answer("person:b", "same again", setting)!);
assert.ok("say" in d.scope("person:b", { action: "return", item: null }, setting)!);
assert.equal((d.scope("person:a", { action: "return", item: null }, setting) as any).parsed.item, "mayo_curved");
d.ask("other", question, setting);
d.answer("other", "curved", setting);
assert.equal((d.answer("other", "the other one", setting) as any).parsed.item, "mayo_straight");
d.event({ type: "returned", t: 2, command_id: handover.id, item: handover.item });
assert.ok("say" in d.answer("person:a", "take it back", setting)!);
assert.equal(localParse("put the curved scissors back", setting).item, "mayo_curved");
assert.equal(localParse("take back scissors", setting).clarify?.candidates.length, 2);

const delayed: Command = { ...handover, id: "delayed", item: "hemostat" };
const sightEvent: ScrubEvent = { type: "clarify", t: 3, command_id: delayed.id, item: "hemostat", say: "Left or right?", candidates: visible, question_id: "delayed-question" };
d.track("late", delayed, setting);
d.event(sightEvent);
assert.ok(d.pending("late"));
d.answer("late", "cancel", setting);
d.event(sightEvent);
assert.ok(!d.pending("late"), "a duplicate event cannot revive a cancelled question");
d.track("late", { ...delayed, id: "newer" }, setting);
d.event(sightEvent);
assert.ok(!d.pending("late"), "an older command cannot replace a newer question");
d.ask("late", question, setting);
d.event(sightEvent);
assert.equal((d.answer("late", "curved", setting) as any).parsed.item, "mayo_curved");

// Actual turn machinery and text handler, with isolated fake I/O.
dialogue.clear();
const saved = { ...io };
const posted: Command[] = [];
const state = async (): Promise<State> => ({ step: "idle", out: [], setting: setting.id, t: 1 });
const command = async (c: Command) => { posted.push(c); return { accepted: false, reason: "test", say: "Test request received." }; };
const td: Partial<TextDeps> = { state, setting: async () => setting, command, stop: async () => ({ accepted: true }) };
Object.assign(io, { currentSetting: async () => setting, parse, postCommand: command, postStop: async () => ({ accepted: true }) });
const turn = async (text: string, context = "call:test") => {
  const said: string[] = [];
  await handleTurn(text, (l) => said.push(l), undefined, Date.now(), context);
  return said.join(" ");
};
try {
  assert.match(await turn("scissors"), /Which scissors/);
  assert.equal(posted.length, 0, "no controller command before clarification");
  assert.match(await handleText("scissors", "+a", td), /Which scissors/);
  assert.equal(posted.length, 0);
  assert.equal(await handleText("curved", "+a", td), "Test request received.");
  assert.equal(posted.at(-1)?.item, "mayo_curved");
  assert.ok(dialogue.pending("call:test"), "text answer cannot consume call question");
  assert.equal(await turn("straight"), "Test request received.");
  assert.equal(posted.at(-1)?.item, "mayo_straight");
  assert.equal(posted.at(-1)?.instance?.variant, "straight");
  await turn("scissors");
  const n = posted.length;
  await turn("stop, curved");
  assert.equal(posted.length, n);
  assert.ok(!dialogue.pending("call:test"));

  // A by-sight event received while another call is open belongs only to its command's context.
  let originCommand: Command | undefined;
  io.postCommand = async (c) => { originCommand = c; return { accepted: false, reason: "pending", say: null }; };
  await turn("kelly", "call:origin");
  receiveEvent({ type: "clarify", t: Date.now() / 1000, command_id: originCommand!.id, item: "hemostat", say: "Left or right?", candidates: visible });
  assert.ok(dialogue.pending("call:origin"));
  assert.ok(!dialogue.pending("call:other"));
  io.postCommand = command;
  assert.match(await turn("right", "call:origin"), /Test request received/);
  assert.deepEqual(posted.at(-1)?.instance, { side: "right", slot: 1 });

  // Same sender in separate Photon spaces is still independent.
  await handleText("scissors", "+same", td, "space-a");
  await handleText("scissors", "+same", td, "space-b");
  await handleText("curved", "+same", td, "space-a");
  assert.ok(dialogue.pending("text:space-b"));
  assert.ok(!dialogue.pending("text:space-a"));

  // Controller events establish conversational memory, never merely requesting an instrument.
  const handed = posted.at(-1)!;
  receiveEvent({ type: "released", t: Date.now() / 1000, command_id: handed.id, item: handed.item });
  await handleText("same again", "+same", td, "space-a");
  assert.equal(posted.at(-1)?.item, "mayo_curved");
  await handleText("take it back", "+same", td, "space-a");
  assert.equal(posted.at(-1)?.action, "return");
  assert.equal(posted.at(-1)?.item, "mayo_curved");
  const beforeUnknown = posted.length;
  assert.match(await handleText("take it back", "+same", td, "space-c"), /haven't handed you/);
  assert.equal(posted.length, beforeUnknown);
  await turn("scissors", "call:other-test");
  await turn("curved", "call:other-test");
  await turn("the other one", "call:other-test");
  assert.equal(posted.at(-1)?.item, "mayo_straight");

  // Model uncertainty prompts before POST /command. Neither a name nor 'another' bypasses yes.
  const confirmed = { action: "handover" as const, item: "hemostat", confirm: true, via: "gemini" as const };
  io.parse = async () => confirmed;
  const beforeConfirmation = posted.length;
  assert.match(await turn("bring me the uncertain thing", "call:confirm"), /Say yes or no/);
  assert.match(await turn("hemostat", "call:confirm"), /Say yes or no/);
  assert.equal(posted.length, beforeConfirmation);
  assert.match(await turn("no", "call:confirm"), /Cancelled/);
  assert.equal(posted.length, beforeConfirmation);
  await turn("bring me the uncertain thing", "call:confirm");
  await turn("yes", "call:confirm");
  assert.equal(posted.length, beforeConfirmation + 1);
  assert.equal(posted.at(-1)?.item, "hemostat");
  const uncertainText = { ...td, parseCommand: async () => confirmed };
  const textBefore = posted.length;
  assert.match(await handleText("bring me the uncertain thing", "+confirm", uncertainText), /Say yes or no/);
  assert.equal(posted.length, textBefore);
  await handleText("yes", "+confirm", uncertainText);
  assert.equal(posted.length, textBefore + 1);

  // HTTP + websocket copies of a texted by-sight question are delivered once, to its own thread.
  let sightCommand: Command | undefined;
  const notices: string[] = [];
  const textQuestion = { say: "Left or right?", item: "hemostat", candidates: visible, question_id: "text-sight" };
  const bySightText = { ...td, notify: (line: string) => notices.push(line), command: async (c: Command) => {
    sightCommand = c; return { accepted: false, reason: "clarify", say: textQuestion.say, clarify: textQuestion };
  } };
  assert.equal(await handleText("kelly", "+sight", bySightText), "Left or right?");
  receiveEvent({ type: "clarify", t: Date.now() / 1000, command_id: sightCommand!.id, ...textQuestion });
  assert.equal(notices.length, 0);
  assert.ok(dialogue.pending("text:+sight"));
  assert.ok(!dialogue.pending("call:+sight"));
  await handleText("right", "+sight", td);
  assert.deepEqual(posted.at(-1)?.instance, { side: "right", slot: 1 });

  const eventOnly = { ...td, notify: (line: string) => notices.push(line), command: async (c: Command) => {
    sightCommand = c; return { accepted: true, reason: null, say: null };
  } };
  await handleText("kelly", "+sight-event", eventOnly);
  receiveEvent({ type: "clarify", t: Date.now() / 1000, command_id: sightCommand!.id, ...textQuestion });
  assert.deepEqual(notices, ["Left or right?"]);
  assert.ok(dialogue.pending("text:+sight-event"));

  // A slow parse finishing after a concurrent stop must not enqueue a request or revive a question.
  let finishParse: (value: any) => void = () => {};
  io.parse = () => new Promise((resolve) => { finishParse = resolve; });
  const beforeStop = posted.length;
  const slow = turn("a slow uncertain request", "call:slow");
  await new Promise((resolve) => setTimeout(resolve, 0));
  const stopping = turn("stop", "call:stopper");
  finishParse(confirmed);
  await Promise.all([slow, stopping]);
  assert.equal(posted.length, beforeStop);
  assert.ok(!dialogue.pending("call:slow"));
} finally { Object.assign(io, saved); dialogue.clear(); }

// Real HTTP routes + websocket controller: /heard and ElevenLabs both preserve context across turns.
const commands: Command[] = [], logs: ClarifyLog[] = [];
let bySight = false;
const fake = http.createServer((req, res) => {
  let raw = "";
  req.on("data", (chunk) => raw += chunk);
  req.on("end", () => {
    res.setHeader("content-type", "application/json");
    if (req.url === "/setting") return res.end(JSON.stringify(setting));
    if (req.url === "/state") return res.end(JSON.stringify({ step: "idle", out: [], setting: "surgical", t: 1 }));
    if (req.url === "/clarify") { logs.push(JSON.parse(raw)); return res.end('{"ok":true}'); }
    if (req.url === "/stop") { emit({ type: "stopped", say: "Stopped." }); return res.end('{"accepted":true}'); }
    if (req.url === "/command") {
      const c: Command = JSON.parse(raw); commands.push(c);
      if (bySight && !c.instance) {
        setTimeout(() => emit({ type: "clarify", command_id: c.id, item: c.item, say: "Left or right?", candidates: visible, question_id: "sight-q" }), 20);
        return res.end('{"accepted":true,"say":null}');
      }
      return res.end(JSON.stringify({ accepted: false, reason: "test", say: "Already out. Return it first." }));
    }
    res.end("[]");
  });
});
const wss = new WebSocketServer({ server: fake });
const emit = (e: Omit<ScrubEvent, "t">) => wss.clients.forEach((ws) => ws.send(JSON.stringify({ ...e, t: Date.now() / 1000 })));
await new Promise<void>((resolve) => fake.listen(0, "127.0.0.1", resolve));
const port = (fake.address() as { port: number }).port;
const voicePort = 3194;
const output: string[] = [];
const child = spawn(process.execPath, ["--import", "tsx", "src/server.ts"], { cwd: path.resolve(import.meta.dirname, ".."),
  env: { ...process.env, VOICE_NO_KEYS: "1", GEMINI_API_KEY: "", PHOTON_API_KEY: "", ELEVENLABS_API_KEY: "", CONTROLLER_URL: `http://127.0.0.1:${port}`, VOICE_PORT: String(voicePort), VOICE_HOLD_S: "0.5", VOICE_BUSY_S: "0" } });
child.stdout.on("data", (data) => output.push(String(data)));
child.stderr.on("data", (data) => output.push(String(data)));
try {
  for (let i = 0; i < 100 && !output.join("").includes("[voice] listening"); i++) await new Promise((r) => setTimeout(r, 50));
  assert.ok(output.join("").includes("[voice] listening"), output.join(""));
  const heard = async (text: string, context = "a") => (await (await fetch(`http://localhost:${voicePort}/heard`, {
    method: "POST", body: JSON.stringify({ text, context }) })).json()).say.join(" ");
  const chat = async (text: string, conv = "conv_test") => {
    const reply = await (await fetch(`http://localhost:${voicePort}/v1/chat/completions`, { method: "POST", body: JSON.stringify({ stream: false,
      messages: [{ role: "system", content: `Conversation: ${conv}` }, { role: "user", content: text }] }) })).json();
    return reply.choices[0].message.content;
  };
  assert.match(await heard("scissors"), /Which scissors/);
  assert.equal(commands.length, 0);
  assert.match(await chat("scissors"), /Which scissors/);
  assert.equal(commands.length, 0);
  assert.match(await chat("curved"), /Already out/);
  assert.equal(commands.at(-1)?.item, "mayo_curved");
  assert.match(await heard("straight"), /Already out/);
  assert.equal(commands.at(-1)?.item, "mayo_straight");
  assert.ok(logs.some((r) => r.type === "clarify_answer" && r.context === "call:conv_test"));
  assert.ok(logs.some((r) => r.type === "clarify_answer" && r.context === "local:a"));
  bySight = true;
  assert.equal(await chat("kelly"), "Left or right?");
  assert.match(await chat("left"), /Already out/);
  assert.deepEqual(commands.at(-1)?.instance, { side: "left", slot: 0 });
  assert.match(await chat("scissors"), /Which scissors/);
  const n = commands.length;
  assert.equal(await chat("stop"), "Stopped.");
  assert.equal(commands.length, n);
} finally { child.kill(); wss.close(); fake.close(); }
console.log("voice Which one tests passed");

await import("./test-dialogue-lifecycle.js");
