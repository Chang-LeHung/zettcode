import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { open } from "./harness.js";

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

test("/harness is offered after a slash, with the words it takes", async () => {
  const ui = await open();
  const input = ui.window.document.querySelector<HTMLTextAreaElement>("#input");
  assert.ok(input);
  input.value = "/harn";
  input.dispatchEvent(new ui.window.Event("input", { bubbles: true }));
  await new Promise((resolve) => setTimeout(resolve, 0));

  const items = [...ui.window.document.querySelectorAll("#menu .menu-item")].map((node) => node.textContent ?? "");
  assert.equal(items.length, 1);
  assert.ok(items[0]?.includes("/harness"), "the composer offers it");
});

test("/harness on and off ask the host to switch it", async () => {
  const ui = await open();

  await submit(ui, "/harness on");
  assert.deepEqual(ui.messages.at(-1), { type: "set-harness", on: true });
  await submit(ui, "/harness off");
  assert.deepEqual(ui.messages.at(-1), { type: "set-harness", on: false });
});

test("a harness word that is neither on nor off changes nothing and says how to write it", async () => {
  const ui = await open();

  await submit(ui, "/harness on");
  const before = ui.messages.length;
  await submit(ui, "/harness maybe");

  assert.equal(ui.messages.length, before, "nothing was posted");
  assert.ok(ui.window.document.querySelector(".toast")?.textContent?.includes("/harness on"));
});

test("the host turns the setting into the server's flag, and registers the palette command it declares", async () => {
  const server = await readFile("src/server.ts", "utf8");
  assert.ok(server.includes('"--harness"'), "the launched server is told to start with the harness on");
  assert.ok(server.includes('config.get<boolean>("harness", false)'), "and it is off unless the setting says so");

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
  assert.equal(manifest.contributes.configuration.properties["zettcode.harness"]?.default, false, "off by default");
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
