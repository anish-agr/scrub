// What ElevenLabs sends to its Custom LLM (OpenAI chat completions) and the chunks we stream back.
// Request: { model, messages: [{role: system|user|assistant|tool, content}], stream: true, tools?, temperature?,
// max_tokens?, user_id?, elevenlabs_extra_body? }. Reply: `data: {chat.completion.chunk}\n\n` ... `data: [DONE]\n\n`.

export type Msg = { role: string; content: unknown };

// content is a string, or (OpenAI style) an array of {type: "text", text} parts.
export const text = (c: unknown): string =>
  typeof c === "string" ? c : Array.isArray(c) ? c.map((p: any) => p?.text ?? "").join(" ") : "";

// The agent's system prompt carries "Caller: {{system__caller_id}}". Unfilled ("{{...}}") or empty gives "".
export function callerFrom(messages: Msg[]): string {
  const sys = messages.filter((m) => m.role === "system").map((m) => text(m.content)).join("\n");
  return sys.match(/caller[^+\d\n]*(\+?\d[\d\s().-]{8,18}\d)/i)?.[1]?.replace(/[\s().-]/g, "") || "";
}

// Which call this turn belongs to. The agent's system prompt carries "Conversation: {{system__conversation_id}}";
// elevenlabs_extra_body.conversation_id or a "conv_..." user_id also count. Unfilled ("{{...}}") or missing gives ""
// (unknown: simulated calls, /heard, `npm run say`), and an unknown call is never kept waiting.
export function conversationFrom(messages: Msg[], body: { elevenlabs_extra_body?: unknown; user_id?: unknown } = {}): string {
  const sys = messages.filter((m) => m.role === "system").map((m) => text(m.content)).join("\n");
  // An id has a digit or "_" in it ("conv_01jx..."): "Conversation: keep it short" elsewhere in the prompt is not one.
  const fromPrompt = [...sys.matchAll(/conversation(?:[ _]?id)?\s*:\s*([A-Za-z0-9_-]{4,})/gi)].map((m) => m[1]).find((v) => /[\d_]/.test(v));
  if (fromPrompt) return fromPrompt;
  const extra = body.elevenlabs_extra_body as Record<string, unknown> | null | undefined;
  const fromExtra = extra && typeof extra === "object" ? extra.conversation_id ?? extra.conversationId : undefined;
  if (typeof fromExtra === "string" && /^[A-Za-z0-9_-]{4,}$/.test(fromExtra)) return fromExtra;
  return typeof body.user_id === "string" && /^conv_[A-Za-z0-9_-]+$/.test(body.user_id) ? body.user_id : "";
}

// The words to act on: the last message, only if the caller said it. ElevenLabs also asks for a reply after
// silence or a tool result; acting on the previous user line there would send the same command twice.
export function heardFrom(messages: Msg[]): string {
  const last = messages.filter((m) => m.role !== "system").at(-1);
  return last?.role === "user" ? text(last.content).trim() : "";
}

export const chunk = (id: string, delta: object, finish: string | null = null) =>
  `data: ${JSON.stringify({ id, object: "chat.completion.chunk", created: Math.floor(Date.now() / 1000), model: "scrub",
    choices: [{ index: 0, delta, finish_reason: finish }] })}\n\n`;
