// One caller turn: what was heard -> controller -> the lines Scrub speaks back.
// Event `say` lines stream into the open reply. Lines that arrive with no reply open wait for the next turn.
import { HOLD_S } from "./config.js";
import { followEvents, makeCommand, postCommand, postStop, type ScrubEvent } from "./controller.js";
import { isEndCase, isStop, isTrayCheck, parse } from "./parse.js";
import { currentSetting, forgetSetting } from "./settings.js";
import { endCase, recordEvent } from "./summary.js";
import { voiceTrayCheck } from "./tray.js";

type Say = (line: string) => void;

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

function speak(line: string | null | undefined) {
  if (!line) return;
  const now = Date.now();
  if (line === lastLine.text && now - lastLine.t < 3000) return; // same line from /command and the event
  lastLine = { text: line, t: now };
  if (open) open.say(line); else pending.push(line);
}

export function startEvents() {
  followEvents((e) => {
    recordEvent(e);
    if (e.setting && e.setting !== settingId) {
      settingId = e.setting;
      forgetSetting();
      currentSetting(settingId).catch(() => {});  // warm the cache before the next turn
    }
    let line = e.say;
    // "Scalpel down" call-out, if the controller didn't word one.
    if (!line && e.type === "set_down" && e.item) line = `${e.item.replace(/_/g, " ")} down`;
    if (line) console.log(`[say] ${line}  (${e.type})`);
    speak(line);
    open?.onEvent(e);
  });
}

export async function handleTurn(heard: string, say: Say, signal?: AbortSignal): Promise<void> {
  console.log(`[heard] ${heard}`);
  const done = new Promise<void>((resolve) => {
    let timer: NodeJS.Timeout | undefined;
    let waitFor: string[] = [];
    const finish = () => { clearTimeout(timer); if (open?.say === say) open = null; resolve(); };
    signal?.addEventListener("abort", finish);
    open = { say, onEvent: (e) => { if (waitFor.includes(e.type)) setTimeout(finish, 300); } };
    run(heard, (types, holdS) => {
      waitFor = types;
      timer = setTimeout(finish, holdS * 1000);
    }).catch((err) => {
      console.log(`[turn] ${(err as Error).message}`);
      say("I can't reach the arm controller.");
      finish();
    });
  });
  return done;
}

async function run(heard: string, hold: (types: string[], holdS: number) => void) {
  // Stop first, before Gemini or anything else that takes time.
  if (isStop(heard)) {
    await postStop();
    console.log("[command] stop (POST /stop)");
    flushPending();
    hold(DONE.stop, 1.5);
    return;
  }
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
  // The controller's current setting, so Gemini only sees ids on this tray.
  const setting = await currentSetting(settingId);
  settingId = setting.id;
  const p = await parse(heard, setting);
  const cmd = makeCommand(p.action, p.item, heard);
  console.log(`[command] ${cmd.action}${cmd.item ? " " + cmd.item : ""}  (${p.via})`);
  const reply = await postCommand(cmd);
  // Lines come from the events only; the reply's `say` repeats the event's.
  if (!reply.accepted) console.log(`[command] rejected: ${reply.reason}`);
  hold(reply.accepted ? DONE[cmd.action] : [], reply.accepted && DONE[cmd.action].length ? HOLD_S : 1);
}

function flushPending() {
  const lines = pending;
  pending = [];
  for (const l of lines) open?.say(l);
}
