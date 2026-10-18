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

const $ = (id) => document.getElementById(id);

function nameOf(itemId) {
  return NAMES[itemId] || String(itemId || "").replaceAll("_", " ");
}

function rateText(row) {
  const pct = percent(row.success_rate);
  if (row.wilson_low == null || row.wilson_high == null || row.successes == null || row.attempts == null) return pct;
  return `${pct} (${row.successes} of ${row.attempts}, ${percent(row.wilson_low)} to ${percent(row.wilson_high)})`;
}

function percent(rate) {
  if (rate == null || Number.isNaN(Number(rate))) return "--";
  return `${Math.round(Number(rate) * 100)}%`;
}

function seconds(value) {
  if (value == null || Number.isNaN(Number(value))) return "--";
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

function paint(report) {
  const safe = report && typeof report === "object" ? report : {};
  const out = $("out");
  out.replaceChildren();
  const items = Array.isArray(safe.out) ? safe.out : [];
  if (!items.length) {
    const empty = document.createElement("li");
    empty.className = "empty";
    empty.textContent = "Nothing out";
    out.appendChild(empty);
  } else {
    items.forEach((itemId) => {
      const li = document.createElement("li");
      li.textContent = nameOf(itemId);
      out.appendChild(li);
    });
  }
  const med = $("median");
  med.replaceChildren();
  const label = document.createElement("small");
  label.textContent = "Median handoff";
  const medianShown = safe.median_request_to_hand_s != null && tableRows(safe.by_item).length > 0;
  med.append(label, medianShown ? seconds(safe.median_request_to_hand_s).replace("s", "") : "--");
  if (medianShown) {
    const unit = document.createElement("span");
    unit.className = "unit";
    unit.textContent = "s";
    med.appendChild(unit);
  }
  const itemRows = tableRows(safe.by_item);
  const lightRows = tableRows(safe.by_lighting);
  fillTable("by-item", itemRows, "item");
  fillTable("by-lighting", lightRows, "lighting");
  const rows = itemRows.length + lightRows.length;
  const tries = itemRows.reduce((sum, row) => sum + (Number(row.attempts) || 0), 0);
  $("handoffs").textContent = rows ? String(tries) : "--";
  const word = $("live-word");
  word.textContent = "live";
  word.className = "status-word live";
  $("live-note").textContent = rows
    ? `Counted from ${tries} real-arm ${tries === 1 ? "try" : "tries"} in the ledger. Updates every 2 seconds.`
    : "No real-arm handoffs recorded yet. Fake-arm and simulated runs are not counted in the rates. This updates every 2 seconds.";
  const next = $("next");
  const guess = safe.next_likely;
  next.hidden = !(rows && guess && guess.item);
  if (rows && guess && guess.item) {
    next.textContent = `After ${nameOf(guess.after)}, the next request is usually ${nameOf(guess.item)} (${percent(guess.share)} of ${guess.n}).`;
  }
  const empty = $("tables-empty");
  if (empty) empty.textContent = "No real-arm tries yet. The tables fill as tests run.";
  document.querySelector("main").classList.toggle("has-rows", rows > 0);
  $("status").hidden = true;
}

async function loadCases() {
  const list = document.getElementById("replays");
  if (!list) return;
  try {
    const response = await fetch("/api/cases", { cache: "no-store", signal: AbortSignal.timeout(3000) });
    if (!response.ok) throw new Error("bad");
    const rows = await response.json();
    if (!Array.isArray(rows)) throw new Error("bad");
    list.replaceChildren();
    const shown = rows.slice(0, 8);
    if (!shown.length) {
      const empty = document.createElement("li");
      empty.textContent = "No cases yet.";
      list.appendChild(empty);
      return;
    }
    shown.forEach((row) => {
      const li = document.createElement("li");
      const link = document.createElement("a");
      link.href = `case.html?id=${encodeURIComponent(row.case_id)}`;
      const id = document.createElement("b");
      id.textContent = row.case_id;
      const setting = document.createElement("span");
      setting.className = "meta";
      setting.textContent = row.setting || "case";
      const held = document.createElement("span");
      held.className = "meta";
      held.textContent = `${row.n || 0} events · ` + ((row.out || []).map(nameOf).join(", ") || "nothing out");
      link.append(id, setting, held);
      li.appendChild(link);
      list.appendChild(li);
    });
  } catch (error) {
    /* the count still updates if the case list fails */
  }
}

async function refresh() {
  try {
    const response = await fetch("/api/stats", { cache: "no-store", signal: AbortSignal.timeout(3000) });
    if (!response.ok) throw new Error("bad");
    const report = await response.json();
    paint(report);
  } catch (error) {
    $("status").hidden = false;
    $("status").textContent = "The ledger is not answering. Numbers below may be old.";
    const word = $("live-word");
    word.textContent = "down";
    word.className = "status-word down";
  }
}

refresh();
loadCases();
setInterval(refresh, 2000);
setInterval(loadCases, 5000);
