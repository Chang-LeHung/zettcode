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
