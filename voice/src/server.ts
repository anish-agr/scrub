// Voice server, port 3000. The ElevenLabs agent uses this as its Custom LLM (OpenAI chat completions, streamed),
// so every caller turn lands here and Scrub's reply is the controller's `say` lines.
import http from "node:http";
import { LLM_SECRET, VOICE_PORT } from "./config.js";
import { endCase, setCaller } from "./summary.js";
import { handleTurn, startEvents } from "./turn.js";

type Msg = { role: string; content: unknown };

const text = (c: unknown): string =>
  typeof c === "string" ? c : Array.isArray(c) ? c.map((p: any) => p?.text ?? "").join(" ") : "";

function readBody(req: http.IncomingMessage): Promise<any> {
  return new Promise((resolve) => {
    let raw = "";
    req.on("data", (d) => (raw += d));
    req.on("end", () => { try { resolve(raw ? JSON.parse(raw) : {}); } catch { resolve({}); } });
  });
}

function json(res: http.ServerResponse, code: number, body: unknown) {
  res.writeHead(code, { "content-type": "application/json" });
  res.end(JSON.stringify(body));
}

async function chatCompletions(req: http.IncomingMessage, res: http.ServerResponse) {
  if (LLM_SECRET && req.headers.authorization !== `Bearer ${LLM_SECRET}`) return json(res, 401, { error: "bad key" });
  const body = await readBody(req);
  const messages: Msg[] = body.messages || body.input || [];
  // The agent's system prompt carries "Caller: {{system__caller_id}}", so the summary goes to the same thread.
  const sys = messages.filter((m) => m.role === "system").map((m) => text(m.content)).join("\n");
  const phone = sys.match(/caller[^+\d\n]*(\+?\d[\d\s-]{9,16}\d)/i)?.[1]?.replace(/[\s-]/g, "");
  if (phone) setCaller(phone);
  const lastUser = [...messages].reverse().find((m) => m.role === "user");
  const heard = lastUser ? text(lastUser.content).trim() : "";

  const id = `chatcmpl-${Date.now()}`;
  const chunk = (delta: object, finish: string | null = null) =>
    JSON.stringify({ id, object: "chat.completion.chunk", created: Math.floor(Date.now() / 1000), model: "scrub",
      choices: [{ index: 0, delta, finish_reason: finish }] });

  if (body.stream === false) {
    const lines: string[] = [];
    if (heard) await handleTurn(heard, (l) => lines.push(l));
    return json(res, 200, { id, object: "chat.completion", model: "scrub",
      choices: [{ index: 0, message: { role: "assistant", content: lines.join(" ") }, finish_reason: "stop" }] });
  }

  res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache", connection: "keep-alive" });
  res.write(`data: ${chunk({ role: "assistant", content: "" })}\n\n`);
  const abort = new AbortController();
  res.on("close", () => abort.abort()); // caller talked over Scrub: ElevenLabs drops the request
  let first = true;
  if (heard) {
    await handleTurn(heard, (line) => {
      if (res.writableEnded) return;
      res.write(`data: ${chunk({ content: (first ? "" : " ") + line })}\n\n`);
      first = false;
    }, abort.signal);
  }
  if (!res.writableEnded) {
    res.write(`data: ${chunk({}, "stop")}\n\n`);
    res.end("data: [DONE]\n\n");
  }
}

const server = http.createServer(async (req, res) => {
  const url = (req.url || "").split("?")[0];
  try {
    if (req.method === "POST" && url.endsWith("/chat/completions")) return await chatCompletions(req, res);
    // Testing without a call: {"text": "grab me the kelly"} -> the lines Scrub would say.
    if (req.method === "POST" && url === "/heard") {
      const { text: heard = "" } = await readBody(req);
      const lines: string[] = [];
      await handleTurn(String(heard), (l) => lines.push(l));
      return json(res, 200, { heard, say: lines });
    }
    if (req.method === "POST" && url === "/summary") return json(res, 200, await endCase());
    if (req.method === "GET" && url === "/health") return json(res, 200, { ok: true });
    json(res, 404, { error: "not found" });
  } catch (e) {
    console.log(`[server] ${(e as Error).message}`);
    if (!res.headersSent) json(res, 500, { error: (e as Error).message });
    else res.end();
  }
});

startEvents();
server.listen(VOICE_PORT, () => console.log(`[voice] listening on :${VOICE_PORT} (POST /v1/chat/completions, /heard, /summary)`));
