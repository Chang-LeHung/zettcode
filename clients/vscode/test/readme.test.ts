import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { inlineImages } from "../scripts/readme-images.mjs";

const readme = (): Promise<string> => readFile("README.md", "utf8");

test("the README links only to absolute addresses, so nothing in the package page can break", async () => {
  const text = await readme();
  // A relative link is rewritten by the packager into a repository address that may not exist (and, from this
  // folder, into a wrong one); a picture is the one relative thing allowed, because the build inlines it.
  const targets = [...text.matchAll(/\]\(([^)\s]+)/g)].map((match) => match[1] ?? "");
  const relative = targets.filter((target) => !/^(https?:|mailto:|#)/.test(target));
  assert.deepEqual(relative, [], `relative links: ${relative.join(", ")}`);
  const sources = [...text.matchAll(/<img\b[^>]*?\bsrc="([^"]+)"/g)].map((match) => match[1] ?? "");
  assert.ok(sources.length >= 1, "the README shows the mascot");
  for (const source of sources) {
    assert.ok(/^https?:|^media\//.test(source), `${source} is neither absolute nor under media/`);
    if (source.startsWith("media/")) {
      assert.ok(existsSync(source), `${source} exists`);
      assert.ok(source.endsWith(".png"), "a README picture is a PNG; SVG is refused by the marketplace");
    }
  }
});

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

test("the picture is put into the packaged README as the file's own bytes, and SVG is refused", async () => {
  const html = '<p><img src="media/icon.png" width="128" alt="x" /></p>';
  const inlined = inlineImages(html, ".");
  const data = /src="data:image\/png;base64,([^"]+)"/.exec(inlined)?.[1];
  assert.ok(data, "a data URI");
  const bytes = Buffer.from(data, "base64");
  assert.equal(bytes.subarray(1, 4).toString("latin1"), "PNG");
  assert.deepEqual(bytes, await readFile("media/icon.png"));
  // Absolute pictures, and everything else in the text, stay as they were.
  const other = '<img src="https://example.com/a.png" /> and `media/icon.png` in code';
  assert.equal(inlineImages(other, "."), other);
  assert.throws(() => inlineImages('<img src="media/logo.svg" />', "."), /SVG/);
});
