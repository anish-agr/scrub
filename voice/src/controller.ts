// Talks to the controller (port 8000): POST /command, POST /stop, GET /state, GET /stats, WS /events.
import WebSocket from "ws";
import { randomUUID } from "node:crypto";
import { CONTROLLER_URL, JUDGE_TTL_MS } from "./config.js";

export type Action = "handover" | "return" | "count" | "stop" | "got_it" | "unknown";
export const ACTIONS: Action[] = ["handover", "return", "count", "stop", "got_it", "unknown"];

export interface Command {
  id: string; action: Action; item: string | null; heard: string; source: "voice"; t: number;
}
export interface CommandReply { accepted: boolean; reason: string | null; say: string | null }
export interface ScrubEvent {
  type: string; t: number; item?: string | null; step?: string | null; say?: string | null;
  command_id?: string | null; setting?: string | null; lighting?: string | null;
  request_to_hand_s?: number | null; retries?: number | null; out?: string[] | null;
  case_id?: string | null;  // optional, "<setting>-<unix start seconds>"
  error?: string | null; code?: number | null;  // on `error` events: the arm model's status (401, 409, 503), optional
  reason?: string | null; judge?: boolean | null;  // every event carries judge (optional)
}
export interface State {
  step: string; out: string[]; setting: string; t: number;
  out_camera?: string[] | null; case_id?: string | null;
  judge?: boolean | null;  // judge mode: the controller only takes handover, count, stop, got_it; refuses /alias
}

export function makeCommand(action: Action, item: string | null, heard: string): Command {
  return { id: randomUUID(), action, item, heard, source: "voice", t: Date.now() / 1000 };
}

async function call(method: string, path: string, body?: unknown, ms = 3000): Promise<any> {
  const res = await fetch(CONTROLLER_URL + path, {
    method,
    headers: body === undefined ? {} : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(ms),
  });
  if (!res.ok) throw new Error(`${method} ${path} -> ${res.status}`);
  return res.json();
}

export const postCommand = (c: Command): Promise<CommandReply> => call("POST", "/command", c);
export const postStop = (): Promise<{ accepted: boolean }> => call("POST", "/stop");
export const getSetting = (): Promise<any> => call("GET", "/setting");
export const getState = (): Promise<State> => call("GET", "/state");
// Judge mode from GET /state, cached for JUDGE_TTL_MS so a tray switch or a clinic word doesn't wait on it each time.
// Only asked on those paths, never on stop or handover. Controller down: false (its POST fails on its own).
export const JUDGE_LINE = "In judge mode I can hand you an instrument, read the count, or stop.";
let judgeCache: { on: boolean; at: number } | null = null;
export const forgetJudge = () => { judgeCache = null; };
// Every controller event carries `judge`, so the flag is usually fresh without asking GET /state.
export const noteJudge = (on: boolean, now = Date.now) => { judgeCache = { on, at: now() }; };
export async function judgeMode(get: () => Promise<State> = () => call("GET", "/state", undefined, 1000),
    ttlMs = JUDGE_TTL_MS, now = Date.now): Promise<boolean> {
  if (judgeCache && now() - judgeCache.at < ttlMs) return judgeCache.on;
  const st = await get().catch(() => null);
  if (!st) return false;
  judgeCache = { on: st.judge === true, at: now() };
  return judgeCache.on;
}
export const postRestock = (r: object): Promise<{ ok: boolean }> => call("POST", "/restock", r);
// X3: the controller asks vision (up to 3 s) and words the answer in `say`.
export interface TrayCheck {
  ok: boolean; say?: string | null; available?: boolean; setting?: string; label?: string; items?: string[];
  missing?: string[]; wrong_slot?: { item: string; in_slot_of?: string | null }[]; extra?: string[]; stale?: boolean | null;
}
export const getTrayCheck = (): Promise<TrayCheck> => call("GET", "/tray_check", undefined, 5000);
export const getStats = (): Promise<unknown> => call("GET", "/stats");
// POST /setting: the HTTP status (409 busy, 404 unknown id) and, on 200, the loaded setting file.
export async function postSetting(id: string): Promise<{ status: number; setting: any }> {
  const res = await fetch(CONTROLLER_URL + "/setting", { method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ setting: id }), signal: AbortSignal.timeout(3000) });
  return { status: res.status, setting: res.ok ? await res.json() : null };
}
// X6: teach a clinic word. Always 200: {"ok", "say", "reason"} (a conflict is ok: false with the line to say).
export interface AliasReply { ok: boolean; say: string; reason?: string | null }
export const postAlias = (item: string, alias: string): Promise<AliasReply> => call("POST", "/alias", { item, alias });
// For GET /health: is the controller up? Never throws.
export const controllerUp = (): Promise<boolean> =>
  fetch(CONTROLLER_URL + "/state", { signal: AbortSignal.timeout(1000) }).then((r) => r.ok, () => false);

// Follow WS /events forever, reconnecting every second if the controller is down.
export function followEvents(onEvent: (e: ScrubEvent) => void): void {
  const url = CONTROLLER_URL.replace(/^http/, "ws") + "/events";
  let warned = false;
  const connect = () => {
    const ws = new WebSocket(url);
    ws.on("open", () => { warned = false; console.log(`[events] connected ${url}`); });
    ws.on("message", (data) => {
      try { onEvent(JSON.parse(data.toString())); } catch { /* not JSON, skip */ }
    });
    ws.on("error", () => { if (!warned) console.log(`[events] can't reach ${url}, retrying`); warned = true; });
    ws.on("close", () => setTimeout(connect, 1000));
  };
  connect();
}
