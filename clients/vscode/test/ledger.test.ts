import assert from "node:assert/strict";
import test from "node:test";

import { applyAll, ChangeLedger } from "../src/core/ledger.js";

/** A ledger over an in-memory disk, with the file already seen once (a read, or an earlier request). */
async function seen(files: Record<string, string | null>, ...remembered: string[]) {
  const disk = new Map<string, string | null>(Object.entries(files));
  const ledger = new ChangeLedger(async (path) => disk.get(path) ?? null, "/work");
  for (const path of remembered) {
    await ledger.observe(path);
  }
  return { disk, ledger };
}

test("a file made new by a write is all additions, even if it was remembered as something else", async () => {
  // The ledger saw `server.py` earlier; a shell command has since removed it, and the request writes it afresh.
  const { disk, ledger } = await seen({ "server.py": "old one\nold two\n" }, "server.py");
  disk.set("server.py", null);
  await ledger.touch("t1", "server.py", [], "print('new')\n");
  disk.set("server.py", "print('new')\n");

  const [change] = await ledger.settle("t1");
  assert.equal(change?.status, "added");
  assert.equal(change?.before, null);
  assert.equal(change?.added, 1);
  assert.equal(change?.removed, 0, "nothing is shown as removed from a file that was not there");
});

test("a write that replaces a file changed behind the ledger's back compares with what was really there", async () => {
  const { disk, ledger } = await seen({ "a.ts": "stale\n" }, "a.ts");
  disk.set("a.ts", "what the reader typed\n");
  await ledger.touch("t1", "a.ts", [], "rewritten\n");
  disk.set("a.ts", "rewritten\n");

  const [change] = await ledger.settle("t1");
  assert.equal(change?.before, "what the reader typed\n");
  assert.equal(change?.status, "modified");
});

test("a write that already landed still compares with the remembered text", async () => {
  const { disk, ledger } = await seen({ "a.ts": "old\n" }, "a.ts");
  disk.set("a.ts", "new\n");
  await ledger.touch("t1", "a.ts", [], "new\n");

  const [change] = await ledger.settle("t1");
  assert.equal(change?.before, "old\n");
  assert.equal(change?.after, "new\n");
});

test("an edit on a file changed behind the ledger's back compares with what was really there", async () => {
  const { disk, ledger } = await seen({ "a.ts": "const a = 1;\n" }, "a.ts");
  disk.set("a.ts", "const a = 5;\nconst b = 1;\n");
  await ledger.touch("t1", "a.ts", [{ oldText: "const b = 1;", newText: "const b = 2;" }]);
  disk.set("a.ts", "const a = 5;\nconst b = 2;\n");

  const [change] = await ledger.settle("t1");
  assert.equal(change?.before, "const a = 5;\nconst b = 1;\n");
  assert.equal(change?.added, 1);
  assert.equal(change?.removed, 1);
});

test("an edit that landed on a file changed behind the ledger's back is rebuilt from its own arguments", async () => {
  const { disk, ledger } = await seen({ "a.ts": "const a = 1;\n" }, "a.ts");
  // The reader changed `a` and the tool has already edited `b` by the time the ledger looks.
  disk.set("a.ts", "const a = 5;\nconst b = 2;\n");
  await ledger.touch("t1", "a.ts", [{ oldText: "const b = 1;", newText: "const b = 2;" }]);

  const [change] = await ledger.settle("t1");
  assert.equal(change?.before, "const a = 5;\nconst b = 1;\n");
});

test("applying edits the way the tool does", () => {
  assert.equal(applyAll("a b a", [{ oldText: "a", newText: "x" }]), "x b a");
  assert.equal(applyAll("a", [{ oldText: "missing", newText: "x" }]), null);
  assert.equal(
    applyAll("one two", [
      { oldText: "one", newText: "1" },
      { oldText: "two", newText: "2" },
    ]),
    "1 2",
  );
});
