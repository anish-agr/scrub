const SETTINGS = {
  surgical: {
    id: "surgical",
    label: "Operating room",
    items: [
      { id: "scalpel", name: "scalpel", sharp: true },
      { id: "hemostat", name: "hemostat", sharp: false },
      { id: "mayo_scissors", name: "mayo scissors", sharp: false },
    ],
  },
  dental: {
    id: "dental",
    label: "Dental office",
    items: [
      { id: "mouth_mirror", name: "mouth mirror", sharp: false },
      { id: "explorer", name: "explorer", sharp: false },
      { id: "cotton_pliers", name: "cotton pliers", sharp: false },
    ],
  },
  bench: {
    id: "bench",
    label: "Robotics bench",
    items: [
      { id: "needle_nose_pliers", name: "needle-nose pliers", sharp: false },
      { id: "wire_cutters", name: "wire cutters", sharp: false },
      { id: "hex_key", name: "hex key", sharp: false },
    ],
  },
};

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

const model = {
  live: false,
  step: "idle",
  item: null,
  queue: [],
  out: [],
  setting: "surgical",
  lighting: "normal",
  fakeArm: null,
  handSeen: null,
  handoff: null,
  events: [],
  catalog: SETTINGS.surgical,
};

let socket = null;
let pollTimer = null;
let fakeTimers = [];
let samplePlayed = false;

const $ = (id) => document.getElementById(id);

function nameOf(itemId) {
  if (!itemId) return "";
  const found = model.catalog.items.find((item) => item.id === itemId);
  return found ? found.name : itemId.replaceAll("_", " ");
}

function clock(t) {
  const date = new Date((t || Date.now() / 1000) * 1000);
  return date.toLocaleTimeString([], { hour12: false });
}

function eventKey(event) {
  return [event.type, event.item, event.step, event.t].join("|");
}

function render() {
  const step = $("step");
  step.textContent = STEP_LABEL[model.step] || model.step;
  step.className = "";
  if (model.step === "stopped" || model.step === "error") step.classList.add(model.step);
  else if (model.step !== "idle") step.classList.add("moving");

  const itemLine = $("step-item");
  itemLine.textContent = model.item ? nameOf(model.item) : "";

  $("hand-seen").textContent = model.handSeen == null ? "—" : model.handSeen ? "seen" : "lost";
  $("queue").textContent = String(model.queue.length);
  $("arm-mode").textContent = model.fakeArm == null ? "—" : model.fakeArm ? "fake" : "real";
  $("handoff").textContent = model.handoff == null ? "—" : `${model.handoff.toFixed(1)}s`;

  const out = $("out");
  out.replaceChildren();
  if (!model.out.length) {
    const empty = document.createElement("li");
    empty.className = "empty";
    empty.textContent = "Nothing out";
    out.appendChild(empty);
  } else {
    model.out.forEach((itemId) => {
      const li = document.createElement("li");
      li.textContent = nameOf(itemId);
      out.appendChild(li);
    });
  }

  const log = $("log");
  const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 24;
  log.replaceChildren();
  model.events.forEach((event) => {
    const li = document.createElement("li");
    const time = document.createElement("time");
    time.textContent = clock(event.t);
    const kind = document.createElement("span");
    kind.className = "kind";
    kind.textContent = event.type;
    const detail = document.createElement("span");
    const bits = [];
    if (event.item) bits.push(nameOf(event.item));
    if (event.step) bits.push(STEP_LABEL[event.step] || event.step);
    if (event.say) bits.push(event.say);
    if (event.request_to_hand_s != null) bits.push(`${Number(event.request_to_hand_s).toFixed(1)}s`);
    detail.textContent = bits.join(" · ");
    if (event.say) detail.classList.add("say");
    li.append(time, kind, detail);
    log.appendChild(li);
  });
  if (atBottom) log.scrollTop = log.scrollHeight;

  const pill = $("link-pill");
  pill.textContent = model.live ? "live" : "sample";
  pill.className = model.live ? "pill live" : "pill offline";

  $("setting").value = model.setting;
  $("lighting").value = model.lighting;
  renderItems();
}

let itemsKey = "";

function renderItems() {
  const key = model.catalog.items.map((item) => `${item.id}:${item.sharp ? 1 : 0}:${item.name}`).join("|");
  if (key === itemsKey) return;
  itemsKey = key;
  const row = $("items");
  row.replaceChildren();
  model.catalog.items.forEach((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.action = "handover";
    button.dataset.item = item.id;
    button.textContent = item.sharp ? `${item.name} (safe spot)` : item.name;
    row.appendChild(button);
  });
}

function fillSettings() {
  const select = $("setting");
  select.replaceChildren();
  Object.values(SETTINGS).forEach((setting) => {
    const option = document.createElement("option");
    option.value = setting.id;
    option.textContent = setting.label;
    select.appendChild(option);
  });
}

function applyState(state) {
  model.step = state.step || "idle";
  model.item = state.item || null;
  model.queue = Array.isArray(state.queue) ? state.queue : [];
  model.out = Array.isArray(state.out) ? state.out : [];
  if (state.setting && SETTINGS[state.setting]) {
    model.setting = state.setting;
    model.catalog = SETTINGS[state.setting];
  }
  if (state.lighting) model.lighting = state.lighting;
  model.fakeArm = Boolean(state.fake_arm);
  model.handSeen = Boolean(state.hand_seen);
  render();
}

function pushEvent(event) {
  if (!event || !event.type) return;
  const key = eventKey(event);
  if (model.events.some((existing) => eventKey(existing) === key)) return;
  model.events.push(event);
  if (model.events.length > 80) model.events.shift();
  if (event.step) model.step = event.step;
  if (event.item) model.item = event.item;
  if (event.request_to_hand_s != null) model.handoff = Number(event.request_to_hand_s);
  if (event.type === "handed" || event.type === "set_down") {
    if (event.item && !model.out.includes(event.item)) model.out.push(event.item);
  }
  if (event.type === "returned" && event.item) {
    const index = model.out.indexOf(event.item);
    if (index >= 0) model.out.splice(index, 1);
  }
  render();
}

function clearFakeTimers() {
  fakeTimers.forEach((timer) => clearTimeout(timer));
  fakeTimers = [];
}

function sampleScript(action, item) {
  const setting = model.setting;
  const lighting = model.lighting;
  const id = `sample-${Date.now()}`;
  const base = { setting, lighting, command_id: id, retries: 0 };
  const now = Date.now() / 1000;
  if (action === "count") {
    const names = model.out.map(nameOf);
    const say = names.length ? `${names.length} out: ${names.join(" and ")}` : "Nothing out";
    return [{ at: 0, event: { ...base, type: "count", item: null, step: model.step, say, t: now } }];
  }
  if (action === "got_it") {
    return [{ at: 0, event: { ...base, type: "released", item: model.item, step: "releasing", say: "got it", t: now } }];
  }
  if (action === "return") {
    const back = model.out[0] || null;
    return [
      { at: 0, event: { ...base, type: "command", item: back, step: "returning", say: back ? `returning the ${nameOf(back)}` : "return spot is empty", t: now } },
      { at: 0.7, event: { ...base, type: "returned", item: back, step: "homing", say: null, t: now + 0.7 } },
      { at: 1.3, event: { ...base, type: "step", item: null, step: "idle", say: null, t: now + 1.3 } },
    ];
  }
  const sharp = model.catalog.items.some((entry) => entry.id === item && entry.sharp);
  const say = sharp ? `${nameOf(item)} down` : `${nameOf(item)} coming`;
  const steps = sharp
    ? [
        ["command", "finding", say],
        ["step", "picking", null],
        ["picked", "checking", null],
        ["set_down", "setting_down", say],
        ["step", "homing", null],
        ["step", "idle", null],
      ]
    : [
        ["command", "finding", say],
        ["step", "picking", null],
        ["picked", "checking", null],
        ["step", "moving_to_hand", null],
        ["handed", "waiting_for_pull", null],
        ["released", "releasing", null],
        ["step", "homing", null],
        ["step", "idle", null],
      ];
  return steps.map(([type, step, line], index) => ({
    at: index * 0.55,
    event: {
      ...base,
      type,
      item: step === "idle" || step === "homing" ? null : item,
      step,
      say: line,
      request_to_hand_s: type === "handed" ? 3.2 : null,
      t: now + index * 0.55,
    },
  }));
}

function playSample(action, item) {
  clearFakeTimers();
  if (!samplePlayed) {
    model.events = [];
    model.out = [];
    model.step = "idle";
    model.item = null;
    model.handoff = null;
    samplePlayed = true;
  }
  const script = sampleScript(action, item);
  script.forEach((beat) => {
    const timer = setTimeout(() => {
      if (model.live) return;
      pushEvent(beat.event);
      if (beat.event.step === "idle") model.item = null;
    }, beat.at * 1000);
    fakeTimers.push(timer);
  });
}

function showSampleList() {
  model.live = false;
  model.fakeArm = true;
  model.handSeen = true;
  model.setting = "surgical";
  model.catalog = SETTINGS.surgical;
  model.lighting = "normal";
  model.step = "idle";
  model.item = null;
  model.queue = [];
  model.out = ["hemostat"];
  model.handoff = 6.4;
  const start = Date.now() / 1000 - 8;
  const beats = [
    ["command", "hemostat", "finding", "hemostat coming", null],
    ["step", "hemostat", "picking", null, null],
    ["picked", "hemostat", "checking", null, null],
    ["step", "hemostat", "moving_to_hand", null, null],
    ["handed", "hemostat", "waiting_for_pull", null, 6.4],
    ["released", "hemostat", "releasing", null, null],
    ["step", null, "homing", null, null],
    ["step", null, "idle", null, null],
  ];
  model.events = beats.map(([type, item, step, say, seconds], index) => ({
    type,
    item,
    step,
    say,
    request_to_hand_s: seconds,
    retries: 0,
    setting: "surgical",
    lighting: "normal",
    command_id: "sample",
    t: start + index,
  }));
  $("banner").hidden = false;
  $("banner").textContent = "Controller is not running. This is a sample handover. Commands play locally until it is up.";
  render();
}

async function postJson(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body == null ? "{}" : JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`${path} ${response.status}`);
  return response.json();
}

async function sendCommand(action, item) {
  if (!model.live) {
    if (action === "stop") return stopLocal();
    playSample(action, item || null);
    return;
  }
  const command = {
    id: crypto.randomUUID(),
    action,
    item: item || null,
    heard: item ? nameOf(item) : action,
    source: "dashboard",
    t: Date.now() / 1000,
  };
  try {
    const result = await postJson("/command", command);
    if (result && result.accepted === false && result.reason) {
      pushEvent({
        type: "error",
        item: item || null,
        step: model.step,
        say: result.reason,
        setting: model.setting,
        lighting: model.lighting,
        command_id: command.id,
        t: Date.now() / 1000,
      });
    }
  } catch (error) {
    pushEvent({
      type: "error",
      item: null,
      step: "error",
      say: "command failed",
      setting: model.setting,
      lighting: model.lighting,
      t: Date.now() / 1000,
    });
  }
}

function stopLocal() {
  clearFakeTimers();
  model.step = "stopped";
  model.item = null;
  pushEvent({
    type: "stopped",
    item: null,
    step: "stopped",
    say: "stopped",
    setting: model.setting,
    lighting: model.lighting,
    t: Date.now() / 1000,
  });
}

async function stopArm() {
  if (!model.live) {
    stopLocal();
    return;
  }
  try {
    await postJson("/stop", null);
  } catch (error) {
    pushEvent({
      type: "error",
      item: null,
      step: "error",
      say: "stop failed",
      setting: model.setting,
      lighting: model.lighting,
      t: Date.now() / 1000,
    });
  }
}

function openSocket() {
  if (socket) socket.close();
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${protocol}://${location.host}/events`);
  socket.onmessage = (message) => {
    try {
      const payload = JSON.parse(message.data);
      const events = Array.isArray(payload) ? payload : [payload];
      events.forEach(pushEvent);
    } catch (error) {
      /* ignore a malformed frame */
    }
  };
  socket.onclose = () => {
    if (model.live) setTimeout(openSocket, 1000);
  };
}

async function pollState() {
  try {
    const response = await fetch("/state", { cache: "no-store" });
    if (!response.ok) return;
    applyState(await response.json());
  } catch (error) {
    /* keep the last state on a missed poll */
  }
}

async function changeSetting(settingId) {
  model.setting = settingId;
  model.catalog = SETTINGS[settingId] || SETTINGS.surgical;
  render();
  if (!model.live) return;
  try {
    const loaded = await postJson("/setting", { setting: settingId });
    if (loaded && loaded.id && SETTINGS[loaded.id]) {
      model.catalog = {
        ...SETTINGS[loaded.id],
        items: loaded.items || SETTINGS[loaded.id].items,
      };
      render();
    }
  } catch (error) {
    /* picker already shows the choice */
  }
}

async function changeLighting(lighting) {
  model.lighting = lighting;
  render();
  if (!model.live) return;
  try {
    await postJson("/lighting", { lighting, lux: null });
  } catch (error) {
    /* picker already shows the choice */
  }
}

function onCamera() {
  const image = $("camera");
  const frame = image.parentElement;
  const show = () => frame.classList.add("has-stream");
  const hide = () => frame.classList.remove("has-stream");
  image.addEventListener("load", show);
  image.addEventListener("error", hide);
  if (image.complete) {
    if (image.naturalWidth > 0) show();
    else hide();
  }
}

function wire() {
  fillSettings();
  onCamera();
  $("stop").addEventListener("click", stopArm);
  $("setting").addEventListener("change", (event) => changeSetting(event.target.value));
  $("lighting").addEventListener("change", (event) => changeLighting(event.target.value));
  document.body.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button || button.id === "stop") return;
    sendCommand(button.dataset.action, button.dataset.item || null);
  });
  document.addEventListener("keydown", (event) => {
    if (event.code !== "Space" || event.repeat) return;
    const tag = event.target && event.target.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    event.preventDefault();
    stopArm();
  });
}

async function connect() {
  wire();
  try {
    const response = await fetch("/state", { cache: "no-store", signal: AbortSignal.timeout(800) });
    if (!response.ok) throw new Error("no state");
    model.live = true;
    model.events = [];
    $("banner").hidden = true;
    applyState(await response.json());
    openSocket();
    pollTimer = setInterval(pollState, 400);
  } catch (error) {
    showSampleList();
  }
}

connect();
