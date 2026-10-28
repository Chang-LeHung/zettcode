// Builds the page into the Python package, where the gateway serves it from: app.js (plus lazy chunks), app.css,
// the KaTeX fonts, index.html and the icon.
import { copyFile, mkdir, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { context } from "esbuild";
import { VUE_DEFINES, vuePlugin } from "./vue-plugin.mjs";

const watch = process.argv.includes("--watch");
const out = "../../zettcode/src/zettcode/gateway/static";
await rm(out, { recursive: true, force: true });
await mkdir(out, { recursive: true });

const build = await context({
  entryPoints: { app: "src/main.ts" },
  bundle: true,
  splitting: true,
  platform: "browser",
  format: "esm",
  target: ["es2022", "safari15"],
  outdir: out,
  chunkNames: "chunks/[name]-[hash]",
  assetNames: "assets/[name]-[hash]",
  minify: !watch,
  legalComments: "none",
  define: VUE_DEFINES,
  loader: { ".woff2": "file", ".woff": "file", ".ttf": "file" },
  plugins: [vuePlugin({ cssFile: `${out}/app.vue.css` })],
  logLevel: "info",
});

async function finish() {
  // Vue's component styles are written beside esbuild's own CSS; the page loads one file.
  let css = await readFile(`${out}/app.css`, "utf8").catch(() => "");
  css += `\n${await readFile(`${out}/app.vue.css`, "utf8").catch(() => "")}`;
  // Every browser the page targets reads woff2, so the older font formats are not shipped.
  css = css.replace(/,\s*url\("?[^)"]*\.(?:woff|ttf)"?\)\s*format\("?[^)"]*"?\)/g, "");
  await writeFile(`${out}/app.css`, css);
  await rm(`${out}/app.vue.css`, { force: true });
  for (const name of await readdir(`${out}/assets`).catch(() => [])) {
    if (/\.(woff|ttf)$/.test(name)) await rm(`${out}/assets/${name}`);
  }
  await copyFile("index.html", `${out}/index.html`);
  await copyFile("public/logo.svg", `${out}/logo.svg`);
  await copyFile("public/icon.png", `${out}/icon.png`);
  await copyFile("public/manifest.webmanifest", `${out}/manifest.webmanifest`);
}

await build.rebuild();
await finish();
if (watch) await build.watch();
else await build.dispose();
