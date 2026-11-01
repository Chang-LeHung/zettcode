// The model form edits strings; the configuration file holds numbers and flags. This turns one into the other, and a
// finished form into only what a request has to say: a new model names what was filled in, a change names what moved.

import type { ModelDraft, ModelOption } from "../types";

/** The reasoning levels a model may be limited to, cheapest first. */
export const EFFORT_LEVELS = ["off", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"];

export function blankDraft(): ModelDraft {
  return {
    model: "",
    display_model: "",
    api: "chat",
    base_url: "",
    token: "",
    context_window: "",
    compact_percent: "",
    temperature: "",
    multimodal: false,
    web_search: false,
    efforts: [],
  };
}

function protocol(api: string): ModelDraft["api"] {
  return api === "anthropic" || api === "responses" ? api : "chat";
}

/** A model as it is now, as the form shows it. The token is never known here, so its box starts empty. */
export function draftOf(model: ModelOption): ModelDraft {
  return {
    model: model.model,
    display_model: model.display_model ?? "",
    api: protocol(model.api),
    base_url: model.base_url ?? "",
    token: "",
    context_window: String(model.context_window),
    compact_percent: model.compact_percent === undefined ? "" : String(model.compact_percent),
    temperature: model.temperature == null ? "" : String(model.temperature),
    multimodal: model.multimodal,
    web_search: model.web_search === true,
    efforts: [...model.efforts],
  };
}

/** A number box: `undefined` for an empty one, `NaN` for text that is not a number. */
function number(text: string): number | undefined {
  const value = text.trim();
  return value === "" ? undefined : Number(value);
}

/** What is wrong with the form, as the English the page translates, or an empty string when it can be sent. */
export function problem(draft: ModelDraft): string {
  if (!draft.model.trim()) return "The model id is required";
  const window = number(draft.context_window);
  if (window !== undefined && (!Number.isInteger(window) || window < 1)) return "The context window is a whole number of tokens";
  const percent = number(draft.compact_percent);
  if (percent !== undefined && !(percent > 0 && percent <= 100)) return "Compact at is a percentage from 1 to 100";
  const heat = number(draft.temperature);
  const top = draft.api === "anthropic" ? 1 : 2;
  if (heat !== undefined && !(heat >= 0 && heat <= top)) return top === 1 ? "The temperature is from 0 to 1 for this protocol" : "The temperature is from 0 to 2";
  return "";
}

/** The keys that choose the protocol: the chosen one is set and the others are taken out, so none is left as false. */
function protocolKeys(api: ModelDraft["api"], change: boolean): Record<string, unknown> {
  if (!change) return api === "anthropic" ? { anthropic: true } : api === "responses" ? { responses_api: true } : {};
  return {
    anthropic: api === "anthropic" ? true : null,
    responses_api: api === "responses" ? true : null,
    chat: null,
  };
}

/** The body that adds a model: only what the person filled in. */
export function entryOf(draft: ModelDraft): Record<string, unknown> {
  const out: Record<string, unknown> = { model: draft.model.trim(), ...protocolKeys(draft.api, false) };
  const text = { display_model: draft.display_model, base_url: draft.base_url, token: draft.token };
  for (const [key, value] of Object.entries(text)) if (value.trim()) out[key] = value.trim();
  const numbers = { context_window: draft.context_window, compact_percent: draft.compact_percent, temperature: draft.temperature };
  for (const [key, value] of Object.entries(numbers)) if (number(value) !== undefined) out[key] = number(value);
  if (draft.multimodal) out.multimodal = true;
  if (draft.web_search) out.web_search = true;
  if (draft.efforts.length) out.reasoning_efforts = draft.efforts;
  return out;
}

/** The body that changes a model: only what differs from the model as it was. `null` removes a key from the file. */
export function changesOf(draft: ModelDraft, before: ModelOption): Record<string, unknown> {
  const was = draftOf(before);
  const out: Record<string, unknown> = {};
  if (draft.model.trim() !== was.model) out.model = draft.model.trim();
  if (draft.api !== was.api) Object.assign(out, protocolKeys(draft.api, true));
  for (const key of ["display_model", "base_url"] as const) {
    if (draft[key].trim() !== was[key]) out[key] = draft[key].trim() || null;
  }
  if (draft.token.trim()) out.token = draft.token.trim();
  for (const key of ["context_window", "compact_percent", "temperature"] as const) {
    if (draft[key].trim() !== was[key]) out[key] = number(draft[key]) ?? null;
  }
  if (draft.multimodal !== was.multimodal) out.multimodal = draft.multimodal || null;
  if (draft.web_search !== was.web_search) out.web_search = draft.web_search || null;
  if (draft.efforts.join() !== was.efforts.join()) out.reasoning_efforts = draft.efforts.length ? draft.efforts : null;
  return out;
}

/** Add a level to the chosen ones, or take it away, keeping them cheapest first as the file does. */
export function toggled(levels: string[], level: string): string[] {
  const next = levels.includes(level) ? levels.filter((item) => item !== level) : [...levels, level];
  return next.sort((a, b) => EFFORT_LEVELS.indexOf(a) - EFFORT_LEVELS.indexOf(b));
}
