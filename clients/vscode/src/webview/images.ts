/** Reading images the reader pasted or dropped into the view. */

import type { PastedFile } from "../core/protocol.js";
import { PASTE_FILES, PASTE_LIMIT } from "../core/pasted.js";
import { MAX_IMAGES, post, state, toast } from "./store.js";

const MAX_BYTES = 8 * 1024 * 1024;

function readAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error ?? new Error("Could not read the image"));
    reader.readAsDataURL(file);
  });
}

/**
 * Hand the host the files that were pasted and are not pictures: name and bytes, which is all a page can know of a file
 * (it has no path). The bytes of a file over the limit stay behind, and the host looks for that one by its name.
 */
export async function pasteFiles(files: File[]): Promise<void> {
  const sent: PastedFile[] = [];
  for (const file of files.slice(0, PASTE_FILES)) {
    const entry: PastedFile = { name: file.name, size: file.size };
    if (file.size <= PASTE_LIMIT) {
      try {
        const data = await readAsDataUrl(file);
        entry.data = data.slice(data.indexOf(",") + 1);
      } catch {
        // Unreadable: it goes by its name, like a file that is too large.
      }
    }
    sent.push(entry);
  }
  post({ type: "paste-files", files: sent });
}

/** Attach up to four images of at most 8 MB each; anything else is skipped with a word about why. */
export async function addFiles(files: FileList | File[] | undefined): Promise<void> {
  if (!files) {
    return;
  }
  for (const file of Array.from(files).slice(0, MAX_IMAGES)) {
    if (!file.type.startsWith("image/")) {
      // A dropped file has no path in a webview, so it cannot be sent by name; the paperclip can.
      toast(`${file.name} is not a picture. Attach it with the paperclip to send its path.`, "info");
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
