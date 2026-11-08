import "./dom-setup";
import assert from "node:assert/strict";
import { test } from "node:test";
import { nextTick } from "vue";
import { storage, useScope } from "../src/lib/storage";
import { prefs, watchPrefs } from "../src/stores/prefs";

test("the look is device-wide and a server's defaults and recent folders are scoped", async () => {
  try {
    localStorage.clear();
    // The pre-split page kept one flat blob; the first load after the split must keep its server half.
    storage.setGlobal("prefs", {
      theme: "light",
      language: "en",
      defaults: { model: "old", effort: "high", permission: "full" },
      templates: [{ label: "old template", name: "", model: "", effort: "", permission: "", message: "" }],
      recent: ["/old"],
    });
    useScope("a");
    watchPrefs();
    assert.equal(prefs.defaults.model, "old");
    assert.equal(prefs.templates[0]?.label, "old template");
    assert.deepEqual(prefs.recent, ["/old"]);

    prefs.theme = "dark";
    prefs.language = "zh";
    prefs.defaults.model = "model-a";
    prefs.recent = ["/work/a"];
    await nextTick();

    const device = storage.getGlobal<Record<string, unknown>>("prefs", {});
    const server = storage.get<Record<string, unknown>>("server", {});
    assert.equal(device.theme, "dark");
    assert.equal(device.language, "zh");
    assert.equal(device.recent, undefined, "a server's recent folders are not device-wide");
    assert.equal(device.defaults, undefined, "a server's defaults are not device-wide");
    assert.deepEqual(server.recent, ["/work/a"]);
    assert.deepEqual(server.defaults, { model: "model-a", effort: "high", permission: "full" });
    assert.equal((server.templates as Array<{ label: string }>)[0]?.label, "old template");
  } finally {
    localStorage.clear();
    useScope("");
  }
});
