// Runs the tests of the page's pure code: bundles each test file with esbuild and runs it with node's test runner.
import { spawn } from "node:child_process";
import { mkdtemp, readdir } from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { build } from "esbuild";
import { symlink } from "node:fs/promises";

const out = await mkdtemp(path.join(os.tmpdir(), "zettcode-gateway-ui-"));
// The bundles live outside the checkout, so bare packages need a way back to the installed ones.
await symlink(path.resolve("node_modules"), path.join(out, "node_modules"), "dir");
const files = (await readdir("test")).filter((name) => name.endsWith(".test.ts"));
if (files.length === 0) {
  console.error("No test files found in test/");
  process.exit(1);
}
const built = [];
for (const name of files) {
  const outfile = path.join(out, name.replace(/\.ts$/, ".mjs"));
  await build({ entryPoints: [`test/${name}`], bundle: true, platform: "node", format: "esm", target: "node20", outfile, external: ["jsdom"], logLevel: "warning" });
  built.push(outfile);
}
const child = spawn(process.execPath, ["--test", ...built], { stdio: "inherit" });
child.on("exit", (code) => process.exit(code ?? 1));
