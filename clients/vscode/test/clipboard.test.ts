import assert from "node:assert/strict";
import test from "node:test";

import { commandsFor, copiedFilePaths, type Runner } from "../src/clipboard.js";
import { absolutePaths } from "../src/core/pasted.js";

/** A system that answers each command with what a test says it prints. */
function system(answers: Record<string, string>): { run: Runner; asked: string[] } {
  const asked: string[] = [];
  const run: Runner = async (command, args) => {
    asked.push([command, ...args].join(" "));
    return answers[command] ?? "";
  };
  return { run, asked };
}

test("a list of files is its absolute paths, from plain paths and file addresses alike, and nothing else", () => {
  assert.deepEqual(absolutePaths("/Users/me/Desktop/a b.pdf\nC:\\Users\\me\\c.txt\n"), [
    "/Users/me/Desktop/a b.pdf",
    "C:\\Users\\me\\c.txt",
  ]);
  assert.deepEqual(absolutePaths("copy\nfile:///home/me/My%20Books/x.pdf\nfile:///home/me/y.md\n"), [
    "/home/me/My Books/x.pdf",
    "/home/me/y.md",
  ]);
  assert.deepEqual(absolutePaths("just a name.pdf\nrelative/path.txt\n\n"), []);
});

test("every system the editor runs on has a way to ask for the files on the clipboard", () => {
  for (const platform of ["darwin", "win32", "linux"]) {
    assert.ok(commandsFor(platform).length > 0, platform);
  }
  assert.deepEqual(commandsFor("freebsd"), [], "a system nobody wrote for has none, and so no files");
});

test("the mac asks the pasteboard for file URLs, as objects, so several files come back and a path keeps its spaces", () => {
  const [[command, args]] = commandsFor("darwin") as [[string, string[]]];

  assert.equal(command, "osascript");
  assert.deepEqual(args.slice(0, 2), ["-l", "JavaScript"]);
  const script = args.at(-1) ?? "";
  assert.ok(script.includes("NSPasteboard.generalPasteboard"));
  assert.ok(script.includes("NSPasteboardURLReadingFileURLsOnlyKey"), "files only, never a web address");
});

test("the paths a system prints for the copied files are the answer, large file or not", async () => {
  const { run } = system({ osascript: "/Users/me/Desktop/Patterns of Distributed Systems (Fowler).pdf\n" });

  assert.deepEqual(await copiedFilePaths("darwin", run), ["/Users/me/Desktop/Patterns of Distributed Systems (Fowler).pdf"]);
});

test("several copied files come back in the order the system gave them", async () => {
  const { run } = system({ powershell: "C:\\a\\one.txt\r\nC:\\a\\two.txt\r\n" });

  assert.deepEqual(await copiedFilePaths("win32", run), ["C:\\a\\one.txt", "C:\\a\\two.txt"]);
});

test("on linux the next way is tried when one has nothing, and the first that has files is the answer", async () => {
  const { run, asked } = system({ xclip: "copy\nfile:///home/me/a.pdf\n" });

  assert.deepEqual(await copiedFilePaths("linux", run), ["/home/me/a.pdf"]);
  assert.ok(asked[0]?.startsWith("wl-paste"), "the Wayland tool is asked first");
  assert.ok(asked[1]?.startsWith("xclip"), "then the X11 one");
  assert.equal(asked.length, 2, "and no further once there is an answer");
});

test("a clipboard with no files, a missing tool, or a failure is no files, never an error", async () => {
  assert.deepEqual(await copiedFilePaths("darwin", system({}).run), []);
  assert.deepEqual(await copiedFilePaths("linux", system({}).run), []);
  assert.deepEqual(await copiedFilePaths("freebsd", system({}).run), []);
  assert.deepEqual(await copiedFilePaths("darwin", system({ osascript: "some text that is not a path\n" }).run), []);
});

test("asking a real mac for its clipboard's files runs, and answers with paths or with none", { skip: process.platform !== "darwin" }, async () => {
  const started = Date.now();

  const paths = await copiedFilePaths();

  assert.ok(Array.isArray(paths));
  assert.ok(paths.every((path) => path.startsWith("/")));
  assert.ok(Date.now() - started < 3500, "answered, not timed out");
});
