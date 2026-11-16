import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { baseState, open } from "./harness.js";

/** The server's plain `/harness`, as `GET /commands` lists it: the words the editor offers and the host runs. */
const harnessState = {
  ...baseState,
  commands: [
    {
      name: "/harness",
      summary: "the just-in-time harness",
      when_busy: "refuse",
      subcommands: ["gen", "reset"],
      needs_more: ["gen", "reset"],
    },
  ],
};

/** Type a line into the real composer and press Enter, the way a person would. */
async function submit(ui: Awaited<ReturnType<typeof open>>, text: string): Promise<void> {
  const input = ui.window.document.querySelector<HTMLTextAreaElement>("#input");
  assert.ok(input, "the composer is there");
  input.value = text;
  input.dispatchEvent(new ui.window.Event("input", { bubbles: true }));
  await new Promise((resolve) => setTimeout(resolve, 0));
  input.dispatchEvent(new ui.window.KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
  await new Promise((resolve) => setTimeout(resolve, 0));
}

test("/harness is offered after a slash, with the words the server declares", async () => {
  const ui = await open([], harnessState);
  const input = ui.window.document.querySelector<HTMLTextAreaElement>("#input");
  assert.ok(input);
  input.value = "/harn";
  input.dispatchEvent(new ui.window.Event("input", { bubbles: true }));
  await new Promise((resolve) => setTimeout(resolve, 0));

  const items = [...ui.window.document.querySelectorAll("#menu .menu-item")].map((node) => node.textContent ?? "");
  assert.equal(items.length, 1);
  assert.ok(items[0]?.includes("/harness"), "the composer offers it");

  input.value = "/harness ";
  input.dispatchEvent(new ui.window.Event("input", { bubbles: true }));
  await new Promise((resolve) => setTimeout(resolve, 0));
  const words = [...ui.window.document.querySelectorAll("#menu .menu-label")].map((node) => node.textContent ?? "");
  assert.deepEqual(words, ["/harness gen", "/harness reset"]);
});

test("a harness word that needs more is filled in, and a second Enter runs it", async () => {
  const ui = await open([], harnessState);
  const input = ui.window.document.querySelector<HTMLTextAreaElement>("#input");
  assert.ok(input);
  input.value = "/harness ";
  input.dispatchEvent(new ui.window.Event("input", { bubbles: true }));
  await new Promise((resolve) => setTimeout(resolve, 0));

  input.dispatchEvent(new ui.window.KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(input.value, "/harness gen ", "the word is filled in, not run");
  assert.equal(ui.messages.some((message) => message.type === "run-command"), false);

  input.dispatchEvent(new ui.window.KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(ui.messages.at(-1), { type: "run-command", name: "/harness", argument: "gen" });
});

test("bare /harness runs the command with no word, and the server reports the switch", async () => {
  const ui = await open([], harnessState);

  await submit(ui, "/harness");

  assert.deepEqual(ui.messages.at(-1), { type: "run-command", name: "/harness", argument: "" });
});

test("/harness gen and reset are the server's command, with the words after it", async () => {
  const ui = await open([], harnessState);

  await submit(ui, "/harness gen a tool for TODOs");
  assert.deepEqual(ui.messages.at(-1), { type: "run-command", name: "/harness", argument: "gen a tool for TODOs" });

  await submit(ui, "/harness reset");
  const input = ui.window.document.querySelector<HTMLTextAreaElement>("#input");
  assert.ok(input);
  input.dispatchEvent(new ui.window.KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(ui.messages.at(-1), { type: "run-command", name: "/harness", argument: "reset" });
});

test("the host turns the setting into the server's flag, and registers the palette command it declares", async () => {
  const server = await readFile("src/server.ts", "utf8");
  assert.ok(server.includes('"--harness"'), "the launched server can be told to start with the harness on");
  assert.ok(server.includes('"--no-harness"'), "and to start with it off");
  assert.ok(
    server.includes('config.get<boolean | undefined>("harness")'),
    "a setting the reader did not touch leaves the choice to the configuration",
  );

  const manifest = JSON.parse(await readFile("package.json", "utf8")) as {
    contributes: {
      commands: { command: string }[];
      configuration: { properties: Record<string, { default?: unknown; enum?: string[] }> };
    };
  };
  const declared = manifest.contributes.commands.map((item) => item.command);
  assert.ok(declared.includes("zettcode.toggleHarness"));
  const extension = await readFile("src/extension.ts", "utf8");
  assert.ok(extension.includes('command("zettcode.toggleHarness"'), "a command that is declared is registered");
  assert.equal(
    manifest.contributes.configuration.properties["zettcode.harness"]?.default,
    undefined,
    "no default of its own: the configuration decides until the reader sets one",
  );
});

test("the permission setting names full and still accepts auto, which the extension reads as full", async () => {
  const manifest = JSON.parse(await readFile("package.json", "utf8")) as {
    contributes: { configuration: { properties: Record<string, { default?: unknown; enum?: string[] }> } };
  };
  const permission = manifest.contributes.configuration.properties["zettcode.permission"];
  assert.deepEqual(permission?.enum, ["deny", "ask", "safe", "full", "auto"]);
  assert.equal(permission?.default, "ask");

  const server = await readFile("src/server.ts", "utf8");
  assert.ok(server.includes('permission === "auto" ? "full"'), "a setting written under the old name starts the server at full");
  const chat = await readFile("src/chat.ts", "utf8");
  assert.ok(chat.includes('value === "auto" ? "full" : value'));
});

test("a change of harness is announced in the conversation like a change of permission", async () => {
  const chat = await readFile("src/chat.ts", "utf8");
  const announce = chat.slice(chat.indexOf("private announceChanges"), chat.indexOf("private async addModel"));
  assert.ok(announce.includes("before.harness !== after.harness"));
  assert.ok(announce.includes("Tool harness turned"));
  assert.ok(chat.includes('case "set-harness"'), "the webview's message reaches the settings");
});

test("no tool the model no longer has is still named by the extension", async () => {
  for (const file of ["src/core/format.ts", "src/core/ledger.ts", "src/webview/components/ToolStep.vue"]) {
    const text = await readFile(file, "utf8");
    assert.ok(!/view_image|read_image|delete_file/.test(text), `${file} still names a tool that is gone`);
  }
});
