import "./test-env.js";
import assert from "node:assert/strict";
import { Dialogue, QUESTION_MS, TIMEOUT_LINE, dialogue, type QuestionTimers } from "../src/dialogue.js";
import { chooseCandidate } from "../src/choice.js";
import { localParse, parse } from "../src/parse.js";
import { handleText, runTexts, type InMessage, type InSpace, type TextDeps } from "../src/texts.js";
import { handleTurn, io, receiveEvent } from "../src/turn.js";
import type { Candidate, ClarifyLog, Command, State } from "../src/controller.js";
import type { Setting } from "../src/settings.js";

// Hemostat variants are fixtures only; do not change the surgical tray used on hardware.
const setting: Setting = { id: "test-hemostats", label: "Test tray", items: [
  { id: "straight_hemostat", name: "straight hemostat", aliases: ["kelly"], group: "hemostat", variant: "straight", sharp: false },
  { id: "curved_hemostat", name: "curved hemostat", aliases: ["kelly"], group: "hemostat", variant: "curved", sharp: false },
] };
const question = localParse("hemostat", setting).clarify!;
assert.equal(question.say, "Which hemostat: straight or curved?");
assert.equal(localParse("curved hemostat", setting).item, "curved_hemostat");
class FakeClock {
  now = 0;
  private next = 0;
  tasks = new Map<number, { at: number; run: () => void }>();
  timers: QuestionTimers = {
    set: (run, ms) => { const id = ++this.next; this.tasks.set(id, { at: this.now + ms, run }); return id; },
    clear: (id) => { this.tasks.delete(id as number); },
  };
  advance(ms: number) {
    const end = this.now + ms;
    for (;;) {
      const next = [...this.tasks].filter(([, t]) => t.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
      if (!next) break;
      this.now = next[1].at; this.tasks.delete(next[0]); next[1].run();
    }
    this.now = end;
  }
}
const clock = new FakeClock();
const rows: ClarifyLog[] = [], notices: string[] = [];
const d = new Dialogue(() => clock.now, async (r) => { rows.push(r); }, clock.timers);
d.bind("text:timer", (line) => notices.push(line));
d.ask("text:timer", { ...question, question_id: "backend-q" }, setting, "handover", false, false);
clock.advance(10_000);
d.ask("text:timer", { ...question, question_id: "backend-q" }, setting, "handover", false, false);
assert.equal(clock.tasks.size, 1, "HTTP + WS share the original deadline");
clock.advance(4999);
assert.ok(d.pending("text:timer"));
clock.advance(1);
assert.ok(!d.pending("text:timer"), "timer clears the question without another utterance");
assert.deepEqual(notices, [TIMEOUT_LINE]);
assert.match(TIMEOUT_LINE, /I'll wait for you to ask again/);
assert.equal(clock.tasks.size, 0);
assert.equal(rows.at(-1)?.answer, "timeout");
assert.equal(rows.at(-1)?.status, "timeout");
assert.equal(rows.at(-1)?.answer_ms, QUESTION_MS);
assert.equal(rows.at(-1)?.question_id, "backend-q");
assert.ok("say" in d.answer("text:timer", "curved", setting)!);
d.ask("legacy", { say: "Left or right?", candidates: [{ item: "straight_hemostat", side: "left", slot: 1 }, { item: "curved_hemostat", side: "right", slot: 2 }] }, setting);
clock.advance(10_000);
d.ask("legacy", { say: "Left or right?", candidates: [{ slot: 1, side: "left", item: "straight_hemostat" }, { slot: 2, side: "right", item: "curved_hemostat" }] }, setting);
assert.equal(d.remaining("legacy"), 5000, "legacy copies without ids ignore JSON property ordering");
d.clear("legacy");
d.ask("text:cancel", question, setting);
d.answer("text:cancel", "never mind", setting);
assert.equal(clock.tasks.size, 0);
assert.equal(rows.at(-1)?.status, "cancelled");
assert.equal(rows.at(-1)?.answer, "never mind");
d.ask("call:stop", question, setting);
d.clear(undefined, "stop");
assert.equal(rows.at(-1)?.answer, "stop");
assert.equal(clock.tasks.size, 0);
clock.advance(QUESTION_MS * 2);
assert.equal(notices.length, 1, "cancelled timers do not send timeout notices");

const rates = { by_item: [
  { item: "straight_hemostat", attempts: 20, success_rate: 0.6 },
  { item: "curved_hemostat", attempts: 20, success_rate: 0.95 },
] };
const positions: Candidate[] = [{ item: "straight_hemostat", distance_m: 0.1 }, { item: "curved_hemostat", distance_m: 0.4 }];
assert.equal(chooseCandidate(positions, rates)?.item, "curved_hemostat", "real success outranks proximity");
assert.equal(chooseCandidate(positions)?.item, "straight_hemostat");
assert.equal(chooseCandidate(positions, { ...rates, source: "controller memory (ledger not loaded)" })?.item, "straight_hemostat");
assert.equal(chooseCandidate(positions, { by_item: [{ item: "curved_hemostat", attempts: 20, success_rate: 1, sim: true }] })?.item, "straight_hemostat");
assert.equal(chooseCandidate([{ item: "far", position: [0.9, 0, 0] }, { item: "near", position: [0.2, 0, 0] }])?.item, "near");
assert.equal(chooseCandidate([{ item: "far", box: [0, 0, 10, 10] }, { item: "near", box: [0, 100, 10, 110] }])?.item, "near");
for (const phrase of ["either", "any", "you pick"]) {
  d.ask("rank", question, setting);
  const answer = await d.answerAsync("rank", phrase, setting, async () => rates);
  assert.ok(answer && "parsed" in answer);
  assert.equal(answer.parsed.item, "curved_hemostat");
  assert.equal(answer.parsed.question_id, undefined, "local telemetry ids are not backend question ids");
}

const one: Setting = { id: "single", label: "Test", items: [{ id: "hemostat", name: "hemostat", aliases: ["kelly"], sharp: false }] };
const offer = { say: "The left one is out. Would you like the right one?", item: "hemostat", confirm: true, question_id: "offer-q",
  candidates: [{ item: "hemostat", instance: { slot: 2, side: "right" as const } }] };
d.ask("offer", offer, one, "handover", false, false);
assert.ok("say" in (await d.answerAsync("offer", "any", one, async () => { throw new Error("must not fetch stats before yes"); }))!);
const yes = d.answer("offer", "yes", one);
assert.ok(yes && "parsed" in yes);
assert.equal(yes.parsed.question_id, "offer-q");
assert.deepEqual(yes.parsed.instance, { slot: 2, side: "right" });

// A return of slot 1 must not erase a different recipient's slot 2 of the same item.
const cmd = (id: string, slot: number): Command => ({ id, action: "handover", item: "hemostat", heard: "kelly", source: "voice", t: 1, instance: { slot } });
for (const [context, slot] of [["person:left", 1], ["person:right", 2]] as const) {
  const c = cmd(context, slot); d.track(context, c, one);
  d.event({ type: "released", t: 1, command_id: c.id, item: c.item, instance: c.instance });
}
d.event({ type: "returned", t: 2, item: "hemostat", instance: { slot: 1 } });
assert.ok("say" in d.answer("person:left", "take it back", one)!);
assert.deepEqual((d.answer("person:right", "take it back", one) as any).parsed.instance, { slot: 2 });
d.clear();

// A hanging ordinary text does not stop the Photon reader from dispatching the next stop.
for (const kind of ["summary", "photo"] as const) {
  let release = (_line: string) => {}, started = () => {}, stopped = () => {};
  const startedP = new Promise<void>((r) => { started = r; });
  const stoppedP = new Promise<void>((r) => { stopped = r; });
  const hanging = () => { started(); return new Promise<string>((r) => { release = r; }); };
  const sent: string[] = [];
  const space: InSpace = { id: `priority-${kind}`, send: async (line) => { sent.push(line); } };
  const deps: Partial<TextDeps> = { state: async (): Promise<State> => ({ step: "idle", out: [], setting: one.id, t: 1 }), setting: async () => one,
    summary: hanging, photo: hanging, stop: async () => { stopped(); return { accepted: true }; } };
  const message = (text: string): InMessage => ({ direction: "inbound", content: { type: "text", text }, sender: { id: "+test" } });
  async function* stream(): AsyncGenerator<[InSpace, InMessage]> {
    yield [space, kind === "summary" ? message("summary") : { direction: "inbound", content: { type: "attachment", mimeType: "image/jpeg", read: async () => Buffer.from("fake") } }];
    await startedP;
    yield [space, message("stop")];
  }
  const work = runTexts(stream(), deps);
  let watchdog: NodeJS.Timeout | undefined;
  try {
    await Promise.race([stoppedP, new Promise((_, reject) => { watchdog = setTimeout(() => reject(new Error(`stop queued behind ${kind}`)), 1000); })]);
  } finally { clearTimeout(watchdog); release("Previous work complete."); }
  await work;
  assert.ok(sent.includes("Stopped."));
}

// Call and text routes forward backend ids and honor controller confirmation, without forwarding local ids.
dialogue.clear();
const saved = { ...io };
const commands: Command[] = [];
const accept = async (c: Command) => { commands.push(c); return { accepted: false, reason: "test", say: "Received." }; };
Object.assign(io, { currentSetting: async () => setting, parse, getStats: async () => rates, postCommand: accept });
try {
  const abort = new AbortController();
  const spoken: string[] = [];
  let done = false;
  const streaming = handleTurn("hemostat", (line) => spoken.push(line), abort.signal, Date.now(), "call:lifecycle").then(() => { done = true; });
  await new Promise((r) => setTimeout(r, 70));
  assert.equal(spoken[0], question.say, "first question chunk is immediate");
  receiveEvent({ type: "clarify_answer", t: Date.now() / 1000, say: TIMEOUT_LINE });
  assert.equal(spoken.length, 1, "timeout telemetry never leaks into an unrelated open reply");
  assert.ok(!done, "streaming phone reply stays open for the pending question");
  abort.abort(); await streaming;
  assert.ok(dialogue.pending("call:lifecycle"), "interruption closes speech, not the pending answer");
  await handleTurn("you pick", () => {}, undefined, Date.now(), "call:lifecycle");
  assert.equal(commands.at(-1)?.item, "curved_hemostat");
  assert.equal(commands.at(-1)?.question_id, undefined);

  const td: Partial<TextDeps> = { state: async () => ({ step: "idle", out: [], setting: one.id, t: 1 }), setting: async () => one,
    command: async () => ({ accepted: false, reason: "clarify", say: offer.say, clarify: offer }) };
  await handleText("kelly", "+offer", td);
  const before = commands.length;
  assert.match(await handleText("either", "+offer", { ...td, command: accept }), /Would you like/);
  assert.equal(commands.length, before);
  await handleText("yes", "+offer", { ...td, command: accept });
  assert.equal(commands.at(-1)?.question_id, "offer-q");

  Object.assign(io, { currentSetting: async () => one, postCommand: async (c: Command) => {
    setTimeout(() => receiveEvent({ type: "clarify", t: Date.now() / 1000, command_id: c.id, ...offer }), 10);
    return { accepted: true, reason: null, say: null };
  } });
  const stopReply = new AbortController();
  const eventLines: string[] = [];
  let eventDone = false;
  const bySight = handleTurn("kelly", (line) => eventLines.push(line), stopReply.signal, Date.now(), "call:offer-event").then(() => { eventDone = true; });
  await new Promise((r) => setTimeout(r, 450));
  assert.equal(eventLines[0], offer.say);
  assert.ok(!eventDone, "clarify event extends only the streaming call reply");
  stopReply.abort(); await bySight;
  io.postCommand = accept;
  await handleTurn("yes", () => {}, undefined, Date.now(), "call:offer-event");
  assert.equal(commands.at(-1)?.question_id, "offer-q");
} finally { Object.assign(io, saved); dialogue.clear(); }
console.log("voice clarification lifecycle tests passed");
