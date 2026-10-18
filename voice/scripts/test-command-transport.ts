// Virtual transport time: a 3.5 s locate preflight must fit /command, while /stop keeps its 3 s budget.
import "./test-env.js";
import assert from "node:assert/strict";
import { COMMAND_TIMEOUT_MS, makeCommand, postCommand, postStop } from "../src/controller.js";
import { dialogue } from "../src/dialogue.js";
import { parse } from "../src/parse.js";
import { handleTurn, io, receiveEvent } from "../src/turn.js";
import type { Setting } from "../src/settings.js";

const originalFetch = globalThis.fetch, originalTimeout = AbortSignal.timeout;
const saved = { ...io };
const budgets = new Map<AbortSignal, number>();
let now = 0;
const tasks: { at: number; run: () => void }[] = [];
const advance = (ms: number) => {
  const end = now + ms;
  while (tasks.some((t) => t.at <= end)) {
    tasks.sort((a, b) => a.at - b.at);
    const next = tasks.shift()!; now = next.at; next.run();
  }
  now = end;
};
let onCommand = () => {};
let withEvents = false;
AbortSignal.timeout = (ms) => {
  const controller = new AbortController(); budgets.set(controller.signal, ms);
  tasks.push({ at: now + ms, run: () => controller.abort(new DOMException("Timed out", "TimeoutError")) });
  return controller.signal;
};
const paths: string[] = [];
globalThis.fetch = async (input, options) => {
  const path = new URL(String(input)).pathname;
  paths.push(path);
  if (path === "/stop") {
    assert.equal(budgets.get(options!.signal!), 3000);
    if (withEvents) receiveEvent({ type: "stopped", t: Date.now() / 1000, say: "Stopped." });
    return new Response('{"accepted":true}');
  }
  assert.equal(path, "/command");
  assert.equal(budgets.get(options!.signal!), COMMAND_TIMEOUT_MS);
  const command = JSON.parse(String(options!.body));
  onCommand();
  return new Promise<Response>((resolve, reject) => {
    options!.signal!.addEventListener("abort", () => reject(options!.signal!.reason), { once: true });
    tasks.push({ at: now + 3500, run: () => {
      if (withEvents) receiveEvent({ type: "handed", t: Date.now() / 1000, command_id: command.id, item: command.item, say: "Hemostat coming." });
      resolve(new Response(JSON.stringify({ accepted: true, reason: null, say: withEvents ? "Hemostat coming." : null })));
    } });
  });
};
try {
  assert.ok(COMMAND_TIMEOUT_MS >= 6000 && COMMAND_TIMEOUT_MS <= 8000);
  const delayed = postCommand(makeCommand("handover", "hemostat", "kelly"));
  await postStop(); // independent request, not queued behind the outstanding preflight
  advance(3100);
  advance(400);
  assert.equal((await delayed).accepted, true);
  assert.deepEqual(paths, ["/command", "/stop"]);

  const setting: Setting = { id: "transport-test", label: "Test", items: [{ id: "hemostat", name: "hemostat", aliases: ["kelly"], sharp: false }] };
  Object.assign(io, { currentSetting: async () => setting, parse, postCommand, postStop });
  let posted = new Promise<void>((resolve) => { onCommand = resolve; });
  withEvents = true;
  const lines: string[] = [];
  const turn = handleTurn("kelly", (line) => lines.push(line), undefined, Date.now(), "local:delayed-accept");
  await posted;
  advance(3500);
  await turn;
  assert.deepEqual(lines, ["Hemostat coming."], "delayed acceptance never falsely claims the controller is unreachable");

  // A stop still invalidates an outstanding POST's eventual clarification response.
  let release = (_reply: any) => {}, began = () => {};
  posted = new Promise<void>((resolve) => { began = resolve; });
  io.postCommand = () => { began(); return new Promise((resolve) => { release = resolve; }); };
  const slow = handleTurn("kelly", () => {}, undefined, Date.now(), "call:delayed-after-stop");
  await posted;
  const stop = handleTurn("stop", () => {}, undefined, Date.now(), "call:stop-delayed");
  release({ accepted: false, reason: "clarify", say: null, clarify: { say: "Which one?", item: "hemostat", question_id: "late-q", candidates: [{ item: "hemostat", slot: 1 }] } });
  await Promise.all([slow, stop]);
  assert.ok(!dialogue.pending("call:delayed-after-stop"));
} finally {
  globalThis.fetch = originalFetch; AbortSignal.timeout = originalTimeout;
  Object.assign(io, saved); dialogue.clear();
}
console.log("voice command transport tests passed");
