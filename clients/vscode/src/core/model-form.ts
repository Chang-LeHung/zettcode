/** What the model forms send: which API an endpoint speaks, and the sampling temperature. */

import type { ModelInput, ModelUpdate } from "../../../typescript/src/types.js";

/** The three request protocols one model entry can speak, as the terminal's `/config` names them. */
export type Api = "chat" | "responses" | "anthropic";

/** Each protocol, in the order a list shows them, with the words that say what it is. */
export const APIS: readonly { value: Api; label: string; detail: string }[] = [
  { value: "chat", label: "Chat completions", detail: "an OpenAI-compatible endpoint" },
  { value: "responses", label: "Responses API", detail: "an OpenAI-compatible endpoint" },
  { value: "anthropic", label: "Anthropic Messages API", detail: "Anthropic's own API" },
];

/** The most a temperature may be: 2 on an OpenAI-compatible endpoint, 1 on Anthropic's. */
export function maxTemperature(api: Api | null): number {
  return api === "anthropic" ? 1 : 2;
}

/**
 * The keys that say a new model speaks `api`: the one flag that selects it, `chat` included, and no other.
 *
 * `chat = true` says outright what an entry with neither of the others already is, so a file written here reads
 * the way one written in the terminal does.
 */
export function apiKeys(api: Api): Pick<ModelInput, "chat" | "anthropic" | "responses_api"> {
  if (api === "anthropic") {
    return { anthropic: true };
  }
  if (api === "responses") {
    return { responses_api: true };
  }
  return { chat: true };
}

/**
 * The change that moves an existing model to `api`: its flag set and the other two taken out of the file (`null`),
 * so one protocol gives way to another without `anthropic = false` being left behind.
 */
export function apiChange(api: Api): ModelUpdate {
  return {
    chat: api === "chat" ? true : null,
    anthropic: api === "anthropic" ? true : null,
    responses_api: api === "responses" ? true : null,
  };
}

/** What a temperature field says: a number to send, nothing (left empty), or a reason it cannot be used. */
export type Temperature = { kind: "none" } | { kind: "value"; value: number } | { kind: "error"; message: string };

/** The hosted search tool each API is sent by default; an entry may name another (`web_search_name`). */
export const SEARCH_DEFAULTS = {
  chat: "web_search",
  responses: "web_search",
  anthropic: "web_search_20260318",
  /** DeepSeek's Anthropic-compatible endpoint knows only the older dated type. */
  deepseekAnthropic: "web_search_20250305",
} as const;

/** Whether a model is DeepSeek's, by its id or by the address it is served from, as the server decides it. */
export function isDeepSeek(model: string, baseUrl: string): boolean {
  return model.toLowerCase().includes("deepseek") || baseUrl.toLowerCase().includes("deepseek");
}

/** The tool type a search is sent as when the entry names none, so the form can show it as the placeholder. */
export function defaultSearchName(api: Api, model: string, baseUrl: string): string {
  if (api !== "anthropic") {
    return SEARCH_DEFAULTS.chat;
  }
  return isDeepSeek(model, baseUrl) ? SEARCH_DEFAULTS.deepseekAnthropic : SEARCH_DEFAULTS.anthropic;
}

/**
 * Why web search cannot be switched on for this model, or `null` when nothing is known against it. DeepSeek serves
 * search only over its Anthropic-compatible endpoint, which the server also enforces; saying it here saves the trip.
 */
export function searchProblem(api: Api | null, model: string, baseUrl: string): string | null {
  if (api !== "anthropic" && isDeepSeek(model, baseUrl)) {
    return "DeepSeek serves web search only on its Anthropic-compatible endpoint: choose the Anthropic API.";
  }
  return null;
}

/** The keys a web-search choice writes: nothing when it is off, and a name only when one was typed. */
export function searchKeys(on: boolean, name: string): Pick<ModelInput, "web_search" | "web_search_name"> {
  if (!on) {
    return {};
  }
  const trimmed = name.trim();
  return trimmed ? { web_search: true, web_search_name: trimmed } : { web_search: true };
}

/**
 * Read the text of a temperature field.
 *
 * Empty is no temperature, so the provider's own is used. Zero is a temperature, and the most deterministic one.
 *
 * @param text What was typed.
 * @param api The protocol it will be sent over, for the limit; `null` when that is not known.
 */
export function parseTemperature(text: string, api: Api | null = null): Temperature {
  const trimmed = text.trim();
  if (!trimmed) {
    return { kind: "none" };
  }
  const limit = maxTemperature(api);
  const value = Number(trimmed);
  if (!Number.isFinite(value)) {
    return { kind: "error", message: `Write the temperature as a number from 0 to ${limit}, such as 0.2.` };
  }
  if (value < 0 || value > limit) {
    return {
      kind: "error",
      message: `The temperature is from 0 to ${limit}${limit === 1 ? " for the Anthropic API" : ""}.`,
    };
  }
  return { kind: "value", value };
}
