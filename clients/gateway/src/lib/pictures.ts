// Pictures to send with a message. A model reads a picture at a size well under what a camera takes, so a large one is
// shrunk here before it goes: the page sends less, the broker takes it, and nothing is lost that the model would see.
//
// The arithmetic and the rules are plain functions, tested without a browser; the decoding that needs a canvas is
// `prepare`, at the end.

import type { Limits, Picture } from "../types";

/** What the broker takes, for a gateway that does not say (see `Limits`). */
export const DEFAULTS = { images: 4, image: 4 << 20, total: 8 << 20 };

/** The types a model reads. */
export const TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp"];

/** The longest side a picture is shrunk to. */
export const MAX_SIDE = 1568;

/** A PNG, GIF or WebP under this size and within `MAX_SIDE` is sent exactly as it is, which keeps a GIF animated and a PNG sharp. */
export const KEEP_BELOW = 1 << 20;

export interface Room {
  images: number;
  image: number;
  total: number;
}

export function roomOf(limits: Limits | undefined): Room {
  return {
    images: limits?.max_images ?? DEFAULTS.images,
    image: limits?.max_image_bytes ?? DEFAULTS.image,
    total: limits?.max_images_bytes ?? DEFAULTS.total,
  };
}

/** The size a picture is drawn at: its own when it fits, otherwise scaled down so its longest side is `max`. */
export function fitWithin(width: number, height: number, max = MAX_SIDE): { width: number; height: number } {
  const longest = Math.max(width, height);
  if (longest <= max || longest <= 0) return { width, height };
  const scale = max / longest;
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) };
}

/** The types that can be sent untouched. A JPEG never is: a photo's file says where it was taken, and which way up it is. */
const AS_IS = ["image/png", "image/gif", "image/webp"];

/** Whether a picked file can be sent untouched: a small PNG, GIF (which stays animated) or WebP within `MAX_SIDE`. */
export function sendAsIs(type: string, bytes: number, width: number, height: number): boolean {
  return AS_IS.includes(type) && bytes <= KEEP_BELOW && Math.max(width, height) <= MAX_SIDE;
}

const u16 = (b: Uint8Array, at: number): number => (b[at] ?? 0) | ((b[at + 1] ?? 0) << 8);
const u24 = (b: Uint8Array, at: number): number => u16(b, at) | ((b[at + 2] ?? 0) << 16);
const be32 = (b: Uint8Array, at: number): number => ((b[at] ?? 0) * 2 ** 24) + (((b[at + 1] ?? 0) << 16) | ((b[at + 2] ?? 0) << 8) | (b[at + 3] ?? 0));
const ascii = (b: Uint8Array, at: number, text: string): boolean => [...text].every((c, i) => b[at + i] === c.charCodeAt(0));

/**
 * The size of a PNG, GIF or WebP, from the first bytes of the file alone, so that a picture that goes as it is is never
 * decoded just to be measured. `null` for anything else, or for a header it cannot read: the picture is then decoded.
 */
export function dimensionsOf(head: Uint8Array): { width: number; height: number } | null {
  if (ascii(head, 1, "PNG") && head.length >= 24) return { width: be32(head, 16), height: be32(head, 20) };
  if ((ascii(head, 0, "GIF87a") || ascii(head, 0, "GIF89a")) && head.length >= 10) return { width: u16(head, 6), height: u16(head, 8) };
  if (ascii(head, 0, "RIFF") && ascii(head, 8, "WEBP") && head.length >= 30) {
    if (ascii(head, 12, "VP8X")) return { width: u24(head, 24) + 1, height: u24(head, 27) + 1 };
    if (ascii(head, 12, "VP8L") && head[20] === 0x2f) {
      const bits = u16(head, 21) | (u16(head, 23) << 16);
      return { width: (bits & 0x3fff) + 1, height: ((bits >>> 14) & 0x3fff) + 1 };
    }
    if (ascii(head, 12, "VP8 ") && head[23] === 0x9d && head[24] === 0x01 && head[25] === 0x2a) {
      return { width: u16(head, 26) & 0x3fff, height: u16(head, 28) & 0x3fff };
    }
  }
  return null;
}

/** The bytes of a base64 string. */
export function bytesOf(base64: string): number {
  const padding = base64.endsWith("==") ? 2 : base64.endsWith("=") ? 1 : 0;
  return Math.floor((base64.length * 3) / 4) - padding;
}

/** Why a picture cannot be added to the ones already chosen, in English the page translates, or an empty string. */
export function refusal(chosen: readonly Picture[], next: Picture, room: Room): string {
  if (chosen.length >= room.images) return "At most {count} pictures go with one message";
  if (next.bytes > room.image) return "That picture is too large";
  if (chosen.reduce((sum, p) => sum + p.bytes, 0) + next.bytes > room.total) return "The pictures are too large together";
  return "";
}

/** Whether a dropped or pasted thing is a picture: a file of an image type. */
export function isPicture(file: { type: string }): boolean {
  return file.type.startsWith("image/");
}

// ---- the part that needs a browser
function load(file: Blob): Promise<ImageBitmap> {
  return createImageBitmap(file);
}

function base64Of(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let text = "";
  for (let at = 0; at < bytes.length; at += 0x8000) text += String.fromCharCode(...bytes.subarray(at, at + 0x8000));
  return btoa(text);
}

/** Read a file the person picked into something that can be sent.
 *
 * A small PNG, GIF or WebP goes exactly as it is, and its size is read from its first bytes, so nothing is decoded for
 * it. Anything else is decoded and drawn again as a JPEG no larger than `MAX_SIDE` (on white, since a JPEG has no
 * transparency): a photo is always drawn again, which also drops what its file says about where it was taken, and
 * applies the way up it was held. A photograph of many megapixels costs its decoded size in memory while that happens.
 */
export async function prepare(file: File): Promise<Picture> {
  if (!isPicture(file)) throw new Error("That is not a picture");
  const size = dimensionsOf(new Uint8Array(await file.slice(0, 64).arrayBuffer()));
  if (size && sendAsIs(file.type, file.size, size.width, size.height)) {
    const data = base64Of(await file.arrayBuffer());
    return { media_type: file.type, data, src: `data:${file.type};base64,${data}`, bytes: file.size, name: file.name };
  }
  const bitmap = await load(file);
  try {
    const { width, height } = fitWithin(bitmap.width, bitmap.height);
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("This browser cannot shrink a picture");
    context.fillStyle = "#fff";
    context.fillRect(0, 0, width, height);
    context.drawImage(bitmap, 0, 0, width, height);
    const url = canvas.toDataURL("image/jpeg", 0.85);
    const data = url.slice(url.indexOf(",") + 1);
    return { media_type: "image/jpeg", data, src: url, bytes: bytesOf(data), name: file.name };
  } finally {
    bitmap.close();
  }
}
