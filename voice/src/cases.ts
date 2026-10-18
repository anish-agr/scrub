// Switching trays from a text or the call ("start a bench case"): POST /setting on the controller.
// The controller starts a new case_id on a switch; the previous case's summary is not sent for it.
// Scrub is surgical first, the robotics bench second. Dental still loads at the controller (keyboard, dashboard),
// but voice never offers it: asking for it by voice or text gets notSetUp() and nothing is posted.
import { getState, JUDGE_LINE, postSetting } from "./controller.js";
import { forgetSetting } from "./settings.js";

export const SETTING_IDS = ["surgical", "bench"];  // what voice offers, in this order
export const HIDDEN_SETTINGS = ["dental"];          // recognised, so the answer is "not set up", never a switch
export const KNOWN_SETTINGS = [...SETTING_IDS, ...HIDDEN_SETTINGS];
export const BUSY = "The arm is busy. Stop or wait, then try again.";
export const JUDGE = JUDGE_LINE;
// Never names the hidden tray back to the user: dental is not shown by voice or text.
export const notSetUp = (_id: string) => "That tray isn't set up for this demo. I have the surgical and bench trays.";

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
  // The switch word has to lead into the tray word. A switch clears the count, so "go grab the kelly off the
  // surgical tray" must stay a handover, not a new case.
  const verb = "(start|starting|switch|switching|change|swap|load|begin|open|set up|go|move)( over| back)?";
  const lead = `( to| into| on| onto| with)?( a| an| the| my)?( new)?`;
  if (new RegExp(` ${verb}${lead} ${word} `).test(s)) return id;
  if (new RegExp(` (switch|change|swap) (the )?(trays?|settings?|cases?)( over)? to( the)? ${word} `).test(s)) return id;
  return new RegExp(`^ (a |the )?${word} (case|tray|setting)( please)? $`).test(s) ? id : null;
}

// Switch the controller's setting; the line to text or speak back. Callers check judge mode first.
// A switch clears the controller's count. Anything still out is named in the reply, so it isn't forgotten.
export async function switchSetting(id: string, post = postSetting,
    state: () => Promise<{ out?: string[] | null }> = () => getState()): Promise<string> {
  if (!SETTING_IDS.includes(id)) return HIDDEN_SETTINGS.includes(id) ? notSetUp(id) : `I don't have a ${id} tray.`;
  const before = await state().catch(() => null);
  const r = await post(id).catch(() => null);
  if (!r) return "I can't reach the arm controller.";
  if (r.status === 409) return BUSY;
  if (r.status === 403) return JUDGE;  // the controller refused it (judge mode turned on since we last looked)
  if (r.status === 404) return `I don't have a ${id} tray.`;
  if (r.status !== 200 || !r.setting) return `Couldn't switch trays (${r.status}).`;
  forgetSetting();
  const names = (r.setting.items || []).map((i: any) => i.name || String(i.id).replace(/_/g, " "));
  console.log(`[setting] switched to ${id}`);
  const out = (before?.out || []).map((i) => i.replace(/_/g, " "));
  const left = out.length ? ` Still out from the last tray: ${out.join(", ")}.` : "";
  return `${id[0].toUpperCase() + id.slice(1)} case started: ${names.join(", ")}.${left}`;
}
