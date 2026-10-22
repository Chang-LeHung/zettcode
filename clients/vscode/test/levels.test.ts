import assert from "node:assert/strict";
import test from "node:test";

import { effortMeta, permissionMeta } from "../src/core/levels.js";

test("the reasoning levels rank from nothing to the most, and only the top two move", () => {
  const names = ["off", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"];
  const levels = names.map((name) => effortMeta(name).level);
  assert.deepEqual(levels, [...levels].sort((a, b) => a - b));
  assert.equal(effortMeta("off").level, 0);
  assert.equal(effortMeta("max").motion, "flow");
  assert.equal(effortMeta("ultra").motion, "aurora");
  for (const name of names.slice(0, 6)) {
    assert.equal(effortMeta(name).motion, "plain");
  }
  assert.equal(effortMeta("HIGH").tone, effortMeta("high").tone);
});

test("a level the table does not know is placed by its position", () => {
  assert.equal(effortMeta("deep", 0, 3).level, 0);
  assert.equal(effortMeta("deep", 2, 3).level, 5);
  assert.equal(effortMeta("deep", 0, 1).motion, "plain");
});

test("each permission has its own icon and tone, and a louder risk the more it allows", () => {
  const levels = ["deny", "ask", "safe", "full"].map(permissionMeta);
  assert.equal(new Set(levels.map((level) => level.icon)).size, 4);
  assert.equal(new Set(levels.map((level) => level.tone)).size, 4);
  assert.deepEqual(
    levels.map((level) => level.risk),
    [0, 1, 2, 3],
  );
  assert.equal(permissionMeta("auto"), permissionMeta("full"), "the old name reads as the same level");
  assert.equal(permissionMeta("nonsense").icon, "shield");
});
