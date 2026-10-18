// Photon (Spectrum, stable docs) side of the phone call, over the Spectrum API (spectrum.photon.codes, Basic auth
// with SPECTRUM_PROJECT_ID / SPECTRUM_PROJECT_SECRET).
//   npm run photon -- status              plan, lines, voice platform, SIP inbound route
//   npm run photon -- route               voice platform on, inbound calls -> sips:sip.rtc.elevenlabs.io:5061 (TLS)
//   npm run photon -- setup +1XXXXXXXXXX  route, then add that phone as a user: Photon gives it a line (the number to
//                                         call and text), saved as PHOTON_LINE (and PHOTON_SUMMARY_TO if empty), and
//                                         imported into ElevenLabs as a SIP trunk number with the Scrub agent
// The project is on a shared iMessage plan: there are no project-wide lines, each user gets a line from the pool.
import { readEnv, setEnv } from "./envfile.js";

const env = readEnv();
const PID = env.SPECTRUM_PROJECT_ID || env.PHOTON_PROJECT_ID || "";
const SECRET = env.SPECTRUM_PROJECT_SECRET || env.PHOTON_API_KEY || "";
export const ELEVENLABS_SIP = "sips:sip.rtc.elevenlabs.io:5061";
const redact = (s: string) => [PID, SECRET].filter(Boolean).reduce((t, v) => t.split(v).join("<redacted>"), s);

async function api(method: string, path: string, body?: unknown): Promise<any> {
  const r = await fetch(`https://spectrum.photon.codes/projects/${PID}${path}`, { method,
    headers: { authorization: `Basic ${Buffer.from(`${PID}:${SECRET}`).toString("base64")}`, "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(30_000) });
  const text = await r.text();
  if (!r.ok) throw new Error(`${method} ${path}: HTTP ${r.status} ${redact(text).slice(0, 300)}`);
  return text ? JSON.parse(text).data : null;
}

// +12065550123 -> +1206***0123 (a user's own number is not ours to log in full).
const mask = (p: string) => (p.length > 8 ? `${p.slice(0, 5)}***${p.slice(-4)}` : p);

async function status() {
  const im = await api("GET", "/imessage/");
  const { lines } = await api("GET", "/lines/");
  const platforms = await api("GET", "/platforms/");
  const sip = await api("GET", "/voice/sip-inbound/");
  const { users, total } = await api("GET", "/users/");
  console.log(`[photon] iMessage plan: ${im.type}; dedicated lines: ${lines.length}; users: ${total}`);
  console.log(`[photon] voice platform: ${platforms.voice?.enabled ? "on" : "off"}; inbound SIP: ${sip?.sipUri || "none"}`);
  for (const l of lines) console.log(`LINE ${l.phoneNumber}  (dedicated, ${l.status})`);
  for (const u of users) console.log(`LINE ${u.assignedPhoneNumber}  (shared, for user ${mask(u.phoneNumber)})`);
  if (env.PHOTON_LINE) console.log(`[photon] PHOTON_LINE in .env: ${env.PHOTON_LINE}`);
}

async function route() {
  const platforms = await api("GET", "/platforms/");
  if (!platforms.voice?.enabled) { await api("PATCH", "/platforms/", { platform: "voice", enabled: true }); console.log("[photon] voice platform on"); }
  const sip = await api("GET", "/voice/sip-inbound/");
  if (sip?.sipUri === ELEVENLABS_SIP) console.log(`[photon] inbound SIP already ${ELEVENLABS_SIP}`);
  else { await api("PATCH", "/voice/sip-inbound/", { sipUri: ELEVENLABS_SIP, username: null, password: null }); console.log(`[photon] inbound SIP -> ${ELEVENLABS_SIP} (TLS)`); }
}

async function setup(phone: string) {
  if (!/^\+[1-9]\d{6,14}$/.test(phone)) throw new Error("phone number must look like +12065550123");
  await route();
  const u = await api("POST", "/users/", { type: "shared", phoneNumber: phone });
  const line = u.assignedPhoneNumber;
  console.log(`[photon] user ${mask(phone)} -> line ${line}`);
  console.log(`LINE ${line}`);
  setEnv("PHOTON_LINE", line);
  if (!env.PHOTON_SUMMARY_TO) setEnv("PHOTON_SUMMARY_TO", phone);
  const { importNumber } = await import("./agent.js");
  await importNumber(line);
}

async function main() {
  const [cmd = "status", arg = ""] = process.argv.slice(2);
  if (!PID || !SECRET) return console.log("[photon] skipped: no SPECTRUM_PROJECT_ID / SPECTRUM_PROJECT_SECRET in .env");
  if (cmd === "status") return status();
  if (cmd === "route") return route();
  if (cmd === "setup") return setup(arg);
  console.log("usage: npm run photon -- status | route | setup +1XXXXXXXXXX");
}

main().catch((e) => { console.log(`[photon] ${(e as Error).message}`); process.exit(1); });
