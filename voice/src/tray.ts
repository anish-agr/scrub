// X3 tray check: "check the tray" on the call or by text -> the controller's GET /tray_check -> its `say`.
// A passing check asked on the call also texts "Tray ready: ..." to the caller's thread; by text, that is the reply.
import { getTrayCheck, type TrayCheck } from "./controller.js";
import { textCaller } from "./summary.js";

export const CANT_CHECK = "I can't check the tray right now.";

export function trayReadyText(r: TrayCheck): string {
  const n = r.items?.length;
  return `Tray ready: ${r.label || r.setting || "tray"}, all ${n ? `${n} ` : ""}instruments in place.`;
}

const ask = (get: () => Promise<TrayCheck>) =>
  get().catch((e) => { console.log(`[tray] ${(e as Error).message}`); return null; });

// On the call: the spoken line. The text goes out in the background (never holds the reply).
export async function voiceTrayCheck(get = getTrayCheck, notify: (text: string) => Promise<unknown> = textCaller): Promise<string> {
  const r = await ask(get);
  console.log(`[tray] ${r ? (r.ok ? "ready" : "not ready") : "can't check"}`);
  if (r?.ok) notify(trayReadyText(r)).catch((e) => console.log(`[tray] text failed: ${(e as Error).message}`));
  return r?.say || CANT_CHECK;
}

// By text: the reply. Passing: the "tray ready" message; otherwise what Scrub would say.
export async function textTrayCheck(get = getTrayCheck): Promise<string> {
  const r = await ask(get);
  return r?.ok ? trayReadyText(r) : r?.say || CANT_CHECK;
}
