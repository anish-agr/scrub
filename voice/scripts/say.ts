// Pretend to be the ElevenLabs agent: send one caller turn to the voice server's custom-LLM endpoint
// and print the streamed reply with timings. Usage: npm run say -- "grab me the kelly"
// Through the tunnel: VOICE_URL=https://<tunnel> npm run say -- "stop"
const heard = process.argv.slice(2).join(" ") || "grab me the kelly";
const base = process.env.VOICE_URL || `http://localhost:${process.env.VOICE_PORT || 3000}`;
const t0 = Date.now();
const ms = () => `+${Date.now() - t0}ms`;
const res = await fetch(`${base}/v1/chat/completions`, {
  method: "POST",
  headers: { "content-type": "application/json", authorization: `Bearer ${process.env.VOICE_LLM_SECRET || ""}` },
  body: JSON.stringify({ model: "scrub", stream: true, messages: [
    { role: "system", content: "You are Scrub. Caller: +15555550123" },
    { role: "user", content: heard },
  ] }),
});
console.log(`${ms()}  HTTP ${res.status}`);
let reply = "";
const decoder = new TextDecoder();
for await (const part of res.body as any) {
  for (const line of decoder.decode(part).split("\n")) {
    if (!line.startsWith("data: ") || line.includes("[DONE]")) continue;
    const d = JSON.parse(line.slice(6)).choices[0].delta;
    if (d.role) console.log(`${ms()}  first chunk (role)`);
    if (d.content) { reply += d.content; console.log(`${ms()}  ${d.content.trim()}`); }
  }
}
console.log(`${ms()}  done. Scrub says: "${reply}"`);
