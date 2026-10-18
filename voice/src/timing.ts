// Per-turn timings: where a caller turn's time goes, one `[timing]` line each and medians in GET /health.
// All times are ms from the request arriving (the clock starts before the body is read).

export interface TurnTiming {
  heard_to_command_ms: number | null;  // arrival -> POST /command (or /stop) sent; null: nothing posted
  gemini_ms: number | null;            // Gemini parse time; null when the local match ran or nothing was parsed
  parser: "gemini" | "local" | null;   // null: the turn never parsed (tray check, end of case, a tray switch)
  controller_ms: number | null;        // POST /command (or /stop) round trip
  first_line_ms: number | null;        // arrival -> first spoken line written to the reply; null: said nothing
}

export const blankTiming = (): TurnTiming =>
  ({ heard_to_command_ms: null, gemini_ms: null, parser: null, controller_ms: null, first_line_ms: null });

const KEEP = 50;
const turns: TurnTiming[] = [];

const ms = (n: number | null) => (n == null ? "-" : `${Math.round(n)}ms`);
export const timingLine = (t: TurnTiming) =>
  `[timing] heard->command ${ms(t.heard_to_command_ms)}, gemini ${t.parser === "gemini" ? ms(t.gemini_ms) : t.parser ?? "-"}, ` +
  `controller ${ms(t.controller_ms)}, first line ${ms(t.first_line_ms)}`;

export function recordTiming(t: TurnTiming) {
  console.log(timingLine(t));
  turns.push(t);
  if (turns.length > KEEP) turns.shift();
}

// Lower median, like gemini_p50_ms in parse.ts. Turns that didn't have that step don't count toward it.
function p50(key: keyof Omit<TurnTiming, "parser">): number | null {
  const v = turns.map((t) => t[key]).filter((x): x is number => x != null).sort((a, b) => a - b);
  return v.length ? Math.round(v[Math.floor((v.length - 1) / 2)]) : null;
}

export function timingStats() {
  return {
    turns: turns.length,
    heard_to_command_p50_ms: p50("heard_to_command_ms"),
    gemini_p50_ms: p50("gemini_ms"),
    controller_p50_ms: p50("controller_ms"),
    first_line_p50_ms: p50("first_line_ms"),
    last: turns.at(-1) ?? null,  // `npm run say` prints it after its turn
  };
}

export const forgetTimings = () => { turns.length = 0; };
