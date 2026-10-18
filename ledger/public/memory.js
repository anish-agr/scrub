function paintNotes(rows) {
  const list = document.getElementById("notes");
  list.replaceChildren();
  const shown = Array.isArray(rows) ? rows.slice().reverse() : [];
  if (!shown.length) {
    const empty = document.createElement("li");
    empty.textContent = "No asks remembered yet.";
    list.appendChild(empty);
    return;
  }
  shown.forEach((row) => {
    const li = document.createElement("li");
    li.textContent = row.text || "";
    list.appendChild(li);
  });
}

async function load() {
  const response = await fetch("/api/memory", { cache: "no-store" });
  if (!response.ok) throw new Error("bad");
  const body = await response.json();
  document.getElementById("mode").textContent = body.backboard
    ? "Questions go to Backboard, which keeps these notes across cases."
    : "Backboard is not connected. Answers come from the local ledger. Set BACKBOARD_API_KEY and BACKBOARD_ASSISTANT_ID to store the notes there.";
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
    document.getElementById("answer").textContent = body.answer || "";
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
