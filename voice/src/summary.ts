// End-of-case summary: Gemini writes it from the ledger stats and this case's events, Photon texts it.
import { GoogleGenAI } from "@google/genai";
import { Spectrum } from "spectrum-ts";
import { imessage } from "spectrum-ts/providers/imessage";
import { GEMINI_API_KEY, GEMINI_MODEL, PHOTON_PROJECT_ID, PHOTON_SECRET, SUMMARY_TO } from "./config.js";
import { getStats, type ScrubEvent } from "./controller.js";

const ai = GEMINI_API_KEY ? new GoogleGenAI({ apiKey: GEMINI_API_KEY }) : null;

let caseEvents: ScrubEvent[] = [];
let caseStart = Date.now() / 1000;
let caller = "";

export const recordEvent = (e: ScrubEvent) => { caseEvents.push(e); };
export const setCaller = (phone: string) => { if (phone && phone !== caller) { caller = phone; console.log(`[case] caller ${phone}`); } };

// What happened this case, counted from the events. Also the fallback text if Gemini is down.
export function caseFacts() {
  const handed: Record<string, number> = {};
  let missed = 0, returned = 0, stops = 0;
  const times: number[] = [];
  let out: string[] = [];
  for (const e of caseEvents) {
    if ((e.type === "handed" || e.type === "set_down") && e.item) {
      handed[e.item] = (handed[e.item] || 0) + 1;
      if (e.request_to_hand_s != null) times.push(e.request_to_hand_s);
      out = [...out.filter((i) => i !== e.item), e.item];
    }
    if (e.type === "returned" && e.item) { returned++; out = out.filter((i) => i !== e.item); }
    if (e.type === "missed") missed++;
    if (e.type === "stopped") stops++;
  }
  times.sort((a, b) => a - b);
  const median = times.length ? times[Math.floor(times.length / 2)] : null;
  return { minutes: Math.round((Date.now() / 1000 - caseStart) / 60), handed, returned, missed, stops, still_out: out, median_request_to_hand_s: median };
}

const name = (id: string) => id.replace(/_/g, " ");

function templateSummary(f: ReturnType<typeof caseFacts>): string {
  const passes = Object.entries(f.handed).map(([i, n]) => `${name(i)} x${n}`).join(", ") || "none";
  const lines = [
    `Scrub case summary (${f.minutes} min)`,
    `Passed: ${passes}`,
    `Returned: ${f.returned}. Missed picks: ${f.missed}. Stops: ${f.stops}.`,
    f.still_out.length ? `Still out: ${f.still_out.map(name).join(", ")}. Check the count.` : "Count: everything is back on the tray.",
  ];
  if (f.median_request_to_hand_s != null) lines.push(`Median request to hand: ${f.median_request_to_hand_s.toFixed(1)} s`);
  return lines.join("\n");
}

export async function writeSummary(): Promise<string> {
  const facts = caseFacts();
  if (!ai) return templateSummary(facts);
  const stats = await getStats().catch(() => null);
  try {
    const res = await ai.models.generateContent({
      model: GEMINI_MODEL,
      contents: `Write the end-of-case text message from Scrub, a robot arm that passed instruments to a clinician.
Plain text, no markdown, under 400 characters, short lines. Say what was passed, what's still out (the count must be clear;
if something is still out, say so first), misses or stops, and the median request-to-hand time if known. No greetings or sign-off.
This case: ${JSON.stringify(facts)}
All-time ledger stats (may be null): ${JSON.stringify(stats)}`,
      config: { temperature: 0.2 },
    });
    const text = (res.text || "").trim();
    if (text) return text;
  } catch (e) {
    console.log(`[gemini] summary failed, using template: ${(e as Error).message}`);
  }
  return templateSummary(facts);
}

let photon: Awaited<ReturnType<typeof Spectrum>> | null = null;

async function sendText(to: string, text: string): Promise<boolean> {
  if (!PHOTON_PROJECT_ID || !PHOTON_SECRET) { console.log("[photon] no PHOTON_PROJECT_ID / PHOTON_API_KEY, not sending"); return false; }
  photon ||= await Spectrum({ projectId: PHOTON_PROJECT_ID, projectSecret: PHOTON_SECRET, providers: [imessage.config()] });
  const space = await imessage(photon).space.create(to);
  await space.send(text);
  return true;
}

// Write the summary, text it to the caller's thread, start a new case.
export async function endCase(): Promise<{ text: string; to: string; sent: boolean; error?: string }> {
  const text = await writeSummary();
  const to = caller || SUMMARY_TO;
  console.log(`[summary]\n${text}`);
  let sent = false, error: string | undefined;
  if (!to) error = "no caller id and no PHOTON_SUMMARY_TO";
  else {
    try { sent = await sendText(to, text); } catch (e) { error = (e as Error).message; }
  }
  console.log(sent ? `[photon] texted ${to}` : `[photon] not sent: ${error ?? "no credentials"}`);
  caseEvents = [];
  caseStart = Date.now() / 1000;
  return { text, to, sent, error };
}
