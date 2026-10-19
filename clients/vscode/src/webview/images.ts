/** Reading images the reader pasted or dropped into the view. */

import { MAX_IMAGES, state, toast } from "./store.js";

const MAX_BYTES = 8 * 1024 * 1024;

function readAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error ?? new Error("Could not read the image"));
    reader.readAsDataURL(file);
  });
}

/** Attach up to four images of at most 8 MB each; anything else is skipped with a word about why. */
export async function addFiles(files: FileList | File[] | undefined): Promise<void> {
  if (!files) {
    return;
  }
  for (const file of Array.from(files).slice(0, MAX_IMAGES)) {
    if (!file.type.startsWith("image/")) {
      continue;
    }
    if (file.size > MAX_BYTES) {
      toast(`${file.name} is larger than 8 MB.`, "warn");
      continue;
    }
    const data = await readAsDataUrl(file);
    const comma = data.indexOf(",");
    const mediaType = /data:([^;]+)/.exec(data.slice(0, comma))?.[1] ?? file.type ?? "image/png";
    state.attachments = [...state.attachments, { name: file.name, mediaType, data: data.slice(comma + 1) }].slice(0, MAX_IMAGES);
  }
}
