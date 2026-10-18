// Words heard on the call -> one Command. "stop" and "got it" skip Gemini; everything else goes through it.
import { GoogleGenAI, Type } from "@google/genai";
import { GEMINI_API_KEY, GEMINI_MODEL, GEMINI_TIMEOUT_MS } from "./config.js";
import { ACTIONS, type Action } from "./controller.js";
import type { Setting } from "./settings.js";

const ai = GEMINI_API_KEY ? new GoogleGenAI({ apiKey: GEMINI_API_KEY }) : null;

export const isStop = (s: string) => /\b(stop|freeze|halt|hold it|abort)\b/i.test(s);
export const isGotIt = (s: string) => /^\W*(got it|i('ve)? got it|thanks?( you)?|okay got it|release)\W*$/i.test(s.trim());
export const isEndCase = (s: string) => /\b(end (of )?(the )?case|case (is )?(over|done|closed|complete)|close (out )?(the )?case|wrap (it )?up)\b/i.test(s);

export interface Parsed { action: Action; item: string | null; via: "local" | "gemini" }

export async function parse(heard: string, setting: Setting): Promise<Parsed> {
  if (isStop(heard)) return { action: "stop", item: null, via: "local" };
  if (isGotIt(heard)) return { action: "got_it", item: null, via: "local" };
  if (ai) {
    try { return { ...(await geminiParse(heard, setting)), via: "gemini" }; }
    catch (e) { console.log(`[gemini] failed, using local match: ${(e as Error).message}`); }
  }
  return { ...localParse(heard, setting), via: "local" };
}

async function geminiParse(heard: string, setting: Setting): Promise<{ action: Action; item: string | null }> {
  const ids = setting.items.map((i) => i.id);
  const list = setting.items.map((i) => `- ${i.id}: ${i.name}${i.aliases.length ? ` (also: ${i.aliases.join(", ")})` : ""}`).join("\n");
  const prompt = `You are the ears of Scrub, a robot arm that passes instruments in a ${setting.label.toLowerCase()}.
Turn what the clinician said into one command.
Actions:
- handover: they want an instrument brought to them
- return: put the instrument in the return spot back in its slot ("put it back", "return that")
- count: they want to know what's out or the count
- got_it: they have the instrument, release it
- stop: stop moving now
- unknown: anything else, or you can't tell which instrument
Instruments on this tray:
${list}
item is the instrument id for handover, otherwise "none". If they ask for an instrument not on this tray, use unknown.
Clinician said: "${heard}"`;
  const res = await ai!.models.generateContent({
    model: GEMINI_MODEL,
    contents: prompt,
    config: {
      responseMimeType: "application/json",
      responseSchema: {
        type: Type.OBJECT,
        properties: {
          action: { type: Type.STRING, enum: ACTIONS },
          item: { type: Type.STRING, enum: [...ids, "none"] },
        },
        required: ["action", "item"],
        propertyOrdering: ["action", "item"],
      },
      temperature: 0,
      abortSignal: AbortSignal.timeout(GEMINI_TIMEOUT_MS),
    },
  });
  const out = JSON.parse(res.text || "{}");
  const action: Action = ACTIONS.includes(out.action) ? out.action : "unknown";
  const item = action === "handover" && ids.includes(out.item) ? out.item : null;
  // Never send an item that isn't in the current setting.
  return action === "handover" && !item ? { action: "unknown", item: null } : { action, item };
}

// No key or Gemini down: match names and aliases. Longest phrase wins ("needle nose" over "pliers").
// Lowercase, punctuation to spaces ("needle-nose" -> "needle nose"), single spaces.
const norm = (x: string) => x.toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();

export function localParse(heard: string, setting: Setting): { action: Action; item: string | null } {
  const s = ` ${norm(heard)} `;
  if (/\b(put (it|that|this) back|return|put back)\b/.test(s)) return { action: "return", item: null };
  if (/\b(count|what s out|whats out|what is out|how many)\b/.test(s)) return { action: "count", item: null };
  let best: { id: string; len: number } | null = null;
  for (const it of setting.items) {
    for (const phrase of [it.name, it.id.replace(/_/g, " "), ...it.aliases]) {
      const p = norm(phrase);
      if (p && s.includes(` ${p} `) || s.includes(` ${p}s `)) {
        if (!best || p.length > best.len) best = { id: it.id, len: p.length };
      }
    }
  }
  return best ? { action: "handover", item: best.id } : { action: "unknown", item: null };
}
