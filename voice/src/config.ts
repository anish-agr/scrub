// Keys come only from the repo-root .env file, never from the shell environment. Never log key values.
// Non-secret wiring (ports, URLs, timings) may also come from the shell.
import { parse } from "dotenv";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

export const VOICE_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const REPO_DIR = path.resolve(VOICE_DIR, "..");
const envFile = path.join(REPO_DIR, ".env");
// VOICE_NO_KEYS=1 (npm test) ignores .env so nothing calls Gemini or Photon.
const keys: Record<string, string | undefined> =
  !process.env.VOICE_NO_KEYS && existsSync(envFile) ? parse(readFileSync(envFile)) : {};
// A key set to empty in the shell (PHOTON_API_KEY= npm run dev) is blanked, so a test copy can run with no Photon
// or Gemini. The shell can only turn a key off, never supply one.
for (const k of Object.keys(keys)) if (process.env[k] === "") keys[k] = "";
const env: Record<string, string | undefined> = { ...keys, ...process.env };  // wiring: the shell wins
export const CONTROLLER_URL = env.CONTROLLER_URL || "http://localhost:8000";
// The recording station (explore/station) drives the real arm by replaying averaged demos; empty = off.
export const STATION_URL = (env.STATION_URL || "").replace(/\/$/, "");
export const VOICE_PORT = Number(env.VOICE_PORT || 3000);
export const GEMINI_API_KEY = keys.GEMINI_API_KEY || "";
export const GEMINI_MODEL = env.GEMINI_MODEL || "gemini-3.5-flash-lite";
// Past this, use the local alias match instead of waiting on Gemini (ms).
export const GEMINI_TIMEOUT_MS = Number(env.GEMINI_TIMEOUT_MS || 1500);
// Opt-in for full reasoning models used by the PC demo; existing deployments stay unchanged.
export const GEMINI_THINKING_LEVEL = env.GEMINI_THINKING_LEVEL?.trim().toLowerCase();
export const GEMINI_MAX_OUTPUT_TOKENS = Number(env.GEMINI_MAX_OUTPUT_TOKENS || 0);
if (GEMINI_THINKING_LEVEL && !["low", "medium", "high"].includes(GEMINI_THINKING_LEVEL)) {
  throw new Error("GEMINI_THINKING_LEVEL must be low, medium or high");
}
if (!Number.isInteger(GEMINI_MAX_OUTPUT_TOKENS) || GEMINI_MAX_OUTPUT_TOKENS < 0) {
  throw new Error("GEMINI_MAX_OUTPUT_TOKENS must be a non-negative integer");
}
export const PHOTON_PROJECT_ID = keys.PHOTON_PROJECT_ID || keys.SPECTRUM_PROJECT_ID || "";
export const PHOTON_SECRET = keys.PHOTON_API_KEY || keys.SPECTRUM_PROJECT_SECRET || "";
// Who gets the end-of-case text when the call didn't carry a caller id.
export const SUMMARY_TO = env.PHOTON_SUMMARY_TO || "";
// Public dashboard base for the "Case replay: <url>/case.html?id=<case_id>" text after the summary. Empty = no link.
// SCRUB_PUBLIC_URL first; else the Vultr box by IP (nginx on port 80 proxies / to the ledger page, which serves
// /case.html), so the link still works before a domain is set up.
export function publicBase(url = "", ip = ""): string {
  const u = url.trim(), i = ip.trim();
  const base = u || (i ? (/^https?:\/\//.test(i) ? i : `http://${i}`) : "");
  return base.replace(/\/+$/, "");
}
export const PUBLIC_URL = publicBase(env.SCRUB_PUBLIC_URL, env.SCRUB_SERVER_IP);
// Shared secret ElevenLabs sends as "Authorization: Bearer ..." (its OPENAI_API_KEY secret). Empty = no check.
export const LLM_SECRET = keys.VOICE_LLM_SECRET || "";
// How long a reply stays open to speak follow-up event lines (seconds).
export const HOLD_S = Number(env.VOICE_HOLD_S || 14);
// A second call is told Scrub is busy while the active call spoke in the last this-many seconds.
export const BUSY_S = Number(env.VOICE_BUSY_S || 45);
// How long the judge-mode flag from GET /state is trusted before asking again (ms).
export const JUDGE_TTL_MS = Number(env.VOICE_JUDGE_TTL_MS || 3000);
// Vision (port 8001), for a photo texted to the Photon thread: POST {VISION_URL}/read/<kind>.
export const VISION_URL = (env.VISION_URL || "http://localhost:8001").replace(/\/+$/, "");
