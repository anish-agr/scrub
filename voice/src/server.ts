// Voice server, port 3000. The ElevenLabs agent uses this as its Custom LLM (OpenAI chat completions, streamed),
// so every caller turn lands here and Scrub's reply is the controller's `say` lines.
import http from "node:http";
import { callerFrom, chunk, heardFrom, type Msg } from "./chat.js";
import { GEMINI_API_KEY, LLM_SECRET, PHOTON_PROJECT_ID, PHOTON_SECRET, VOICE_PORT } from "./config.js";
import { controllerUp } from "./controller.js";
import { endCase, setCaller } from "./summary.js";
import { startTexts } from "./texts.js";
import { handleTurn, startEvents } from "./turn.js";

function readBody(req: http.IncomingMessage): Promise<any> {
  return new Promise((resolve) => {
    let raw = "";
    req.on("data", (d) => { raw += d; if (raw.length > 1_000_000) { req.destroy(); resolve({}); } });  // a chat turn is a few KB
    req.on("end", () => { try { resolve(raw ? JSON.parse(raw) : {}); } catch { resolve({}); } });
    req.on("error", () => resolve({}));  // caller hung up mid-body
  });
}

// With VOICE_LLM_SECRET set, /heard and /summary (they move the arm and send a text) need it too when the request
// came through the tunnel. Plain local curl (loopback, no forwarding header) still works without it.
function allowed(req: http.IncomingMessage): boolean {
  if (!LLM_SECRET || req.headers.authorization === `Bearer ${LLM_SECRET}`) return true;
  const local = ["127.0.0.1", "::1", "::ffff:127.0.0.1"].includes(req.socket.remoteAddress || "");
  const forwarded = ["x-forwarded-for", "x-real-ip", "cf-connecting-ip", "forwarded"].some((h) => h in req.headers);
  return local && !forwarded;
}

function json(res: http.ServerResponse, code: number, body: unknown) {
  res.writeHead(code, { "content-type": "application/json" });
  res.end(JSON.stringify(body));
}

async function chatCompletions(req: http.IncomingMessage, res: http.ServerResponse) {
  if (LLM_SECRET && req.headers.authorization !== `Bearer ${LLM_SECRET}`) {
    console.log("[server] 401: Authorization doesn't match VOICE_LLM_SECRET");
    return json(res, 401, { error: "bad key" });
  }
  const body = await readBody(req);
  const messages: Msg[] = Array.isArray(body.messages) ? body.messages : [];
  // The agent's system prompt carries "Caller: {{system__caller_id}}", so the summary goes to the same thread.
  setCaller(callerFrom(messages));
  const heard = heardFrom(messages);
  const id = `chatcmpl-${Date.now()}`;

  if (body.stream === false) {
    const lines: string[] = [];
    if (heard) await handleTurn(heard, (l) => lines.push(l));
    return json(res, 200, { id, object: "chat.completion", created: Math.floor(Date.now() / 1000), model: "scrub",
      choices: [{ index: 0, message: { role: "assistant", content: lines.join(" ") }, finish_reason: "stop" }] });
  }

  res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache", connection: "keep-alive" });
  res.write(chunk(id, { role: "assistant", content: "" }));  // first bytes now, before the controller answers
  const abort = new AbortController();
  res.on("close", () => abort.abort()); // caller talked over Scrub: ElevenLabs drops the request
  let first = true;
  if (heard) {
    await handleTurn(heard, (line) => {
      if (res.writableEnded) return;
      res.write(chunk(id, { content: (first ? "" : " ") + line }));
      first = false;
    }, abort.signal);
  }
  if (!res.writableEnded) {
    res.write(chunk(id, {}, "stop"));
    res.end("data: [DONE]\n\n");
  }
}

const server = http.createServer(async (req, res) => {
  const url = (req.url || "").split("?")[0];
  try {
    if (req.method === "POST" && url.endsWith("/chat/completions")) return await chatCompletions(req, res);
    // Testing without a call: {"text": "grab me the kelly"} -> the lines Scrub would say.
    if (req.method === "POST" && (url === "/heard" || url === "/summary") && !allowed(req)) {
      console.log(`[server] 401 ${url}: needs VOICE_LLM_SECRET through the tunnel`);
      return json(res, 401, { error: "bad key" });
    }
    if (req.method === "POST" && url === "/heard") {
      const { text: heard = "" } = await readBody(req);
      const lines: string[] = [];
      await handleTurn(String(heard), (l) => lines.push(l));
      return json(res, 200, { heard, say: lines });
    }
    if (req.method === "POST" && url === "/summary") return json(res, 200, await endCase());
    // Which keys are set (booleans only, never values) and whether the controller answers.
    if (req.method === "GET" && url === "/health") return json(res, 200, { ok: true,
      keys: { gemini: !!GEMINI_API_KEY, photon: !!(PHOTON_PROJECT_ID && PHOTON_SECRET), llm_secret: !!LLM_SECRET },
      controller: await controllerUp() });
    console.log(`[server] 404 ${req.method} ${url}`);  // a wrong Custom LLM URL shows up here
    json(res, 404, { error: "not found" });
  } catch (e) {
    console.log(`[server] ${(e as Error).message}`);
    if (!res.headersSent) json(res, 500, { error: (e as Error).message });
    else res.end();
  }
});

startEvents();
startTexts();
server.listen(VOICE_PORT, () => console.log(`[voice] listening on :${VOICE_PORT} (POST /v1/chat/completions, /heard, /summary, GET /health)`));
