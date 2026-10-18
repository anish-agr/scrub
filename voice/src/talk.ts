// GET /talk: talk to Scrub without a phone. One self-contained page: hold the button (or the space bar) and speak;
// the browser's speech recognition (Chrome, Edge, Safari) gives the words, which go to POST /heard like a caller
// turn, and the `say` lines are spoken with speechSynthesis. A text box works without a microphone.
// Open it on the voice laptop (http://localhost:3000/talk): speech recognition needs localhost or https, and with
// VOICE_LLM_SECRET set, /heard from another machine needs the secret (the page asks for it on a 401).
export const TALK_HTML = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Scrub — talk without a phone</title>
<style>
  :root { --bg: #f6f7f8; --fg: #16191d; --muted: #5d6670; --card: #fff; --line: #d9dde2; --accent: #0b6e4f; --hot: #c0392b; }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #111417; --fg: #e8ebee; --muted: #9aa3ad; --card: #1a1f24; --line: #2c333a; --accent: #2fb385; --hot: #e5604f; }
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--fg); font: 16px/1.45 system-ui, -apple-system, Segoe UI, sans-serif; }
  main { max-width: 640px; margin: 0 auto; padding: 24px 16px 48px; }
  h1 { font-size: 1.4rem; margin: 0 0 4px; }
  p.sub { color: var(--muted); margin: 0 0 20px; }
  #ptt { display: block; width: 100%; padding: 44px 16px; font-size: 1.5rem; font-weight: 650; border: 0; border-radius: 18px;
    background: var(--accent); color: #fff; cursor: pointer; user-select: none; -webkit-user-select: none; touch-action: none; }
  #ptt.on { background: var(--hot); }
  #ptt:disabled { opacity: .5; cursor: not-allowed; }
  form { display: flex; gap: 8px; margin: 16px 0; }
  input { flex: 1; min-width: 0; padding: 12px; font: inherit; border: 1px solid var(--line); border-radius: 10px; background: var(--card); color: var(--fg); }
  button.send { padding: 12px 18px; font: inherit; border: 1px solid var(--line); border-radius: 10px; background: var(--card); color: var(--fg); cursor: pointer; }
  #status { min-height: 1.5em; color: var(--muted); margin: 12px 0; }
  #status.err { color: var(--hot); font-weight: 600; }
  #secret { display: none; }
  #log { list-style: none; padding: 0; margin: 0; border-top: 1px solid var(--line); }
  #log li { padding: 10px 0; border-bottom: 1px solid var(--line); }
  #log .who { display: inline-block; min-width: 4.5em; color: var(--muted); font-size: .85rem; }
  #log .scrub { color: var(--accent); }
  #log .err { color: var(--hot); }
</style>
</head>
<body>
<main>
  <h1>Scrub — talk without a phone</h1>
  <p class="sub">Hold the button (or the space bar) and ask, like on the call: "grab me the kelly", "what's out", "stop".</p>
  <button id="ptt" type="button">Hold to talk</button>
  <div id="status"></div>
  <form id="typed"><input id="text" placeholder="Or type what you'd say" autocomplete="off"><button class="send">Send</button></form>
  <form id="secret"><input id="key" type="password" placeholder="VOICE_LLM_SECRET (needed from another machine)" autocomplete="off"><button class="send">Save</button></form>
  <ul id="log"></ul>
</main>
<script>
const $ = (id) => document.getElementById(id);
const ptt = $("ptt"), status = $("status"), log = $("log");
let key = "";  // only in this tab's memory

function note(text, err) { status.textContent = text; status.className = err ? "err" : ""; }
function add(who, text, cls) {
  const li = document.createElement("li");
  const w = document.createElement("span"); w.className = "who"; w.textContent = who;
  const t = document.createElement("span"); t.textContent = text; if (cls) t.className = cls;
  li.append(w, t); log.prepend(li);
}
function speak(lines) {
  if (!("speechSynthesis" in window) || !lines.length) return;
  speechSynthesis.cancel();
  speechSynthesis.speak(new SpeechSynthesisUtterance(lines.join(" ")));
}

async function send(text) {
  text = text.trim();
  if (!text) return;
  add("you", text);
  note("Scrub is on it...");
  const t0 = performance.now();
  try {
    const res = await fetch("/heard", { method: "POST", headers: { "content-type": "application/json",
      ...(key ? { authorization: "Bearer " + key } : {}) }, body: JSON.stringify({ text }) });
    if (res.status === 401) {
      note("401: this voice server has VOICE_LLM_SECRET set and the request didn't come from the laptop itself. " +
        "Open http://localhost:3000/talk on the voice laptop, or paste the secret below.", true);
      $("secret").style.display = "flex";
      add("scrub", "Refused (401). Needs the secret from this machine.", "err");
      return;
    }
    if (!res.ok) throw new Error("HTTP " + res.status);
    const body = await res.json();
    const lines = Array.isArray(body.say) ? body.say : [];
    add("scrub", lines.join(" ") || "(nothing to say)", "scrub");
    note("Answered in " + Math.round(performance.now() - t0) + " ms");
    speak(lines);
  } catch (e) {
    note("Can't reach the voice server: " + e.message, true);
    add("scrub", "No answer: " + e.message, "err");
  }
}

$("typed").addEventListener("submit", (e) => { e.preventDefault(); send($("text").value); $("text").value = ""; });
$("secret").addEventListener("submit", (e) => { e.preventDefault(); key = $("key").value.trim(); $("secret").style.display = "none"; note("Secret set for this tab. Try again."); });

const Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
let rec = null, heard = "", held = false;
if (!Rec) {
  ptt.disabled = true;
  ptt.textContent = "No speech recognition here";
  note("This browser has no speech recognition (try Chrome or Safari). Type below instead.", true);
} else if (!window.isSecureContext) {
  ptt.disabled = true;
  ptt.textContent = "Microphone needs localhost";
  note("Speech recognition only works on localhost or https. Open http://localhost:3000/talk on the voice laptop, or type below.", true);
} else {
  rec = new Rec();
  rec.lang = "en-US"; rec.interimResults = true; rec.continuous = true;
  rec.onresult = (e) => {
    heard = Array.from(e.results).map((r) => r[0].transcript).join(" ");
    note("Heard: " + heard);
  };
  rec.onerror = (e) => { if (e.error !== "aborted" && e.error !== "no-speech") note("Microphone: " + e.error, true); };
  rec.onend = () => { held = false; ptt.classList.remove("on"); ptt.textContent = "Hold to talk"; const h = heard; heard = ""; send(h); };
}
function down(e) {
  if (!rec || held) return;
  e.preventDefault(); held = true; heard = "";
  speechSynthesis?.cancel();  // talking over Scrub, like on the call
  try { rec.start(); ptt.classList.add("on"); ptt.textContent = "Listening... let go to send"; note("Listening..."); }
  catch (err) { held = false; note("Microphone: " + err.message, true); }
}
function up() { if (!rec || !held) return; held = false; rec.stop(); }
ptt.addEventListener("pointerdown", down);
ptt.addEventListener("pointerup", up);
ptt.addEventListener("pointercancel", up);
ptt.addEventListener("pointerleave", up);
document.addEventListener("keydown", (e) => { if (e.code === "Space" && !e.repeat && document.activeElement?.tagName !== "INPUT") down(e); });
document.addEventListener("keyup", (e) => { if (e.code === "Space" && document.activeElement?.tagName !== "INPUT") up(); });
</script>
</body>
</html>
`;
