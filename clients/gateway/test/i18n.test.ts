import assert from "node:assert/strict";
import { test } from "node:test";
import { currentLanguage, setLanguage, t } from "../src/i18n";
import { ZH } from "../src/i18n/zh";

test("the page starts in English, and a string is shown as written", () => {
  assert.equal(currentLanguage(), "en");
  assert.equal(t("Settings"), "Settings");
});

test("choosing Chinese translates by the English text, and choosing English goes back", () => {
  setLanguage("zh");
  assert.equal(t("Settings"), "设置");
  setLanguage("en");
  assert.equal(t("Settings"), "Settings");
});

test("a string with no translation shows as written in Chinese too, and placeholders are filled", () => {
  setLanguage("zh");
  assert.equal(t("Never translated"), "Never translated");
  assert.equal(t("Stop {name}?", { name: "review" }), "停止 review?");
  assert.equal(t("Never {x}", { x: 3 }), "Never 3");
  setLanguage("en");
  assert.equal(t("Stop {name}?", { name: "review" }), "Stop review?");
});

test("every placeholder of an English string is kept by its translation", () => {
  for (const [english, chinese] of Object.entries(ZH)) {
    const wanted = [...english.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
    const kept = [...chinese.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
    assert.deepEqual(kept, wanted, english);
  }
});
