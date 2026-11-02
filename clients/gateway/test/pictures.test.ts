import assert from "node:assert/strict";
import { test } from "node:test";
import { DEFAULTS, KEEP_BELOW, MAX_SIDE, bytesOf, dimensionsOf, fitWithin, isPicture, refusal, roomOf, sendAsIs } from "../src/lib/pictures";
import type { Picture } from "../src/types";

const picture = (bytes: number): Picture => ({ media_type: "image/png", data: "", src: "", bytes, name: "p.png" });

test("a picture that fits is left as it is, and a large one is scaled to its longest side", () => {
  assert.deepEqual(fitWithin(800, 600), { width: 800, height: 600 });
  assert.deepEqual(fitWithin(MAX_SIDE, 10), { width: MAX_SIDE, height: 10 });
  assert.deepEqual(fitWithin(4032, 3024), { width: 1568, height: 1176 });
  assert.deepEqual(fitWithin(3024, 4032), { width: 1176, height: 1568 });
  assert.deepEqual(fitWithin(100000, 1), { width: 1568, height: 1 }, "never to nothing");
  assert.deepEqual(fitWithin(0, 0), { width: 0, height: 0 });
});

test("a small file of a type a model reads goes as it is; anything else is drawn again", () => {
  assert.equal(sendAsIs("image/gif", 200_000, 400, 300), true);
  assert.equal(sendAsIs("image/png", KEEP_BELOW + 1, 400, 300), false, "too heavy");
  assert.equal(sendAsIs("image/webp", 100_000, MAX_SIDE + 1, 10), false, "too wide");
  assert.equal(sendAsIs("image/jpeg", 100, 10, 10), false, "a photo is always drawn again, which drops where it was taken");
  assert.equal(sendAsIs("image/bmp", 1000, 10, 10), false, "not a type a model reads");
  assert.equal(sendAsIs("image/svg+xml", 1000, 10, 10), false);
});

test("the size of a base64 string is the size of what it holds", () => {
  assert.equal(bytesOf(btoa("abc")), 3);
  assert.equal(bytesOf(btoa("ab")), 2);
  assert.equal(bytesOf(btoa("a")), 1);
  assert.equal(bytesOf(""), 0);
});

test("a picture is added unless there are too many, it is too large, or they are together", () => {
  const room = roomOf(undefined);
  assert.deepEqual(room, { images: DEFAULTS.images, image: DEFAULTS.image, total: DEFAULTS.total });
  assert.equal(refusal([], picture(1000), room), "");
  assert.match(refusal([1, 2, 3, 4].map(() => picture(10)), picture(10), room), /At most/);
  assert.match(refusal([], picture(room.image + 1), room), /too large/);
  assert.match(refusal([picture(room.image), picture(room.image - 1)], picture(room.image), room), /together/);
  const small = roomOf({ max_text: 1, rate_limit: 1, rate_window: 1, used: 0, max_images: 1, max_image_bytes: 10, max_images_bytes: 10 });
  assert.match(refusal([picture(1)], picture(1), small), /At most/, "what the gateway says wins over the defaults");
});

test("only an image type is a picture", () => {
  assert.equal(isPicture({ type: "image/webp" }), true);
  assert.equal(isPicture({ type: "text/plain" }), false);
  assert.equal(isPicture({ type: "" }), false);
});

// ---- the size of a picture, from its first bytes
const bytes = (...parts: (number[] | string)[]): Uint8Array =>
  Uint8Array.from(parts.flatMap((p) => (typeof p === "string" ? [...p].map((c) => c.charCodeAt(0)) : p)));
const pad = (head: Uint8Array, to = 64): Uint8Array => {
  const out = new Uint8Array(to);
  out.set(head);
  return out;
};
const be = (n: number): number[] => [(n >>> 24) & 255, (n >>> 16) & 255, (n >>> 8) & 255, n & 255];

test("a PNG's size is in its header", () => {
  const png = pad(bytes([0x89], "PNG\r\n", [0x1a, 0x0a], be(13), "IHDR", be(4032), be(3024)));
  assert.deepEqual(dimensionsOf(png), { width: 4032, height: 3024 });
});

test("a GIF's size is in its header", () => {
  assert.deepEqual(dimensionsOf(pad(bytes("GIF89a", [0x90, 0x01, 0xc8, 0x00]))), { width: 400, height: 200 });
  assert.deepEqual(dimensionsOf(pad(bytes("GIF87a", [0x0a, 0x00, 0x14, 0x00]))), { width: 10, height: 20 });
});

test("a WebP's size is where its kind puts it", () => {
  const riff = (kind: string, body: number[]) => pad(bytes("RIFF", [0, 0, 0, 0], "WEBP", kind, [0, 0, 0, 0], body));
  // extended: 24-bit width-1 and height-1 at 24 and 27
  const x = riff("VP8X", [0, 0, 0, 0, 0x8f, 0x03, 0x00, 0x57, 0x02, 0x00]);
  assert.deepEqual(dimensionsOf(x), { width: 912, height: 600 });
  // lossless: signature 0x2f, then 14 bits of width-1 and 14 of height-1
  const w = 799, h = 599;
  const bits = (w | (h << 14)) >>> 0;
  const l = riff("VP8L", [0x2f, bits & 255, (bits >>> 8) & 255, (bits >>> 16) & 255, (bits >>> 24) & 255]);
  assert.deepEqual(dimensionsOf(l), { width: 800, height: 600 });
  // lossy: the start code, then 14 bits each (the top two are a scale)
  const v = riff("VP8 ", [0, 0, 0, 0x9d, 0x01, 0x2a, 0x20, 0x03, 0x58, 0x02]);
  assert.deepEqual(dimensionsOf(v), { width: 800, height: 600 });
});

test("what is not a PNG, GIF or WebP, or is cut short, has no size to read", () => {
  assert.equal(dimensionsOf(pad(bytes([0xff, 0xd8, 0xff, 0xe0]))), null, "a JPEG is decoded");
  assert.equal(dimensionsOf(new Uint8Array(0)), null);
  assert.equal(dimensionsOf(bytes("GIF89a")), null, "a header that stops early");
  assert.equal(dimensionsOf(pad(bytes("RIFF", [0, 0, 0, 0], "WEBP", "VP8X")))?.width, 1, "an all-zero extended header is one pixel, not an error");
});
