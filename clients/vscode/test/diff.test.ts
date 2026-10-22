import assert from "node:assert/strict";
import test from "node:test";

import { diffText, splitLines } from "../src/core/diff.js";
import { ChangeLedger, changesFile, unapply } from "../src/core/ledger.js";

test("lines split without a phantom last line", () => {
  assert.deepEqual(splitLines("a\nb\n"), ["a", "b"]);
  assert.deepEqual(splitLines("a\r\nb"), ["a", "b"]);
  assert.deepEqual(splitLines(null), []);
  assert.deepEqual(splitLines(""), []);
});

test("a diff counts exactly and keeps a little context", () => {
  const before = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine"].join("\n");
  const after = ["one", "two", "THREE", "four", "five", "six", "seven", "eight", "nine", "ten"].join("\n");
  const diff = diffText(before, after, { context: 1 });
  assert.equal(diff.added, 2);
  assert.equal(diff.removed, 1);
  const kinds = diff.rows.map((row) => row.kind);
  assert.deepEqual(kinds, ["ctx", "del", "add", "ctx", "gap", "ctx", "add"]);
  const first = diff.rows[1];
  assert.equal(first?.oldLine, 3);
  assert.equal(diff.rows[2]?.newLine, 3);
});

test("a new file is all additions and a deleted one all removals", () => {
  const created = diffText(null, "a\nb\n");
  assert.equal(created.added, 2);
  assert.equal(created.removed, 0);
  assert.ok(created.rows.every((row) => row.kind === "add"));
  const deleted = diffText("a\nb\n", null);
  assert.equal(deleted.removed, 2);
  assert.ok(deleted.rows.every((row) => row.kind === "del"));
});

test("rows are capped while the counts stay exact", () => {
  const after = Array.from({ length: 50 }, (_, index) => `line ${index}`).join("\n");
  const diff = diffText("", after, { maxRows: 10 });
  assert.equal(diff.added, 50);
  assert.equal(diff.rows.length, 10);
  assert.equal(diff.truncated, true);
});

test("identical text is no change", () => {
  const diff = diffText("same\n", "same\n");
  assert.equal(diff.added + diff.removed, 0);
  assert.deepEqual(diff.rows, []);
});

test("the ledger snapshots a file once, then keeps only what really changed", async () => {
  const disk = new Map<string, string | null>([
    ["src/a.ts", "one\ntwo\n"],
    ["src/b.ts", "same\n"],
  ]);
  const ledger = new ChangeLedger(async (path) => disk.get(path) ?? null, "/work");
  await ledger.touch("t1", "/work/src/a.ts");
  await ledger.touch("t1", "src/b.ts");
  await ledger.touch("t1", "src/new.ts");
  disk.set("src/a.ts", "one\nTWO\nthree\n");
  disk.set("src/new.ts", "hello\n");
  await ledger.touch("t1", "src/a.ts");
  const changes = await ledger.settle("t1");
  assert.deepEqual(
    changes.map((change) => [change.path, change.status, change.added, change.removed]),
    [
      ["src/a.ts", "modified", 2, 1],
      ["src/new.ts", "added", 1, 0],
    ],
  );
  assert.equal(ledger.find("t1", "/work/src/a.ts")?.before, "one\ntwo\n");
  assert.deepEqual(ledger.summaries("t1").map((change) => change.path), ["src/a.ts", "src/new.ts"]);
  assert.deepEqual(await ledger.settle("unknown"), []);
});

test("only the file-changing tools are tracked", () => {
  assert.equal(changesFile("edit"), true);
  assert.equal(changesFile("write_file"), true);
  assert.equal(changesFile("replace_in_file"), true);
  assert.equal(changesFile("bash"), false);
  assert.equal(changesFile("read_file"), false);
  assert.equal(changesFile("read"), false);
});

test("there is no delete tool to follow: a deletion is only ever seen as the real difference in the file", async () => {
  assert.equal(changesFile("delete_file"), false);
  assert.equal(changesFile("mcp__fs__delete_file"), false);
  assert.equal(changesFile("delete"), false);

  // A file the request edited and then removed (with `rm`, which is how it is removed now) still shows as deleted,
  // because the card compares what the file held with what it holds, whatever removed it.
  let present: string | null = "one\ntwo\n";
  const ledger = new ChangeLedger(async () => present, "/work");
  await ledger.touch("t1", "a.ts", [{ oldText: "two", newText: "2" }]);
  present = null;
  await ledger.settle("t1");
  const [change] = ledger.summaries("t1");
  assert.equal(change?.status, "deleted");
  assert.equal(change?.removed, 2);
  assert.equal(ledger.find("t1", "a.ts")?.after, null);
});

test("the ledger forgets the oldest requests", async () => {
  const ledger = new ChangeLedger(async () => "x", "/work");
  for (let index = 0; index < 45; index += 1) {
    await ledger.touch(`t${index}`, "a.ts");
    await ledger.settle(`t${index}`);
  }
  assert.ok(ledger.turnIds().length <= 40);
  assert.equal(ledger.turnIds().includes("t0"), false);
});

test("an edit that landed before the snapshot is rebuilt from its own arguments", async () => {
  const disk = new Map<string, string | null>([["a.ts", "const a = 2;\nconst b = 3;\n"]]);
  const ledger = new ChangeLedger(async (path) => disk.get(path) ?? null, "/work");
  // The tool already ran: the snapshot sees the new text.
  await ledger.touch("t1", "a.ts", [{ oldText: "const a = 1;", newText: "const a = 2;" }]);
  const [change] = await ledger.settle("t1");
  assert.equal(change?.status, "modified");
  assert.equal(change?.before, "const a = 1;\nconst b = 3;\n");
  assert.equal(change?.added, 1);
  assert.equal(change?.removed, 1);
});

test("a file observed before the request is what the request replaced", async () => {
  const disk = new Map<string, string | null>([["a.ts", "old\n"]]);
  const ledger = new ChangeLedger(async (path) => disk.get(path) ?? null, "/work");
  await ledger.observe("a.ts");
  disk.set("a.ts", "new\n");
  await ledger.touch("t1", "a.ts");
  const [change] = await ledger.settle("t1");
  assert.equal(change?.before, "old\n");
  assert.equal(change?.after, "new\n");
});

test("unapply refuses to guess", () => {
  assert.equal(unapply("x", [{ oldText: "a", newText: "missing" }]), null);
  assert.equal(unapply("x", []), null);
  assert.equal(unapply("x b y", [{ oldText: "a", newText: "b" }]), "x a y");
});
