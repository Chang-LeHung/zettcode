import assert from "node:assert/strict";
import { test } from "node:test";
import { eraseWhole } from "../src/lib/erase";

const at = (value: string, handles: string[] = []) => eraseWhole(value, value.length, handles);
/** What the text and caret become; `from`/`to` are checked on their own. */
const result = (r: ReturnType<typeof eraseWhole>) => (r ? { value: r.value, caret: r.caret } : null);

test("a picked mention goes at once, and what was before it stays", () => {
  assert.deepEqual(result(at("hi @reviewer ", ["reviewer"])), { value: "hi ", caret: 3 });
  assert.deepEqual(result(at("@reviewer ", ["Reviewer"])), { value: "", caret: 0 });
  assert.deepEqual(result(at("@测试员 ", ["测试员"])), { value: "", caret: 0 });
});

test("a word that is not a member's, or one still being typed, is erased a character at a time", () => {
  assert.equal(at("mail @bob ", ["reviewer"]), null);
  assert.equal(at("hi @review", ["reviewer"]), null);
  assert.equal(at("a@reviewer ", ["reviewer"]), null, "an address inside a word is not a mention");
});

test("a mention is erased whole from the middle of a line as well", () => {
  const value = "hi @reviewer please";
  assert.deepEqual(result(eraseWhole(value, "hi @reviewer ".length, ["reviewer"])), { value: "hi please", caret: 3 });
});

test("a quote goes at once with the blank line after it", () => {
  assert.deepEqual(result(at("> one\n> two\n\n")), { value: "", caret: 0 });
  assert.deepEqual(result(at("> one\n")), { value: "", caret: 0 });
  assert.deepEqual(result(at("hello\n\n> quoted\n\n")), { value: "hello\n", caret: 6 });
});

test("only the quote just before the caret goes", () => {
  assert.deepEqual(result(at("> a\n\n> b\n\n")), { value: "> a\n", caret: 4 });
  assert.deepEqual(result(eraseWhole("> a\n\nmy reply", "> a\n\n".length)), { value: "my reply", caret: 0 });
});

test("an ordinary line is left to the browser", () => {
  assert.equal(at("hello\n"), null);
  assert.equal(at("hello"), null);
  assert.equal(at("> quote text"), null, "the caret is still on the quote's own line");
  assert.equal(at(""), null);
});

test("the span that goes is exactly what the new text lacks, so a native delete of it gives the same result", () => {
  for (const [value, caret, handles] of [
    ["hi @reviewer please", "hi @reviewer ".length, ["reviewer"]],
    ["hello\n\n> quoted\n\n", "hello\n\n> quoted\n\n".length, []],
    ["> a\n\n> b\n\nmy reply", "> a\n\n> b\n\n".length, []],
  ] as const) {
    const whole = eraseWhole(value, caret, [...handles])!;
    assert.equal(value.slice(0, whole.from) + value.slice(whole.to), whole.value);
    assert.equal(whole.to, caret);
  }
});
