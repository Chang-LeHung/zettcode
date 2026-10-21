import assert from "node:assert/strict";
import test from "node:test";

import {
  baseName,
  choose,
  isAbsolutePath,
  PASTE_LIMIT,
  pathsOnClipboard,
  plan,
  safeFileName,
  searchPattern,
} from "../src/core/pasted.js";
import { baseState, open } from "./harness.js";

test("a name is the last part of a path, with either kind of slash", () => {
  assert.equal(baseName("/work/src/app.ts"), "app.ts");
  assert.equal(baseName("C:\\work\\src\\app.ts"), "app.ts");
  assert.equal(baseName("/work/src/"), "src");
  assert.equal(baseName("app.ts"), "app.ts");
});

test("a path starts at a root, and a bare name or a relative path does not", () => {
  for (const path of ["/usr/a", "C:\\a", "c:/a", "\\\\server\\share\\a"]) {
    assert.equal(isAbsolutePath(path), true, path);
  }
  for (const path of ["a.ts", "src/a.ts", "./a.ts", "../a.ts"]) {
    assert.equal(isAbsolutePath(path), false, path);
  }
});

test("a clipboard that holds the path of a copied file already says what is wanted", () => {
  const found = pathsOnClipboard("/work/src/app.ts\nfile:///work/my%20docs/notes.md\nC:\\x\\other.txt\n", [
    "app.ts",
    "notes.md",
  ]);

  assert.deepEqual([...found], [
    ["app.ts", "/work/src/app.ts"],
    ["notes.md", "/work/my docs/notes.md"],
  ]);
});

test("a clipboard that holds only the name, or another file, is no answer", () => {
  assert.equal(pathsOnClipboard("app.ts", ["app.ts"]).size, 0, "a bare name is the problem, not the answer");
  assert.equal(pathsOnClipboard("/work/other.ts", ["app.ts"]).size, 0, "the path of a file that was not pasted");
  assert.equal(pathsOnClipboard("", ["app.ts"]).size, 0);
  assert.equal(pathsOnClipboard("file://%E0%A4%A", ["app.ts"]).size, 0, "an address that cannot be read is skipped");
});

test("windows paths of copied files are read as they come, and a drive in a file address loses its slash", () => {
  const found = pathsOnClipboard("C:\\work\\app.ts\r\nfile:///D:/work/notes.md", ["app.ts", "notes.md"]);

  assert.equal(found.get("app.ts"), "C:\\work\\app.ts");
  assert.equal(found.get("notes.md"), "D:/work/notes.md");
});

test("one file of the name is that file, none is none, and several are the reader's choice", () => {
  assert.deepEqual(choose([], []), { kind: "none" });
  assert.deepEqual(choose(["/w/a.ts"], []), { kind: "one", path: "/w/a.ts" });
  assert.deepEqual(choose(["/w/a.ts", "/w/a.ts"], []), { kind: "one", path: "/w/a.ts" }, "the same file twice is one");
  assert.deepEqual(choose(["/w/x/a.ts", "/w/y/a.ts"], []), { kind: "many", paths: ["/w/x/a.ts", "/w/y/a.ts"] });
});

test("of several files of that name, the one that is open is the likely one, if only one is", () => {
  assert.deepEqual(choose(["/w/x/a.ts", "/w/y/a.ts"], ["/w/y/a.ts", "/w/z/b.ts"]), { kind: "one", path: "/w/y/a.ts" });
  assert.equal(choose(["/w/x/a.ts", "/w/y/a.ts"], ["/w/x/a.ts", "/w/y/a.ts"]).kind, "many", "two open: ask");
});

test("a name is searched for by its letters, and a character the pattern would read is any one letter", () => {
  assert.equal(searchPattern("app.ts"), "**/app.ts");
  assert.equal(searchPattern("a[1]{x}*?.ts"), "**/a?1??x???.ts");
});

const none = { identical: [], byName: [], hasBytes: true, preferred: [] } as const;

test("a path the clipboard gave is used, before anything is looked for", () => {
  assert.deepEqual(plan({ ...none, known: "/work/a.ts", identical: ["/other/a.ts"] }), { kind: "path", path: "/work/a.ts" });
});

test("with its bytes, the file of the workspace that is the same is the one, whatever else shares its name", () => {
  const byName = ["/w/x/a.ts", "/w/y/a.ts", "/w/z/a.ts"];

  assert.deepEqual(plan({ ...none, byName, identical: ["/w/y/a.ts"] }), { kind: "path", path: "/w/y/a.ts" });
});

test("with its bytes, a file that matches none of the workspace came from elsewhere, so its bytes are kept", () => {
  assert.deepEqual(plan({ ...none, byName: ["/w/x/a.ts", "/w/y/a.ts"] }), { kind: "save" }, "same name, other bytes");
  assert.deepEqual(plan(none), { kind: "save" }, "no file of that name at all");
});

test("with its bytes, identical copies are told apart by the one that is open, and otherwise asked", () => {
  const identical = ["/w/x/a.ts", "/w/y/a.ts"];

  assert.deepEqual(plan({ ...none, identical, preferred: ["/w/y/a.ts"] }), { kind: "path", path: "/w/y/a.ts" });
  assert.deepEqual(plan({ ...none, identical }), { kind: "ask", paths: identical });
});

test("a file too large to send is looked for by its name alone, and a name no file has is not found", () => {
  const large = { ...none, hasBytes: false };

  assert.deepEqual(plan({ ...large, byName: ["/w/a.ts"] }), { kind: "path", path: "/w/a.ts" });
  assert.deepEqual(plan({ ...large, byName: ["/w/x/a.ts", "/w/y/a.ts"] }).kind, "ask");
  assert.deepEqual(plan(large), { kind: "missing" }, "nothing to go on, and nothing to keep");
});

test("a kept copy is named for what it is and can never leave its folder", () => {
  assert.equal(safeFileName("notes.md"), "notes.md");
  assert.equal(safeFileName("../../etc/passwd"), "passwd");
  assert.equal(safeFileName("a:b*c?.txt"), "a_b_c_.txt");
  assert.equal(safeFileName(".hidden"), "_hidden");
  assert.equal(safeFileName(""), "pasted-file");
  assert.equal(safeFileName("x".repeat(300)).length, 120);
});

/** A paste event carrying files, as the browser makes one: jsdom has no clipboard, so the data is given directly. */
function paste(window: Awaited<ReturnType<typeof open>>["window"], files: File[]): Event {
  const event = new window.Event("paste", { bubbles: true, cancelable: true });
  Object.defineProperty(event, "clipboardData", { value: { files } });
  window.document.dispatchEvent(event);
  return event;
}

test("a pasted file that is not a picture is not pasted as its name; the host is given its name and its bytes", async () => {
  const ui = await open([], baseState);
  const notes = new ui.window.File(["hello"], "notes.md", { type: "text/markdown" });
  const code = new ui.window.File(["x = 1"], "app.ts", { type: "" });

  const event = paste(ui.window, [notes, code]);
  await new Promise((resolve) => setTimeout(resolve, 30));

  assert.equal(event.defaultPrevented, true, "the browser does not put the bare name into the box");
  assert.deepEqual(ui.messages.at(-1), {
    type: "paste-files",
    files: [
      { name: "notes.md", size: 5, data: Buffer.from("hello").toString("base64") },
      { name: "app.ts", size: 5, data: Buffer.from("x = 1").toString("base64") },
    ],
  });
});

test("a pasted file over the limit goes by its name and size alone, so a large file is never read into the page", async () => {
  const ui = await open([], baseState);
  const large = new ui.window.File(["x"], "big.bin", { type: "application/octet-stream" });
  Object.defineProperty(large, "size", { value: PASTE_LIMIT + 1 });

  paste(ui.window, [large]);
  await new Promise((resolve) => setTimeout(resolve, 30));

  assert.deepEqual(ui.messages.at(-1), { type: "paste-files", files: [{ name: "big.bin", size: PASTE_LIMIT + 1 }] });
});

test("a pasted picture is attached as before, and only the files beside it are asked about", async () => {
  const ui = await open([], baseState);
  const picture = new ui.window.File(["\x89PNG"], "shot.png", { type: "image/png" });
  const notes = new ui.window.File(["x"], "notes.md", { type: "text/markdown" });

  const event = paste(ui.window, [picture, notes]);
  await new Promise((resolve) => setTimeout(resolve, 20));

  assert.equal(event.defaultPrevented, true);
  assert.equal(ui.all("#attachments .attachment").length, 1, "the picture is a chip, not a name in the box");
  assert.deepEqual(ui.messages.at(-1), {
    type: "paste-files",
    files: [{ name: "notes.md", size: 1, data: Buffer.from("x").toString("base64") }],
  });
});

test("text with no file in it is left to the box, and nothing is asked of the host", async () => {
  const ui = await open([], baseState);
  const before = ui.messages.length;

  const plain = paste(ui.window, []);

  assert.equal(plain.defaultPrevented, false, "ordinary text pastes as it always did");
  assert.equal(ui.messages.length, before, "and nothing is asked of the host");
});
