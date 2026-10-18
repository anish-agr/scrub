// Bridge to the recording station's arm (explore/station, :8090) when STATION_URL is set: a spoken handover
// runs that instrument's averaged demo replay, "let go" / "got it" opens the jaw, "stop" stops the run.
// The controller still gets every command as before; if it is not running, the station alone answers.
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { REPO_DIR, STATION_SETTING, STATION_URL } from "./config.js";
import type { Command } from "./controller.js";

type Post = (action: string, extra?: Record<string, unknown>) => Promise<any>;
type Get = () => Promise<any>;

async function post(action: string, extra: Record<string, unknown> = {}): Promise<any> {
  const res = await fetch(STATION_URL + "/control", {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ action, ...extra }), signal: AbortSignal.timeout(3000),
  });
  return res.json();
}
const status: Get = async () => (await fetch(STATION_URL + "/status", { signal: AbortSignal.timeout(2000) })).json();

// The settings instruction the demos were recorded under ("pick the hemostat"), else "pick the <name>".
export function taskFor(item: string, dir = path.join(REPO_DIR, "settings")): string {
  try {
    for (const f of readdirSync(dir).filter((n) => n.endsWith(".json") && !n.includes(".local."))) {
      const s = JSON.parse(readFileSync(path.join(dir, f), "utf8"));
      const it = (s.items || []).find((i: any) => i.id === item);
      if (it?.pick_instruction) return it.pick_instruction;
    }
  } catch { /* fall through */ }
  return `pick the ${item.replace(/_/g, " ")}`;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// What the station did, as a short line for the log; never throws.
export async function stationCommand(c: Command, p: Post = post, get: Get = status, waitMs = 6000): Promise<string> {
  try {
    if (c.action === "stop") return (await p("pause")).msg;  // freeze where it is; "continue" resumes
    if (c.action === "got_it" || c.action === "let_go") return (await p("release")).msg;
    if (c.action !== "handover" || !c.item) return "not a station command";
    let s = await get();
    if (s.state === "running") return "busy: a run is already going";
    if (s.state !== "idle") {  // parked / off: wake in place, wait until it follows (idle)
      await p("wake");
      const t0 = Date.now();
      while (Date.now() - t0 < waitMs) {
        await sleep(250);
        s = await get();
        if (s.state === "idle") break;
      }
      if (s.state !== "idle") return `arm not ready (${s.state})`;
    }
    const r = await p("run", { driver: "autopick", args: { mode: "average", task: taskFor(c.item) } });
    return r.msg;
  } catch (e) {
    return `station unreachable (${(e as Error).message})`;
  }
}

// Fast path for the spoken reply: stop / let go are quick station calls (awaited); a handover only checks the
// station isn't busy (one local GET), then wakes + starts the run in the background so Scrub answers at once.
export async function stationFast(c: Command, p: Post = post, get: Get = status,
  later: (m: string) => void = () => {}): Promise<string> {
  if (c.action !== "handover") return stationCommand(c, p, get);
  try {
    const s = await get();
    if (s.state === "running") return "busy: a run is already going";
  } catch (e) {
    return `station unreachable (${(e as Error).message})`;
  }
  stationCommand(c, p, get).then(later);
  return "starting";
}

// Arm control words besides stop: kill (motors off now), return to home (home, motors off), continue (resume a
// frozen run). Checked before any parsing. Returns the spoken line, or null when the words aren't one of these.
const KILL = /\b(kill( it| the (arm|motors?))?|power off|motors off|turn (it|the arm) off)\b/i;
const HOME = /\b(return (to )?home|go (back )?home|back (to )?home|home position)\b/i;
const CONTINUE = /\b(continue|resume|keep going|carry on|go on|go ahead)\b/i;
export async function stationPhrase(heard: string, p: Post = post): Promise<{ say: string; msg: string } | null> {
  const want = KILL.test(heard) ? "kill" : HOME.test(heard) ? "home" : CONTINUE.test(heard) ? "resume" : null;
  if (!want) return null;
  let msg: string;
  try { msg = (await p(want)).msg || ""; } catch (e) { return { say: "I can't reach the arm.", msg: String(e) }; }
  const ok = !/nothing is running|not while|refused|unknown/i.test(msg);
  const say = want === "kill" ? "Motors off." : want === "home" ? "Going home." : ok ? "Continuing." : "Nothing to continue.";
  return { say, msg };
}

// On when STATION_URL is set, or (unset) whenever a station answers on this Mac: checked every 2 s, so a
// rewritten .env or a station started later never leaves voice talking only to the sim controller.
// Calls and texts (the Photon line) drive the station's real arm only while its page has the Photon tab open
// (photon_tab in /status, a heartbeat from that tab). Otherwise they go to the controller as before.
let reachable = false;
async function probe() {
  try {
    const r = await fetch(STATION_URL + "/status", { signal: AbortSignal.timeout(600) });
    reachable = r.ok && Boolean((await r.json()).photon_tab);
  } catch { reachable = false; }
}
if (STATION_SETTING !== "off" && !process.env.VOICE_NO_KEYS) { void probe(); setInterval(probe, 2000).unref(); }
export const stationOn = () => STATION_SETTING !== "off" && reachable;

// One line of the conversation to the Photon tab's feed (fire and forget, never throws).
export function photonLog(who: string, text: string | null | undefined): void {
  if (!text || !stationOn()) return;
  fetch(STATION_URL + "/control", { method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ action: "photon_log", who, text }), signal: AbortSignal.timeout(1500) }).catch(() => {});
}
export const STATION_ACTIONS = new Set(["handover", "got_it", "let_go", "stop"]);

export function stationSay(c: Command): string {
  if (c.action === "handover") return `Getting the ${(c.item || "instrument").replace(/_/g, " ")}.`;
  if (c.action === "stop") return "Stopped.";
  return "Letting go.";
}

// The spoken reply for what the station did (its own message), short.
export function stationReply(c: Command, msg: string): { accepted: boolean; reason: string | null; say: string | null } {
  const m = (msg || "").toLowerCase();
  if (m.includes("unreachable")) return { accepted: false, reason: msg, say: "I can't reach the arm." };
  if (m.includes("busy") || m.includes("not while")) return { accepted: false, reason: msg, say: "I'm already moving." };
  if (m.includes("not ready")) return { accepted: false, reason: msg, say: "The arm isn't ready." };
  if (m.includes("nothing is being held")) return { accepted: false, reason: msg, say: "I'm not holding anything." };
  if (m.includes("no usable demos")) return { accepted: false, reason: msg, say: "I haven't learned that one yet." };
  return { accepted: true, reason: null, say: stationSay(c) };
}
