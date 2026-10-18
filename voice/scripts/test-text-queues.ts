import "./test-env.js";
import assert from "node:assert/strict";
import { dialogue } from "../src/dialogue.js";
import { TextQueues } from "../src/text-queue.js";
import { runTexts, type InMessage, type InSpace, type TextDeps } from "../src/texts.js";
import type { Command } from "../src/controller.js";
import type { Setting } from "../src/settings.js";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}
const flush = async () => { for (let i = 0; i < 50; i++) await Promise.resolve(); };
const msg = (text: string): InMessage => ({ direction: "inbound", content: { type: "text", text }, sender: { id: "+same-sender" } });
const photo: InMessage = { direction: "inbound", content: { type: "attachment", mimeType: "image/jpeg", read: async () => Buffer.from("fake") } };
const setting: Setting = { id: "queue-test", label: "Test", items: [
  { id: "straight_hemostat", name: "straight hemostat", aliases: [], group: "hemostat", variant: "straight", sharp: false },
  { id: "curved_hemostat", name: "curved hemostat", aliases: [], group: "hemostat", variant: "curved", sharp: false },
] };
const base: Partial<TextDeps> = { state: async () => ({ step: "idle", out: [], setting: setting.id, t: 1 }), setting: async () => setting };

// Same sender, distinct spaces: B's hanging photo must not consume A's answer window.
dialogue.clear();
{
  const asked = deferred<void>(), photoStarted = deferred<void>(), releasePhoto = deferred<string>();
  const commands: Command[] = [], replies: [string, string][] = [];
  const a: InSpace = { id: "answer-thread", send: async (line) => { replies.push(["a", line]); if (line.startsWith("Which")) asked.resolve(); } };
  const b: InSpace = { id: "photo-thread", send: async (line) => { replies.push(["b", line]); } };
  async function* stream(): AsyncGenerator<[InSpace, InMessage]> {
    yield [a, msg("hemostat")];
    await asked.promise;
    yield [b, photo];
    await photoStarted.promise;
    yield [a, msg("curved")];
  }
  const work = runTexts(stream(), { ...base,
    photo: async () => { photoStarted.resolve(); return releasePhoto.promise; },
    command: async (c) => { commands.push(c); return { accepted: true, reason: null, say: "Curved coming." }; },
  });
  try {
    await photoStarted.promise;
    await flush();
    assert.equal(commands.length, 1, "A answers while B's photo remains unresolved");
    assert.equal(commands[0].item, "curved_hemostat");
    assert.ok(replies.some(([thread, line]) => thread === "a" && line === "Curved coming."));
    assert.ok(!replies.some(([thread]) => thread === "b"), "B is still blocked, not A");
    assert.ok(!dialogue.pending("text:answer-thread"));
  } finally { releasePhoto.resolve("Photo read."); await work; dialogue.clear(); }
}

// Receipt-time generations: stop, then reset, must not resurrect an older queued handover.
{
  const photoStarted = deferred<void>(), releasePhoto = deferred<string>(), stopped = deferred<void>();
  let frozen = false, resets = 0;
  const commands: Command[] = [];
  const space: InSpace = { id: "generation-thread", send: async (line) => { if (line === "Stopped.") stopped.resolve(); } };
  const single: Setting = { id: "single", label: "Test", items: [{ id: "hemostat", name: "hemostat", aliases: ["kelly"], sharp: false }] };
  async function* stream(): AsyncGenerator<[InSpace, InMessage]> {
    yield [space, photo];
    await photoStarted.promise;
    yield [space, msg("hemostat")]; // queued before stop, must be dropped even after reset
    yield [space, msg("stop")];
    await stopped.promise;
    frozen = false; resets++; // fake controller reset, no API or sleep
    yield [space, msg("kelly")]; // newly received work remains valid
  }
  const work = runTexts(stream(), { ...base, setting: async () => single,
    photo: async () => { photoStarted.resolve(); return releasePhoto.promise; },
    stop: async () => { frozen = true; return { accepted: true }; },
    command: async (c) => { assert.ok(!frozen); commands.push(c); return { accepted: true, reason: null, say: "Coming." }; },
  });
  try {
    await stopped.promise;
    await flush();
    assert.equal(resets, 1);
    releasePhoto.resolve("Photo read.");
    await work;
    assert.deepEqual(commands.map((c) => c.heard), ["kelly"], "only the post-stop/reset receipt can execute");
  } finally { releasePhoto.resolve("Photo read."); await work; dialogue.clear(); }
}

// Empty queues are removed; an older completion must not remove a newer tail on the same thread.
{
  const queues = new TextQueues(), gate = deferred<void>();
  const order: number[] = [];
  void queues.enqueue("same", async () => { await gate.promise; order.push(1); });
  void queues.enqueue("same", async () => { order.push(2); });
  await queues.enqueue("other", async () => { order.push(0); });
  assert.deepEqual(order, [0]);
  assert.equal(queues.size, 1);
  gate.resolve(); await queues.drain();
  assert.deepEqual(order, [0, 1, 2]);
  assert.equal(queues.size, 0);
  for (let pass = 0; pass < 3; pass++) {
    await Promise.all(Array.from({ length: 50 }, (_, i) => queues.enqueue(`thread-${i}`, async () => {})));
    assert.equal(queues.size, 0, "completed threads never accumulate");
  }
}
console.log("voice text queue tests passed");
