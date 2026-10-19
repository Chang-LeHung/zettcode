import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("the logo is the mascot cropped to a square, with no background and no dangling reference", async () => {
  const svg = await readFile("media/logo.svg", "utf8");
  const box = /viewBox="([\d.\s-]+)"/.exec(svg)?.[1]?.trim().split(/\s+/).map(Number);
  assert.ok(box && box.length === 4, "a viewBox");
  assert.equal(box[2], box[3], "square, so it fills an icon slot the way a square mark does");

  // The tile the other variants sit on was a rounded rectangle clipped to the canvas; none of that is in here.
  assert.ok(!/<clipPath/.test(svg), "no clipped tile");
  assert.ok(!/rx="105"/.test(svg), "no rounded tile");
  assert.ok(!/id="(?:bgDark|bgGreen)"/.test(svg), "no background gradient");

  const defined = new Set([...svg.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]));
  const used = [...svg.matchAll(/url\(#([^)]+)\)/g)].map((match) => match[1] ?? "");
  const missing = used.filter((id) => !defined.has(id));
  assert.deepEqual(missing, [], `references with no definition: ${missing.join(", ")}`);
});

test("the extension icon is a PNG with a transparent background", async () => {
  const png = await readFile("media/icon.png");
  assert.equal(png.subarray(1, 4).toString("latin1"), "PNG");
  const width = png.readUInt32BE(16);
  const height = png.readUInt32BE(20);
  const colourType = png[25];
  assert.equal(width, height);
  assert.ok(width >= 128, "large enough for the marketplace");
  // Colour type 6 is RGBA, 4 is grey with alpha: either one has the transparency a tile would not.
  assert.ok(colourType === 6 || colourType === 4, `colour type ${colourType} has no alpha channel`);
});
