// Short-lived questions are scoped to a call or a text thread, never to the robot globally.
import { randomUUID } from "node:crypto";
import { postClarify, type Action, type Candidate, type Clarification, type ClarifyLog, type Command, type Instance, type ScrubEvent } from "./controller.js";
import { candidateFor, isGotIt, localParse, whichOne, type ParseResult } from "./parse.js";
import type { Setting } from "./settings.js";

const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
export const QUESTION_MS = 15_000;
const CANCEL = /\b(cancel|never mind|nevermind|forget it)\b/;
const CHOICE = /\b(left|right|closest|first|second|either|any|you pick|other|yes|no)\b/;
interface Question { q: Clarification; setting: string; action: Action; at: number; confirm: boolean; chosen?: Candidate }
interface Context { question?: Question; lastQuestion?: Question; lastHanded?: Candidate; setting?: string }
interface Origin { context: string; command: Command; setting: Setting; at: number; epoch: number; notify?: (line: string) => void }
export type Answer = { say: string } | { parsed: ParseResult } | null;

export class Dialogue {
  private contexts = new Map<string, Context>();
  private commands = new Map<string, Origin>();
  private epoch = 0;
  private caseId?: string;
  constructor(private now = Date.now, private log: (row: ClarifyLog) => Promise<unknown> = postClarify) {}
  private note(row: ClarifyLog) { void this.log(row).catch(() => {}); }
  private context(id: string, setting?: string): Context {
    let c = this.contexts.get(id);
    if (!c || (setting && c.setting && c.setting !== setting)) { c = {}; this.contexts.set(id, c); }
    if (setting) c.setting = setting;
    if (this.contexts.size > 128) this.contexts.delete(this.contexts.keys().next().value!);
    return c;
  }
  clear(context?: string) {
    if (context) this.contexts.delete(context);
    else { this.contexts.clear(); this.epoch++; }
  }
  pending(context: string) { const q = this.contexts.get(context)?.question; return !!q && this.now() - q.at < QUESTION_MS; }
  track(context: string, command: Command, setting: Setting, notify?: (line: string) => void) {
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
    if (question.question_id && c.question?.q.question_id === question.question_id) return c.question.q.say;
    const q = this.clean(question, setting);
    const previous = c.question;
    if (previous && !question.question_id && previous.q.say === q.say && JSON.stringify(previous.q.candidates) === JSON.stringify(q.candidates)) return previous.q.say;
    c.question = { q, setting: setting.id, action, at: this.now(), confirm };
    c.lastQuestion = c.question;
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
  answer(context: string, heard: string, setting: Setting): Answer {
    const c = this.context(context, setting.id), q = c.question, s = norm(heard);
    if (CANCEL.test(s)) { c.question = undefined; if (q) this.answered(context, q, heard); return { say: "Cancelled. Nothing will move." }; }
    const followup = q?.confirm ? null : this.followup(context, heard, setting);
    if (followup) { c.question = undefined; return followup; }
    if (!q) return null;
    if (isGotIt(heard)) return null; // release must not be trapped behind a question
    if (this.now() - q.at >= QUESTION_MS) {
      c.question = undefined;
      return { say: "That question timed out. Please ask for the instrument again." };
    }
    if (q.confirm && /^(no|nope|not that|negative)( please)?$/.test(s)) {
      c.question = undefined; this.answered(context, q, heard);
      return { say: "Cancelled. Nothing will move." };
    }
    let chosen: Candidate | undefined;
    if (q.confirm) {
      if (/^(yes|yes please|yeah|yep|correct|that s right)$/.test(s)) chosen = q.q.candidates[0];
    } else {
      if (/\b(first|1st)\b/.test(s) || /^(the )?one( please)?$/.test(s)) chosen = q.q.candidates[0];
      if (/\b(second|2nd)\b/.test(s) || /^(the )?two( please)?$/.test(s)) chosen = q.q.candidates[1];
      if (/\b(either|any|you pick)\b/.test(s)) chosen = q.q.candidates[0];
      const side = s.match(/\b(left|right|closest)\b/)?.[1];
      if (side) {
        const sided = q.q.candidates.filter((x) => (x.instance?.side || x.side) === side);
        if (sided.length === 1) chosen = sided[0];
        else if (new Set(q.q.candidates.map((x) => x.item)).size === 1) chosen = { item: q.q.candidates[0].item, instance: { side: side as Instance["side"] } };
      }
      const named = q.q.candidates.map((x) => {
        const it = setting.items.find((i) => i.id === x.item);
        const words = [x.label, x.variant, x.instance?.variant, x.id, it?.name, ...(it?.aliases || [])].filter((x): x is string => !!x).map(norm);
        return { x, score: Math.max(0, ...words.filter((w) => w && (` ${s} `).includes(` ${w} `)).map((w) => w.length)) };
      });
      const max = Math.max(0, ...named.map((x) => x.score));
      const best = named.filter((x) => x.score === max && max > 0);
      if (!chosen && best.length === 1) chosen = best[0].x;
      // Repeating the two options is not an answer, even if one name is longer.
      if (/\bor\b/.test(s) && !/\b(either|any|you pick)\b/.test(s)) chosen = undefined;
    }
    if (chosen?.item) {
      c.question = undefined; q.chosen = chosen; this.answered(context, q, heard);
      return { parsed: { action: q.action, item: chosen.item, ...(Object.keys(chosen.instance || {}).length ? { instance: chosen.instance } : {}) } };
    }
    if (q.confirm) return { say: q.q.say }; // no alternative wording can accidentally bypass the required yes
    // A new explicit non-choice command replaces the question. An unrecognized answer just repeats it.
    const local = localParse(heard, setting);
    if (!CHOICE.test(s) && local.action !== "unknown" && !local.clarify) { c.question = undefined; return null; }
    return { say: q.q.say };
  }
  private answered(context: string, q: Question, answer: string) {
    this.note({ type: "clarify_answer", item: q.q.item, candidates: q.q.candidates, question_id: q.q.question_id,
      answer, answer_ms: this.now() - q.at, context });
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
  event(e: ScrubEvent): { context: string; line?: string; notify?: (line: string) => void } | null {
    if (e.case_id && this.caseId && e.case_id !== this.caseId) {
      const previous = Number(this.caseId.match(/-(\d+(?:\.\d+)?)$/)?.[1]);
      const next = Number(e.case_id.match(/-(\d+(?:\.\d+)?)$/)?.[1]);
      if (Number.isFinite(previous) && Number.isFinite(next) && next < previous) return null;
      const active = e.command_id ? this.commands.get(e.command_id) : undefined;
      this.clear();
      // The first event of a new case may be the command we just posted. Keep its routing, not old history.
      if (active) active.epoch = this.epoch;
    }
    if (e.case_id) this.caseId = e.case_id;
    if (e.type === "stopped") { this.clear(); return null; }
    const o = e.command_id ? this.commands.get(e.command_id) : undefined;
    if (!o || o.epoch !== this.epoch || this.now() - o.at > 300_000) return null;
    if (e.type === "clarify" && e.candidates && e.say) {
      const line = this.ask(o.context, { say: e.say, item: e.item, candidates: e.candidates, question_id: e.question_id }, o.setting, o.command.action, false, false);
      return { context: o.context, line, notify: o.notify };
    }
    if ((e.type === "released" || e.type === "handed") && e.item) {
      this.context(o.context, o.setting.id).lastHanded = { item: e.item, instance: e.instance || o.command.instance };
    }
    if (e.type === "returned") {
      // A return by another person still makes that instrument no longer out.
      for (const c of this.contexts.values()) if (c.lastHanded?.item === e.item) c.lastHanded = undefined;
    }
    return { context: o.context, notify: o.notify };
  }
}

export const dialogue = new Dialogue();
