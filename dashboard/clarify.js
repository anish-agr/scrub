// Read-only waiting questions shared by the dashboard and ops page.
// A question never sends a command from either page.
(function (root) {
  function waitingQuestion(events, now = Date.now() / 1000) {
    const questions = new Map();
    for (const e of events) {
      if (e.type === "stopped" || (e.type === "error" && e.step === "error")) questions.clear();
      const key = e.question_id || e.command_id || e.context || "question";
      if (e.type === "clarify" && e.say && Array.isArray(e.candidates) && e.candidates.length) {
        questions.set(key, e);
      }
      if (e.type === "clarify_answer") questions.delete(key);
    }
    return [...questions.values()].reverse().find(e =>
      Number.isFinite(e.t) && now >= e.t && now < (e.expires_at || e.t + 15)) || null;
  }
  root.scrubWaitingQuestion = waitingQuestion;
  root.scrubOutItems = function (state) {
    return (Array.isArray(state.out_instances) ? state.out_instances.map(row => row.item) : state.out || [])
      .filter(item => typeof item === "string" && item);
  };
  if (typeof module !== "undefined") module.exports = waitingQuestion;
})(typeof window === "undefined" ? globalThis : window);
