/** The extension host's half of a plugin command's answer: words first, then a document, and never a broken one. */

import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

/**
 * The host reads and does not change: `chat.ts` is not importable outside the editor (it imports `vscode`), so what
 * it does is pinned by reading it, the way `harness-command.test.ts` pins the server's flag. The source is what the
 * editor runs, and a behaviour that lives inside one method has no smaller seam to test.
 */
async function chatSource(): Promise<string> {
  return readFile("src/chat.ts", "utf8");
}

/** The body of one method, from its signature to the brace that closes it. */
function methodBody(source: string, signature: string): string {
  const start = source.indexOf(signature);
  assert.notEqual(start, -1, `${signature} is there`);
  const open = source.indexOf("{", start);
  const end = source.indexOf("\n  }", open);
  assert.notEqual(end, -1, `${signature} has a body`);
  return source.slice(open, end);
}

test("a document opens after the words, and a field the server does not send is not a document", async () => {
  const body = methodBody(await chatSource(), "private async runCommand(");

  // A server that predates `markdown` sends no field at all, and `undefined !== ""` would open an empty page.
  assert.ok(body.includes("if (answer.markdown)"), "the test is truthiness, not a comparison with an empty string");
  assert.ok(!body.includes('answer.markdown !== ""'), "a field the server does not send is not a document");

  const words = body.indexOf("await this.announce(answer.message)");
  const document = body.indexOf("await this.showDocument(answer.markdown");
  assert.notEqual(words, -1, "the answer's words are announced");
  assert.notEqual(document, -1, "the answer's document is opened");
  assert.ok(words < document, "the words come first, as the terminal draws a message before the page over it");
});

test("a document the editor cannot open is told, and does not hide the words", async () => {
  const source = await chatSource();
  const body = methodBody(source, "private async runCommand(");
  const call = body.indexOf("await this.showDocument(answer.markdown");
  const guarded = body.slice(Math.max(0, call - 120), call);

  assert.ok(guarded.includes("try {"), "opening the document is guarded");
  assert.ok(body.slice(call).includes('this.say("warn"'), "and a failure is said, not thrown");

  const document = methodBody(source, "private async showDocument(");
  assert.ok(document.includes('executeCommand("markdown.showPreview"'), "the editor renders the document itself");
  assert.ok(document.includes("openTextDocument"), "as an untitled document, so nothing is written to disk");
});
