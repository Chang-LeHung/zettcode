import assert from "node:assert/strict";
import { test } from "node:test";
import { PHONE_TABS, TABS } from "../src/sections";
import { NAVS } from "../src/stores/route";

test("every section of the page has exactly one tab, so a new section cannot be left out of the rail", () => {
  assert.deepEqual([...TABS.map((tab) => tab.nav)].sort(), [...NAVS].sort());
});

test("a phone's bar keeps four tabs and the rest are behind More, so a new section must say which it is", () => {
  assert.equal(TABS.filter((tab) => !tab.extra).length, PHONE_TABS);
  assert.deepEqual(
    TABS.filter((tab) => tab.extra).map((tab) => tab.nav),
    ["config", "logs", "graph"],
  );
});
