import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

/**
 * The manifest and the code that fills it, held against each other.
 *
 * Nothing here is about how a command behaves: it is about the two lists VS Code reads (what the palette offers, and
 * what activates the extension) agreeing with what the extension actually registers. A command in one list and not
 * the other is either a row that does nothing when chosen, or a handler nobody can reach.
 */

interface Manifest {
  main: string;
  engines: { vscode: string };
  activationEvents?: string[];
  contributes: {
    commands: { command: string; title: string }[];
    viewsContainers: Record<string, { id: string }[]>;
    views: Record<string, { id: string; type?: string }[]>;
    configuration: { properties: Record<string, unknown> };
  };
}

const readManifest = async (): Promise<Manifest> =>
  JSON.parse(await readFile("package.json", "utf8")) as Manifest;

/** Every `command("zettcode.…")` the entry point registers, in the order it does. */
async function registered(): Promise<string[]> {
  const source = await readFile("src/extension.ts", "utf8");
  return [...source.matchAll(/\bcommand\("(zettcode\.[\w.]+)"/g)].flatMap((match) => match[1] ?? []);
}

/** Every `executeCommand("zettcode.…")` anywhere in the source: the calls that would quietly do nothing if misspelt. */
async function executed(): Promise<{ file: string; name: string }[]> {
  const files = ["src/chat.ts", "src/extension.ts", "src/server.ts", "src/usage.ts", "src/provision.ts"];
  const found: { file: string; name: string }[] = [];
  for (const file of files) {
    const source = await readFile(file, "utf8");
    for (const match of source.matchAll(/executeCommand\("(zettcode\.[\w.]+)"/g)) {
      found.push({ file, name: match[1] ?? "" });
    }
  }
  return found;
}

test("every command the extension registers is in the palette, and every palette row has a handler", async () => {
  const declared = (await readManifest()).contributes.commands.map((entry) => entry.command).sort();
  const handled = (await registered()).sort();

  const unreachable = handled.filter((name) => !declared.includes(name));
  assert.deepEqual(unreachable, [], `registered but not contributed (nobody can pick them): ${unreachable.join(", ")}`);
  const dead = declared.filter((name) => !handled.includes(name));
  assert.deepEqual(dead, [], `contributed but never registered (choosing them does nothing): ${dead.join(", ")}`);
  assert.equal(new Set(declared).size, declared.length, "two rows share a command name");
});

test("a command is executed by the name the palette declares, or by the one VS Code makes for a view", async () => {
  const declaredManifest = await readManifest();
  const declared = new Set(declaredManifest.contributes.commands.map((entry) => entry.command));
  // Contributors get `<view id>.focus` without declaring it, and the chat view's is how the palette focuses it.
  const views = new Set(Object.values(declaredManifest.contributes.views).flat().map((view) => `${view.id}.focus`));

  const unknown = (await executed()).filter((call) => !declared.has(call.name) && !views.has(call.name));
  const where = unknown.map((call) => `${call.file}: ${call.name}`);
  assert.deepEqual(where, [], `executed but neither contributed nor generated: ${where.join("; ")}`);
});

test("the chat view the extension registers is the one the manifest declares, inside a container that exists", async () => {
  const declaredManifest = await readManifest();
  const source = await readFile("src/extension.ts", "utf8");
  const registered = /registerWebviewViewProvider\("([^"]+)"/.exec(source)?.[1];
  assert.equal(registered, "zettcode.chat");

  const views = Object.entries(declaredManifest.contributes.views);
  const chat = views.flatMap(([, items]) => items).find((view) => view.id === registered);
  assert.ok(chat !== undefined, `${registered} is not declared under contributes.views`);
  assert.equal(chat.type, "webview", "a view we register a webview provider for has to be one");

  const containers = new Set(Object.values(declaredManifest.contributes.viewsContainers).flat().map((entry) => entry.id));
  const owner = views.find(([, items]) => items.some((view) => view.id === registered))?.[0] ?? "";
  assert.ok(containers.has(owner), `the view hangs under ${owner}, which is not a declared container`);
});

test("no activation event re-declares what a command or a view already activates", async () => {
  // Since VS Code 1.74 a contributed command activates the extension by itself, and so does `onView` for a declared
  // view. A hand-written list of them was here and had gone stale — twelve commands were missing from it — so what is
  // left is only what the contributions cannot say: startup, a file in the workspace, a language.
  const declaredManifest = await readManifest();
  const [major = 0, minor = 0] = (/(\d+)\.(\d+)/.exec(declaredManifest.engines.vscode) ?? []).slice(1).map(Number);
  assert.ok(major > 1 || minor >= 74, `VS Code ${declaredManifest.engines.vscode} is old enough to need activation events`);

  const redundant = (declaredManifest.activationEvents ?? []).filter(
    (event) => event.startsWith("onCommand:") || event.startsWith("onView:"),
  );
  assert.deepEqual(redundant, [], `derived from the contributions, so do not list them: ${redundant.join(", ")}`);
});

test("every row in the palette says whose it is", async () => {
  const entries = (await readManifest()).contributes.commands;
  const nameless = entries.filter((entry) => !entry.title.startsWith("ZettCode: ")).map((entry) => entry.command);
  assert.deepEqual(nameless, [], `a palette mixes extensions, so a row has to name its own: ${nameless.join(", ")}`);
});
