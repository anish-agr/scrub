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
  $("median").textContent = `Median handoff ${seconds(safe.median_request_to_hand_s)}`;
  const itemRows = tableRows(safe.by_item);
  const lightRows = tableRows(safe.by_lighting);
  fillTable("by-item", itemRows, "item");
  fillTable("by-lighting", lightRows, "lighting");
  const rows = itemRows.length + lightRows.length;
  const empty = $("tables-empty");
  if (empty) empty.textContent = "No real-arm tries yet.";
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
      link.textContent = `${row.case_id} · ${row.setting || "case"}`;
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
    $("status").textContent = "The ledger is not answering.";
  }
}

refresh();
loadCases();
setInterval(refresh, 2000);
setInterval(loadCases, 5000);
