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

const SHOWN_SETTINGS = ["surgical", "bench"];

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
  serverCatalog: null,
  settingPending: false,
  link: "connecting",
};

let socket = null;
let pollTimer = null;
let statsTimer = null;
let fakeTimers = [];
let samplePlayed = false;

const $ = (id) => document.getElementById(id);

function nameOf(itemId) {
  if (!itemId) return "";
  const found = model.catalog.items.find((item) => item.id === itemId);
  return found ? found.name : String(itemId).replaceAll("_", " ");
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
  $("lighting-now").textContent = model.lighting || "—";
  $("handoff").textContent = model.handoff == null ? "—" : `${model.handoff.toFixed(1)}s`;
  const recent = model.events
    .filter((event) => event.request_to_hand_s != null)
    .slice(-6)
    .map((event) => seconds(event.request_to_hand_s));
  $("handoffs").textContent = recent.length ? `Recent handoffs ${recent.join(", ")}` : "";
  const reset = $("reset");
  if (reset) reset.hidden = !(model.live && (model.step === "stopped" || model.step === "error"));

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
  if (!model.events.length) {
    const empty = document.createElement("li");
    empty.className = "empty";
    empty.textContent = "No events yet.";
    log.appendChild(empty);
  }
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
    if (event.request_to_hand_s != null && !Number.isNaN(Number(event.request_to_hand_s))) {
      bits.push(`${Number(event.request_to_hand_s).toFixed(1)}s`);
    }
    detail.textContent = bits.join(" · ");
    if (event.say) detail.classList.add("say");
    li.append(time, kind, detail);
    log.appendChild(li);
  });
  if (atBottom) log.scrollTop = log.scrollHeight;

  const pill = $("link-pill");
  if (!model.live) {
    pill.textContent = "sample";
    pill.className = "pill offline";
  } else if (model.link === "live") {
    pill.textContent = "live";
    pill.className = "pill live";
  } else {
    pill.textContent = model.link === "reconnecting" ? "reconnecting" : "connecting";
    pill.className = "pill offline";
  }

  if (SHOWN_SETTINGS.includes(model.setting)) $("setting").value = model.setting;
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
  SHOWN_SETTINGS.forEach((id) => {
    const setting = SETTINGS[id];
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
  if (state.setting && !model.settingPending) {
    model.setting = state.setting;
    if (model.serverCatalog && model.serverCatalog.id === state.setting) {
      model.catalog = model.serverCatalog;
    } else if (SETTINGS[state.setting]) {
      model.catalog = SETTINGS[state.setting];
    }
  }
  if (state.lighting) model.lighting = state.lighting;
  const caseLink = $("case-link");
  if (caseLink) {
    if (state.case_id) {
      caseLink.hidden = false;
      caseLink.href = `${ledgerOrigin()}/case.html?id=${encodeURIComponent(state.case_id)}`;
    } else {
      caseLink.hidden = true;
    }
  }
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
  else if (event.type === "step" && (event.step === "idle" || event.step === "homing")) model.item = null;
  if (event.request_to_hand_s != null) {
    const seconds = Number(event.request_to_hand_s);
    if (!Number.isNaN(seconds)) model.handoff = seconds;
  }
  if (Array.isArray(event.out)) {
    model.out = event.out.filter((item) => item);
  } else if (event.type === "handed" || event.type === "set_down") {
    if (event.item && !model.out.includes(event.item)) model.out.push(event.item);
  } else if (event.type === "returned" && event.item) {
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
  if (socket) {
    socket.onclose = null;
    socket.onmessage = null;
    socket.close();
  }
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const current = new WebSocket(`${protocol}://${location.host}/events`);
  socket = current;
  current.onopen = () => {
    if (socket !== current) return;
    model.link = "live";
    pullRecent();
    render();
  };
  current.onmessage = (message) => {
    try {
      const payload = JSON.parse(message.data);
      const events = Array.isArray(payload) ? payload : [payload];
      events.forEach(pushEvent);
    } catch (error) {
      /* ignore a malformed frame */
    }
  };
  current.onclose = () => {
    if (socket !== current || !model.live) return;
    model.link = "reconnecting";
    render();
    setTimeout(() => {
      if (socket === current && model.live) openSocket();
    }, 1000);
  };
}

function rateText(row) {
  const pct = percent(row.success_rate);
  if (row.wilson_low == null || row.wilson_high == null || row.successes == null || row.attempts == null) return pct;
  return `${pct} (${row.successes} of ${row.attempts}, ${percent(row.wilson_low)} to ${percent(row.wilson_high)})`;
}

function ledgerOrigin() {
  const host = location.hostname || "127.0.0.1";
  return new URLSearchParams(location.search).get("ledger") || `http://${host}:8080`;
}

function percent(rate) {
  if (rate == null || Number.isNaN(Number(rate))) return "—";
  return `${Math.round(Number(rate) * 100)}%`;
}

function seconds(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return `${Number(value).toFixed(1)}s`;
}

function tableRows(rows) {
  return Array.isArray(rows) ? rows.filter((row) => row && typeof row === "object") : [];
}

function fillTable(tableId, rows, labelKey) {
  const body = document.querySelector(`#${tableId} tbody`);
  body.replaceChildren();
  tableRows(rows).forEach((row) => {
    const tr = document.createElement("tr");
    const raw = labelKey === "item" ? nameOf(row.item) : row[labelKey];
    const label = raw == null ? "" : String(raw);
    [label, row.attempts, rateText(row), seconds(row.median_request_to_hand_s)].forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      tr.appendChild(cell);
    });
    body.appendChild(tr);
  });
}

function paintStats(report) {
  const safe = report && typeof report === "object" ? report : {};
  const itemRows = tableRows(safe.by_item);
  const lightRows = tableRows(safe.by_lighting);
  const rows = itemRows.length + lightRows.length;
  $("median").textContent = `Median handoff ${seconds(safe.median_request_to_hand_s)}`;
  const recent = model.events
    .filter((event) => event.request_to_hand_s != null)
    .slice(-6)
    .map((event) => seconds(event.request_to_hand_s));
  $("handoffs").textContent = recent.length ? `Recent handoffs ${recent.join(", ")}` : "";
  const next = safe.next_likely;
  const line = $("next-likely");
  if (line) {
    const share = next ? Number(next.share) : NaN;
    line.textContent = next && next.item
      ? `Likely next: ${nameOf(next.item)}${Number.isNaN(share) ? "" : ` (${Math.round(share * 100)}%)`}`
      : "";
  }
  fillTable("by-item", itemRows, "item");
  fillTable("by-lighting", lightRows, "lighting");
  const empty = $("tables-empty");
  if (empty) empty.textContent = "No real-arm tries yet.";
  document.querySelector(".tables").classList.toggle("has-rows", rows > 0);
}

async function loadStats() {
  if (!model.live) return;
  try {
    const response = await fetch("/stats", { cache: "no-store", signal: AbortSignal.timeout(3000) });
    if (!response.ok) return;
    paintStats(await response.json());
  } catch (error) {
    /* tables stay as they were */
  }
}

async function pollState() {
  try {
    const response = await fetch("/state", { cache: "no-store", signal: AbortSignal.timeout(3000) });
    if (!response.ok) return;
    applyState(await response.json());
  } catch (error) {
    /* keep the last state on a missed poll */
  }
}

function catalogFrom(document) {
  const known = SETTINGS[document.id] || { id: document.id, label: document.id, items: [] };
  const items = (document.items || known.items).map((item) => ({
    id: item.id,
    name: item.name || item.id,
    sharp: Boolean(item.sharp),
  }));
  return { id: document.id, label: document.label || known.label, items };
}

async function pullRecent() {
  try {
    const response = await fetch("/events/recent?n=40", { cache: "no-store", signal: AbortSignal.timeout(3000) });
    if (!response.ok) return;
    const events = await response.json();
    if (Array.isArray(events)) events.forEach(pushEvent);
  } catch (error) {
    /* the live socket still fills the log */
  }
}

async function pullSetting() {
  try {
    const response = await fetch("/setting", { cache: "no-store", signal: AbortSignal.timeout(3000) });
    if (!response.ok) return;
    const document = await response.json();
    if (!document || !document.id) return;
    model.serverCatalog = catalogFrom(document);
    model.catalog = model.serverCatalog;
    model.setting = document.id;
  } catch (error) {
    /* the local tray list still draws the buttons */
  }
}

async function changeSetting(settingId) {
  if (!SHOWN_SETTINGS.includes(settingId)) return;
  const previous = model.setting;
  model.setting = settingId;
  model.catalog = SETTINGS[settingId] || SETTINGS.surgical;
  model.settingPending = true;
  render();
  if (!model.live) {
    model.settingPending = false;
    return;
  }
  try {
    const loaded = await postJson("/setting", { setting: settingId });
    if (loaded && loaded.id) {
      model.serverCatalog = catalogFrom(loaded);
      model.catalog = model.serverCatalog;
      model.setting = loaded.id;
    }
    $("banner").hidden = true;
  } catch (error) {
    model.setting = previous;
    model.catalog = (model.serverCatalog && model.serverCatalog.id === previous && model.serverCatalog) || SETTINGS[previous] || model.catalog;
    $("banner").hidden = false;
    $("banner").textContent = "Could not switch trays. Wait until the arm is idle, or reset a stop first.";
  } finally {
    model.settingPending = false;
    render();
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

function visionOrigin() {
  const host = location.hostname || "127.0.0.1";
  return new URLSearchParams(location.search).get("vision") || `http://${host}:8001`;
}

function onCamera() {
  const image = $("camera");
  const frame = image.parentElement;
  let streamOn = false;
  const check = () => {
    const probe = new Image();
    probe.onload = () => {
      if (!streamOn) {
        image.src = `${visionOrigin()}/stream`;
        streamOn = true;
      }
      frame.classList.add("has-stream");
    };
    probe.onerror = () => {
      streamOn = false;
      image.removeAttribute("src");
      frame.classList.remove("has-stream");
    };
    probe.src = `${visionOrigin()}/snapshot?t=${Date.now()}`;
  };
  check();
  setInterval(check, 3000);
}

async function pollVision() {
  const banner = $("vision-stale");
  let tray = null;
  let age = null;
  try {
    const response = await fetch("/vision", { cache: "no-store", signal: AbortSignal.timeout(3000) });
    if (response.ok) {
      const body = await response.json();
      tray = body && body.tray ? body.tray : null;
      if (body && body.tray_age_s != null) age = Number(body.tray_age_s);
    }
  } catch (error) {
    tray = null;
  }
  if (!tray) {
    try {
      const response = await fetch(`${visionOrigin()}/vision/tray`, { cache: "no-store", signal: AbortSignal.timeout(3000) });
      if (!response.ok) throw new Error("down");
      tray = await response.json();
    } catch (error) {
      banner.hidden = true;
      return;
    }
  }
  if (!tray || !tray.slots) {
    banner.hidden = true;
    return;
  }
  if (age == null && tray.t) age = Date.now() / 1000 - Number(tray.t);
  banner.hidden = !(tray.stale || (age != null && age > 3));
}

async function resetArm() {
  if (!model.live) return;
  try {
    await postJson("/reset", {});
    $("banner").hidden = true;
  } catch (error) {
    $("banner").hidden = false;
    $("banner").textContent = "Reset did not go through. Stop the arm first if it is still moving.";
  }
}

function wire() {
  fillSettings();
  onCamera();
  const cases = $("cases-link");
  if (cases) cases.href = `${ledgerOrigin()}/cases.html`;
  const series = $("series-link");
  if (series) series.href = `${ledgerOrigin()}/series.html`;
  const memory = $("memory-link");
  if (memory) memory.href = `${ledgerOrigin()}/memory.html`;
  $("stop").addEventListener("click", stopArm);
  $("reset").addEventListener("click", resetArm);
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
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || tag === "BUTTON") return;
    event.preventDefault();
    stopArm();
  });
}

function goLive(state) {
  clearFakeTimers();
  model.live = true;
  model.link = "connecting";
  model.events = [];
  samplePlayed = false;
  $("banner").hidden = true;
  applyState(state);
  openSocket();
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(pollState, 400);
  pullSetting().then(render);
  pullRecent();
  loadStats();
  if (!statsTimer) statsTimer = setInterval(loadStats, 2000);
}

async function connect() {
  wire();
  pollVision();
  setInterval(pollVision, 2000);
  try {
    const response = await fetch("/state", { cache: "no-store", signal: AbortSignal.timeout(800) });
    if (!response.ok) throw new Error("no state");
    goLive(await response.json());
  } catch (error) {
    showSampleList();
    setInterval(async () => {
      if (model.live) return;
      try {
        const response = await fetch("/state", { cache: "no-store", signal: AbortSignal.timeout(3000) });
        if (!response.ok) return;
        goLive(await response.json());
      } catch (err) {
        /* stay on the sample until the controller answers */
      }
    }, 2000);
  }
}

connect();
