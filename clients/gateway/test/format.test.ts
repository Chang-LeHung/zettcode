import assert from "node:assert/strict";
import { test } from "node:test";
import { percent } from "../src/lib/format";

test("a share is a percentage with one decimal, or a dash when it was not measured", () => {
  assert.equal(percent(null), "–");
  assert.equal(percent(0), "0.0%");
  assert.equal(percent(0.9737), "97.4%");
  assert.equal(percent(0.5), "50.0%");
});

test("a share that rounds to all of it is written 100%, not 100.0%", () => {
  assert.equal(percent(1), "100%");
  assert.equal(percent(0.99996), "100%");
  assert.equal(percent(0.9994), "99.9%", "short of the rounding point it keeps its decimal");
});

test("the number of decimals can be asked for, and the whole-number case follows it", () => {
  assert.equal(percent(0.1234, 0), "12%");
  assert.equal(percent(0.996, 0), "100%");
  assert.equal(percent(0.1234, 2), "12.34%");
});
