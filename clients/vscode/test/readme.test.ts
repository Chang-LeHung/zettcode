import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const readme = (): Promise<string> => readFile("README.md", "utf8");

/**
 * A picture in the extension page is fetched by the marketplace, from a public address: a path beside the README is not
 * one, and a `data:` URI is stripped by its sanitiser (which is how the first release showed a broken image).
 */
test("every address in the README is absolute, and its picture is a PNG the marketplace can fetch", async () => {
  const text = await readme();
  const targets = [...text.matchAll(/\]\(([^)\s]+)/g)].map((match) => match[1] ?? "");
  const relative = targets.filter((target) => !/^(https?:|mailto:|#)/.test(target));
  assert.deepEqual(relative, [], `relative links: ${relative.join(", ")}`);

  const sources = [...text.matchAll(/<img\b[^>]*?\bsrc="([^"]+)"/g)].map((match) => match[1] ?? "");
  assert.ok(sources.length >= 1, "the README shows the mascot");
  for (const source of sources) {
    assert.ok(source.startsWith("https://"), `${source} is not an absolute address`);
    assert.equal(source.startsWith("data:"), false, "a data URI is stripped by the marketplace");
    const path = source.replace(/^https:\/\/[^/]+\//, "");
    assert.ok(path.endsWith(".png"), `${source} is not a PNG; SVG is refused by the marketplace`);
    const inside = path.slice(path.indexOf("clients/vscode/") + "clients/vscode/".length);
    assert.ok(await exists(inside), `${source} does not name a file of this repository (${inside})`);
  }
});

async function exists(file: string): Promise<boolean> {
  try {
    await readFile(file);
    return true;
  } catch {
    return false;
  }
}

test("the README introduces the extension to the person using it, not to the person building it", async () => {
  const text = await readme();
  for (const forbidden of [
    /npm (run|test|install)/,
    /\bmake [a-z-]+/,
    /vue-tsc|esbuild|jsdom/,
    /\bsrc\/|\.ts\b|\.vue\b/,
    /Extension Development Host|F5/,
    /Turn\b.*reducer|reducer/,
  ]) {
    assert.ok(!forbidden.test(text), `developer detail in the README: ${forbidden}`);
  }
  for (const wanted of ["Getting started", "What you can do", "Shell permission", "Settings"]) {
    assert.ok(text.includes(wanted), `the README has a "${wanted}" section`);
  }
});

test("the manifest names the author and points every link at the repository", async () => {
  const manifest = JSON.parse(await readFile("package.json", "utf8")) as {
    author?: { name?: string; url?: string };
    publisher?: string;
    repository?: { url?: string };
    bugs?: { url?: string };
    homepage?: string;
  };
  assert.equal(manifest.author?.name, "Chang LeHung");
  assert.equal(manifest.author?.url, "https://github.com/Chang-LeHung");
  for (const url of [manifest.repository?.url, manifest.bugs?.url, manifest.homepage]) {
    assert.ok(url?.includes("github.com/Chang-LeHung/zettcode"), `a link to the repository: ${url}`);
  }
  // The publisher is an ID on the marketplace, not a person's name: it must be the one the extension is uploaded
  // under, and it never changes.
  assert.equal(manifest.publisher, "zettcode");
});
