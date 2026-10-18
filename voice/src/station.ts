// Bridge to the recording station's arm (explore/station, :8090) when STATION_URL is set: a spoken handover
// runs that instrument's averaged demo replay, "let go" / "got it" opens the jaw, "stop" stops the run.
// The controller still gets every command as before; if it is not running, the station alone answers.
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { REPO_DIR, STATION_URL } from "./config.js";
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
    if (c.action === "stop") return (await p("stop")).msg;
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

export const stationOn = () => Boolean(STATION_URL);
export const STATION_ACTIONS = new Set(["handover", "got_it", "let_go", "stop"]);

export function stationSay(c: Command): string {
  if (c.action === "handover") return `Getting the ${(c.item || "instrument").replace(/_/g, " ")}.`;
  if (c.action === "stop") return "Stopped.";
  return "Letting go.";
}
