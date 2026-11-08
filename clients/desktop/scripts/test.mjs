// Runs the shell's tests without Electron: the store is plain Node, and that is where the rules worth pinning live.

import { spawn } from "node:child_process";
import { mkdtemp, readdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const out = await mkdtemp(join(tmpdir(), "zettcode-desktop-"));
const files = (await readdir(join(root, "test"))).filter((name) => name.endsWith(".test.ts"));
if (files.length === 0) {
  console.error("No test files found in test/");
  process.exit(1);
}
const built = [];
for (const name of files) {
  const outfile = join(out, name.replace(/\.ts$/, ".mjs"));
  await build({
    entryPoints: [join(root, "test", name)],
    bundle: true,
    platform: "node",
    format: "esm",
    target: "node20",
    outfile,
    logLevel: "warning",
  });
  built.push(outfile);
}
const child = spawn(process.execPath, ["--test", ...built], { stdio: "inherit" });
child.on("exit", (code) => process.exit(code ?? 1));
