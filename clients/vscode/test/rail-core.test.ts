import assert from "node:assert/strict";
import test from "node:test";

import { GROUP, isDense, popupTop, railHeight, unitsOf } from "../src/core/rail.js";

test("a view that is not laid out, or a short conversation, never groups", () => {
  assert.equal(isDense(500, 0), false);
  assert.equal(isDense(GROUP, 400), false);
  assert.equal(isDense(2, 400), false);
});

test("bars group exactly when each would get less than six pixels", () => {
  // 400px of view: the rail may take 288px. 48 bars get 6px each, 49 get less.
  assert.equal(railHeight(80, 400), 288);
  assert.equal(isDense(48, 400), false);
  assert.equal(isDense(49, 400), true);
  // A taller view fits more before it groups.
  assert.equal(isDense(80, 1000), false);
});

test("units are single messages, or runs of ten with a short last run", () => {
  assert.deepEqual(unitsOf(3, false), [
    { first: 0, last: 0 },
    { first: 1, last: 1 },
    { first: 2, last: 2 },
  ]);
  const grouped = unitsOf(25, true);
  assert.deepEqual(grouped, [
    { first: 0, last: 9 },
    { first: 10, last: 19 },
    { first: 20, last: 24 },
  ]);
  assert.deepEqual(unitsOf(0, true), []);
});

test("the list sits beside its bar and stays inside the view", () => {
  assert.equal(popupTop(200, 100, 800), 150);
  assert.equal(popupTop(10, 100, 800), 8, "not above the top");
  assert.equal(popupTop(790, 100, 800), 692, "not below the bottom");
});
