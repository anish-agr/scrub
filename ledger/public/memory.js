function paintNotes(rows) {
  const list = document.getElementById("notes");
  list.replaceChildren();
  const shown = Array.isArray(rows) ? rows.slice(-8).reverse() : [];
  if (!shown.length) {
    const empty = document.createElement("li");
    empty.textContent = "No asks remembered yet.";
    list.appendChild(empty);
    return;
  }
  shown.forEach((row) => {
    const li = document.createElement("li");
    const time = document.createElement("time");
    time.textContent = row.t ? new Date(Number(row.t) * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false }) : "";
    const text = document.createElement("span");
    text.textContent = row.text || "";
    li.append(time, text);
    list.appendChild(li);
  });
}

async function load() {
  const response = await fetch("/api/memory", { cache: "no-store" });
  if (!response.ok) throw new Error("bad");
  const body = await response.json();
  const word = document.getElementById("mode-word");
  word.textContent = body.backboard ? "Backboard connected" : "Local ledger";
  word.className = body.backboard ? "status-word live" : "status-word wait";
  document.getElementById("mode-text").textContent = body.backboard
    ? "Questions go to Backboard, which keeps these notes across cases. If it does not answer, the reply says so."
    : "Backboard is not connected, so answers are counted from the local ledger. They switch to Backboard once its keys are set.";
  paintNotes(body.notes);
}

document.getElementById("ask").addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = document.getElementById("q").value;
  const status = document.getElementById("status");
  try {
    const response = await fetch("/api/memory", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ q: question }),
    });
    if (!response.ok) throw new Error("bad");
    const body = await response.json();
    const from = document.getElementById("answer-from");
    const fromBackboard = body.source === "backboard";
    from.hidden = false;
    from.className = "answer-from " + (fromBackboard ? "live" : "wait");
    from.textContent = fromBackboard
      ? "Answered by Backboard"
      : body.backboard ? "Backboard did not answer. Counted from the local ledger" : "Counted from the local ledger. Not from Backboard";
    document.getElementById("answer-text").textContent = body.answer || "";
    status.hidden = true;
  } catch (error) {
    status.hidden = false;
    status.textContent = "The ledger is not answering.";
  }
});

load().catch(() => {
  const status = document.getElementById("status");
  status.hidden = false;
  status.textContent = "The ledger is not answering.";
});
