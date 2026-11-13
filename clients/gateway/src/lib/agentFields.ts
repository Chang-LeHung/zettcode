// The settings a plugin lets the page choose for an agent: which choices to offer and what to send. Apart from the
// component so the rules are tested; the gateway checks everything again, so this only keeps the page from offering
// what it would refuse.

import type { AgentField } from "../types";

/** The choices a field offers: all of them, less the unrestricted one when the gateway does not allow full access. */
export function offered(field: AgentField, allowFull: boolean): string[] {
  return field.choices.filter((choice) => allowFull || !field.unrestricted || choice !== field.unrestricted);
}

/** The value a field starts at: its default when it is offered, else nothing (the plugin's own setting applies). */
export function initial(field: AgentField, allowFull: boolean): string {
  if (field.kind !== "choice") return field.default;
  return offered(field, allowFull).includes(field.default) ? field.default : "";
}

/** What to send: only the fields the person filled in, trimmed; an empty one is left out so the plugin's own applies. */
export function optionsOf(fields: AgentField[], values: Record<string, string>): Record<string, string> {
  const sent: Record<string, string> = {};
  for (const field of fields) {
    const value = (values[field.name] ?? "").trim();
    if (value) sent[field.name] = value;
  }
  return sent;
}
