// Switching trays from a text or the call ("start a dental case"): POST /setting on the controller.
// The controller starts a new case_id on a switch; the previous case's summary is not sent for it.
import { postSetting } from "./controller.js";
import { forgetSetting } from "./settings.js";

export const SETTING_IDS = ["surgical", "dental", "bench"];
export const BUSY = "The arm is busy. Stop or wait, then try again.";

const norm = (x: string) => x.toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();

// "start a dental case", "switch to the bench tray", "surgical case" -> the setting id; anything else -> null.
export function settingAsked(text: string): string | null {
  const s = ` ${norm(text)} `;
  const id = SETTING_IDS.find((i) => s.includes(` ${i} `));
  if (!id) return null;
  if (/ (start|starting|switch|change|swap|load|begin|go|move|set up|open) /.test(s)) return id;
  return new RegExp(`^ (a |the )?${id} (case|tray|setting)( please)? $`).test(s) ? id : null;
}

// Switch the controller's setting; the line to text or speak back.
export async function switchSetting(id: string, post = postSetting): Promise<string> {
  const r = await post(id).catch(() => null);
  if (!r) return "I can't reach the arm controller.";
  if (r.status === 409) return BUSY;
  if (r.status === 404) return `I don't have a ${id} tray.`;
  if (r.status !== 200 || !r.setting) return `Couldn't switch trays (${r.status}).`;
  forgetSetting();
  const names = (r.setting.items || []).map((i: any) => i.name || String(i.id).replace(/_/g, " "));
  console.log(`[setting] switched to ${id}`);
  return `${id[0].toUpperCase() + id.slice(1)} case started: ${names.join(", ")}.`;
}
