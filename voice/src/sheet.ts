// Count sheet math and the reading lines, the same as controller/reads.py and controller/lines.py.
// Used for a photo texted to the thread (vision answers, voice words it) and for the end-of-case summary.
import type { SheetState } from "./controller.js";

export type Mismatch = { item: string; sheet: number | null; scrub?: number | null; expected?: number | null };

const int = (v: unknown): number | null => (typeof v === "number" && Number.isInteger(v) ? v : null);

// Vision's count sheet result -> State.sheet shape.
export function sheetState(res: any): SheetState {
  const items: SheetState["items"] = {};
  for (const row of Array.isArray(res?.items) ? res.items : []) {
    if (row && row.item) items[String(row.item)] = { expected: int(row.expected), initial: int(row.initial), closing: int(row.closing) };
  }
  return { tray: res?.tray ?? null, method: res?.method ?? null, items };
}

// Scrub's on-tray count: the sheet's expected (1 when blank) minus how many of the item are out.
const onTray = (r: { expected: number | null }, id: string, out: string[]) => (r.expected ?? 1) - out.filter((i) => i === id).length;

// Where a written closing count differs from Scrub's. null: no closing count written.
export function closingMismatch(sheet: SheetState, out: string[]): Mismatch[] | null {
  const rows = Object.entries(sheet.items || {}).filter(([, r]) => r.closing != null);
  if (!rows.length) return null;
  return rows.filter(([id, r]) => r.closing !== onTray(r, id, out)).map(([id, r]) => ({ item: id, sheet: r.closing, scrub: onTray(r, id, out) }));
}

// Where a written initial count differs from the expected. null: none written.
export function initialMismatch(sheet: SheetState): Mismatch[] | null {
  const rows = Object.entries(sheet.items || {}).filter(([, r]) => r.initial != null && r.expected != null);
  if (!rows.length) return null;
  return rows.filter(([, r]) => r.initial !== r.expected).map(([id, r]) => ({ item: id, sheet: r.initial, expected: r.expected }));
}

// "1 hemostat", "0 hemostats", "2 mayo scissors".
const countOf = (n: number | null, name: string) => `${n} ${n === 1 || name.endsWith("s") ? name : name + "s"}`;
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export const CANT_READ_SHEET = "I can't read the count sheet.";
export const CANT_READ_TAG = "I can't read the tray tag.";
export const CANT_READ_PACK = "I can't read the pack label.";
export const SHEET_MATCHES = "Sheet matches my count.";
export const SHEET_NO_COUNTS = "No counts are written on the sheet yet.";

// The count sheet line, and the compare and mismatch to keep with the read. name: item id -> its name.
export function sheetWords(sheet: SheetState, out: string[], current: { id: string; label: string }, label: (id: string) => string,
    name: (id: string) => string): { say: string; compare: "closing" | "initial" | null; mismatch: Mismatch[] } {
  const parts: string[] = [];
  if (sheet.tray && sheet.tray !== current.id) parts.push(`This sheet is for the ${label(sheet.tray)} tray, not the ${current.label} tray.`);
  let compare: "closing" | "initial" | null = "closing";
  let mism = closingMismatch(sheet, out);
  if (mism === null) { compare = "initial"; mism = initialMismatch(sheet); }
  if (mism === null) { compare = null; parts.push(SHEET_NO_COUNTS); }
  else if (!mism.length) parts.push(SHEET_MATCHES);
  for (const m of mism || []) {
    parts.push(m.scrub !== undefined ? `Sheet says ${countOf(m.sheet, name(m.item))} back, I count ${m.scrub}.`
      : `Sheet says ${countOf(m.sheet, name(m.item))} at the start, ${m.expected} expected.`);
  }
  return { say: parts.join(" "), compare, mismatch: mism || [] };
}

export const packLine = (name: string, expires: string | null, expired: boolean) =>
  expired ? `Expired: ${name.toLowerCase()} pack, ${expires}. Don't open it.`
    : expires ? `${cap(name)} pack, expires ${expires}.` : `${cap(name)} pack, no expiry date.`;

// For the end-of-case summary: "Count sheet matches." or where it disagrees.
export function summarySheetLine(cs: { compare: string | null; mismatch: Mismatch[] | null } | null, name: (id: string) => string): string | null {
  if (!cs) return null;
  if (cs.compare === null && !cs.mismatch?.length) return "Count sheet: no counts written.";
  if (!cs.mismatch?.length) return "Count sheet matches.";
  return `Count sheet disagrees: ${cs.mismatch.map((m) => m.scrub !== undefined
    ? `${name(m.item)} (sheet ${m.sheet}, Scrub ${m.scrub})`
    : `${name(m.item)} (sheet ${m.sheet} at the start, ${m.expected} expected)`).join(", ")}.`;
}
