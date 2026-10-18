// GET /talk: talk to Scrub without a phone. One self-contained page that is always listening while it is open
// (after the browser's one-time microphone permission): the browser's speech recognition (Chrome, Edge, Safari)
// gives each finished phrase, which goes to POST /heard like a caller turn, and the `say` lines are spoken with
// speechSynthesis (listening pauses while Scrub talks, so it doesn't hear itself). One button pauses/resumes.
// A text box works without a microphone.
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
  <p class="sub">Always listening while this page is open. Just talk, like on the call: "get the hemostat", "let go", "stop".</p>
  <button id="ptt" type="button">Starting the microphone...</button>
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
let talking = false;  // Scrub is speaking: don't listen to ourselves
function speak(lines) {
  if (!("speechSynthesis" in window) || !lines.length) return;
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(lines.join(" "));
  talking = true; pauseRec();
  u.onend = u.onerror = () => { talking = false; resumeRec(); };
  speechSynthesis.speak(u);
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
let rec = null, listening = false, paused = false, running = false;
function show() {
  ptt.classList.toggle("on", listening && running && !talking);
  ptt.textContent = paused ? "Paused - click to listen" : (talking ? "Scrub is talking..." : (running ? "Listening - click to pause" : "Click to start listening"));
}
function pauseRec() { if (rec && running) { try { rec.stop(); } catch (e) {} } show(); }
function resumeRec() {
  if (!rec || paused || talking || running) return show();
  try { rec.start(); running = true; listening = true; } catch (e) { /* already starting */ }
  show();
}
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
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const r = e.results[i];
      if (r.isFinal) send(r[0].transcript);   // each finished phrase goes to Scrub right away
      else note("Hearing: " + r[0].transcript);
    }
  };
  rec.onerror = (e) => {
    if (e.error === "not-allowed" || e.error === "service-not-allowed") {
      paused = true; note("Microphone blocked: allow it in the address bar, then click the button.", true);
    } else if (e.error !== "aborted" && e.error !== "no-speech") note("Microphone: " + e.error, true);
  };
  rec.onend = () => { running = false; setTimeout(resumeRec, 250); };  // the browser stops after a while: start again
  resumeRec();
  if (!running) note("Click the button once to let the browser use the microphone.");
}
ptt.addEventListener("click", () => {
  paused = !paused;
  if (paused) { pauseRec(); note("Paused. Click to listen again."); }
  else { speechSynthesis?.cancel(); talking = false; resumeRec(); note("Listening..."); }
  show();
});
</script>
</body>
</html>
`;
