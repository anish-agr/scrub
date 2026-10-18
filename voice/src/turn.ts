// One caller turn: what was heard -> controller -> the lines Scrub speaks back.
// Event `say` lines stream into the open reply. Lines that arrive with no reply open wait for the next turn,
// but only the last 2 and only if they are under 10 s old (a dashboard or smoke run left 20 lines for the next caller).
import { HOLD_S } from "./config.js";
import { SETTING_IDS, settingAsked, switchSetting } from "./cases.js";
import { followEvents, JUDGE_LINE, judgeMode, makeCommand, noteJudge, postCommand, postStop, type ScrubEvent } from "./controller.js";
import { countTurn, isEndCase, isStop, isTrayCheck, parse, parseAlias } from "./parse.js";
import { currentSetting, forgetSetting, teach } from "./settings.js";
import { canText, endCase, recordEvent } from "./summary.js";
import { voiceTrayCheck } from "./tray.js";
import { blankTiming, recordTiming, type TurnTiming } from "./timing.js";
import { dialogue } from "./dialogue.js";

type Say = (line: string) => void;
type Hold = (types: string[], holdS: number, commandId?: string) => void;

// The network and parse calls a turn makes; tests swap them (in-process, never the real controller or Gemini).
export const io = { parse, postStop, postCommand, currentSetting, judgeMode, switchSetting, teach };

let open: { say: Say; onEvent: (e: ScrubEvent) => void; context: string } | null = null;
let pending: { line: string; t: number; context?: string }[] = [];
const PENDING_MS = 10_000;  // a line nobody heard within 10 s is stale: drop it
const PENDING_MAX = 2;
let settingId = "surgical";
let lastLine: { text: string; t: number; cmd?: string | null } = { text: "", t: 0 };

// Ends the hold for an action once one of these arrives.
const DONE: Record<string, string[]> = {
  handover: ["handed", "released", "set_down", "missed", "stopped", "error", "clarify"],
  got_it: ["released", "stopped", "error"],
  return: ["returned", "missed", "stopped", "error", "clarify"],
  count: ["count", "error"],
  stop: ["stopped"],
  unknown: [],
  // Reads take 1 to 3 s: hold until the `read` event, so its `say` is spoken in this reply.
  read_sheet: ["read", "error", "stopped"],
  read_tray: ["read", "error", "stopped"],
  read_pack: ["read", "error", "stopped"],
};
// Hold (seconds) for actions that wait longer than HOLD_S.
const HOLD_FOR: Record<string, number> = { read_sheet: 25, read_tray: 25, read_pack: 25 };

// fromEvent: skip an event line said in the last 3 s for the same command (the controller repeating itself).
// A new command that gets the same answer ("I'm stopped. Reset me first." twice) is said again: keyed on the
// text alone, the second ask got silence. Our own replies (judge mode, busy, a tray switch) are always said.
export function speak(line: string | null | undefined, fromEvent = false, cmd?: string | null, context?: string) {
  if (!line) return;
  const now = Date.now();
  if (fromEvent && line === lastLine.text && now - lastLine.t < 3000 && (cmd ?? null) === (lastLine.cmd ?? null)) return;
  lastLine = { text: line, t: now, cmd };
  if (open && (!context || open.context === context)) open.say(line); else pending.push({ line, t: now, context });
}

export function receiveEvent(e: ScrubEvent) {
    recordEvent(e);
    if (typeof e.judge === "boolean") noteJudge(e.judge);
    if (e.setting && e.setting !== settingId) {
      settingId = e.setting;
      forgetSetting();
      currentSetting(settingId).catch(() => {});  // warm the cache before the next turn
    }
    const origin = dialogue.event(e);
    if (origin?.ignore) return;
    let line = origin?.line || e.say;
    // "Scalpel down" call-out, if the controller didn't word one.
    if (!line && e.type === "set_down" && e.item) line = `${e.item.replace(/_/g, " ")} down`;
    if (line) console.log(`[say] ${line}  (${e.type}${e.skill_source === "taught" ? ", taught skill" : ""})`);
    if (origin?.notify) { if (line) origin.notify(line); }
    else if (e.type !== "clarify" || origin) speak(line, true, e.command_id, origin?.context);
    if (!origin || origin.context === open?.context) open?.onEvent(e);
}

export function startEvents() {
  followEvents(receiveEvent, recordEvent);  // missed while reconnecting: counted in the summary, never spoken
}

// t0: when the request arrived (the server passes it, so the timings include reading the body).
export async function handleTurn(heard: string, sayTo: Say, signal?: AbortSignal, t0 = Date.now(), context = "local"): Promise<void> {
  countTurn();
  console.log(`[heard] ${heard}`);
  const tm = blankTiming();
  const say: Say = (line) => { tm.first_line_ms ??= Date.now() - t0; sayTo(line); };
  let logged = false;
  const done = new Promise<void>((resolve) => {
    let timer: NodeJS.Timeout | undefined;
    let waitFor: string[] = [];
    let cmdId: string | undefined;
    // Events seen during the turn. The controller emits `count`, `stopped` and an early `error` while it answers
    // the POST, so the event can land before hold() is called; without this the reply stayed open the full hold.
    const seen: ScrubEvent[] = [];
    // Ends the hold: a type it waits for, for this command. A stop, or an error that holds the arm, ends it whatever
    // command it names. A robot-model error from pre-opening sessions (command_id null, arm not held) is only spoken.
    const ends = (e: ScrubEvent) => {
      if (!waitFor.includes(e.type)) return false;
      if (e.type === "stopped") return true;
      // "got it" releases the handover's item: that released event names the handover's command, not this one.
      // Matched on the id, the reply stayed open the full hold.
      if (e.type === "released" && !waitFor.includes("handed")) return true;
      if (e.type === "error") return e.step === "error" || (!!cmdId && e.command_id === cmdId);
      return !cmdId || !e.command_id || e.command_id === cmdId;
    };
    const finish = () => {
      clearTimeout(timer);
      if (open?.say === say) open = null;
      if (!logged) { logged = true; recordTiming(tm); }
      resolve();
    };
    signal?.addEventListener("abort", finish);
    open = { say, context, onEvent: (e) => { seen.push(e); if (ends(e)) setTimeout(finish, 300); } };
    run(heard, { tm, t0 }, (types, holdS, id) => {
      waitFor = types;
      cmdId = id;
      timer = setTimeout(finish, holdS * 1000);
      if (seen.some(ends)) setTimeout(finish, 300);
    }, context, signal).catch((err) => {
      console.log(`[turn] ${(err as Error).message}`);
      say("I can't reach the arm controller.");
      finish();
    });
  });
  return done;
}

// POST /stop: skips the controller's queue and is always accepted. Nothing awaits Gemini, settings or state first.
async function stopNow(hold: Hold, clock: Clock) {
  dialogue.clear();
  const sent = posting(clock);
  await io.postStop().catch(() => io.postStop());
  clock.tm.controller_ms = Date.now() - sent;  // one retry: a dropped connection must not lose a stop
  console.log("[command] stop (POST /stop)");
  flushPending();
  hold(DONE.stop, 1.5);
}

// The turn's timings and when its request arrived.
type Clock = { tm: TurnTiming; t0: number };
const posting = ({ tm, t0 }: Clock) => { const now = Date.now(); tm.heard_to_command_ms = now - t0; return now; };

async function run(heard: string, clock: Clock, hold: Hold, context: string, signal?: AbortSignal) {
  const say = (line: string) => speak(line, false, undefined, context);
  // Stop first, before Gemini or anything else that takes time.
  if (isStop(heard)) { clock.tm.parser = "local"; return stopNow(hold, clock); }
  const version = dialogue.version();
  const stale = () => signal?.aborted || dialogue.version() !== version;
  flushPending();
  if (isEndCase(heard)) {
    dialogue.clear(context);
    // Only promise a text that can be sent; with no Photon keys or no number the summary is just logged.
    say(canText() ? "Closing the case. The summary is on its way to your phone." : "Closing the case.");
    hold([], 0.5);
    endCase().catch((e) => console.log(`[summary] ${(e as Error).message}`));
    return;
  }
  if (isTrayCheck(heard)) {
    say(await voiceTrayCheck());
    hold([], 0.5);
    return;
  }
  // "start a bench case": a local phrase match, before Gemini (the Command actions don't include it).
  // Judge mode (from a short-lived cache of GET /state): no POST /setting.
  const asked = settingAsked(heard);
  if (asked) {
    dialogue.clear(context);
    // A tray voice doesn't offer (dental) gets its "not set up" line without asking for judge mode.
    say(SETTING_IDS.includes(asked) && await io.judgeMode() ? JUDGE_LINE : await io.switchSetting(asked));
    hold([], 0.5);
    return;
  }
  // The controller's current setting, so Gemini only sees ids on this tray.
  const setting = await io.currentSetting(settingId);
  if (stale()) { hold([], 0); return; }
  settingId = setting.id;
  // X6 clinic words, before Gemini: "call the hemostat a clamp" -> POST /alias, say its line. Not in judge mode.
  const taught = parseAlias(heard, setting);
  if (taught) {
    if (await io.judgeMode()) { say(JUDGE_LINE); hold([], 0.5); return; }
    const r = await io.teach(taught.item, taught.alias);
    console.log(`[alias] ${taught.alias} -> ${taught.item}${r.ok ? "" : ` refused: ${r.reason}`}`);
    say(r.say);
    hold([], 0.5);
    return;
  }
  const parsed = Date.now();
  const answer = dialogue.answer(context, heard, setting);
  if (answer && "say" in answer) { say(answer.say); hold([], 0.05); return; }
  let p = answer && "parsed" in answer ? { ...answer.parsed, via: "local" as const } : await io.parse(heard, setting);
  if (stale()) { hold([], 0); return; }
  clock.tm.parser = p.via;
  if (p.via === "gemini") clock.tm.gemini_ms = Date.now() - parsed;
  // Gemini heard a stop the local words missed ("hold on, freeze it up"): the POST /stop fast path, not the queue.
  if (p.action === "stop") { console.log(`[command] stop  (${p.via})`); return stopNow(hold, clock); }
  const scoped = dialogue.scope(context, p, setting);
  if (scoped && "say" in scoped) { say(scoped.say); hold([], 0.05); return; }
  if (scoped && "parsed" in scoped) p = { ...scoped.parsed, via: p.via };
  const question = dialogue.askParsed(context, p, setting);
  if (question) { say(question); hold([], 0.05); return; }
  const cmd = makeCommand(p.action, p.item, heard);
  if (p.instance) cmd.instance = p.instance;
  dialogue.track(context, cmd, setting);
  console.log(`[command] ${cmd.action}${cmd.item ? " " + cmd.item : ""}  (${p.via})`);
  const sent = posting(clock);
  const reply = await io.postCommand(cmd);
  clock.tm.controller_ms = Date.now() - sent;
  if (reply.clarify) {
    if (!dialogue.commandActive(cmd.id)) { hold([], 0); return; }
    speak(dialogue.ask(context, reply.clarify, setting, cmd.action, false, false), true, cmd.id, context);
    hold([], 0.05, cmd.id); return;
  }
  // HTTP-only refusals (for example "already out") must also reach the caller. Event duplicates are suppressed.
  speak(reply.say, true, cmd.id, context);
  if (!reply.accepted) console.log(`[command] rejected: ${reply.reason}`);
  hold(reply.accepted ? DONE[cmd.action] : [], reply.accepted && DONE[cmd.action].length ? HOLD_FOR[cmd.action] ?? HOLD_S : 1, cmd.id);
}

function flushPending() {
  const now = Date.now();
  const lines = pending.filter((p) => now - p.t < PENDING_MS && (!p.context || p.context === open?.context)).slice(-PENDING_MAX);
  pending = pending.filter((p) => now - p.t < PENDING_MS && p.context && p.context !== open?.context);
  for (const p of lines) open?.say(p.line);
}
