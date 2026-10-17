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

function percent(rate) {
  if (rate == null || Number.isNaN(Number(rate))) return "—";
  return `${Math.round(Number(rate) * 100)}%`;
}

function seconds(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return `${Number(value).toFixed(1)}s`;
}

function fillTable(tableId, rows, labelKey) {
  const body = document.querySelector(`#${tableId} tbody`);
  body.replaceChildren();
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    const label = labelKey === "item" ? nameOf(row.item) : row[labelKey];
    [label, row.attempts, percent(row.success_rate), seconds(row.median_request_to_hand_s)].forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      tr.appendChild(cell);
    });
    body.appendChild(tr);
  });
}

function paint(report) {
  const out = $("out");
  out.replaceChildren();
  const items = report.out || [];
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
  $("median").textContent = `Median handoff ${seconds(report.median_request_to_hand_s)}`;
  fillTable("by-item", report.by_item || [], "item");
  fillTable("by-lighting", report.by_lighting || [], "lighting");
  const rows = (report.by_item || []).length + (report.by_lighting || []).length;
  document.querySelector("main").classList.toggle("has-rows", rows > 0);
  $("status").hidden = true;
}

async function refresh() {
  try {
    const response = await fetch("/api/stats", { cache: "no-store" });
    if (!response.ok) throw new Error("bad");
    paint(await response.json());
  } catch (error) {
    $("status").hidden = false;
    $("status").textContent = "The ledger is not answering.";
  }
}

refresh();
setInterval(refresh, 2000);
