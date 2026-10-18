// The ElevenLabs agent that answers the phone. Its LLM is "Custom LLM" = this server's /v1/chat/completions.
//   npm run agent -- https://<tunnel>       create the agent (no ELEVENLABS_AGENT_ID) or point it at this tunnel
//   npm run agent -- status                 the agent, its LLM URL, the phone numbers
//   npm run agent -- import +1XXXXXXXXXX    import the Photon line as a SIP trunk number and assign the agent
//   npm run agent -- test "hemostat"        text-only simulated call through the tunnel (it moves the arm)
// Prints "AGENT <id>" and "PHONE <number>" lines (controller/run_all.py reads them). Never prints a key.
import { randomBytes } from "node:crypto";
import { readEnv, setEnv } from "./envfile.js";

const API = "https://api.elevenlabs.io/v1/convai";
const SECRET_NAME = "scrub_voice_llm";
const LABEL = "Scrub Photon";
const env = readEnv();
const KEY = env.ELEVENLABS_API_KEY || "";
// Photon (Spectrum) outbound SIP: username is the project id, password the project secret (photon.codes/docs voice).
const PHOTON_SIP = "sip.spectrum.photon.codes:5061";
// Error bodies can echo the request (a 422 lists its input): blank every long .env value before printing one.
const secrets = Object.values(env).filter((v) => v && v.length >= 12);
const redact = (s: string) => secrets.reduce((t, v) => t.split(v).join("<redacted>"), s);

export const FIRST_MESSAGE = "Scrub here. What do you need?";
export const CALLER_LINE = "Caller: {{system__caller_id}}";
export const CONVERSATION_LINE = "Conversation: {{system__conversation_id}}";  // the voice server tells overlapping calls apart by it
export const PROMPT = `You are Scrub, a robot arm that passes surgical instruments.\n${CALLER_LINE}\n${CONVERSATION_LINE}`;
// Fast TTS. SIP uses G.711/G.722 whatever the agent's audio formats say (docs: sip-trunking), so formats stay pcm_16000.
export const TTS_MODEL = "eleven_flash_v2";
export const KEYWORDS = ["kelly", "hemostat", "scalpel", "mayo", "scissors", "knife", "stop", "got it", "end of case"];

// "https://x", "https://x/" or "https://x/v1" -> "https://x/v1" (server.ts serves /v1/chat/completions).
export const llmUrl = (base: string) => `${base.trim().replace(/\/+$/, "").replace(/\/v1$/, "")}/v1`;

export function agentBody(base: string, secretId: string | null) {
  return {
    name: "Scrub",
    conversation_config: {
      agent: {
        first_message: FIRST_MESSAGE,
        language: "en",
        prompt: {
          prompt: PROMPT,
          llm: "custom-llm",
          temperature: null,  // our server ignores it
          custom_llm: { url: llmUrl(base), model_id: "scrub", api_type: "chat_completions",
            ...(secretId ? { api_key: { secret_id: secretId } } : {}) },
        },
      },
      asr: { keywords: KEYWORDS },
      tts: { model_id: TTS_MODEL, expressive_mode: false, optimize_streaming_latency: 3 },
      turn: { turn_timeout: 30, turn_eagerness: "eager", soft_timeout_config: { timeout_seconds: -1 } },
      // "interruption" must stay in client_events or the caller can't talk over Scrub ("stop").
      conversation: { max_duration_seconds: 1800,
        client_events: ["audio", "interruption", "agent_response", "user_transcript", "agent_response_correction"] },
    },
    // Open to any caller: no auth/allowlist. No concurrency limit: a rejected call is silent, our server says "Scrub is busy".
    platform_settings: { auth: { enable_auth: false, allowlist: [] }, call_limits: { agent_concurrency_limit: -1 } },
  };
}

async function api(method: string, path: string, body?: unknown): Promise<any> {
  const r = await fetch(`${API}${path}`, { method, headers: { "xi-api-key": KEY, "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(120_000) });
  const text = await r.text();
  if (!r.ok) throw Object.assign(new Error(`${method} ${path}: HTTP ${r.status} ${redact(text).slice(0, 400)}`), { status: r.status });
  return text ? JSON.parse(text) : {};
}

// VOICE_LLM_SECRET guards the public endpoint (it moves the arm). Made here if empty, stored in .env and as an
// ElevenLabs workspace secret, which the agent sends as "Authorization: Bearer <it>".
async function secretId(): Promise<string> {
  let value = env.VOICE_LLM_SECRET || "";
  if (!value) {
    value = randomBytes(24).toString("hex");
    secrets.push(value);
    setEnv("VOICE_LLM_SECRET", value);
    console.log("[agent] made a new VOICE_LLM_SECRET: restart voice/ so it checks it");
  }
  const { secrets: list = [] } = await api("GET", "/secrets");
  const old = list.find((s: any) => s.name === SECRET_NAME);
  if (old) {
    await api("PATCH", `/secrets/${old.secret_id}`, { type: "update", name: SECRET_NAME, value });
    return old.secret_id;
  }
  return (await api("POST", "/secrets", { type: "new", name: SECRET_NAME, value })).secret_id;
}

const numbers = async (): Promise<any[]> => await api("GET", "/phone-numbers");

async function printPhones(agentId: string) {
  for (const n of await numbers()) {
    const mine = n.assigned_agent?.agent_id === agentId;
    console.log(`${mine ? "PHONE" : "phone (other agent)"} ${n.phone_number}  (${n.label}, ${n.provider})`);
  }
}

async function upsert(base: string) {
  const body = agentBody(base, await secretId());
  let id = env.ELEVENLABS_AGENT_ID || "";
  if (id) {
    try { await api("PATCH", `/agents/${id}`, body); console.log(`[agent] updated: Custom LLM ${llmUrl(base)}`); }
    catch (e) { if ((e as any).status !== 404) throw e; console.log("[agent] ELEVENLABS_AGENT_ID not found: creating"); id = ""; }
  }
  if (!id) {
    id = (await api("POST", "/agents/create", body)).agent_id;
    setEnv("ELEVENLABS_AGENT_ID", id);
    console.log(`[agent] created: Custom LLM ${llmUrl(base)}`);
    for (const n of await numbers())  // a re-made agent takes over the Photon number
      if (n.label === LABEL) await api("PATCH", `/phone-numbers/${n.phone_number_id}`, { agent_id: id });
  }
  console.log(`AGENT ${id}`);
  await printPhones(id);
}

async function status() {
  const id = env.ELEVENLABS_AGENT_ID || "";
  if (!id) return console.log("[agent] no ELEVENLABS_AGENT_ID yet: npm run agent -- https://<tunnel>");
  const a = await api("GET", `/agents/${id}`);
  const p = a.conversation_config?.agent?.prompt || {};
  const cc = a.conversation_config || {}, ps = a.platform_settings || {}, yn = (b: boolean) => (b ? "y" : "N");
  console.log(`AGENT ${id}  (${a.name})\n  llm ${p.llm}  url ${p.custom_llm?.url}  key ${p.custom_llm?.api_key ? "secret set" : "none"}`);
  console.log(`  first message "${cc.agent?.first_message}"  tts ${cc.tts?.model_id} (${cc.tts?.agent_output_audio_format}, latency ${cc.tts?.optimize_streaming_latency})`);
  console.log(`  prompt has Caller line ${yn((p.prompt || "").includes(CALLER_LINE))}, Conversation line ${yn((p.prompt || "").includes(CONVERSATION_LINE))}`);
  console.log(`  turn ${cc.turn?.turn_eagerness}, interruption event ${yn((cc.conversation?.client_events || []).includes("interruption"))}, auth ${ps.auth?.enable_auth ? "ON" : "off"}, allowlist ${(ps.auth?.allowlist || []).length}, concurrency limit ${ps.call_limits?.agent_concurrency_limit}`);
  await printPhones(id);
}

export async function importNumber(phone: string) {
  const id = env.ELEVENLABS_AGENT_ID || "";
  if (!/^\+[1-9]\d{6,14}$/.test(phone)) throw new Error("phone number must look like +12065550123");
  if (!id) throw new Error("no ELEVENLABS_AGENT_ID yet: npm run agent -- https://<tunnel> first");
  const old = (await numbers()).find((n) => n.phone_number === phone);
  if (old) {
    await api("PATCH", `/phone-numbers/${old.phone_number_id}`, { agent_id: id });
    console.log(`[agent] ${phone} already imported; assigned to the agent`);
  } else {
    const trunk = env.SPECTRUM_PROJECT_ID && env.SPECTRUM_PROJECT_SECRET
      ? { address: PHOTON_SIP, transport: "tls", media_encryption: "allowed",
          credentials: { username: env.SPECTRUM_PROJECT_ID, password: env.SPECTRUM_PROJECT_SECRET } } : null;
    const r = await api("POST", "/phone-numbers", { provider: "sip_trunk", phone_number: phone, label: LABEL, agent_id: id,
      inbound_trunk_config: { allowed_addresses: ["0.0.0.0/0"], media_encryption: "allowed" },
      ...(trunk ? { outbound_trunk_config: trunk } : {}) });
    console.log(`[agent] imported ${phone} (${r.phone_number_id}) and assigned the agent`);
  }
  await printPhones(id);
}

async function test(said: string) {
  const id = env.ELEVENLABS_AGENT_ID || "";
  if (!id) throw new Error("no ELEVENLABS_AGENT_ID");
  console.log(`[agent] simulated call: the caller says "${said}" (ElevenLabs calls our Custom LLM through the tunnel)`);
  const r = await api("POST", `/agents/${id}/simulate-conversation`, { new_turns_limit: 3, simulation_specification: {
    simulated_user_config: { first_message: "", prompt: { prompt: `You are a surgeon on a call. Your only line is: "${said}". Say it once, then stay silent.` } },
  } });
  for (const t of r.simulated_conversation || []) console.log(`  ${t.role}: ${t.message ?? ""}`);
}

async function main() {
  const [cmd = "status", arg = ""] = process.argv.slice(2);
  if (!KEY) return console.log("[agent] skipped: no ELEVENLABS_API_KEY in .env");
  if (/^https?:\/\//.test(cmd)) return upsert(cmd);
  if (cmd === "status") return status();
  if (cmd === "import") return importNumber(arg);
  if (cmd === "test") return test(process.argv.slice(3).join(" ") || "hemostat");
  console.log("usage: npm run agent -- https://<tunnel> | status | import +1... | test \"hemostat\"");
}

if (process.argv[1]?.endsWith("agent.ts")) main().catch((e) => { console.log(`[agent] ${(e as Error).message}`); process.exit(1); });
