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
  const label = STEP_LABEL[state.step] || state.step || "Idle";
  step.textContent = label;
  step.className = state.step === "stopped" || state.step === "error" ? state.step : state.step && state.step !== "idle" ? "moving" : "";
  document.getElementById("item").textContent = state.item ? nameOf(state.item) : "";
  const held = Array.isArray(state.out) ? state.out : [];
  document.getElementById("out").textContent = held.length ? held.map(nameOf).join(", ") : "Nothing out";
  document.getElementById("link").textContent = "live";
}

async function refresh() {
  try {
    const response = await fetch("/state", { cache: "no-store" });
    if (!response.ok) throw new Error("down");
    paint(await response.json());
  } catch (error) {
    document.getElementById("link").textContent = "not connected";
  }
}

async function post(path) {
  await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  refresh();
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
