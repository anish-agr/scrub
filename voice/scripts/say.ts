// Pretend to be the ElevenLabs agent: send one caller turn to the voice server's custom-LLM endpoint
// and print the streamed reply with timings. Usage: npm run say -- "grab me the kelly"
// Through the tunnel: VOICE_URL=https://<tunnel> npm run say -- "stop"
// No caller id by default, so a test turn never moves the live server's end-of-case text to a made-up number.
// SAY_CALLER=+1... npm run say -- "end of case" acts as that caller.
import { LLM_SECRET } from "../src/config.js";  // the .env VOICE_LLM_SECRET, sent like ElevenLabs sends it

const heard = process.argv.slice(2).join(" ") || "grab me the kelly";
const base = process.env.VOICE_URL || `http://localhost:${process.env.VOICE_PORT || 3000}`;
const t0 = Date.now();
const ms = () => `+${Date.now() - t0}ms`;
const res = await fetch(`${base}/v1/chat/completions`, {
  method: "POST",
  headers: { "content-type": "application/json", authorization: `Bearer ${process.env.VOICE_LLM_SECRET || LLM_SECRET}` },
  body: JSON.stringify({ model: "scrub", stream: true, messages: [
    { role: "system", content: `You are Scrub. Caller: ${process.env.SAY_CALLER || "{{system__caller_id}}"}` },
    { role: "user", content: heard },
  ] }),
});
console.log(`${ms()}  HTTP ${res.status}`);
let reply = "";
const decoder = new TextDecoder();
let rest = "";  // a chunk can end mid-line (through a tunnel): keep the tail for the next one
for await (const part of res.body as any) {
  const lines = (rest + decoder.decode(part, { stream: true })).split("\n");
  rest = lines.pop() ?? "";
  for (const line of lines) {
    if (!line.startsWith("data: ") || line.includes("[DONE]")) continue;
    const d = JSON.parse(line.slice(6)).choices[0].delta;
    if (d.role) console.log(`${ms()}  first chunk (role)`);
    if (d.content) { reply += d.content; console.log(`${ms()}  ${d.content.trim()}`); }
  }
}
console.log(`${ms()}  done. Scrub says: "${reply}"`);
// The server's own timings for this turn (and the medians), from GET /health. Another call in between can make
// `last` someone else's turn; the server log's [timing] line is the exact one.
const t = await fetch(`${base}/health`).then((r) => r.json()).then((h) => h.timing, () => null);
if (t?.last) {
  const f = (n: number | null) => (n == null ? "-" : `${n}ms`);
  const l = t.last;
  console.log(`server: heard->command ${f(l.heard_to_command_ms)}, gemini ${l.parser === "gemini" ? f(l.gemini_ms) : l.parser ?? "-"}, ` +
    `controller ${f(l.controller_ms)}, first line ${f(l.first_line_ms)}`);
  console.log(`medians of ${t.turns}: heard->command ${f(t.heard_to_command_p50_ms)}, gemini ${f(t.gemini_p50_ms)}, ` +
    `controller ${f(t.controller_p50_ms)}, first line ${f(t.first_line_p50_ms)}`);
}
