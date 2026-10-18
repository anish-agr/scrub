// Texts in on the Photon thread: restock, "what's out?", "summary". Gemini parses (structured output), local match if not.
// Restocks go to the ledger via the controller's POST /restock, else voice/restocks.jsonl.
import { appendFileSync } from "node:fs";
import path from "node:path";
import { GoogleGenAI, Type } from "@google/genai";
import { GEMINI_API_KEY, GEMINI_MODEL, VOICE_DIR } from "./config.js";
import { getState, makeCommand, postCommand, postRestock, postStop, type Command, type CommandReply, type State } from "./controller.js";
import { isEndCase, isStop, isTrayCheck, localParse, parse, parseAlias, readAction, type Parsed, type ParseResult } from "./parse.js";
import { dialogue } from "./dialogue.js";
import { handlePhoto, READ_ACTIONS, textRead, type Photo, type ReadAction } from "./reads.js";
import { currentSetting, teach, type Setting } from "./settings.js";
import type { AliasReply } from "./controller.js";
import { closeCaseWithLink, getPhoton, photonConfigured, withTimeout } from "./summary.js";
import { textTrayCheck } from "./tray.js";
import { HIDDEN_SETTINGS, JUDGE, KNOWN_SETTINGS, notSetUp, SETTING_IDS, settingAsked, switchSetting } from "./cases.js";

const ai = GEMINI_API_KEY ? new GoogleGenAI({ apiKey: GEMINI_API_KEY }) : null;

export const SETTINGS = SETTING_IDS;  // offered: surgical, bench (dental is recognised only to say it isn't set up)
// read_sheet, read_tray, read_pack (OCR pass): the same Command as on the call, the reply is the `read` event's say.
const KINDS = ["restock", "count", "summary", "setting", "alias", "help", "read_sheet", "read_tray", "read_pack"] as const;
type Kind = typeof KINDS[number];
export interface TextIntent { kind: Kind; item: string | null; qty: number; setting: string | null; alias?: string }

export const RESTOCKS_FILE = path.join(VOICE_DIR, "restocks.jsonl");
export const HELP = `Text me "add a hemostat to the surgical tray", "what's out?", "switch to the bench tray" or "summary".`;
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
- setting: they want to start a case on, or switch to, a tray ("start a surgical case", "switch to the bench tray"). setting is that tray.
- alias: they teach a word for an instrument on this tray ("call the hemostat a clamp", "clamp means the hemostat", "when I say clamp I mean the hemostat"). item is that instrument, alias is the new word, lowercase.
- read_sheet: read the paper count sheet in view ("read the count sheet", "check the count sheet")
- read_tray: read the tray tag or label to tell which tray this is ("what tray is this", "read the tray tag")
- read_pack: read a sterile pack label, lot or expiry date ("read the pack", "is this pack expired")
- help: anything else
Instruments on the current tray:
${list}
item is the instrument id for restock or alias, otherwise "none". alias is the new word for alias, otherwise "none". setting is the tray they name (${SETTINGS.join(" or ")}; "dental" only if they name the dental tray), otherwise "none".
Text: "${text}"`,
    config: {
      responseMimeType: "application/json",
      responseSchema: {
        type: Type.OBJECT,
        properties: {
          kind: { type: Type.STRING, enum: [...KINDS] },
          item: { type: Type.STRING, enum: [...ids, "none"] },
          qty: { type: Type.INTEGER },
          setting: { type: Type.STRING, enum: [...KNOWN_SETTINGS, "none"] },
          alias: { type: Type.STRING },
        },
        required: ["kind", "item", "qty", "setting", "alias"],
        propertyOrdering: ["kind", "item", "qty", "setting", "alias"],
      },
      temperature: 0,
      abortSignal: AbortSignal.timeout(5000),
    },
  });
  const out = JSON.parse(res.text || "{}");
  const kind: Kind = KINDS.includes(out.kind) ? out.kind : "help";
  if (kind === "alias") {
    const alias = norm(String(out.alias || "")).replace(/^(the|a|an) /, "");
    return { kind, item: ids.includes(out.item) ? out.item : null, qty: 1, setting: null, alias: alias && alias !== "none" ? alias : undefined };
  }
  return {
    kind,
    item: kind === "restock" && ids.includes(out.item) ? out.item : null,
    qty: Number.isInteger(out.qty) && out.qty > 0 ? Math.min(out.qty, 20) : 1,
    setting: KNOWN_SETTINGS.includes(out.setting) ? out.setting : null,
  };
}

const norm = (x: string) => x.toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
const NUMS: Record<string, number> = { two: 2, three: 3, four: 4, five: 5, six: 6, couple: 2, pair: 2 };

export function localText(text: string, setting: Setting): TextIntent {
  const s = ` ${norm(text)} `;
  const named = KNOWN_SETTINGS.find((id) => s.includes(` ${id} `)) || null;
  const taught = parseAlias(text, setting);
  if (taught) return { kind: "alias", item: taught.item, qty: 1, setting: null, alias: taught.alias };
  // Before the count words: "count sheet" has "count" in it. "check the tray" is the tray check (handleText, first).
  const read = readAction(text);
  if (read) return { kind: read as Kind, item: null, qty: 1, setting: null };
  if (isEndCase(text) || /\b(summary|recap|wrap up)\b/.test(s)) return { kind: "summary", item: null, qty: 1, setting: named };
  if (/\b(what s out|whats out|what is out|count|how many|anything out)\b/.test(s)) return { kind: "count", item: null, qty: 1, setting: named };
  const asked = settingAsked(text);
  if (asked) return { kind: "setting", item: null, qty: 1, setting: asked };
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
  trayCheck: () => Promise<string>;
  switchTo: (id: string) => Promise<string>;
  teach: (item: string, alias: string) => Promise<AliasReply>;
  read: (action: ReadAction, text: string) => Promise<string>;
  photo: (photo: Photo, text: string, from: string | null) => Promise<string>;
  command: (command: Command) => Promise<CommandReply>;
  stop: () => Promise<{ accepted: boolean }>;
  parseCommand: (text: string, setting: Setting) => Promise<Parsed>;
  notify?: (line: string) => void;
}
const DEFAULTS: TextDeps = { state: getState, setting: currentSetting, parse: parseText, log: logRestock,
  summary: () => closeCaseWithLink(), trayCheck: () => textTrayCheck(), switchTo: (id) => switchSetting(id), teach,
  read: (action, text) => textRead(action, text), photo: (p, text, from) => handlePhoto(p, text, from),
  command: postCommand, stop: postStop, parseCommand: parse };

// One text in -> the reply text.
export async function handleText(text: string, from: string | null, deps: Partial<TextDeps> = {}, thread = from || "anonymous"): Promise<string> {
  const d = { ...DEFAULTS, ...deps };
  const context = `text:${thread}`;
  // Safety first: even an outstanding question or a slow setting fetch cannot delay a texted stop.
  if (isStop(text)) {
    dialogue.clear();
    return d.stop().catch(() => d.stop()).then(() => "Stopped.", () => "I can't reach the arm controller.");
  }
  if (isTrayCheck(text)) { console.log(`[text] ${from ?? "?"}: ${text} -> tray check`); return d.trayCheck(); }
  const st = await d.state().catch(() => null);
  const setting = await d.setting(st?.setting || "surgical");
  const answer = dialogue.answer(context, text, setting);
  if (answer && "say" in answer) return answer.say;
  const local = localParse(text, setting);
  const restock = /\b(add|added|restock|restocked|refill|extra|new)\b/i.test(text);
  if (answer && "parsed" in answer) return sendTextCommand(answer.parsed, text, context, setting, d);
  if (!restock && !parseAlias(text, setting) && ["handover", "return", "got_it"].includes(local.action)) {
    return sendTextCommand(local, text, context, setting, d);
  }
  const p = await d.parse(text, setting);
  console.log(`[text] ${from ?? "?"}: ${text} -> ${p.kind}${p.item ? ` ${p.qty} ${p.item}` : ""}`);
  if (p.kind === "count") return st ? countReply(st) : "I can't reach the arm controller.";
  if (p.kind === "summary") { dialogue.clear(context); return d.summary(); }
  if (READ_ACTIONS.includes(p.kind as ReadAction)) return st?.judge ? JUDGE : d.read(p.kind as ReadAction, text);
  // Judge mode: the controller only takes handover, count, stop and got_it. Don't post a switch, a word or a restock.
  if (st?.judge && (p.kind === "setting" || p.kind === "alias" || p.kind === "restock")) return JUDGE;
  if (p.kind === "setting") { dialogue.clear(context); return p.setting ? d.switchTo(p.setting) : `Which tray? ${SETTINGS.join(", ")}.`; }
  if (p.kind === "alias") {
    if (!p.item || !p.alias) return `Say it like: call the ${setting.items[0]?.name ?? "hemostat"} a clamp. On this tray: ${setting.items.map((i) => i.name).join(", ")}.`;
    return d.teach(p.item, p.alias).then((r) => r.say, () => "I can't reach the arm controller.");
  }
  if (p.kind === "restock") {
    if (!p.item) return `Which instrument? On this tray: ${setting.items.map((i) => i.name).join(", ")}.`;
    const tray = p.setting || setting.id;
    if (HIDDEN_SETTINGS.includes(tray)) return notSetUp(tray);  // never log or echo the hidden tray
    await d.log({ type: "restock", item: p.item, qty: p.qty, setting: tray, from, heard: text, case_id: st?.case_id ?? null, t: Date.now() / 1000 });
    return `Logged: +${p.qty} ${name(p.item)} on the ${tray} tray.`;
  }
  if (/\b(hand|bring|give|pass|grab|get)\b/i.test(text)) {
    const command = await d.parseCommand(text, setting);
    if (command.action !== "unknown") return sendTextCommand(command, text, context, setting, d);
  }
  return HELP;
}

async function sendTextCommand(p: ParseResult, text: string, context: string, setting: Setting, d: TextDeps): Promise<string> {
  const question = dialogue.askParsed(context, p, setting);
  if (question) return question;
  const cmd = makeCommand(p.action, p.item, text);
  if (p.instance) cmd.instance = p.instance;
  let waiting = true;
  const early: string[] = [];
  let last = "";
  const notify = (line: string) => {
    if (line === last) return;
    last = line;
    if (waiting) early.push(line); else d.notify?.(line);
  };
  dialogue.track(context, cmd, setting, notify);
  try {
    const r = await d.command(cmd);
    waiting = false;
    if (r.clarify) return dialogue.ask(context, r.clarify, setting, cmd.action, false, false);
    return early.join(" ") || r.say || (r.accepted ? "Request sent." : "The controller couldn't accept that request.");
  } catch { waiting = false; return "I can't reach the arm controller."; }
}

// The bits of Spectrum's [Space, Message] this uses, so tests can feed a fake stream.
export interface InSpace { id?: string; send(text: string): Promise<unknown> }
// Spectrum (iMessage) content: a text is {type: "text"}; a photo alone is {type: "attachment", mimeType, name, read()}
// (read() downloads the bytes); a photo with a caption is {type: "group", items: [Message, Message]}.
export interface InContent { type: string; text?: string; mimeType?: string; name?: unknown; read?: () => Promise<Buffer>; items?: { content: InContent }[] }
export interface InMessage { direction: string; content: InContent; sender?: { id: string } }

// The text and the first image in a message (either may be missing).
export function partsOf(c: InContent): { text: string; image: Photo | null } {
  const all = c.type === "group" && Array.isArray(c.items) ? c.items.map((m) => m.content).filter(Boolean) : [c];
  const text = all.filter((x) => x.type === "text" && x.text).map((x) => x.text!.trim()).join(" ").trim();
  const img = all.find((x) => x.type === "attachment" && typeof x.read === "function" && /^image\//i.test(x.mimeType || ""));
  return { text, image: img ? { mimeType: img.mimeType, name: typeof img.name === "string" ? img.name : undefined, read: img.read! } : null };
}

export async function runTexts(stream: AsyncIterable<[InSpace, InMessage]>, deps: Partial<TextDeps> = {}) {
  for await (const [space, msg] of stream) {
    if (msg.direction !== "inbound" || !msg.content) continue;
    const { text, image } = partsOf(msg.content);
    if (!text && !image) continue;
    const from = msg.sender?.id ?? null;
    const photo = deps.photo ?? DEFAULTS.photo;
    // One text at a time: a reply that hangs (Photon, or a slow summary) must not hold up every text after it.
    // A photo gets longer: the download, then vision's read (up to 25 s).
    try {
      const reply = image ? photo(image, text, from) : handleText(text, from, { ...deps,
        notify: (line) => { void space.send(line).catch(() => {}); } }, space.id || from || "anonymous");
      await withTimeout(reply.then((r) => space.send(r)), image ? 45_000 : 30_000, "text reply");
    }
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
