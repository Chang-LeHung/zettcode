import { readFileSync } from "node:fs";
import path from "node:path";

const TYPES = { ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp" };

/**
 * The README with every `<img src="media/...">` replaced by the file's own bytes, as a data URI.
 *
 * SVG is refused on purpose: the marketplace does not allow it in a README, so a README that used one would work here
 * and fail the day the extension is published.
 */
export function inlineImages(markdown, folder) {
  return markdown.replace(/(<img\b[^>]*?\bsrc=")(media\/[^"]+)(")/g, (_match, head, source, tail) => {
    const type = TYPES[path.extname(source).toLowerCase()];
    if (type === undefined) {
      throw new Error(`README image ${source} is not a picture type a README can carry (SVG is refused)`);
    }
    const bytes = readFileSync(path.join(folder, source));
    return `${head}data:${type};base64,${bytes.toString("base64")}${tail}`;
  });
}
