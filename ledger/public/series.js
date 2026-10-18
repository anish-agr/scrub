function clock(t) {
  return new Date(Number(t) * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

function paint(report) {
    const tiger = report.source === "tiger";
  const word = document.getElementById("source-word");
  word.textContent = tiger ? "Time-series table" : "Local ledger";
  word.className = tiger ? "status-word live" : "status-word wait";
  document.getElementById("source-text").textContent = tiger
    ? "These minutes are read from the scrub_handoff time-series table."
    : "These minutes are counted from the ledger.";
  const bars = document.getElementById("bars");
  const buckets = Array.isArray(report.buckets) ? report.buckets : [];
  bars.replaceChildren();
  document.getElementById("empty").hidden = buckets.length > 0;
  const max = Math.max(1, ...buckets.map((row) => Number(row.n) || 0));
  buckets.forEach((row) => {
    const line = document.createElement("div");
    line.className = "bar";
    const label = document.createElement("span");
    label.textContent = clock(row.t);
    const track = document.createElement("span");
    track.className = "track";
    const fill = document.createElement("span");
    fill.className = "fill";
    fill.style.width = `${Math.round(((Number(row.n) || 0) / max) * 100)}%`;
    track.appendChild(fill);
    const count = document.createElement("span");
    const median = row.median_s == null ? "" : `, ${Number(row.median_s).toFixed(1)} s`;
    count.textContent = `${row.n} ${Number(row.n) === 1 ? "handoff" : "handoffs"}, ${row.real} real${median}`;
    line.append(label, track, count);
    bars.appendChild(line);
  });
}

async function load() {
  try {
    const response = await fetch("/api/series", { cache: "no-store" });
    if (!response.ok) throw new Error("bad");
    paint(await response.json());
    document.getElementById("status").hidden = true;
  } catch (error) {
    const status = document.getElementById("status");
    status.hidden = false;
    status.textContent = "The ledger is not answering.";
  }
}

load();
setInterval(load, 5000);
