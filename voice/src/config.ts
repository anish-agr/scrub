// Keys come only from the repo-root .env file, never from the shell environment. Never log key values.
// Non-secret wiring (ports, URLs, timings) may also come from the shell.
import { parse } from "dotenv";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

export const VOICE_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const REPO_DIR = path.resolve(VOICE_DIR, "..");
const envFile = path.join(REPO_DIR, ".env");
const keys: Record<string, string | undefined> = existsSync(envFile) ? parse(readFileSync(envFile)) : {};
const env: Record<string, string | undefined> = { ...keys, ...process.env };  // wiring: the shell wins
export const CONTROLLER_URL = env.CONTROLLER_URL || "http://localhost:8000";
export const VOICE_PORT = Number(env.VOICE_PORT || 3000);
export const GEMINI_API_KEY = keys.GEMINI_API_KEY || "";
export const GEMINI_MODEL = env.GEMINI_MODEL || "gemini-3.5-flash-lite";
// Past this, use the local alias match instead of waiting on Gemini (ms).
export const GEMINI_TIMEOUT_MS = Number(env.GEMINI_TIMEOUT_MS || 1500);
export const PHOTON_PROJECT_ID = keys.PHOTON_PROJECT_ID || keys.SPECTRUM_PROJECT_ID || "";
export const PHOTON_SECRET = keys.PHOTON_API_KEY || keys.SPECTRUM_PROJECT_SECRET || "";
// Who gets the end-of-case text when the call didn't carry a caller id.
export const SUMMARY_TO = env.PHOTON_SUMMARY_TO || "";
// Shared secret ElevenLabs sends as "Authorization: Bearer ..." (its OPENAI_API_KEY secret). Empty = no check.
export const LLM_SECRET = keys.VOICE_LLM_SECRET || "";
// How long a reply stays open to speak follow-up event lines (seconds).
export const HOLD_S = Number(env.VOICE_HOLD_S || 8);
