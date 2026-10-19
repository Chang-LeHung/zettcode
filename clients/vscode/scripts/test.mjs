import { mkdir, mkdtemp, readdir, rm, symlink, unlink } from "node:fs/promises";
import { spawn } from "node:child_process";
import * as os from "node:os";
import * as path from "node:path";
import { build } from "esbuild";
import { VUE_DEFINES, vuePlugin } from "./vue-plugin.mjs";

// Tests run from a temporary directory: the suite must not write into the checkout.
const out = await mkdtemp(path.join(os.tmpdir(), "zettcode-vscode-"));
await mkdir(out, { recursive: true });
// The bundles live outside the checkout, so bare packages need a way back to the installed ones.
await symlink(path.resolve("node_modules"), path.join(out, "node_modules"), process.platform === "win32" ? "junction" : "dir");

const entries = (await readdir("test"))
  .filter((name) => name.endsWith(".test.ts"))
  .map((name) => `test/${name}`);

if (entries.length === 0) {
  console.error("No test files found in test/");
  process.exit(1);
}

for (const entry of entries) {
  const name = entry.replace(/^test\//, "").replace(/\.ts$/, ".mjs");
  await build({
    entryPoints: [entry],
    bundle: true,
    platform: "node",
    format: "esm",
    target: "node20",
    outfile: path.join(out, name),
    external: ["jsdom"],
    alias: { vscode: path.resolve("test/vscode-stub.ts") },
    logLevel: "warning",
  });
}

await build({
  entryPoints: ["src/webview/main.ts"],
  bundle: true,
  platform: "browser",
  format: "iife",
  target: "es2022",
  outfile: path.join(out, "webview.js"),
  define: VUE_DEFINES,
  loader: { ".svg": "dataurl" },
  plugins: [vuePlugin()],
  logLevel: "warning",
});

const outputs = entries.map((entry) =>
  path.join(out, entry.replace(/^test\//, "").replace(/\.ts$/, ".mjs")),
);
const child = spawn(process.execPath, ["--test", ...outputs], {
  stdio: "inherit",
  env: { ...process.env, ZETTCODE_WEBVIEW_BUNDLE: path.join(out, "webview.js") },
});
child.on("exit", async (code) => {
  await unlink(path.join(out, "node_modules")).catch(() => undefined);
  await rm(out, { recursive: true, force: true });
  process.exit(code ?? 1);
});
