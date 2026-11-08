// Builds the page. `--app` writes a bundle a shell can serve from its own origin: index.html at the root and
// everything it asks for under /static, which is the layout the gateway already serves. Without it the page is
// written into the Python package, where the gateway serves it from /static.
import { copyFile, mkdir, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { context } from "esbuild";
import { VUE_DEFINES, vuePlugin } from "./vue-plugin.mjs";

const argv = process.argv.slice(2);
const watch = argv.includes("--watch");
const app = argv.includes("--app");
const asked = argv.indexOf("--out");
const where = asked >= 0 ? argv[asked + 1] : app ? "dist/app" : "../../packages/zettcode-gateway/src/zettcode/gateway/static";
if (!where) {
  console.error("--out needs a directory");
  process.exit(1);
}
const out = resolve(where);
const assets = app ? `${out}/static` : out;
await rm(out, { recursive: true, force: true });
await mkdir(assets, { recursive: true });

const build = await context({
  entryPoints: { app: "src/main.ts" },
  bundle: true,
  splitting: true,
  platform: "browser",
  format: "esm",
  target: ["es2022", "safari15"],
  outdir: assets,
  chunkNames: "chunks/[name]-[hash]",
  assetNames: "assets/[name]-[hash]",
  minify: !watch,
  legalComments: "none",
  define: VUE_DEFINES,
  loader: { ".woff2": "file", ".woff": "file", ".ttf": "file" },
  plugins: [vuePlugin({ cssFile: `${assets}/app.vue.css` })],
  logLevel: "info",
});

async function finish() {
  // Vue's component styles are written beside esbuild's own CSS; the page loads one file.
  let css = await readFile(`${assets}/app.css`, "utf8").catch(() => "");
  css += `\n${await readFile(`${assets}/app.vue.css`, "utf8").catch(() => "")}`;
  // Every browser the page targets reads woff2, so the older font formats are not shipped.
  css = css.replace(/,\s*url\("?[^)"]*\.(?:woff|ttf)"?\)\s*format\("?[^)"]*"?\)/g, "");
  await writeFile(`${assets}/app.css`, css);
  await rm(`${assets}/app.vue.css`, { force: true });
  for (const name of await readdir(`${assets}/assets`).catch(() => [])) {
    if (/\.(woff|ttf)$/.test(name)) await rm(`${assets}/assets/${name}`);
  }
  await copyFile("index.html", `${out}/index.html`);
  await copyFile("public/logo.svg", `${assets}/logo.svg`);
  await copyFile("public/icon.png", `${assets}/icon.png`);
  await copyFile("public/manifest.webmanifest", `${assets}/manifest.webmanifest`);
  if (app) await copyFile("public/manifest.webmanifest", `${out}/manifest.webmanifest`);
}

await build.rebuild();
await finish();
if (watch) await build.watch();
else await build.dispose();
