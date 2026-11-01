// What the person chose on this device: the look, the language, how sending behaves, and the forms they reuse.
// It is kept in the browser and nowhere else; the gateway never sees it.

import { reactive, watch } from "vue";
import { setLanguage, type LanguagePreference } from "../i18n";
import { storage } from "../lib/storage";

export interface Template {
  label: string;
  name: string;
  model: string;
  effort: string;
  permission: string;
  message: string;
}

export interface Prefs {
  theme: "auto" | "light" | "dark";
  size: "s" | "m" | "l";
  language: LanguagePreference;
  /** How a message is drawn: as markdown (code highlighted, math typeset) or as the source text. */
  render: "markdown" | "source";
  /** The picture shown beside your messages, as a small data URL; empty is the default one. */
  avatar: string;
  notify: boolean;
  /** Ask a daemon to answer with `send_message` unless a message says otherwise. */
  askReply: boolean;
  /** Ask before the first message to a session that has a person at it. */
  confirmSession: boolean;
  defaults: { model: string; effort: string; permission: string };
  templates: Template[];
  recent: string[];
}

const DEFAULTS: Prefs = {
  theme: "auto",
  size: "m",
  language: "en",
  render: "markdown",
  avatar: "",
  notify: false,
  askReply: true,
  confirmSession: true,
  defaults: { model: "", effort: "", permission: "safe" },
  templates: [],
  recent: [],
};

const saved = storage.get<Partial<Prefs>>("prefs", {});

export const prefs: Prefs = reactive({ ...DEFAULTS, ...saved, defaults: { ...DEFAULTS.defaults, ...saved.defaults } });
// English is the default and Chinese is a choice. A device that saved the old "auto" (follow the browser) gets English.
if (prefs.language !== "zh") prefs.language = "en";

export function applyPrefs(): void {
  const root = document.documentElement;
  if (prefs.theme === "light" || prefs.theme === "dark") root.dataset.theme = prefs.theme;
  else delete root.dataset.theme;
  if (prefs.size === "s" || prefs.size === "l") root.dataset.size = prefs.size;
  else delete root.dataset.size;
  setLanguage(prefs.language);
}

/** Keep the preferences and apply them whenever one changes. Called once, at start. */
export function watchPrefs(): void {
  applyPrefs();
  watch(
    prefs,
    () => {
      storage.set("prefs", prefs);
      applyPrefs();
    },
    { deep: true },
  );
}

/** Remember a directory something was started in, newest first. */
export function rememberWorkspace(path: string): void {
  prefs.recent = [path, ...prefs.recent.filter((item) => item !== path)].slice(0, 8);
}

export function resetPrefs(): void {
  Object.assign(prefs, structuredClone(DEFAULTS));
}
