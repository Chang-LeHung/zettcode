// Builds the window's program, then the page it shows. The page is the gateway's own Vue application, built in its
// app mode, so a component changed for the browser is changed for the desktop in the same commit.

import { spawnSync } from "node:child_process";
import { mkdir, rm } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const here = dirname(fileURLToPath(import.meta.url));
const desktop = resolve(here, "..");
const gateway = resolve(desktop, "..", "gateway");

const page = spawnSync(process.execPath, ["scripts/build.mjs", "--app", "--out", resolve(desktop, "renderer")], {
  cwd: gateway,
  stdio: "inherit",
});
if (page.status !== 0) process.exit(page.status ?? 1);

await rm(resolve(desktop, "dist"), { recursive: true, force: true });
await mkdir(resolve(desktop, "dist"), { recursive: true });
await build({
  entryPoints: {
    main: resolve(desktop, "src/main.ts"),
    preload: resolve(desktop, "src/preload.ts"),
  },
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
