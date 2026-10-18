// Words heard on the call -> one Command. "stop" and "got it" skip Gemini; everything else goes through it.
import { GoogleGenAI, Type } from "@google/genai";
import { GEMINI_API_KEY, GEMINI_MODEL, GEMINI_TIMEOUT_MS } from "./config.js";
import { ACTIONS, type Action } from "./controller.js";
import type { Setting } from "./settings.js";

const ai = GEMINI_API_KEY ? new GoogleGenAI({ apiKey: GEMINI_API_KEY }) : null;

export const isStop = (s: string) => /\b(stop|freeze|halt|hold it|abort)\b/i.test(s);
// "thanks got it", "okay, got it": an ok/thanks lead-in is allowed before the release words.
export const isGotIt = (s: string) =>
  /^\W*((ok(ay)?|thanks?( you)?)\W+)?(got it|i('ve)? got it|thanks?( you)?|release)\W*$/i.test(s.trim());
// "check the tray", "is the tray ready", "tray check": GET /tray_check, not a Command (the action enum stays as is).
export const isTrayCheck = (s: string) =>
  /\b(check (the |my |your )?tray|tray check|(is|are) (the |my )?tray (ready|set( up)?|good|complete|okay|ok)|tray (is )?ready\s*\?)/i.test(s);
// Reading (OCR pass): "read the count sheet", "what tray is this", "read the pack". Checked before the count and
// handover words ("count sheet" has "count" in it). "check the tray" stays a tray check (isTrayCheck, in turn.ts first).
const READS: { action: Action; re: RegExp }[] = [
  { action: "read_sheet", re: /\b(read|check|scan) (the |my |this |our )?(count )?sheet\b|\bcount sheet\b/ },
  { action: "read_tray", re: /\b(what|which) tray (is (this|that|it)|this is|am i on|are we on)\b|\b(read|scan) (the |this |that )?tray( s)? (tag|label|qr|code)\b|\bwhat does the tray (tag|label) say\b/ },
  { action: "read_pack", re: /\b(read|check|scan) (the |this |that |my )?(sterile )?pack( label| labels| tag)?\b|\b(is|are) (this|that|the|these) (sterile )?packs? (expired|out of date|in date|good|still good)\b|\bpack label\b/ },
];
export function readAction(heard: string): Action | null {
  const s = ` ${norm(heard)} `;
  return READS.find((r) => r.re.test(s))?.action ?? null;
}
export const isEndCase = (s: string) => /\b(end (of )?(the )?case|case (is )?(over|done|closed|complete)|close (out )?(the )?case|wrap (it )?up)\b/i.test(s);

export interface Parsed { action: Action; item: string | null; via: "local" | "gemini" }

// Caller turns handled and the last 50 Gemini parse times, for GET /health.
const geminiTimes: number[] = [];
let turnCount = 0;
export const countTurn = () => { turnCount++; };
export function parseStats() {
  const sorted = [...geminiTimes].sort((a, b) => a - b);
  return {
    turns: turnCount,
    gemini_ms: geminiTimes.length ? geminiTimes[geminiTimes.length - 1] : null,
    gemini_p50_ms: sorted.length ? sorted[Math.floor((sorted.length - 1) / 2)] : null,
  };
}

export async function parse(heard: string, setting: Setting): Promise<Parsed> {
  if (isStop(heard)) return { action: "stop", item: null, via: "local" };
  if (isGotIt(heard)) return { action: "got_it", item: null, via: "local" };
  const read = readAction(heard);
  if (read) return { action: read, item: null, via: "local" };
  if (ai) {
    const t0 = Date.now();
    try {
      const out = await geminiParse(heard, setting);
      geminiTimes.push(Date.now() - t0);
      if (geminiTimes.length > 50) geminiTimes.shift();
      return { ...out, via: "gemini" };
    } catch (e) { console.log(`[gemini] failed, using local match: ${(e as Error).message}`); }
  }
  return { ...localParse(heard, setting), via: "local" };
}

// Gemini's answer shape: a fixed list of actions and item ids, so it can never invent either.
export const commandSchema = (ids: string[]) => ({
  type: Type.OBJECT,
  properties: {
    action: { type: Type.STRING, enum: ACTIONS },
    item: { type: Type.STRING, enum: [...ids, "none"] },
  },
  required: ["action", "item"],
  propertyOrdering: ["action", "item"],
});

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
- read_sheet: read the paper count sheet in view ("read the count sheet", "check the count sheet")
- read_tray: read the tray tag or label to tell which tray this is ("what tray is this", "read the tray tag")
- read_pack: read a sterile pack label, lot or expiry date ("read the pack", "is this pack expired")
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
      responseSchema: commandSchema(ids),
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

// X6 clinic words: "call the hemostat a clamp", "clamp means the hemostat", "when I say clamp I mean the hemostat".
// The item side must name an item on this tray (name, id or alias); the other side is the new word.
// Each pattern gives [item side, word side], or for "call X Y" the whole "X Y" to split where X names an item.
const TEACH: { re: RegExp; order: "call" | "word_item" }[] = [
  { re: /^(?:please )?(?:let s |lets |we ll |we )?call (.+?)(?: from now on| please)?$/, order: "call" },
  { re: /^(?:when|if) (?:i|we) say (.+?) (?:i|we) mean (.+?)(?: from now on)?$/, order: "word_item" },
  // "means" only: "Y is the X" would teach "next up" from "next up is the hemostat".
  { re: /^(.+?) means (.+?)(?: from now on)?$/, order: "word_item" },
];
const NOT_WORDS = new Set(["it", "this", "that", "what", "which", "who", "here", "there", "everything", "nothing", "something"]);
const bare = (w: string) => w.replace(/^(the|a|an|my|our) /, "").trim();

export function parseAlias(heard: string, setting: Setting): { item: string; alias: string } | null {
  const s = norm(heard);
  const named = (w: string) => setting.items.find((it) =>
    [it.name, it.id.replace(/_/g, " "), ...it.aliases].map(norm).some((p) => p === w || `${p}s` === w));
  const ok = (item: string, word: string) => {
    const it = named(bare(item)), w = bare(word);
    return it && w && w.length <= 40 && !NOT_WORDS.has(w.split(" ")[0]) ? { item: it.id, alias: w } : null;
  };
  for (const { re, order } of TEACH) {
    const m = s.match(re);
    if (!m) continue;
    if (order === "word_item") { const r = ok(m[2], m[1]); if (r) return r; continue; }
    const parts = m[1].split(" ");  // "the mayo scissors shears": the longest item name on the left wins
    for (let i = parts.length - 1; i >= 1; i--) { const r = ok(parts.slice(0, i).join(" "), parts.slice(i).join(" ")); if (r) return r; }
  }
  return null;
}

export function localParse(heard: string, setting: Setting): { action: Action; item: string | null } {
  const s = ` ${norm(heard)} `;
  const read = readAction(heard);
  if (read) return { action: read, item: null };
  // "take back the mayo scissors" is a return, not a handover of the scissors.
  if (/\b(put (it|that|this) back|return|put back|take (it |that |this )?back)\b/.test(s)) return { action: "return", item: null };
  if (/\b(count|what s out|whats out|what is out|how many)\b/.test(s)) return { action: "count", item: null };
  let best: { id: string; len: number } | null = null;
  for (const it of setting.items) {
    for (const phrase of [it.name, it.id.replace(/_/g, " "), ...it.aliases]) {
      const p = norm(phrase);
      // Grouped: an empty alias used to match any " s " ("let's go" -> "let s go") through the plural test.
      if (p && (s.includes(` ${p} `) || s.includes(` ${p}s `))) {
        if (!best || p.length > best.len) best = { id: it.id, len: p.length };
      }
    }
  }
  return best ? { action: "handover", item: best.id } : { action: "unknown", item: null };
}
