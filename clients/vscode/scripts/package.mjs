/**
 * Package the extension into a .vsix.
 *
 * The README refers to its picture by a path (`media/icon.png`), which is what GitHub needs to show it. `vsce` would
 * turn that into a link to the repository's `raw` address, and the extension page then shows a broken picture unless
 * the file is public at exactly that address. So the picture is put into the README that goes in the package itself,
 * as a data URI: the page shows it from the installed extension, offline, whatever the repository looks like.
 */

import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { inlineImages } from "./readme-images.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

// `vsce` only reads a README that lies inside the extension's folder, so it is written under `build/`, which is
// ignored by git and left out of the package, and removed again afterwards.
const readme = path.join("build", "README.package.md");
mkdirSync(path.join(root, "build"), { recursive: true });
try {
  writeFileSync(path.join(root, readme), inlineImages(readFileSync(path.join(root, "README.md"), "utf8"), root));
  execFileSync(
    "npx",
    ["--yes", "@vscode/vsce", "package", "--no-dependencies", "--readme-path", readme, "--no-rewrite-relative-links"],
    { cwd: root, stdio: "inherit", shell: process.platform === "win32" },
  );
} finally {
  rmSync(path.join(root, readme), { force: true });
}
