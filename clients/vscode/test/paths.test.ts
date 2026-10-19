import assert from "node:assert/strict";
import test from "node:test";

import { looksLikePath, parsePathTarget, pathLabel } from "../src/core/paths.js";

test("a path carries a line and a column", () => {
  assert.deepEqual(parsePathTarget("src/app.ts:12:3"), { path: "src/app.ts", line: 12, column: 3 });
  assert.deepEqual(parsePathTarget("src/app.ts:12"), { path: "src/app.ts", line: 12 });
  assert.deepEqual(parsePathTarget("README.md"), { path: "README.md" });
});

test("a line can be written as a fragment", () => {
  assert.deepEqual(parsePathTarget("docs/a.md#L10"), { path: "docs/a.md", line: 10 });
  assert.deepEqual(parsePathTarget("docs/a.md#L10-L20"), { path: "docs/a.md", line: 10 });
});

test("a Windows drive is a path, not a line suffix", () => {
  assert.deepEqual(parsePathTarget("C:\\work\\a.py:7"), { path: "C:\\work\\a.py", line: 7 });
  assert.deepEqual(parsePathTarget("C:\\work\\a.py"), { path: "C:\\work\\a.py" });
});

test("a URL is not a path", () => {
  assert.equal(parsePathTarget("https://example.com/a.ts:3"), null);
  assert.equal(parsePathTarget("mailto:someone@example.com"), null);
});

test("prose is not a path", () => {
  assert.equal(parsePathTarget("a sentence with spaces"), null);
  assert.equal(parsePathTarget(""), null);
});

test("wrapping quotes and backticks come off", () => {
  assert.deepEqual(parsePathTarget("`src/a.ts`"), { path: "src/a.ts" });
  assert.deepEqual(parsePathTarget("\"src/a.ts:2\""), { path: "src/a.ts", line: 2 });
});

test("a token looks like a path by its separators or its extension", () => {
  assert.equal(looksLikePath("src/foo.py"), true);
  assert.equal(looksLikePath("README.md"), true);
  assert.equal(looksLikePath("a/b"), true);
  assert.equal(looksLikePath("C:\\work\\a.py"), true);
  assert.equal(looksLikePath("npm test"), false);
  assert.equal(looksLikePath("e.g."), false);
  assert.equal(looksLikePath("src/*.py"), false);
});

test("a label drops the place", () => {
  assert.equal(pathLabel("src/a.ts:12:3"), "src/a.ts");
  assert.equal(pathLabel("  src/a.ts  "), "src/a.ts");
});
