// The station bridge: handover -> wake + averaged replay of that item's demos; let go / got it -> release; stop -> stop.
import assert from "node:assert/strict";
import { makeCommand } from "../src/controller.js";
import { stationCommand, taskFor } from "../src/station.js";

assert.equal(taskFor("hemostat"), "pick the hemostat");
assert.equal(taskFor("mayo_scissors"), "pick the mayo scissors");
assert.equal(taskFor("not_in_settings"), "pick the not in settings");

const calls: any[] = [];
let state = "parked";
const post = async (action: string, extra: Record<string, unknown> = {}) => {
  calls.push({ action, ...extra });
  if (action === "wake") state = "idle";
  return { ok: true, msg: `${action} ok` };
};
const get = async () => ({ state });

assert.equal(await stationCommand(makeCommand("handover", "hemostat", "get the hemostat"), post, get, 2000), "run ok");
assert.deepEqual(calls.map((c) => c.action), ["wake", "run"]);
assert.deepEqual(calls[1].args, { mode: "average", task: "pick the hemostat" });

calls.length = 0;
assert.equal(await stationCommand(makeCommand("let_go", null, "let go"), post, get), "release ok");
assert.equal(await stationCommand(makeCommand("got_it", null, "got it"), post, get), "release ok");
assert.equal(await stationCommand(makeCommand("stop", null, "stop"), post, get), "pause ok");  // stop = freeze
assert.deepEqual(calls.map((c) => c.action), ["release", "release", "pause"]);

state = "running";
assert.match(await stationCommand(makeCommand("handover", "scalpel", "scalpel"), post, get), /busy/);
const down = async () => { throw new Error("connect ECONNREFUSED"); };
assert.match(await stationCommand(makeCommand("handover", "scalpel", "scalpel"), post, down as any), /unreachable/);
console.log("voice station bridge tests passed");

import { fixMishears } from "../src/parse.js";
assert.equal(fixMishears("get the email set"), "get the hemostat");
assert.equal(fixMishears("get the hemo stat please"), "get the hemostat please");
console.log("voice mishear tests passed");

import { stationReply } from "../src/station.js";
assert.equal(stationReply(makeCommand("handover", "hemostat", "x"), "RUN autopick ...").say, "Getting the hemostat.");
assert.equal(stationReply(makeCommand("handover", "hemostat", "x"), "busy: a run is already going").say, "I'm already moving.");
assert.equal(stationReply(makeCommand("let_go", null, "x"), "let go: nothing is being held out").say, "I'm not holding anything.");
console.log("voice station reply tests passed");

import { stationFast } from "../src/station.js";
{
  const order: string[] = [];
  let st2 = "parked";
  const p2 = async (a: string) => { order.push(a); if (a === "wake") st2 = "idle"; return { msg: `${a} ok` }; };
  const g2 = async () => ({ state: st2 });
  const t0 = Date.now();
  let later = "";
  const m = await stationFast(makeCommand("handover", "hemostat", "x"), p2, g2, (d) => { later = d; });
  assert.equal(m, "starting");
  assert.ok(Date.now() - t0 < 100, "the handover reply must not wait for the arm");
  await new Promise((r) => setTimeout(r, 600));
  assert.deepEqual(order, ["wake", "run"]);
  assert.equal(later, "run ok");
  console.log("voice station fast-reply tests passed");
}

import { stationPhrase } from "../src/station.js";
{
  const got: string[] = [];
  const p3 = async (a: string) => { got.push(a); return { msg: a === "resume" ? "continuing" : "ok" }; };
  assert.equal((await stationPhrase("kill it", p3))?.say, "Motors off.");
  assert.equal((await stationPhrase("return to home", p3))?.say, "Going home.");
  assert.equal((await stationPhrase("okay continue", p3))?.say, "Continuing.");
  assert.equal(await stationPhrase("get the hemostat", p3), null);
  assert.deepEqual(got, ["kill", "home", "resume"]);
  const calls2: string[] = [];
  await stationCommand(makeCommand("stop", null, "stop"), async (a: string) => { calls2.push(a); return { msg: "frozen where it is" }; }, get);
  assert.deepEqual(calls2, ["pause"]);  // stop freezes in place, it does not send the arm home
  console.log("voice station words tests passed");
}
