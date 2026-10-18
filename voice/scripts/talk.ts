// Talk to Scrub by typing, no phone: each line goes to POST /heard like a caller turn. npm run talk
// The browser version (push to talk, spoken replies) is GET /talk on the voice server.
import { createInterface } from "node:readline/promises";
import { LLM_SECRET } from "../src/config.js";  // /heard needs it only through the tunnel

const base = process.env.VOICE_URL || `http://localhost:${process.env.VOICE_PORT || 3000}`;
const rl = createInterface({ input: process.stdin, output: process.stdout });
console.log(`Talking to ${base}/heard. Type what you'd say ("grab me the kelly", "stop"); Ctrl-D to quit.`);
for await (const line of rl) {
  const text = line.trim();
  if (!text) continue;
  const t0 = Date.now();
  try {
    const res = await fetch(`${base}/heard`, { method: "POST", headers: { "content-type": "application/json",
      ...(LLM_SECRET ? { authorization: `Bearer ${LLM_SECRET}` } : {}) }, body: JSON.stringify({ text }) });
    if (res.status === 401) { console.log("401: /heard needs VOICE_LLM_SECRET through the tunnel"); continue; }
    const { say = [] } = await res.json();
    console.log(`Scrub (${Date.now() - t0}ms): ${say.join(" ") || "(nothing)"}`);
  } catch (e) { console.log(`can't reach ${base}: ${(e as Error).message}`); }
}
