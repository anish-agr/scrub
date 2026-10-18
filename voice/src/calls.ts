// One call at a time. A second phone call while the first is mid-case would interleave commands on one arm, so a
// turn from another conversation gets the busy line while the active one spoke in the last VOICE_BUSY_S. A "stop"
// from any call still stops the arm (server.ts): safety over turn-taking. An unknown conversation id never counts.
import { BUSY_S } from "./config.js";

export const BUSY_LINE = "Scrub is busy with another call. Try again in a minute.";

let active: { id: string; last: number } | null = null;

// true: this conversation may go ahead (and is now the active one). false: another call holds Scrub.
export function claimCall(id: string, now = Date.now(), busyS = BUSY_S): boolean {
  if (!id) return true;
  if (active && active.id !== id && now - active.last < busyS * 1000) return false;
  active = { id, last: now };
  return true;
}

// The call holding Scrub right now, or null once it has been quiet VOICE_BUSY_S.
export const activeCall = (now = Date.now(), busyS = BUSY_S) => (active && now - active.last < busyS * 1000 ? active.id : null);
export const forgetCalls = () => { active = null; };
