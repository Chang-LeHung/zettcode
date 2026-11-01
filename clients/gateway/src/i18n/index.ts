// Two languages. English is the text written in the code and Chinese is looked up by that text, so a string with
// no translation shows as written and a new one never breaks a page. The active language is reactive: a template
// that calls `t` is drawn again when it changes.

import { ref } from "vue";
import { ZH } from "./zh";

export type LanguagePreference = "en" | "zh";

const active = ref<"en" | "zh">("en");

export function setLanguage(preference: LanguagePreference): void {
  active.value = preference;
  if (typeof document !== "undefined") document.documentElement.lang = active.value === "zh" ? "zh-CN" : "en";
}

export function currentLanguage(): "en" | "zh" {
  return active.value;
}

/** Translate `text` and fill its `{name}` placeholders from `vars`. */
export function t(text: string, vars?: Record<string, string | number>): string {
  const translated = active.value === "zh" ? (ZH[text] ?? text) : text;
  if (!vars) return translated;
  return translated.replace(/\{(\w+)\}/g, (_, name: string) => String(vars[name] ?? ""));
}
