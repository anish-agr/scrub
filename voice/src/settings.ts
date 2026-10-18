// The current setting's items: from the controller's GET /setting, else settings/<id>.json, else the CONTRACTS ids.
// FALLBACK aliases match controller/settings.py's built-in defaults.
import { readFileSync } from "node:fs";
import path from "node:path";
import { REPO_DIR } from "./config.js";
import { getSetting } from "./controller.js";

export interface Item { id: string; name: string; aliases: string[]; sharp: boolean }
export interface Setting { id: string; label: string; items: Item[] }

const item = (id: string, aliases: string[], sharp = false): Item =>
  ({ id, name: id.replace(/_/g, " "), aliases, sharp });

const FALLBACK: Record<string, Setting> = {
  surgical: { id: "surgical", label: "Operating room", items: [
    item("scalpel", ["knife", "blade", "ten blade", "number ten"], true),
    item("hemostat", ["kelly", "clamp", "hemo"]),
    item("mayo_scissors", ["mayo", "scissors"]),
  ] },
  dental: { id: "dental", label: "Dental office", items: [
    item("mouth_mirror", ["mirror"]),
    item("explorer", ["probe", "pick"]),
    item("cotton_pliers", ["pliers", "tweezers", "cotton forceps"]),
  ] },
  bench: { id: "bench", label: "Robotics bench", items: [
    item("needle_nose_pliers", ["needle nose", "pliers"]),
    item("wire_cutters", ["cutters", "snips", "flush cutters"]),
    item("hex_key", ["allen key", "allen wrench", "hex"]),
  ] },
};

const fromFile = (raw: any): Setting => ({
  id: raw.id, label: raw.label || raw.id,
  items: raw.items.map((i: any) => ({ id: i.id, name: i.name || i.id, aliases: i.aliases || [], sharp: !!i.sharp })),
});

// The controller's setting is cached so a turn doesn't wait on GET /setting before Gemini.
// turn.ts drops the cache when an event shows a different setting.
const CACHE_MS = 30_000;
let cache: { setting: Setting; at: number } | null = null;
export const forgetSetting = () => { cache = null; };

export async function currentSetting(lastId: string): Promise<Setting> {
  if (cache && cache.setting.id === lastId && Date.now() - cache.at < CACHE_MS) return cache.setting;
  try {
    const setting = fromFile(await getSetting());
    cache = { setting, at: Date.now() };
    return setting;
  } catch { /* controller down */ }
  try { return fromFile(JSON.parse(readFileSync(path.join(REPO_DIR, "settings", `${lastId}.json`), "utf8"))); } catch { /* not there yet */ }
  return FALLBACK[lastId] || FALLBACK.surgical;
}
