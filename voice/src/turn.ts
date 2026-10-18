// One caller turn: what was heard -> controller -> the lines Scrub speaks back.
// Event `say` lines stream into the open reply. Lines that arrive with no reply open wait for the next turn.
import { HOLD_S } from "./config.js";
import { SETTING_IDS, settingAsked, switchSetting } from "./cases.js";
import { followEvents, JUDGE_LINE, judgeMode, makeCommand, noteJudge, postCommand, postStop, type ScrubEvent } from "./controller.js";
import { isEndCase, isStop, isTrayCheck, parse, parseAlias } from "./parse.js";
import { currentSetting, forgetSetting, teach } from "./settings.js";
import { endCase, recordEvent } from "./summary.js";
import { voiceTrayCheck } from "./tray.js";

type Say = (line: string) => void;
type Hold = (types: string[], holdS: number, commandId?: string) => void;

// The network and parse calls a turn makes; tests swap them (in-process, never the real controller or Gemini).
export const io = { parse, postStop, postCommand, currentSetting, judgeMode, switchSetting, teach };

let open: { say: Say; onEvent: (e: ScrubEvent) => void } | null = null;
let pending: string[] = [];
let settingId = "surgical";
let lastLine = { text: "", t: 0 };

// Ends the hold for an action once one of these arrives.
const DONE: Record<string, string[]> = {
  handover: ["handed", "released", "set_down", "missed", "stopped", "error"],
  got_it: ["released", "stopped", "error"],
  return: ["returned", "missed", "stopped", "error"],
  count: ["count", "error"],
  stop: ["stopped"],
  unknown: [],
};

// fromEvent: skip an event line said in the last 3 s (the controller repeating itself). Our own replies
// (judge mode, busy, a tray switch) are always said: asking twice used to get silence the second time.
function speak(line: string | null | undefined, fromEvent = false) {
  if (!line) return;
  const now = Date.now();
  if (fromEvent && line === lastLine.text && now - lastLine.t < 3000) return;
  lastLine = { text: line, t: now };
  if (open) open.say(line); else pending.push(line);
}

export function startEvents() {
  followEvents((e) => {
    recordEvent(e);
    if (typeof e.judge === "boolean") noteJudge(e.judge);
    if (e.setting && e.setting !== settingId) {
      settingId = e.setting;
      forgetSetting();
      currentSetting(settingId).catch(() => {});  // warm the cache before the next turn
    }
    let line = e.say;
    // "Scalpel down" call-out, if the controller didn't word one.
    if (!line && e.type === "set_down" && e.item) line = `${e.item.replace(/_/g, " ")} down`;
    if (line) console.log(`[say] ${line}  (${e.type})`);
    speak(line, true);
    open?.onEvent(e);
  });
}

export async function handleTurn(heard: string, say: Say, signal?: AbortSignal): Promise<void> {
  console.log(`[heard] ${heard}`);
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
      if (e.type === "error") return e.step === "error" || (!!cmdId && e.command_id === cmdId);
      return !cmdId || !e.command_id || e.command_id === cmdId;
    };
    const finish = () => { clearTimeout(timer); if (open?.say === say) open = null; resolve(); };
    signal?.addEventListener("abort", finish);
    open = { say, onEvent: (e) => { seen.push(e); if (ends(e)) setTimeout(finish, 300); } };
    run(heard, (types, holdS, id) => {
      waitFor = types;
      cmdId = id;
      timer = setTimeout(finish, holdS * 1000);
      if (seen.some(ends)) setTimeout(finish, 300);
    }).catch((err) => {
      console.log(`[turn] ${(err as Error).message}`);
      say("I can't reach the arm controller.");
      finish();
    });
  });
  return done;
}

// POST /stop: skips the controller's queue and is always accepted. Nothing awaits Gemini, settings or state first.
async function stopNow(hold: Hold) {
  await io.postStop();
  console.log("[command] stop (POST /stop)");
  flushPending();
  hold(DONE.stop, 1.5);
}

async function run(heard: string, hold: Hold) {
  // Stop first, before Gemini or anything else that takes time.
  if (isStop(heard)) return stopNow(hold);
  flushPending();
  if (isEndCase(heard)) {
    speak("Closing the case. The summary is on its way to your phone.");
    hold([], 0.5);
    endCase().catch((e) => console.log(`[summary] ${(e as Error).message}`));
    return;
  }
  if (isTrayCheck(heard)) {
    speak(await voiceTrayCheck());
    hold([], 0.5);
    return;
  }
  // "start a bench case": a local phrase match, before Gemini (the Command actions don't include it).
  // Judge mode (from a short-lived cache of GET /state): no POST /setting.
  const asked = settingAsked(heard);
  if (asked) {
    // A tray voice doesn't offer (dental) gets its "not set up" line without asking for judge mode.
    speak(SETTING_IDS.includes(asked) && await io.judgeMode() ? JUDGE_LINE : await io.switchSetting(asked));
    hold([], 0.5);
    return;
  }
  // The controller's current setting, so Gemini only sees ids on this tray.
  const setting = await io.currentSetting(settingId);
  settingId = setting.id;
  // X6 clinic words, before Gemini: "call the hemostat a clamp" -> POST /alias, say its line. Not in judge mode.
  const taught = parseAlias(heard, setting);
  if (taught) {
    if (await io.judgeMode()) { speak(JUDGE_LINE); hold([], 0.5); return; }
    const r = await io.teach(taught.item, taught.alias);
    console.log(`[alias] ${taught.alias} -> ${taught.item}${r.ok ? "" : ` refused: ${r.reason}`}`);
    speak(r.say);
    hold([], 0.5);
    return;
  }
  const p = await io.parse(heard, setting);
  // Gemini heard a stop the local words missed ("hold on, freeze it up"): the POST /stop fast path, not the queue.
  if (p.action === "stop") { console.log(`[command] stop  (${p.via})`); return stopNow(hold); }
  const cmd = makeCommand(p.action, p.item, heard);
  console.log(`[command] ${cmd.action}${cmd.item ? " " + cmd.item : ""}  (${p.via})`);
  const reply = await io.postCommand(cmd);
  // Lines come from the events only; the reply's `say` repeats the event's.
  if (!reply.accepted) console.log(`[command] rejected: ${reply.reason}`);
  hold(reply.accepted ? DONE[cmd.action] : [], reply.accepted && DONE[cmd.action].length ? HOLD_S : 1, cmd.id);
}

function flushPending() {
  const lines = pending;
  pending = [];
  for (const l of lines) open?.say(l);
}
