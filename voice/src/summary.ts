// End-of-case summary: Gemini writes it from the ledger stats and this case's events, Photon texts it.
import { GoogleGenAI } from "@google/genai";
import { Spectrum } from "spectrum-ts";
import { imessage } from "spectrum-ts/providers/imessage";
import { GEMINI_API_KEY, GEMINI_MODEL, PHOTON_PROJECT_ID, PHOTON_SECRET, PUBLIC_URL, SUMMARY_TO } from "./config.js";
import { getState, getStats, type ScrubEvent } from "./controller.js";

const ai = GEMINI_API_KEY ? new GoogleGenAI({ apiKey: GEMINI_API_KEY }) : null;

let caseEvents: ScrubEvent[] = [];
let caseStart = Date.now() / 1000;
let caseId: string | null = null;  // the controller's case_id ("<setting>-<unix start>"), when events carry one
let closedAt = 0;                  // last time the voice side closed a case ("end of case")
let caller = "";
// The controller's `out` from the newest event, kept across "end of case". Bug: a second summary in the same
// case (or one after a voice restart) had no events yet and said "everything is back" with items still out.
let lastOut: string[] | null = null;

// A Photon call that never answers fails after this, so a summary or a reply never hangs (ms).
const SEND_MS = 15_000;
export function withTimeout<T>(p: Promise<T>, ms: number, what: string): Promise<T> {
  let timer: NodeJS.Timeout | undefined;
  const late = new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error(`${what} timed out`)), ms); });
  return Promise.race([p, late]).finally(() => clearTimeout(timer));
}
// A day of step events stays well under this; past it the oldest go (the counts read `out` from the newest).
const MAX_EVENTS = 5000;

// Events with a new case_id start a new case. Without case_id: one case until "end of case" (newCase).
export function recordEvent(e: ScrubEvent) {
  if (e.case_id && e.case_id !== caseId) {
    const start = Number(e.case_id.match(/-(\d+(\.\d+)?)$/)?.[1]) || e.t;
    // A changed case_id is a new case at the controller. The first one seen may predate a voice "end of case".
    caseStart = caseId ? start : Math.max(start, closedAt);
    if (caseId) caseEvents = [];
    caseId = e.case_id;
  }
  caseEvents.push(e);
  if (Array.isArray(e.out)) lastOut = e.out;
  if (caseEvents.length > MAX_EVENTS) caseEvents.splice(0, caseEvents.length - MAX_EVENTS);
}
export const setCaller = (phone: string) => { if (phone && phone !== caller) { caller = phone; console.log(`[case] caller ${phone}`); } };

// Starts a new case: forget the events so far.
export function newCase() { caseEvents = []; caseStart = closedAt = Date.now() / 1000; }

// "2:41 PM" in the server's local time.
export const clock = (t: number) =>
  new Date(t * 1000).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }).replace(/\s/g, " ");

// What happened this case, counted from the events. Also the fallback text if Gemini is down.
// Per command: a missed before the pick is a retry if the pick then worked, else a failed request;
// a missed after the pick (out of reach) is a failed request. "Passed" means released into a hand, or a
// planned sharp set-down (it carries request_to_hand_s). An unplanned set-down (no pull, no hand) is counted apart.
export function caseFacts() {
  const passed: Record<string, number> = {};
  const setDown: Record<string, number> = {};
  const cmds = new Map<string, { ok: boolean; pre: number; post: number }>();
  let returned = 0, stops = 0, failed = 0, retried = 0;
  const times: number[] = [];
  let reported: string[] | null = null;  // the controller's own out list, on every event
  let derived: string[] = [];
  const used: string[] = [];  // items passed or set down, in first-use order
  let setting: string | null = caseId?.replace(/-[\d.]+$/, "") || null;
  const add = (id: string) => { derived = [...derived.filter((i) => i !== id), id]; if (!used.includes(id)) used.push(id); };
  for (const e of caseEvents) {
    if (Array.isArray(e.out)) reported = e.out;
    if (e.setting) setting = e.setting;
    const c = cmds.get(e.command_id || "") || { ok: false, pre: 0, post: 0 };
    cmds.set(e.command_id || "", c);
    if (e.type === "picked" || e.type === "returned") c.ok = true;
    if (e.type === "missed") { if (c.ok) c.post++; else c.pre++; }
    if (e.type === "handed" && e.request_to_hand_s != null) times.push(e.request_to_hand_s);
    if (e.type === "released" && e.item) { passed[e.item] = (passed[e.item] || 0) + 1; add(e.item); }
    if (e.type === "set_down" && e.item) {
      add(e.item);
      if (e.request_to_hand_s != null) { passed[e.item] = (passed[e.item] || 0) + 1; times.push(e.request_to_hand_s); }
      else setDown[e.item] = (setDown[e.item] || 0) + 1;
    }
    if (e.type === "returned") { returned++; if (e.item) derived = derived.filter((i) => i !== e.item); }
    if (e.type === "stopped") stops++;
  }
  for (const c of cmds.values()) {
    if (c.pre && c.ok) retried++;
    if ((c.pre && !c.ok) || c.post) failed++;
  }
  times.sort((a, b) => a - b);
  const mid = Math.floor(times.length / 2);
  const median = !times.length ? null : times.length % 2 ? times[mid] : (times[mid - 1] + times[mid]) / 2;
  return {
    case_id: caseId, setting, started: clock(caseStart), used,
    minutes: Math.round((Date.now() / 1000 - caseStart) / 60), still_out: reported ?? lastOut ?? derived, passed,
    set_down_at_safe_spot: setDown, returned, failed_requests: failed, picks_retried: retried, stops,
    median_request_to_hand_s: median,
  };
}

const name = (id: string) => id.replace(/_/g, " ");
const list = (r: Record<string, number>) => Object.entries(r).map(([i, n]) => `${name(i)} x${n}`).join(", ");

export function templateSummary(f: ReturnType<typeof caseFacts>): string {
  const lines = [
    f.still_out.length ? `Still out: ${f.still_out.map(name).join(", ")}. Check the count.` : "Count: everything is back on the tray.",
    `Scrub case: ${f.setting ?? "case"}, started ${f.started} (${f.minutes} min)`,
    `Used: ${f.used.map(name).join(", ") || "none"}`,
    `Passed: ${list(f.passed) || "none"}`,
  ];
  if (Object.keys(f.set_down_at_safe_spot).length) lines.push(`Set at the safe spot: ${list(f.set_down_at_safe_spot)}`);
  lines.push(`Returned: ${f.returned}. Failed requests: ${f.failed_requests}. Retried picks: ${f.picks_retried}. Stops: ${f.stops}.`);
  if (f.median_request_to_hand_s != null) lines.push(`Median request to hand: ${f.median_request_to_hand_s.toFixed(1)} s`);
  return lines.join("\n");
}

// Item names instead of ids, so the text says "mayo scissors", not "mayo_scissors".
const renamed = (r: Record<string, number>) => Object.fromEntries(Object.entries(r).map(([i, n]) => [name(i), n]));
const readable = (f: ReturnType<typeof caseFacts>) =>
  ({ ...f, used: f.used.map(name), still_out: f.still_out.map(name), passed: renamed(f.passed), set_down_at_safe_spot: renamed(f.set_down_at_safe_spot) });

export async function writeSummary(): Promise<string> {
  const facts = caseFacts();
  // The count is the safety line: ask the controller now, so it is never older than the last event.
  const st = await getState().catch(() => null);
  if (st && Array.isArray(st.out)) facts.still_out = st.out;
  if (st && !facts.setting) facts.setting = st.setting;  // no events yet (voice just restarted)
  if (!ai) return templateSummary(facts);
  const stats = await getStats().catch(() => null);
  try {
    const res = await ai.models.generateContent({
      model: GEMINI_MODEL,
      contents: `Write the end-of-case text message from Scrub, a robot arm that passed instruments to a clinician.
Plain text, no markdown, under 400 characters, short lines. Start with the count: name every item still out, or say everything is back on the tray.
Then name the case: the setting and its start time (as given, e.g. "2:41 PM"). Then the items used, what was passed, anything set at the safe spot, failed requests and stops, and the median request-to-hand time if known.
Use only the numbers below. No greetings or sign-off.
This case: ${JSON.stringify(readable(facts))}
All-time ledger stats (may be null): ${JSON.stringify(stats)}`,
      config: { temperature: 0.2, abortSignal: AbortSignal.timeout(8000) },  // past this, the template
    });
    const text = (res.text || "").trim();
    if (text) return text;
  } catch (e) {
    console.log(`[gemini] summary failed, using template: ${(e as Error).message}`);
  }
  return templateSummary(facts);
}

let photon: ReturnType<typeof Spectrum> | null = null;
export const photonConfigured = () => !!(PHOTON_PROJECT_ID && PHOTON_SECRET);
// Whether an end-of-case text can go out at all (Photon keys and someone to send it to).
export const canText = () => photonConfigured() && !!(caller || SUMMARY_TO);

// One Spectrum instance for the summary text and the inbound texts (texts.ts), so both use the same thread.
export async function getPhoton() {
  // Cache the promise, so the text listener and a summary starting together share one connection.
  photon ||= Spectrum({ projectId: PHOTON_PROJECT_ID, projectSecret: PHOTON_SECRET, providers: [imessage.config()] });
  return photon.catch((e) => { photon = null; throw e; });
}

export type Send = (to: string, text: string) => Promise<boolean>;

async function sendText(to: string, text: string): Promise<boolean> {
  if (!photonConfigured()) { console.log("[photon] no PHOTON_PROJECT_ID / PHOTON_API_KEY, not sending"); return false; }
  const space = await withTimeout(getPhoton().then((app) => imessage(app).space.create(to)), SEND_MS, "Photon connect")
    .catch((e) => { photon = null; throw e; });  // a connect that hung is not reused for the next text
  await withTimeout(space.send(text), SEND_MS, "Photon send");
  return true;
}

// Write the summary and start a new case. A "summary" text (texts.ts) gets it as the reply on its own thread.
export async function closeCase(write: () => Promise<string> = writeSummary): Promise<string> {
  const text = await write();
  console.log(`[summary]\n${text}`);
  newCase();
  return text;
}

// "Case replay: <SCRUB_PUBLIC_URL>/case.html?id=<case_id> (the ledger public page)", or null with no public URL or no case_id.
export const caseLink = (id: string | null | undefined, base = PUBLIC_URL): string | null =>
  base && id ? `Case replay: ${base.replace(/\/+$/, "")}/case.html?id=${encodeURIComponent(id)}` : null;

// closeCase for a "summary" text: the case link (if any) on its own line after the summary.
export async function closeCaseWithLink(write: () => Promise<string> = writeSummary, base = PUBLIC_URL): Promise<string> {
  const link = caseLink(caseId, base);
  const text = await closeCase(write);
  return link ? `${text}\n\n${link}` : text;
}

// Write the summary, text it to the caller's thread, start a new case. Then a second short text with the case link.
export async function endCase(send: Send = sendText, write: () => Promise<string> = writeSummary, base = PUBLIC_URL):
    Promise<{ text: string; to: string; sent: boolean; error?: string; link?: string }> {
  const to = caller || SUMMARY_TO;
  const link = caseLink(caseId, base);
  const text = await closeCase(write);
  let sent = false, error: string | undefined;
  if (!to) error = "no caller id and no PHOTON_SUMMARY_TO";
  else {
    try { sent = await send(to, text); } catch (e) { error = (e as Error).message; }
  }
  console.log(sent ? `[photon] texted ${to}` : `[photon] not sent: ${error ?? "no credentials"}`);
  if (sent && link) {
    try { await send(to, link); console.log(`[photon] ${link}`); }
    catch (e) { console.log(`[photon] case link not sent: ${(e as Error).message}`); }
  }
  return { text, to, sent, error, ...(link ? { link } : {}) };
}

// A short text to the caller's thread (the X3 "tray ready" text): same sender and thread as the summary.
export async function textCaller(text: string, send: Send = sendText): Promise<boolean> {
  const to = caller || SUMMARY_TO;
  let sent = false, error = "no caller id and no PHOTON_SUMMARY_TO";
  if (to) {
    try { sent = await send(to, text); error = "no credentials"; } catch (e) { error = (e as Error).message; }
  }
  console.log(sent ? `[photon] texted ${to}: ${text}` : `[photon] not sent: ${error}`);
  return sent;
}
