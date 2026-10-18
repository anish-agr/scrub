// Reading by text (OCR pass).
// "read the count sheet", "what tray is this", "read the pack": the same Command as on the call; the reply is the
// `say` of the controller's `read` event for that command (GET /events/recent, polled up to 25 s).
// A photo on the thread: vision's POST /read/<kind> with the image (the controller only reads its overhead camera),
// worded the way the controller words it. Nothing is posted to the controller; the read is kept for the summary.
import { execFile } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { VISION_URL } from "./config.js";
import { getRecent, getState, makeCommand, postCommand, type Action, type Command, type CommandReply, type ScrubEvent, type State } from "./controller.js";
import { HIDDEN_SETTINGS, notSetUp, SETTING_IDS } from "./cases.js";
import { currentSetting, trayLabel, type Setting } from "./settings.js";
import { CANT_READ_PACK, CANT_READ_SHEET, CANT_READ_TAG, packLine, sheetState, sheetWords } from "./sheet.js";
import { recordEvent } from "./summary.js";

export type ReadAction = "read_sheet" | "read_tray" | "read_pack";
export const READ_ACTIONS: ReadAction[] = ["read_sheet", "read_tray", "read_pack"];
const CANT: Record<ReadAction, string> = { read_sheet: CANT_READ_SHEET, read_tray: CANT_READ_TAG, read_pack: CANT_READ_PACK };
export const READ_SLOW = "The read is taking too long. Try again in a moment.";
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// Post the read Command, then wait for its `read` event. A refusal ("Still reading.", judge mode) is its `say`.
export async function textRead(action: ReadAction, heard: string, post: (c: Command) => Promise<CommandReply> = postCommand,
    recent: () => Promise<ScrubEvent[]> = () => getRecent(100), waitMs = 25_000, everyMs = 500): Promise<string> {
  const cmd = makeCommand(action as Action, null, heard);
  const reply = await post(cmd).catch(() => null);
  if (!reply) return "I can't reach the arm controller.";
  if (!reply.accepted) return reply.say || CANT[action];
  const end = Date.now() + waitMs;
  while (Date.now() < end) {
    await sleep(everyMs);
    const evs = await recent().catch(() => [] as ScrubEvent[]);
    const e = evs.find((x) => x.type === "read" && x.command_id === cmd.id);
    if (e) return e.say || CANT[action];
  }
  return READ_SLOW;
}

// ---------- a photo on the thread ----------

export type PhotoKind = "count_sheet" | "tray_tag" | "pack_label";
export interface Photo { mimeType?: string; name?: string; read: () => Promise<Buffer> }

// The text with the photo picks the reader: "pack" -> pack label, "tray" or "tag" -> tray tag, else the count sheet.
export function photoKind(text: string): PhotoKind {
  const s = ` ${text.toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ")} `;
  if (/ (sheet|count) /.test(s)) return "count_sheet";
  if (/ (packs?|labels?|expir\w*|lot|sterile) /.test(s)) return "pack_label";
  if (/ (tray|tags?|qr) /.test(s)) return "tray_tag";
  return "count_sheet";
}

// iPhone photos can be HEIC, which vision (OpenCV) can't open: macOS `sips` turns them into a JPEG.
export async function toJpeg(bytes: Buffer, mime = "", name = ""): Promise<Buffer> {
  if (!/hei[cf]/i.test(mime) && !/\.hei[cf]$/i.test(name)) return bytes;
  if (process.platform !== "darwin") throw new Error("HEIC needs macOS sips");
  const dir = mkdtempSync(path.join(tmpdir(), "scrub-photo-"));
  try {
    writeFileSync(path.join(dir, "in.heic"), bytes);
    await promisify(execFile)("sips", ["-s", "format", "jpeg", path.join(dir, "in.heic"), "--out", path.join(dir, "out.jpg")], { timeout: 15_000 });
    return readFileSync(path.join(dir, "out.jpg"));
  } finally { rmSync(dir, { recursive: true, force: true }); }
}

// Vision's answer (its JSON, also on a 4xx), or null when it can't be reached.
export async function postVision(kind: PhotoKind, jpeg: Buffer, setting: string, today: string, base = VISION_URL): Promise<any | null> {
  const q = new URLSearchParams({ setting, today });
  try {
    const res = await fetch(`${base}/read/${kind}?${q}`, { method: "POST", headers: { "content-type": "image/jpeg" },
      body: new Uint8Array(jpeg), signal: AbortSignal.timeout(25_000) });
    const data = await res.json().catch(() => null);
    return data && typeof data === "object" ? data : null;
  } catch { return null; }
}

// Local date, YYYY-MM-DD, for vision's `expired`.
export const localDay = (d = new Date()) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

// Vision's result -> the reply, worded like controller/core.py, and the `read` object kept for the summary.
export function wordPhoto(kind: PhotoKind, res: any, setting: Setting, out: string[]): { say: string; read: Record<string, unknown> } {
  const ok = !!res?.ok;
  const read: Record<string, unknown> = { ...(res || {}), kind, ok, photo: true };
  const name = (id: string) => setting.items.find((i) => i.id === id)?.name ?? id.replace(/_/g, " ");
  if (kind === "count_sheet") {
    if (!ok) return { say: CANT_READ_SHEET, read };
    const w = sheetWords(sheetState(res), out, { id: setting.id, label: trayLabel(setting.id) }, trayLabel, name);
    return { say: w.say, read: { ...read, compare: w.compare, mismatch: w.mismatch } };
  }
  if (kind === "tray_tag") {
    const tray = ok && typeof res.tray === "string" ? res.tray : null;
    if (!tray) return { say: CANT_READ_TAG, read };
    if (HIDDEN_SETTINGS.includes(tray)) return { say: notSetUp(tray), read };
    if (tray === setting.id) return { say: `This is the ${trayLabel(tray)} tray.`, read };
    const hint = SETTING_IDS.includes(tray) ? ` Text "switch to the ${tray} tray" to change.` : "";
    return { say: `This is the ${trayLabel(tray)} tray, not the ${trayLabel(setting.id)} tray.${hint}`, read };
  }
  const labels = ok && Array.isArray(res.labels) ? res.labels.filter((l: any) => l && typeof l === "object") : [];
  if (!labels.length) return { say: CANT_READ_PACK, read };
  const say = labels.map((l: any) => packLine(l.item ? name(String(l.item)) : String(l.item_text || "instrument"),
    typeof l.expires === "string" ? l.expires : null, !!l.expired)).join(" ");
  return { say, read };
}

export interface PhotoDeps {
  state: () => Promise<State>;
  setting: (id: string) => Promise<Setting>;
  vision: (kind: PhotoKind, jpeg: Buffer, setting: string, today: string) => Promise<any | null>;
  record: (e: ScrubEvent) => void;
  convert: (bytes: Buffer, mime?: string, name?: string) => Promise<Buffer>;
}
const PHOTO_DEFAULTS: PhotoDeps = { state: getState, setting: currentSetting, vision: postVision, record: recordEvent, convert: toJpeg };

// One photo in -> the reply text.
export async function handlePhoto(photo: Photo, text: string, from: string | null, deps: Partial<PhotoDeps> = {}): Promise<string> {
  const d = { ...PHOTO_DEFAULTS, ...deps };
  const kind = photoKind(text);
  console.log(`[text] ${from ?? "?"}: photo (${photo.mimeType ?? "?"})${text ? ` "${text}"` : ""} -> ${kind}`);
  let jpeg: Buffer;
  try { jpeg = await d.convert(await photo.read(), photo.mimeType, photo.name); }
  catch (e) { console.log(`[photo] ${(e as Error).message}`); return "I can't open that photo. Send it as a JPEG."; }
  const st = await d.state().catch(() => null);
  const setting = await d.setting(st?.setting || "surgical");
  const res = await d.vision(kind, jpeg, setting.id, localDay());
  if (!res) console.log("[photo] vision can't be reached");
  else console.log(`[photo] ${kind} ok=${!!res.ok} method=${res.method ?? null} ${res.latency_ms ?? "?"} ms`);
  const { say, read } = wordPhoto(kind, res, setting, st?.out || []);
  // Kept for the end-of-case summary only (sheet comparison, expired packs). Never sent to the controller.
  if (res) d.record({ type: "read", t: Date.now() / 1000, command_id: null, case_id: st?.case_id ?? null, say, read: read as ScrubEvent["read"] });
  return say;
}
