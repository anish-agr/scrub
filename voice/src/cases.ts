// Switching trays from a text or the call ("start a bench case"): POST /setting on the controller.
// The controller starts a new case_id on a switch; the previous case's summary is not sent for it.
// Scrub is surgical first, the robotics bench second. Dental still loads at the controller (keyboard, dashboard),
// but voice never offers it: asking for it by voice or text gets notSetUp() and nothing is posted.
import { JUDGE_LINE, postSetting } from "./controller.js";
import { forgetSetting } from "./settings.js";

export const SETTING_IDS = ["surgical", "bench"];  // what voice offers, in this order
export const HIDDEN_SETTINGS = ["dental"];          // recognised, so the answer is "not set up", never a switch
export const KNOWN_SETTINGS = [...SETTING_IDS, ...HIDDEN_SETTINGS];
export const BUSY = "The arm is busy. Stop or wait, then try again.";
export const JUDGE = JUDGE_LINE;
export const notSetUp = (id: string) => `The ${id} tray isn't set up for this demo.`;

const norm = (x: string) => x.toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
// Words that name each tray (the id first).
const WORDS: Record<string, string[]> = {
  surgical: ["surgical", "surgery", "operating room"],
  bench: ["bench", "robotics"],
  dental: ["dental", "dentist"],
};

// "start a surgical case", "switch to the bench tray", "bench case" -> the setting id; anything else -> null.
// Can return a hidden id (dental): switchSetting answers that one with notSetUp.
export function settingAsked(text: string): string | null {
  const s = ` ${norm(text)} `;
  let id: string | null = null, word = "";
  for (const k of KNOWN_SETTINGS) {
    const w = WORDS[k].find((x) => s.includes(` ${x} `));
    if (w) { id = k; word = w; break; }
  }
  if (!id) return null;
  if (/ (start|starting|switch|change|swap|load|begin|go|move|set up|open) /.test(s)) return id;
  return new RegExp(`^ (a |the )?${word} (case|tray|setting)( please)? $`).test(s) ? id : null;
}

// Switch the controller's setting; the line to text or speak back. Callers check judge mode first.
export async function switchSetting(id: string, post = postSetting): Promise<string> {
  if (!SETTING_IDS.includes(id)) return HIDDEN_SETTINGS.includes(id) ? notSetUp(id) : `I don't have a ${id} tray.`;
  const r = await post(id).catch(() => null);
  if (!r) return "I can't reach the arm controller.";
  if (r.status === 409) return BUSY;
  if (r.status === 403) return JUDGE;  // the controller refused it (judge mode turned on since we last looked)
  if (r.status === 404) return `I don't have a ${id} tray.`;
  if (r.status !== 200 || !r.setting) return `Couldn't switch trays (${r.status}).`;
  forgetSetting();
  const names = (r.setting.items || []).map((i: any) => i.name || String(i.id).replace(/_/g, " "));
  console.log(`[setting] switched to ${id}`);
  return `${id[0].toUpperCase() + id.slice(1)} case started: ${names.join(", ")}.`;
}
