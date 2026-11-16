/** The extension host's half of the command parity work: what the webview asks for and what reaches the server. */

import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

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

test("a preset whose command asks to queue is held for the run to end, not steered into it", async () => {
  const source = await chatSource();
  const run = methodBody(source, "private async runCommand(");
  assert.ok(run.includes('command.when_busy === "queue"'), "the command's own when_busy decides");
  assert.ok(run.includes("refreshAfterCommand"), "settings a command moved are read back before the turn");

  const refresh = methodBody(source, "private async refreshAfterCommand(");
  assert.ok(refresh.includes("client.settings") && refresh.includes("announceChanges"), "and the change is announced");

  const start = methodBody(source, "private async startCommandTurn(");
  assert.ok(start.includes("queueWhenBusy"), "the preset is told whether it may wait");
  assert.ok(start.includes('type: "queue-turn"'), "waiting is the webview's queue, not a new run");
  assert.ok(start.includes("cache === undefined ? {} : { cache }"), "the cache mode travels with the preset");

  const prompt = methodBody(source, "private async sendPrompt(");
  assert.ok(prompt.includes("request.shown"), "the line the conversation keeps is the command as typed");
  assert.ok(prompt.includes("instructions: text"), "what the model reads is the preset, not the shown line");
});

test("the queued turn keeps its line and cache when it is finally sent", async () => {
  const source = await chatSource();
  const dispatch = source.slice(source.indexOf('case "prompt":'), source.indexOf('case "run-command":'));
  assert.ok(dispatch.includes("message.shown"), "the shown line crosses the boundary");
  assert.ok(dispatch.includes("message.cache"), "and so does the cache mode");
});

test("/resume with an id is guarded, and /export takes a path", async () => {
  const source = await chatSource();
  const open = source.slice(source.indexOf('case "open-session":'), source.indexOf('case "refresh-sessions":'));
  assert.ok(open.includes("try {") && open.includes("catch"), "an id the server does not know is said, not thrown");

  const exportBody = methodBody(source, "async exportSession(");
  assert.ok(source.includes("async exportSession(file?: string)"), "the command's argument reaches the host");
  assert.ok(exportBody.includes("this.busy"), "the terminal refuses an export while a request is going");
  assert.ok(exportBody.includes("try the export when it ends"), "and says when to try again");
  assert.ok(exportBody.includes("isRooted(wanted)"), "a rooted path is taken as it is");
  assert.ok(exportBody.includes("os.homedir()"), "and a home-relative one is expanded, as the terminal does");
  assert.ok(exportBody.includes("vscode.Uri.joinPath(folder, wanted)"), "a relative one is resolved in the workspace");
  assert.ok(exportBody.includes("createDirectory"), "a parent folder that is not there is made first");
  assert.ok(exportBody.includes("writeFile(target"), "the HTML is written where the reader asked");
});

test("a queued turn or side question that loses the race goes back to the queue", async () => {
  const source = await chatSource();
  const prompt = methodBody(source, "private async sendPrompt(");
  assert.ok(prompt.includes('type: "queue-turn"'), "a preset refused by a run that just began is put back");
  assert.ok(prompt.includes("this.postState()"), "and the page is told the run is still going, so it drains later");
  const notReady = prompt.slice(prompt.indexOf("if (!this.readyForPrompt())"), prompt.indexOf("const images"));
  assert.ok(notReady.includes('type: "queue-turn"'), "a preset that finds no model waits instead of being lost");
  assert.ok(notReady.includes('type: "queue-message"'), "and so does a typed follow-up");
  assert.ok(prompt.includes("session === undefined"), "the conversation travels with the re-queue");
  assert.ok(prompt.includes("request.session !== undefined"), "a prompt from another conversation is not run here");
  assert.ok(prompt.includes("session: request.session"), "it is put back in the one it came from");

  const ask = methodBody(source, "private async askAside(");
  assert.ok(ask.includes('type: "queue-ask"'), "and so is a side question");
  assert.ok(ask.includes("this.postState()"), "with the same correction to the page's idea of busy");
  assert.ok(ask.includes("session === undefined"), "the conversation travels with the question too");
  assert.ok(ask.includes("session: fromSession"), "and a question from another conversation is put back there");
  const askNotReady = ask.slice(ask.indexOf("health?.ready"));
  assert.ok(askNotReady.includes('type: "queue-ask"'), "a side question that finds no model waits too");

  const store = await readFile("src/webview/store.ts", "utf8");
  assert.ok(store.includes('case "queue-ask"'), "the page reads the re-queued question");
  assert.ok(store.includes('case "queue-message"'), "and the re-queued typed follow-up");
  assert.ok(store.includes("queued.id > id"), "a re-queued item goes back where it was");
  assert.ok(store.includes("item.sessionId === session"), "draining stays in one conversation");
  assert.ok(store.includes("state.ui.ready !== true"), "no model means no drain, not a retry loop");
  assert.ok(store.includes("session: item.sessionId"), "the item's conversation crosses with the prompt");
});

test("/plugins enable|disable reaches the switch endpoint, and /help opens a document", async () => {
  const source = await chatSource();
  assert.ok(source.includes('case "set-plugin":'), "the webview's switch message is dispatched");
  assert.ok(source.includes('case "show-document":'), "and so is a document a command built");

  const body = methodBody(source, "private async setPlugin(");
  assert.ok(body.includes("setPluginEnabled(name, enabled)"), "the server owns the switch");
  assert.ok(body.includes("next server start"), "the answer says when it takes effect");
});
