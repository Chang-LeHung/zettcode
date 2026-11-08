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

export const prefs: Prefs = reactive({
  ...DEFAULTS,
  defaults: { ...DEFAULTS.defaults },
  templates: [],
  recent: [],
});

export function applyPrefs(): void {
  const root = document.documentElement;
  if (prefs.theme === "light" || prefs.theme === "dark") root.dataset.theme = prefs.theme;
  else delete root.dataset.theme;
  if (prefs.size === "s" || prefs.size === "l") root.dataset.size = prefs.size;
  else delete root.dataset.size;
  setLanguage(prefs.language);
}

/** Load the device's look and this server's defaults/drafts and keep both, applying the look whenever one changes. */
export function watchPrefs(): void {
  const global = storage.getGlobal<Partial<Prefs>>("prefs", {});
  // Before the split this page kept one flat blob; take a server's part from it until its own key exists.
  const saved = storage.get<Partial<Prefs>>("server", {
    defaults: global.defaults,
    templates: global.templates,
    recent: global.recent,
  });
  Object.assign(prefs, structuredClone(DEFAULTS), global, saved, {
    defaults: { ...DEFAULTS.defaults, ...(saved.defaults ?? {}) },
    templates: saved.templates ?? [],
    recent: saved.recent ?? [],
  });
  // English is the default and Chinese is a choice. A device that saved the old "auto" (follow the browser) gets English.
  if (prefs.language !== "zh") prefs.language = "en";
  applyPrefs();
  watch(
    prefs,
    () => {
      storage.setGlobal("prefs", {
        theme: prefs.theme,
        size: prefs.size,
        language: prefs.language,
        render: prefs.render,
        avatar: prefs.avatar,
        notify: prefs.notify,
        askReply: prefs.askReply,
        confirmSession: prefs.confirmSession,
      });
      storage.set("server", {
        defaults: prefs.defaults,
        templates: prefs.templates,
        recent: prefs.recent,
      });
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
