import "./dom-setup";
import assert from "node:assert/strict";
import { test } from "node:test";
import { storage, useScope } from "../src/lib/storage";

test("server values are kept apart while the device value is shared", () => {
  try {
    localStorage.clear();
    useScope("a");
    storage.setGlobal("device", { theme: "dark" });
    storage.set("prefs", { theme: "dark" });
    storage.set("draft.1", "from a");

    useScope("b");
    assert.equal(storage.get("prefs", null), null);
    assert.deepEqual(storage.getGlobal("device", null), { theme: "dark" });
    assert.equal(storage.get("device", null), null);
    storage.set("prefs", { theme: "light" });
    storage.set("draft.1", "from b");

    useScope("a");
    assert.deepEqual(storage.get("prefs", null), { theme: "dark" });
    assert.equal(storage.get("draft.1", ""), "from a");

    storage.clear();
    assert.equal(storage.get("prefs", null), null);
    assert.equal(storage.getGlobal("device", null), null);
    useScope("b");
    assert.equal(storage.get("draft.1", ""), "");
  } finally {
    storage.clear();
    useScope("");
    localStorage.clear();
  }
});
