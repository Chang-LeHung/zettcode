import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import * as path from "node:path";
import test from "node:test";

const SOURCE = "src";

/** The modules allowed to import `vscode` and the HTTP client: everything on the host side. */
const HOST = new Set(["extension.ts", "server.ts", "chat.ts", "usage.ts", "diffs.ts", "provision.ts"]);

async function sources(folder = SOURCE): Promise<{ file: string; text: string }[]> {
  const found: { file: string; text: string }[] = [];
  for (const entry of await readdir(folder, { withFileTypes: true })) {
    const full = path.join(folder, entry.name);
    if (entry.isDirectory()) {
      found.push(...(await sources(full)));
    } else if (entry.name.endsWith(".ts")) {
      found.push({ file: path.relative(SOURCE, full), text: await readFile(full, "utf8") });
    }
  }
  return found;
}

function imports(text: string): string[] {
  return [...text.matchAll(/(?:from\s+|import\s*\(\s*|require\s*\(\s*)["']([^"']+)["']/g)].map(
    (match) => match[1] ?? "",
  );
}

test("the extension speaks HTTP through the TypeScript client", async () => {
  const files = await sources();
  assert.ok(files.length >= 10);
  for (const file of files) {
    for (const specifier of imports(file.text)) {
      assert.ok(
        !/^(zettcode|zettcode_server|zettcode\.)/.test(specifier),
        `${file.file} imports ${specifier}; the extension must reach the agent over HTTP`,
      );
      // The highlighter ships a grammar called python; a bridge would be a path or a process, never that.
      assert.ok(
        !specifier.includes("python") || specifier.startsWith("highlight.js/lib/languages/"),
        `${file.file} imports ${specifier}; there is no Python bridge`,
      );
    }
  }
});

test("only the extension host imports vscode and the HTTP client", async () => {
  const files = await sources();
  for (const file of files) {
    const host = HOST.has(file.file);
    const specifiers = imports(file.text);
    if (specifiers.includes("vscode")) {
      assert.ok(host, `${file.file} imports vscode; only ${[...HOST].join(", ")} may`);
    }
    if (specifiers.some((item) => item.includes("typescript/src/index.js"))) {
      assert.ok(host, `${file.file} imports the HTTP client; the webview must post messages instead`);
    }
  }
});

test("the reducer and the webview are free of the editor and the network", async () => {
  const files = await sources();
  const pure = files.filter((file) => file.file.startsWith("core") || file.file.startsWith("webview"));
  assert.ok(pure.length >= 5);
  for (const file of pure) {
    const specifiers = imports(file.text);
    assert.ok(!specifiers.includes("vscode"), `${file.file} must not import vscode`);
    assert.ok(
      !specifiers.some((item) => item.includes("typescript/src/index.js")),
      `${file.file} must not import the HTTP client`,
    );
    assert.ok(!file.text.includes("acquireVsCodeApi") || file.file.startsWith("webview"));
  }
});

test("the editor-host half reaches no Markdown renderer, typesetter or highlighter", async () => {
  const files = new Map((await sources()).map((file) => [file.file, file.text]));
  const heavy = new Set(["core/markdown.ts", "core/math.ts", "core/highlight.ts"]);
  const reached = (start: string): string[] => {
    const seen = new Set<string>();
    const walk = (file: string): void => {
      if (seen.has(file)) {
        return;
      }
      seen.add(file);
      for (const specifier of imports(files.get(file) ?? "")) {
        if (specifier.startsWith(".") && !specifier.includes("typescript/src")) {
          walk(path.normalize(path.join(path.dirname(file), specifier.replace(/\.js$/, ".ts"))));
        }
      }
    };
    walk(start);
    return [...seen];
  };
  for (const host of HOST) {
    assert.ok(files.has(host), `${host} is a host file`);
    const heavyOnes = reached(host).filter((file) => heavy.has(file));
    assert.deepEqual(heavyOnes, [], `${host} reaches ${heavyOnes.join(", ")}, which only the webview needs`);
  }
});
