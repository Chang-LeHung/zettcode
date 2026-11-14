// Builds the window's program. The page the window shows is the gateway's own, loaded from the gateway at run time,
// so nothing about it is built here: a change to the page ships with the gateway, not with an installer.

import { mkdir, rm } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const desktop = resolve(dirname(fileURLToPath(import.meta.url)), "..");

await rm(resolve(desktop, "dist"), { recursive: true, force: true });
await mkdir(resolve(desktop, "dist"), { recursive: true });
await build({
  entryPoints: { main: resolve(desktop, "src/main.ts") },
  outdir: resolve(desktop, "dist"),
  outExtension: { ".js": ".cjs" },
  bundle: true,
  platform: "node",
  format: "cjs",
  target: "node20",
  sourcemap: true,
  external: ["electron"],
  logLevel: "info",
});
