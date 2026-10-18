// Words heard on the call -> one Command or a question. Known names and ambiguity are deterministic.
import { GoogleGenAI, ThinkingLevel, Type } from "@google/genai";
import { GEMINI_API_KEY, GEMINI_MODEL, GEMINI_TIMEOUT_MS, GEMINI_THINKING_LEVEL, GEMINI_MAX_OUTPUT_TOKENS } from "./config.js";
import { ACTIONS, type Action, type Candidate, type Clarification, type Instance } from "./controller.js";
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

export interface ParseResult { action: Action; item: string | null; instance?: Instance; clarify?: Clarification; confidence?: number; confirm?: boolean; question_id?: string }
export interface Parsed extends ParseResult { via: "local" | "gemini" }

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
  // Resolve known names and shared group words before a model can guess one of them.
  const local = localParse(heard, setting);
  if (local.action !== "unknown") return { ...local, via: "local" };
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
    action: { type: Type.STRING, enum: [...ACTIONS, "clarify"] },
    item: { type: Type.STRING, enum: [...ids, "none"] },
    candidates: { type: Type.ARRAY, items: { type: Type.STRING, enum: ids } },
    confidence: { type: Type.NUMBER },
    confirm: { type: Type.BOOLEAN },
  },
  required: ["action", "item"],
  propertyOrdering: ["action", "item"],
});

async function geminiParse(heard: string, setting: Setting): Promise<ParseResult> {
  const ids = setting.items.map((i) => i.id);
  const list = setting.items.map((i) => `- ${i.id}: ${i.name}${i.aliases.length ? ` (also: ${i.aliases.join(", ")})` : ""}${i.group ? `; group: ${i.group}` : ""}${i.variant ? `; variant: ${i.variant}` : ""}`).join("\n");
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
- unknown: anything else
Instruments on this tray:
${list}
item is the instrument id for handover, and for return when they name one, otherwise "none". If they ask for an instrument not on this tray, use unknown.
Never choose between plausible instruments. For ambiguity return candidates (ids from this tray only), item "none", action clarify.
confidence is 0 to 1. Set confirm true for an uncertain single interpretation; no movement occurs until the clinician says yes.
Clinician said: "${heard}"`;
  const res = await ai!.models.generateContent({
    model: GEMINI_MODEL,
    contents: prompt,
    config: {
      responseMimeType: "application/json",
      responseSchema: commandSchema(ids),
      temperature: 0,
      ...(GEMINI_THINKING_LEVEL ? { thinkingConfig: {
        thinkingLevel: ({ low: ThinkingLevel.LOW, medium: ThinkingLevel.MEDIUM, high: ThinkingLevel.HIGH })[GEMINI_THINKING_LEVEL as "low" | "medium" | "high"],
      } } : {}),
      ...(GEMINI_MAX_OUTPUT_TOKENS ? { maxOutputTokens: GEMINI_MAX_OUTPUT_TOKENS } : {}),
      abortSignal: AbortSignal.timeout(GEMINI_TIMEOUT_MS),
    },
  });
  return validateGemini(JSON.parse(res.text || "{}"), setting);
}

// Validate again at the trust boundary; even a malformed model response cannot introduce a tray item.
export function validateGemini(out: any, setting: Setting): ParseResult {
  const ids = setting.items.map((i) => i.id);
  const action: Action = out.action === "clarify" ? "handover" : ACTIONS.includes(out.action) ? out.action : "unknown";
  const candidates = Array.isArray(out.candidates) ? [...new Set<string>(out.candidates.filter((id: unknown) => typeof id === "string" && ids.includes(id)))] : [];
  if (action === "handover" && candidates.length > 1) return { action, item: null, clarify: whichOne(candidates.map((id) => candidateFor(setting, id))) };
  const item = ["handover", "return"].includes(action) && ids.includes(out.item) ? out.item : null;
  // Never send an item that isn't in the current setting.
  if (action === "handover" && !item) return { action: "unknown", item: null };
  const uncertain = item && (out.confirm === true || (typeof out.confidence === "number" && out.confidence < 0.8));
  return { action, item, ...(uncertain ? { confirm: true } : {}) };
}

export function candidateFor(setting: Setting, id: string): Candidate {
  const it = setting.items.find((i) => i.id === id)!;
  return { item: id, label: it.name, ...(it.group ? { group: it.group } : {}), ...(it.variant ? { variant: it.variant } : {}) };
}
export function whichOne(candidates: Candidate[]): Clarification {
  const group = candidates[0]?.group;
  const shared = group && candidates.every((c) => c.group === group && c.variant);
  return { say: `Which ${shared ? group : "one"}: ${candidates.map((c) => shared ? c.variant : c.label || c.variant || c.item || c.id).join(" or ")}?`, candidates };
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

export function localParse(heard: string, setting: Setting): ParseResult {
  if (isStop(heard)) return { action: "stop", item: null };
  if (isGotIt(heard)) return { action: "got_it", item: null };
  const s = ` ${norm(heard)} `;
  const read = readAction(heard);
  if (read) return { action: read, item: null };
  // "take back the mayo scissors" is a return of the scissors (item named), not a handover; "put it back": item null.
  const isReturn = /\b(put( [a-z ]+)? back|return|take( [a-z ]+)? back)\b/.test(s);
  if (!isReturn && /\b(count|what s out|whats out|what is out|how many)\b/.test(s)) return { action: "count", item: null };
  const action: Action = isReturn ? "return" : "handover";
  const matches: { id: string; len: number }[] = [];
  for (const it of setting.items) {
    let len = 0;
    for (const phrase of [it.name, it.id.replace(/_/g, " "), ...it.aliases, it.group || ""]) {
      const p = norm(phrase);
      // Grouped: an empty alias used to match any " s " ("let's go" -> "let s go") through the plural test.
      if (p && (s.includes(` ${p} `) || s.includes(` ${p}s `))) {
        len = Math.max(len, p.length);
      }
    }
    if (len) matches.push({ id: it.id, len });
  }
  const max = Math.max(...matches.map((m) => m.len));
  let best = matches.filter((m) => /\bor\b/.test(s) || m.len === max);
  const variants = best.filter((m) => { const v = setting.items.find((i) => i.id === m.id)?.variant; return v && s.includes(` ${norm(v)} `); });
  if (variants.length) best = variants;
  if (best.length > 1) return { action, item: null, clarify: whichOne(best.map((m) => candidateFor(setting, m.id))) };
  const side = s.match(/\b(left|right|closest)\b/)?.[1] as Instance["side"];
  return best.length ? { action, item: best[0].id, ...(side ? { instance: { side } } : {}) } : { action: isReturn ? "return" : "unknown", item: null };
}
