// Texts in on the Photon thread: restock, "what's out?", "summary". Gemini parses (structured output), local match if not.
// Restocks go to the ledger via the controller's POST /restock, else voice/restocks.jsonl.
import { appendFileSync } from "node:fs";
import path from "node:path";
import { GoogleGenAI, Type } from "@google/genai";
import { GEMINI_API_KEY, GEMINI_MODEL, VOICE_DIR } from "./config.js";
import { getState, postRestock, type State } from "./controller.js";
import { isEndCase } from "./parse.js";
import { currentSetting, type Setting } from "./settings.js";
import { closeCase, getPhoton, photonConfigured } from "./summary.js";

const ai = GEMINI_API_KEY ? new GoogleGenAI({ apiKey: GEMINI_API_KEY }) : null;

export const SETTINGS = ["surgical", "dental", "bench"];
const KINDS = ["restock", "count", "summary", "help"] as const;
type Kind = typeof KINDS[number];
export interface TextIntent { kind: Kind; item: string | null; qty: number; setting: string | null }

export const RESTOCKS_FILE = path.join(VOICE_DIR, "restocks.jsonl");
export const HELP = `Text me "add a hemostat to the surgical tray", "what's out?" or "summary".`;
const name = (id: string) => id.replace(/_/g, " ");

export async function parseText(text: string, setting: Setting): Promise<TextIntent> {
  if (ai) {
    try { return await geminiText(text, setting); }
    catch (e) { console.log(`[gemini] text parse failed, using local match: ${(e as Error).message}`); }
  }
  return localText(text, setting);
}

async function geminiText(text: string, setting: Setting): Promise<TextIntent> {
  const ids = setting.items.map((i) => i.id);
  const list = setting.items.map((i) => `- ${i.id}: ${i.name}${i.aliases.length ? ` (also: ${i.aliases.join(", ")})` : ""}`).join("\n");
  const res = await ai!.models.generateContent({
    model: GEMINI_MODEL,
    contents: `You read texts sent to Scrub, a robot arm that passes instruments in a ${setting.label.toLowerCase()}.
Kinds:
- restock: they added instruments to a tray ("add a second hemostat to the surgical tray"). qty is how many were added (a second one = 1).
- count: they want to know what's out
- summary: they want the end-of-case summary, or say the case is over
- help: anything else
Instruments on the current tray:
${list}
item is the instrument id for restock, otherwise "none". setting is the tray they name (${SETTINGS.join(", ")}), otherwise "none".
Text: "${text}"`,
    config: {
      responseMimeType: "application/json",
      responseSchema: {
        type: Type.OBJECT,
        properties: {
          kind: { type: Type.STRING, enum: [...KINDS] },
          item: { type: Type.STRING, enum: [...ids, "none"] },
          qty: { type: Type.INTEGER },
          setting: { type: Type.STRING, enum: [...SETTINGS, "none"] },
        },
        required: ["kind", "item", "qty", "setting"],
        propertyOrdering: ["kind", "item", "qty", "setting"],
      },
      temperature: 0,
      abortSignal: AbortSignal.timeout(5000),
    },
  });
  const out = JSON.parse(res.text || "{}");
  const kind: Kind = KINDS.includes(out.kind) ? out.kind : "help";
  return {
    kind,
    item: kind === "restock" && ids.includes(out.item) ? out.item : null,
    qty: Number.isInteger(out.qty) && out.qty > 0 ? Math.min(out.qty, 20) : 1,
    setting: SETTINGS.includes(out.setting) ? out.setting : null,
  };
}

const norm = (x: string) => x.toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
const NUMS: Record<string, number> = { two: 2, three: 3, four: 4, five: 5, six: 6, couple: 2, pair: 2 };

export function localText(text: string, setting: Setting): TextIntent {
  const s = ` ${norm(text)} `;
  const named = SETTINGS.find((id) => s.includes(` ${id} `)) || null;
  if (isEndCase(text) || /\b(summary|recap|wrap up)\b/.test(s)) return { kind: "summary", item: null, qty: 1, setting: named };
  if (/\b(what s out|whats out|what is out|count|how many|anything out)\b/.test(s)) return { kind: "count", item: null, qty: 1, setting: named };
  if (/\b(add|added|restock|restocked|refill|another|extra|more|put|new)\b/.test(s)) {
    let best: { id: string; len: number } | null = null;
    for (const it of setting.items) {
      for (const phrase of [it.name, it.id.replace(/_/g, " "), ...it.aliases]) {
        const p = norm(phrase);
        if (p && (s.includes(` ${p} `) || s.includes(` ${p}s `)) && (!best || p.length > best.len)) best = { id: it.id, len: p.length };
      }
    }
    const n = s.match(/\b(\d+)\b/)?.[1];
    const word = Object.keys(NUMS).find((w) => s.includes(` ${w} `));
    const qty = n ? Math.min(Number(n), 20) || 1 : word ? NUMS[word] : 1;
    return { kind: "restock", item: best?.id ?? null, qty, setting: named };
  }
  return { kind: "help", item: null, qty: 1, setting: named };
}

export interface Restock { type: "restock"; item: string; qty: number; setting: string; from: string | null; heard: string; case_id: string | null; t: number }

// To the ledger through the controller's POST /restock; the local file if that fails or the ledger isn't loaded.
export async function logRestock(r: Restock, file = RESTOCKS_FILE, post = postRestock) {
  const ok = await post(r).then((res) => res.ok, () => false);
  if (!ok) appendFileSync(file, JSON.stringify(r) + "\n");
}

export function countReply(st: State): string {
  const out = st.out || [];
  let line = out.length ? `Out (${out.length}): ${out.map(name).join(", ")}.` : "Count: everything is back on the tray.";
  if (Array.isArray(st.out_camera)) {
    const same = st.out_camera.length === out.length && st.out_camera.every((i) => out.includes(i));
    line += same ? " The camera agrees." : ` The camera sees out: ${st.out_camera.map(name).join(", ") || "nothing"}.`;
  }
  return line;
}

export interface TextDeps {
  state: () => Promise<State>;
  setting: (id: string) => Promise<Setting>;
  parse: (text: string, setting: Setting) => Promise<TextIntent>;
  log: (r: Restock) => void | Promise<void>;
  summary: () => Promise<string>;
}
const DEFAULTS: TextDeps = { state: getState, setting: currentSetting, parse: parseText, log: logRestock, summary: () => closeCase() };

// One text in -> the reply text.
export async function handleText(text: string, from: string | null, deps: Partial<TextDeps> = {}): Promise<string> {
  const d = { ...DEFAULTS, ...deps };
  const st = await d.state().catch(() => null);
  const setting = await d.setting(st?.setting || "surgical");
  const p = await d.parse(text, setting);
  console.log(`[text] ${from ?? "?"}: ${text} -> ${p.kind}${p.item ? ` ${p.qty} ${p.item}` : ""}`);
  if (p.kind === "count") return st ? countReply(st) : "I can't reach the arm controller.";
  if (p.kind === "summary") return d.summary();
  if (p.kind === "restock") {
    if (!p.item) return `Which instrument? On this tray: ${setting.items.map((i) => i.name).join(", ")}.`;
    const tray = p.setting || setting.id;
    await d.log({ type: "restock", item: p.item, qty: p.qty, setting: tray, from, heard: text, case_id: st?.case_id ?? null, t: Date.now() / 1000 });
    return `Logged: +${p.qty} ${name(p.item)} on the ${tray} tray.`;
  }
  return HELP;
}

// The bits of Spectrum's [Space, Message] this uses, so tests can feed a fake stream.
export interface InSpace { send(text: string): Promise<unknown> }
export interface InMessage { direction: string; content: { type: string; text?: string }; sender?: { id: string } }

export async function runTexts(stream: AsyncIterable<[InSpace, InMessage]>, deps: Partial<TextDeps> = {}) {
  for await (const [space, msg] of stream) {
    if (msg.direction !== "inbound" || msg.content.type !== "text" || !msg.content.text?.trim()) continue;
    try { await space.send(await handleText(msg.content.text.trim(), msg.sender?.id ?? null, deps)); }
    catch (e) { console.log(`[text] reply failed: ${(e as Error).message}`); }
  }
}

// Listen on the Photon line, only with credentials. Reconnects if the stream ends or throws.
export function startTexts() {
  if (!photonConfigured()) { console.log("[texts] off: no PHOTON_PROJECT_ID / PHOTON_API_KEY"); return; }
  const loop = async () => {
    try {
      const app = await getPhoton();
      console.log("[texts] listening on the Photon line");
      await runTexts(app.messages);
    } catch (e) { console.log(`[texts] stream error: ${(e as Error).message}`); }
    setTimeout(loop, 5000);
  };
  loop();
}
