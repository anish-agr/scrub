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
  return new Date(Number(t) * 1000).toLocaleTimeString([], { hour12: false });
}

function showError(text) {
  const status = document.getElementById("status");
  status.hidden = false;
  status.textContent = text;
}

let shown = 25;

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
    const total = rows.length;
    const more = document.getElementById("more");
    if (more) {
      more.hidden = total <= shown;
      more.textContent = `Show more (${total - shown} older)`;
      more.onclick = () => { shown += 50; loadCases(); };
    }
    const note = document.getElementById("cases-count");
    if (note) note.textContent = `${total} ${total === 1 ? "case" : "cases"} in the ledger, newest first.`;
    rows.slice(0, shown).forEach((row) => {
      const li = document.createElement("li");
      const link = document.createElement("a");
      link.href = `case.html?id=${encodeURIComponent(row.case_id)}`;
      const held = (row.out || []).map(nameOf).join(", ") || "nothing out";
      const count = Number(row.n) || 0;
      const id = document.createElement("b");
      id.textContent = row.case_id;
      const setting = document.createElement("span");
      setting.className = "meta";
      setting.textContent = row.setting || "case";
      const rest = document.createElement("span");
      rest.className = "meta";
      rest.textContent = `${count} ${count === 1 ? "event" : "events"} · ${held}`;
      link.append(id, setting, rest);
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
      li.className = "ev" + (event.type === "step" ? " minor" : "");
      const time = document.createElement("time");
      time.textContent = clock(event.t);
      const type = document.createElement("span");
      type.className = "type " + String(event.type || "").replace(/[^a-z_]/g, "");
      type.textContent = String(event.type || "").replaceAll("_", " ");
      const what = document.createElement("span");
      const bits = [];
      if (event.item) bits.push(nameOf(event.item));
      if (event.step && event.type === "step") bits.push(String(event.step).replaceAll("_", " "));
      if (event.say) bits.push(event.say);
      if (event.skill_source) bits.push(event.skill_source === "taught" ? "taught skill" : "model");
      if (event.read_line) {
        bits.length = Math.min(bits.length, 1);
        bits.push(event.read_line);
        if (event.say) bits.push(event.say);
      }
      if (Array.isArray(event.sheet_mismatch) && event.sheet_mismatch.length) {
        bits.push("sheet mismatch: " + event.sheet_mismatch.map((m) => `${nameOf(m.item)} sheet ${m.sheet}, scrub ${m.scrub}`).join("; "));
      }
      what.textContent = bits.join(" · ");
      const secs = document.createElement("span");
      secs.className = "secs";
      secs.textContent = event.request_to_hand_s != null ? `${Number(event.request_to_hand_s).toFixed(1)} s` : "";
      li.append(time, type, what, secs);
      if (Array.isArray(event.out)) {
        const held = document.createElement("span");
        held.className = "out-line";
        held.textContent = "out: " + (event.out.map(nameOf).join(", ") || "nothing");
        li.appendChild(held);
      }
      if (event.caption && event.caption.label) {
        const note = document.createElement("span");
        note.className = "caption";
        note.textContent = `Camera: ${event.caption.label}` + (event.caption.disagrees ? " (camera disagrees)" : "");
        li.appendChild(note);
      }
      list.appendChild(li);
    });
    const steps = list.querySelectorAll(".minor").length;
    const toggle = document.getElementById("toggle-steps");
    if (toggle && steps) {
      toggle.hidden = false;
      list.classList.add("compact");
      toggle.textContent = `Show ${steps} step lines`;
      toggle.onclick = () => {
        const compact = list.classList.toggle("compact");
        toggle.textContent = compact ? `Show ${steps} step lines` : "Hide step lines";
      };
    }
  } catch (error) {
    showError("That case is not in the ledger.");
  }
}

if (document.getElementById("cases")) loadCases();
if (document.getElementById("timeline")) loadCase();
