import assert from "node:assert/strict";
import test from "node:test";

import { APIS, apiChange, apiKeys, maxTemperature, parseTemperature } from "../src/core/model-form.js";

test("each API is one flag, and chat is a flag of its own that says the default outright", () => {
  assert.deepEqual(apiKeys("chat"), { chat: true });
  assert.deepEqual(apiKeys("responses"), { responses_api: true });
  assert.deepEqual(apiKeys("anthropic"), { anthropic: true });
  for (const { value } of APIS) {
    assert.equal(Object.keys(apiKeys(value)).length, 1, `${value} sets exactly one flag`);
  }
});

test("the three APIs are listed in the terminal's order, each with the words that say what it is", () => {
  assert.deepEqual(
    APIS.map((api) => api.value),
    ["chat", "responses", "anthropic"],
  );
  assert.ok(APIS.every((api) => api.label && api.detail));
});

test("moving a model to another API sets its flag and takes the other two out, rather than writing false", () => {
  assert.deepEqual(apiChange("chat"), { chat: true, anthropic: null, responses_api: null });
  assert.deepEqual(apiChange("anthropic"), { chat: null, anthropic: true, responses_api: null });
  assert.deepEqual(apiChange("responses"), { chat: null, anthropic: null, responses_api: true });
  for (const { value } of APIS) {
    const change = apiChange(value);
    assert.equal(Object.values(change).filter((flag) => flag === true).length, 1);
    assert.ok(!Object.values(change).includes(false), "a flag is removed with null, never set to false");
  }
});

test("an empty temperature is none, and zero is a temperature", () => {
  assert.deepEqual(parseTemperature(""), { kind: "none" });
  assert.deepEqual(parseTemperature("   "), { kind: "none" });
  assert.deepEqual(parseTemperature("0"), { kind: "value", value: 0 });
  assert.deepEqual(parseTemperature("0.2"), { kind: "value", value: 0.2 });
  assert.deepEqual(parseTemperature(" 2 "), { kind: "value", value: 2 });
});

test("a temperature is from 0 to 2, or from 0 to 1 for Anthropic, and anything else says why not", () => {
  assert.equal(maxTemperature("chat"), 2);
  assert.equal(maxTemperature("responses"), 2);
  assert.equal(maxTemperature("anthropic"), 1);
  assert.equal(maxTemperature(null), 2, "with no API known, the wider limit; the server has the last word");

  const hot = parseTemperature("2.5");
  assert.equal(hot.kind, "error");
  assert.ok(hot.kind === "error" && hot.message.includes("0 to 2"));
  const anthropic = parseTemperature("1.5", "anthropic");
  assert.ok(anthropic.kind === "error" && anthropic.message.includes("0 to 1") && anthropic.message.includes("Anthropic"));
  assert.deepEqual(parseTemperature("1", "anthropic"), { kind: "value", value: 1 });
  assert.equal(parseTemperature("-0.1").kind, "error");
  const word = parseTemperature("warm");
  assert.ok(word.kind === "error" && word.message.includes("number"));
  assert.equal(parseTemperature("NaN").kind, "error");
  assert.equal(parseTemperature("Infinity").kind, "error");
});
