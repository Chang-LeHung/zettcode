import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

// A <button> with no type submits the form it is in. Choosing "Full" in the New daemon form once started the daemon
// because the segmented control's buttons were submit buttons, so the shared controls must say what they are.
const CONTROLS = ["Segmented", "SwitchRow"];

for (const name of CONTROLS) {
  test(`every button of ${name} says it is not a submit button`, () => {
    const source = readFileSync(`src/components/common/${name}.vue`, "utf8");
    const tags = source.match(/<button\b[^>]*>/gs) ?? [];
    assert.ok(tags.length > 0, "the control has a button");
    for (const tag of tags) assert.match(tag, /\btype="button"/, tag);
  });
}
