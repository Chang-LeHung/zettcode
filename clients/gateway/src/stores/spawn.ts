// What the new-daemon form holds. It lives outside the form so leaving the page and coming back keeps what was typed,
// and so another view (a stopped daemon's "start again") can fill it in and send the person there.

import { reactive } from "vue";
import type { SpawnForm, Thread } from "../types";
import { prefs, type Template } from "./prefs";

const blank = (): SpawnForm => ({
  workspace: "",
  model: prefs.defaults.model,
  effort: prefs.defaults.effort,
  permission: prefs.defaults.permission || "safe",
  name: "",
  resume: "",
  message: "",
});

export const draft = reactive<SpawnForm>(blank());

export function resetDraft(changes: Partial<SpawnForm> = {}): void {
  Object.assign(draft, blank(), changes);
}

export function applyTemplate(template: Template): void {
  Object.assign(draft, {
    name: template.name,
    model: template.model,
    effort: template.effort,
    permission: template.permission,
    message: template.message,
  });
}

/** Fill the form from a daemon, to start it again (with `resume`) on the same conversation. */
export function fromThread(thread: Thread): void {
  resetDraft({
    workspace: thread.workspace,
    model: thread.model ?? "",
    effort: thread.effort ?? "",
    permission: thread.permission ?? "safe",
    name: thread.name === thread.id.slice(0, 8) ? "" : thread.name,
    resume: thread.id,
  });
}

export const BUILT_IN_TEMPLATES: Template[] = [
  { label: "Reviewer", name: "reviewer", model: "", effort: "", permission: "safe", message: "Review the current diff and list concrete problems." },
  { label: "Explorer", name: "explorer", model: "", effort: "", permission: "safe", message: "Find where this is implemented and summarize how it works." },
];
