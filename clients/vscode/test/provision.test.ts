import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { environmentDirectory, executable, installPlan, PACKAGE, serverHome } from "../src/core/provision.js";

test("the server lives in an environment of the extension's own, beside the agent it drives", () => {
  const home = serverHome("/storage");
  const directory = environmentDirectory(home);
  assert.equal(home, "/storage/server");
  assert.equal(directory, "/storage/server/venv");
  assert.equal(executable(directory, "darwin"), "/storage/server/venv/bin/zettcode-server");
  assert.equal(executable(directory, "win32"), "\\storage\\server\\venv\\Scripts\\zettcode-server.exe");
});

test("the server and the agent are one package, so the install names zettcode", () => {
  assert.match(PACKAGE, /^zettcode>=/);
  assert.ok(!PACKAGE.includes("zettcode-server"), "a separate server package would be a second version to keep in step");
});

test("uv makes the environment and installs into it, and is used before python", () => {
  const directory = "/storage/server/venv";
  const plan = installPlan({
    directory,
    platform: "linux",
    tools: { uv: "/usr/local/bin/uv", python: "/usr/bin/python3" },
  });
  assert.deepEqual(
    plan?.map((step) => [step.command, step.args]),
    [
      ["/usr/local/bin/uv", ["venv", directory]],
      ["/usr/local/bin/uv", ["pip", "install", "--python", `${directory}/bin/python`, PACKAGE]],
    ],
  );
  assert.ok(plan?.every((step) => step.note.length > 0), "each step says what it is doing");
});

test("without uv, python's own venv and pip do the same, and on Windows through Scripts", () => {
  const directory = "C:\\storage\\server\\venv";
  const plan = installPlan({ directory, platform: "win32", tools: { uv: null, python: "C:\\Python312\\python.exe" } });
  assert.deepEqual(
    plan?.map((step) => [step.command, step.args]),
    [
      ["C:\\Python312\\python.exe", ["-m", "venv", directory]],
      [`${directory}\\Scripts\\python.exe`, ["-m", "pip", "install", "--upgrade", PACKAGE]],
    ],
  );
});

test("a machine with neither uv nor python has no plan, and the reader is told to install it", () => {
  assert.equal(installPlan({ directory: "/x", tools: { uv: null, python: null } }), null);
});

test("the extension installs only when the command is nowhere, and only if the reader allows it", async () => {
  const server = await readFile("src/server.ts", "utf8");
  assert.ok(server.includes("if (!isAvailable(configured))"), "an existing command is never replaced");
  assert.ok(server.includes("this.provision === null ? null : await this.provision()"), "installed once, on demand");
  const extension = await readFile("src/extension.ts", "utf8");
  assert.ok(extension.includes('get<boolean>("server.autoInstall", true)'), "the setting gates it");
  const manifest = JSON.parse(await readFile("package.json", "utf8")) as {
    contributes: { configuration: { properties: Record<string, { default?: unknown }> } };
  };
  assert.equal(manifest.contributes.configuration.properties["zettcode.server.autoInstall"]?.default, true);
});
