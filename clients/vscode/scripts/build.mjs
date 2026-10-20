import { mkdir, rm } from "node:fs/promises";
import { context } from "esbuild";
import { VUE_DEFINES, vuePlugin } from "./vue-plugin.mjs";

const watch = process.argv.includes("--watch");
await rm("dist", { recursive: true, force: true });
await mkdir("dist", { recursive: true });

const options = [
  {
    entryPoints: ["src/extension.ts"],
    bundle: true,
    platform: "node",
    format: "cjs",
    target: "node20",
    external: ["vscode"],
    outfile: "dist/extension.js",
    sourcemap: true,
    logLevel: "info",
  },
  {
    entryPoints: ["src/webview/main.ts"],
    bundle: true,
    platform: "browser",
    format: "iife",
    target: "es2022",
    outfile: "dist/webview.js",
    sourcemap: true,
    minify: !watch,
    define: VUE_DEFINES,
    loader: { ".svg": "dataurl" },
    plugins: [vuePlugin({ cssFile: "dist/webview.css" })],
    logLevel: "info",
  },
  {
    // Mermaid, as a script of its own that the view adds when an answer holds a diagram: about three megabytes the view
    // should not parse at startup.
    entryPoints: ["src/webview/mermaid-entry.ts"],
    bundle: true,
    platform: "browser",
    format: "iife",
    target: "es2022",
    outfile: "dist/mermaid.js",
    minify: !watch,
    legalComments: "none",
    logLevel: "info",
  },
];

if (watch) {
  const contexts = await Promise.all(options.map((option) => context(option)));
  await Promise.all(contexts.map((item) => item.watch()));
  console.log("watching the extension and the webview");
} else {
  for (const option of options) {
    await context(option).then(async (item) => {
      await item.rebuild();
      await item.dispose();
    });
  }
}
