// Short-lived questions are scoped to a call or a text thread, never to the robot globally.
import { randomUUID } from "node:crypto";
import { getStats, postClarify, type Action, type Candidate, type Clarification, type ClarifyLog, type Command, type Instance, type ScrubEvent } from "./controller.js";
import { chooseCandidate } from "./choice.js";
import { candidateFor, isGotIt, localParse, whichOne, type ParseResult } from "./parse.js";
import type { Setting } from "./settings.js";

const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
export const QUESTION_MS = 15_000;
export const TIMEOUT_LINE = "That question timed out. I'll wait for you to ask again.";
export interface QuestionTimers { set(callback: () => void, ms: number): unknown; clear(timer: unknown): void }
const realQuestionTimers: QuestionTimers = {
  set: (callback, ms) => { const timer = setTimeout(callback, ms); timer.unref(); return timer; },
  clear: (timer) => clearTimeout(timer as NodeJS.Timeout),
};
const CANCEL = /\b(cancel|never mind|nevermind|forget it)\b/;
const selectorOf = (s: string) => s.match(/^(?:(?:please|i ll take|i want|give me|hand me|pass me|bring me|take|choose|pick) )?(?:the )?(?:one on (?:the )?)?(left|right|closest|first|second|1st|2nd|one|two)(?: one)?(?: please)?$/)?.[1];
const freeChoice = (s: string) => /^(?:(?:please|i ll take|give me|hand me|choose|pick) )?(either(?: one)?|any(?: one)?|you pick)(?: please)?$/.test(s);
interface Question { q: Clarification; setting: string; action: Action; at: number; confirm: boolean; chosen?: Candidate; timer?: unknown; controllerId?: string }
interface Context { question?: Question; expired?: Question; lastQuestion?: Question; lastHanded?: Candidate; setting?: string; latestCommand?: string; notify?: (line: string) => void }
interface Origin { context: string; command: Command; setting: Setting; at: number; epoch: number; notify?: (line: string) => void }
export type Answer = { say: string } | { parsed: ParseResult } | null;

export class Dialogue {
  private contexts = new Map<string, Context>();
  private commands = new Map<string, Origin>();
  private epoch = 0;
  private caseId?: string;
  constructor(private now = Date.now, private log: (row: ClarifyLog) => Promise<unknown> = postClarify, private timers = realQuestionTimers) {}
  private note(row: ClarifyLog) { try { void this.log(row).catch(() => {}); } catch { /* telemetry never blocks a stop */ } }
  private context(id: string, setting?: string): Context {
    let c = this.contexts.get(id);
    if (!c || (setting && c.setting && c.setting !== setting)) {
      if (c) this.close(id, c, "setting_changed", "cancelled");
      c = { notify: c?.notify }; this.contexts.set(id, c);
    }
    if (setting) c.setting = setting;
    if (this.contexts.size > 128) this.clear(this.contexts.keys().next().value!, "context_evicted");
    return c;
  }
  clear(context?: string, reason = "cancelled") {
    if (context) {
      const c = this.contexts.get(context);
      if (c) this.close(context, c, reason, "cancelled");
      this.contexts.delete(context);
    } else {
      for (const [id, c] of this.contexts) this.close(id, c, reason, "cancelled");
      this.contexts.clear(); this.epoch++;
    }
  }
  bind(context: string, notify?: (line: string) => void) { this.context(context).notify = notify; }
  private close(context: string, c: Context, answer: string, status = "answered", say?: string) {
    const q = c.question;
    if (!q) return;
    if (q.timer !== undefined) this.timers.clear(q.timer);
    c.question = undefined; c.latestCommand = undefined;
    this.note({ type: "clarify_answer", item: q.q.item, candidates: q.q.candidates, question_id: q.q.question_id,
      answer, answer_ms: this.now() - q.at, context, status, ...(status !== "answered" ? { reason: answer } : {}), ...(say ? { say } : {}) });
  }
  private expire(context: string, q: Question) {
    const c = this.contexts.get(context);
    if (c?.question !== q) return;
    const remaining = QUESTION_MS - (this.now() - q.at);
    if (remaining > 0) { q.timer = this.timers.set(() => this.expire(context, q), remaining); return; }
    this.close(context, c, "timeout", "timeout", TIMEOUT_LINE);
    c.expired = q;
    try { c.notify?.(TIMEOUT_LINE); } catch { /* closed sender; state and telemetry already updated */ }
  }
  version() { return this.epoch; }
  commandActive(id: string) {
    const o = this.commands.get(id);
    return !!o && o.epoch === this.epoch && this.contexts.get(o.context)?.latestCommand === id;
  }
  pending(context: string) { const q = this.contexts.get(context)?.question; return !!q && this.now() - q.at < QUESTION_MS; }
  remaining(context: string) { const q = this.contexts.get(context)?.question; return q ? Math.max(0, QUESTION_MS - (this.now() - q.at)) : 0; }
  track(context: string, command: Command, setting: Setting, notify?: (line: string) => void) {
    this.context(context, setting.id).latestCommand = command.id;
    for (const [id, o] of this.commands) if (this.now() - o.at > 300_000) this.commands.delete(id);
    if (this.commands.size > 500) this.commands.delete(this.commands.keys().next().value!);
    this.commands.set(command.id, { context, command, setting, at: this.now(), epoch: this.epoch, notify });
  }
  private clean(q: Clarification, setting: Setting): Clarification {
    const candidates = q.candidates.flatMap((c) => {
      const item = [c.item, c.id, q.item].find((id) => setting.items.some((it) => it.id === id));
      if (!item) return [];
      const raw = { ...c, ...c.instance };
      const instance: Instance = {};
      if (typeof raw.variant === "string") instance.variant = raw.variant;
      if (["left", "right", "closest"].includes(raw.side || "")) instance.side = raw.side as Instance["side"];
      if (Number.isInteger(raw.slot) && raw.slot! >= 0) instance.slot = raw.slot;
      return [{ ...c, item, instance }];
    });
    return { ...q, candidates, question_id: q.question_id || randomUUID() };
  }
  ask(context: string, question: Clarification, setting: Setting, action: Action = "handover", confirm = false, local = true): string {
    const c = this.context(context, setting.id);
    // The same controller question can arrive by HTTP and websocket, in either order.
    if (question.question_id && c.question?.q.question_id === question.question_id) {
      c.question.confirm ||= confirm || question.confirm === true;
      return c.question.q.say;
    }
    const q = this.clean(question, setting);
    const previous = c.question;
    const key = (x: Candidate) => JSON.stringify([x.item, x.id, x.label, x.variant, x.side, x.slot, x.instance?.variant, x.instance?.side, x.instance?.slot]);
    if (previous && !question.question_id && previous.q.say === q.say && previous.q.candidates.length === q.candidates.length
        && previous.q.candidates.every((x, i) => key(x) === key(q.candidates[i]))) {
      previous.confirm ||= confirm || question.confirm === true;
      return previous.q.say;
    }
    this.close(context, c, "superseded", "cancelled");
    c.expired = undefined;
    c.question = { q, setting: setting.id, action, at: this.now(), confirm: confirm || question.confirm === true,
      ...(!local && question.question_id ? { controllerId: question.question_id } : {}) };
    c.lastQuestion = c.question;
    const active = c.question;
    active.timer = this.timers.set(() => this.expire(context, active), QUESTION_MS);
    if (local) c.latestCommand = undefined;
    if (local) this.note({ type: "clarify", ...q, context });
    return q.say;
  }
  askParsed(context: string, p: ParseResult, setting: Setting): string | null {
    if (p.clarify) return this.ask(context, p.clarify, setting, p.action);
    if (p.confirm && p.item) {
      const candidate = candidateFor(setting, p.item);
      if (p.instance) candidate.instance = p.instance;
      return this.ask(context, { say: `Did you mean ${candidate.label}? Say yes or no.`, candidates: [candidate] }, setting, p.action, true);
    }
    return null;
  }
  scope(context: string, p: ParseResult, setting: Setting): Answer {
    // Even a model-parsed pronoun return must not invoke the controller's global last-out fallback.
    return p.action === "return" && !p.item && !p.clarify ? this.followup(context, "put it back", setting) : { parsed: p };
  }
  async answerAsync(context: string, heard: string, setting: Setting, stats = getStats): Promise<Answer> {
    const q = this.contexts.get(context)?.question;
    if (!q || q.confirm || !freeChoice(norm(heard))) return this.answer(context, heard, setting);
    let timer: NodeJS.Timeout | undefined;
    const data = await Promise.race([
      Promise.resolve().then(stats).catch(() => null),
      new Promise<null>((resolve) => { timer = setTimeout(() => resolve(null), 1000); }),
    ]).finally(() => clearTimeout(timer));
    if (this.contexts.get(context)?.question !== q) return { say: "That question is no longer pending. Please ask again." };
    return this.answer(context, heard, setting, chooseCandidate(q.q.candidates, data));
  }
  answer(context: string, heard: string, setting: Setting, preferred?: Candidate): Answer {
    const c = this.context(context, setting.id), q = c.question, s = norm(heard);
    if (CANCEL.test(s)) { this.close(context, c, heard, "cancelled"); c.expired = undefined; c.latestCommand = undefined; return { say: "Cancelled." }; }
    if (!q && c.expired) {
      const old = c.expired; c.expired = undefined;
      const bareAnswer = !!selectorOf(s) || freeChoice(s) || /^(yes|no)$/.test(s)
        || old.q.candidates.some((x) => [x.variant, x.instance?.variant, x.label].some((w) => w && norm(w) === s));
      if (bareAnswer) return { say: TIMEOUT_LINE };
    }
    const followup = q?.confirm ? null : this.followup(context, heard, setting);
    if (followup) { this.close(context, c, "superseded", "cancelled"); return followup; }
    if (!q) return null;
    if (isGotIt(heard)) return null; // release must not be trapped behind a question
    const local = localParse(heard, setting);
    // These are new non-movement commands, not choice answers, even when they contain "right" or "first".
    if (["count", "read_sheet", "read_tray", "read_pack"].includes(local.action)) {
      this.close(context, c, "superseded", "cancelled"); return null;
    }
    if (this.now() - q.at >= QUESTION_MS) {
      this.expire(context, q);
      return { say: TIMEOUT_LINE };
    }
    if (q.confirm && /^(no|nope|not that|negative)( please)?$/.test(s)) {
      this.close(context, c, heard, "cancelled");
      return { say: "Cancelled." };
    }
    let chosen: Candidate | undefined;
    if (q.confirm) {
      if (/^(yes|yes please|yeah|yep|correct|that s right)$/.test(s)) chosen = q.q.candidates[0];
    } else {
      const selector = selectorOf(s);
      if (["first", "1st", "one"].includes(selector || "")) chosen = q.q.candidates[0];
      if (["second", "2nd", "two"].includes(selector || "")) chosen = q.q.candidates[1];
      if (freeChoice(s)) chosen = preferred || chooseCandidate(q.q.candidates);
      const side = ["left", "right", "closest"].includes(selector || "") ? selector : undefined;
      if (side) {
        const sided = q.q.candidates.filter((x) => (x.instance?.side || x.side) === side);
        if (sided.length === 1) chosen = sided[0];
        else if (new Set(q.q.candidates.map((x) => x.item)).size === 1) chosen = { item: q.q.candidates[0].item, instance: { side: side as Instance["side"] } };
      }
      const named = q.q.candidates.map((x) => {
        const it = setting.items.find((i) => i.id === x.item);
        const words = [x.label, x.variant, x.instance?.variant, x.id, it?.name, ...(it?.aliases || [])]
          .filter((x): x is string => !!x).map(norm).filter((w) => !selectorOf(w));
        return { x, score: Math.max(0, ...words.filter((w) => w && (` ${s} `).includes(` ${w} `)).map((w) => w.length)) };
      });
      const max = Math.max(0, ...named.map((x) => x.score));
      const best = named.filter((x) => x.score === max && max > 0);
      if (!chosen && best.length === 1) chosen = best[0].x;
      // Repeating the two options is not an answer, even if one name is longer.
      if (/\bor\b/.test(s) && !/\b(either|any|you pick)\b/.test(s)) chosen = undefined;
    }
    if (chosen?.item) {
      q.chosen = chosen; this.close(context, c, heard);
      return { parsed: { action: q.action, item: chosen.item, ...(Object.keys(chosen.instance || {}).length ? { instance: chosen.instance } : {}),
        ...(q.controllerId ? { question_id: q.controllerId } : {}) } };
    }
    if (q.confirm) return { say: q.q.say }; // no alternative wording can accidentally bypass the required yes
    // A new explicit non-choice command replaces the question. An unrecognized answer just repeats it.
    if (!selectorOf(s) && !freeChoice(s) && local.action !== "unknown" && !local.clarify) { this.close(context, c, "superseded", "cancelled"); return null; }
    return { say: q.q.say };
  }
  private followup(context: string, heard: string, setting: Setting): Answer {
    const c = this.context(context, setting.id), s = norm(heard);
    const phrase = s.replace(/^(?:(?:please|can you|could you|hand me|give me|pass me|bring me|get me|grab me) )+/, "").replace(/ please$/, "");
    if (/^(the )?other( one)?$/.test(phrase)) {
      const last = c.lastQuestion;
      if (!last?.chosen) return { say: "Which instrument? Please ask for it by name." };
      const candidates = last.q.candidates.filter((x) => JSON.stringify(x) !== JSON.stringify(last.chosen));
      if (candidates.length === 1 && candidates[0].item) {
        last.chosen = candidates[0];
        return { parsed: { action: last.action, item: candidates[0].item!, instance: candidates[0].instance } };
      }
      return candidates.length ? { parsed: { action: last.action, item: null, clarify: whichOne(candidates) } } : { say: "There isn't another candidate. Please ask by name." };
    }
    const local = localParse(heard, setting);
    const returning = local.action === "return" && !local.item && !local.clarify;
    const again = /^(another( one)?|same( one)?( again)?|that again|again|one more)$/.test(phrase);
    if (!returning && !again) return null;
    const last = c.lastHanded;
    if (!last?.item || !setting.items.some((i) => i.id === last.item)) return { say: "Which instrument? I haven't handed you one in this conversation. Please ask by name." };
    const instance = returning ? last.instance : last.instance?.variant ? { variant: last.instance.variant } : undefined;
    return { parsed: { action: returning ? "return" : "handover", item: last.item, ...(instance ? { instance } : {}) } };
  }
  // Returns the originating context; callers route this line only there, not into an unrelated open call.
  event(e: ScrubEvent): { context: string; line?: string; notify?: (line: string) => void; ignore?: boolean } | null {
    if (e.case_id && this.caseId && e.case_id !== this.caseId) {
      const previous = Number(this.caseId.match(/-(\d+(?:\.\d+)?)$/)?.[1]);
      const next = Number(e.case_id.match(/-(\d+(?:\.\d+)?)$/)?.[1]);
      if (Number.isFinite(previous) && Number.isFinite(next) && next < previous) return null;
      const active = e.command_id ? this.commands.get(e.command_id) : undefined;
      this.clear();
      // The first event of a new case may be the command we just posted. Keep its routing, not old history.
      if (active) {
        active.epoch = this.epoch;
        this.context(active.context, active.setting.id).latestCommand = active.command.id;
      }
    }
    if (e.case_id) this.caseId = e.case_id;
    if (e.type === "stopped") { this.clear(undefined, "stop"); return null; }
    const o = e.command_id ? this.commands.get(e.command_id) : undefined;
    if (e.type === "returned") {
      const matched: Context[] = [];
      for (const [id, c] of this.contexts) {
        const last = c.lastHanded;
        if (!last || last.item !== e.item) continue;
        const keys = ["slot", "side", "variant"] as const;
        const identity = keys.filter((k) => e.instance?.[k] !== undefined);
        const stableSlot = last.instance?.slot !== undefined || e.instance?.slot !== undefined;
        const matches = identity.length > 0 && (!stableSlot || last.instance?.slot === e.instance?.slot)
          && identity.every((k) => String(last.instance?.[k] ?? "").toLowerCase() === String(e.instance![k]).toLowerCase());
        if (matches) matched.push(c);
        else if (!identity.length && o?.context === id) c.lastHanded = undefined;
      }
      // Variant-only metadata can describe several copies. Never erase two recipients on that evidence.
      if (matched.length === 1) matched[0].lastHanded = undefined;
    }
    if (!o || o.epoch !== this.epoch || this.now() - o.at > 300_000) return null;
    if (e.type === "clarify" && e.candidates && e.say) {
      if (!this.commandActive(o.command.id)) return { context: o.context, ignore: true };
      const line = this.ask(o.context, { say: e.say, item: e.item, candidates: e.candidates, question_id: e.question_id, confirm: e.confirm }, o.setting, o.command.action, false, false);
      return { context: o.context, line, notify: o.notify };
    }
    if ((e.type === "released" || e.type === "handed") && e.item) {
      this.context(o.context, o.setting.id).lastHanded = { item: e.item, instance: e.instance || o.command.instance };
    }
    return { context: o.context, notify: o.notify };
  }
}

export const dialogue = new Dialogue();
