/**
 * Package the extension into a .vsix.
 *
 * The README goes in as it is, pictures and all: every address in it is absolute, because the extension page shows the
 * README from the marketplace and cannot load a file beside it. `--no-rewrite-relative-links` keeps `vsce` from
 * rewriting anything into a repository address that may not exist.
 */

import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

execFileSync(
  "npx",
  ["--yes", "@vscode/vsce", "package", "--no-dependencies", "--readme-path", "README.md", "--no-rewrite-relative-links"],
  { cwd: root, stdio: "inherit", shell: process.platform === "win32" },
);
