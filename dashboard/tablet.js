const STEP_LABEL = {
  idle: "Idle",
  finding: "Finding",
  picking: "Picking",
  checking: "Checking grasp",
  moving_to_hand: "Moving to hand",
  setting_down: "Setting down",
  waiting_for_pull: "Waiting for pull",
  releasing: "Releasing",
  homing: "Homing",
  returning: "Returning",
  stopped: "Stopped",
  error: "Error",
};

let noticeUntil = 0;
let lastSource = null;

function sourceLabel(source) {
  return source === "taught" ? "taught skill" : source === "model" ? "model" : "";
}

const NAMES = {
  scalpel: "scalpel",
  hemostat: "hemostat",
  mayo_scissors: "mayo scissors",
  mouth_mirror: "mouth mirror",
  explorer: "explorer",
  cotton_pliers: "cotton pliers",
  needle_nose_pliers: "needle-nose pliers",
  wire_cutters: "wire cutters",
  hex_key: "hex key",
};

function nameOf(itemId) {
  return NAMES[itemId] || String(itemId || "").replaceAll("_", " ");
}

function paint(state) {
  const step = document.getElementById("step");
  const stepName = STEP_LABEL[state.step] || state.step || "Idle";
  step.textContent = stepName;
  step.className = state.step === "stopped" || state.step === "error" ? state.step : state.step && state.step !== "idle" ? "moving" : "";
  if (state.skill_source) lastSource = state.skill_source;
  if (!state.item) lastSource = null;
  const label = state.item ? sourceLabel(lastSource) : "";
  document.getElementById("item").textContent = state.item ? nameOf(state.item) + (label ? ` · ${label}` : "") : "";
  const held = Array.isArray(state.out) ? state.out : [];
  document.getElementById("out").textContent = held.length ? held.map(nameOf).join(", ") : "Nothing out";
  if (Date.now() >= noticeUntil) {
    const link = document.getElementById("link");
    link.textContent = "live";
    link.className = "link live";
  }
  const halted = state.step === "stopped" || state.step === "error";
  document.getElementById("reset").hidden = !halted;
  const banner = document.getElementById("stopped-banner");
  banner.hidden = !halted;
  banner.textContent = state.step === "error" ? "ARM FROZEN. A person must reset." : "STOPPED. A person must reset the arm.";
}

function notice(text) {
  document.getElementById("link").textContent = text;
  noticeUntil = Date.now() + 2500;
}

async function recentSource() {
  try {
    const response = await fetch("/events/recent?n=12", { cache: "no-store", signal: AbortSignal.timeout(2000) });
    const events = await response.json();
    const found = events.filter((event) => event.skill_source).pop();
    return found ? found.skill_source : null;
  } catch (error) {
    return null;
  }
}

async function refresh() {
  try {
    const response = await fetch("/state", { cache: "no-store", signal: AbortSignal.timeout(3000) });
    if (!response.ok) throw new Error("down");
    const state = await response.json();
    if (state.item && !state.skill_source) state.skill_source = await recentSource();
    paint(state);
  } catch (error) {
    const link = document.getElementById("link");
    link.textContent = "not connected";
    link.className = "link bad";
  }
}

async function post(path) {
  try {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    if (!response.ok) {
      notice("wait until the arm is idle");
      return;
    }
    noticeUntil = 0;
    refresh();
  } catch (error) {
    document.getElementById("link").textContent = "not connected";
  }
}

document.getElementById("stop").addEventListener("click", () => post("/stop"));
document.getElementById("reset").addEventListener("click", () => post("/reset"));
document.addEventListener("keydown", (event) => {
  if (event.code !== "Space" || event.repeat) return;
  if (event.target && event.target.tagName === "BUTTON") return;
  event.preventDefault();
  post("/stop");
});

refresh();
setInterval(refresh, 400);
