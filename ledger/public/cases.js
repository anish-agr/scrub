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

function clock(t) {
  if (t == null) return "";
  return new Date(Number(t) * 1000).toLocaleString([], { hour12: false });
}

function showError(text) {
  const status = document.getElementById("status");
  status.hidden = false;
  status.textContent = text;
}

async function loadCases() {
  const list = document.getElementById("cases");
  try {
    const response = await fetch("/api/cases", { cache: "no-store", signal: AbortSignal.timeout(3000) });
    if (!response.ok) throw new Error("bad");
    const rows = await response.json();
    if (!Array.isArray(rows)) throw new Error("bad");
    list.replaceChildren();
    if (!rows.length) {
      const empty = document.createElement("li");
      empty.textContent = "No cases yet.";
      list.appendChild(empty);
      return;
    }
    rows.forEach((row) => {
      const li = document.createElement("li");
      const link = document.createElement("a");
      link.href = `case.html?id=${encodeURIComponent(row.case_id)}`;
      const held = (row.out || []).map(nameOf).join(", ") || "nothing out";
      const count = Number(row.n) || 0;
      link.textContent = `${row.case_id} · ${row.setting || "case"} · ${count} ${count === 1 ? "event" : "events"} · ${held}`;
      li.appendChild(link);
      list.appendChild(li);
    });
  } catch (error) {
    showError("The ledger is not answering.");
  }
}

async function loadCase() {
  const caseId = new URLSearchParams(location.search).get("id") || "";
  document.getElementById("case-id").textContent = caseId || "Case";
  try {
    const response = await fetch(`/api/case?id=${encodeURIComponent(caseId)}`, { cache: "no-store", signal: AbortSignal.timeout(3000) });
    if (!response.ok) throw new Error("missing");
    const view = await response.json();
    document.getElementById("summary").textContent = view.summary || "";
    const list = document.getElementById("timeline");
    list.replaceChildren();
    const events = Array.isArray(view.events) ? view.events : [];
    if (!events.length) {
      const empty = document.createElement("li");
      empty.textContent = "No events in this case.";
      list.appendChild(empty);
    }
    events.forEach((event) => {
      const li = document.createElement("li");
      const bits = [clock(event.t), event.type];
      if (event.item) bits.push(nameOf(event.item));
      if (event.say) bits.push(event.say);
      if (event.request_to_hand_s != null) bits.push(`${Number(event.request_to_hand_s).toFixed(1)}s`);
      if (Array.isArray(event.out)) bits.push("out: " + (event.out.map(nameOf).join(", ") || "nothing"));
      li.textContent = bits.join(" · ");
      list.appendChild(li);
    });
  } catch (error) {
    showError("That case is not in the ledger.");
  }
}

if (document.getElementById("cases")) loadCases();
if (document.getElementById("timeline")) loadCase();
