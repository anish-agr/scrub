// Pretend to be the ElevenLabs agent: send one caller turn to the voice server's custom-LLM endpoint
// and print the streamed reply. Usage: npm run say -- "grab me the kelly"
const heard = process.argv.slice(2).join(" ") || "grab me the kelly";
const port = process.env.VOICE_PORT || 3000;
const res = await fetch(`http://localhost:${port}/v1/chat/completions`, {
  method: "POST",
  headers: { "content-type": "application/json", authorization: `Bearer ${process.env.VOICE_LLM_SECRET || ""}` },
  body: JSON.stringify({ model: "scrub", stream: true, messages: [
    { role: "system", content: "You are Scrub. Caller: +15555550123" },
    { role: "user", content: heard },
  ] }),
});
const t0 = Date.now();
let reply = "";
const decoder = new TextDecoder();
for await (const part of res.body as any) {
  for (const line of decoder.decode(part).split("\n")) {
    if (!line.startsWith("data: ") || line.includes("[DONE]")) continue;
    const d = JSON.parse(line.slice(6)).choices[0].delta.content;
    if (d) { reply += d; console.log(`+${((Date.now() - t0) / 1000).toFixed(1)}s  ${d.trim()}`); }
  }
}
console.log(`Scrub says: "${reply}"`);
