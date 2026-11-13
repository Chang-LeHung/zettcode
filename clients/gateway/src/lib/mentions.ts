/**
 * Draw `@handle` in a rendered message as a mention, when the handle is one of `handles` (the group's members): the words are
 * wrapped in `<span class="mention">`, and `mine` (the reader's own handle, if they have one) gets `mention me` besides. A word
 * that only starts with `@` ("mail me @ noon", an address) is text and is left as it is, and so is anything inside code or a
 * link. Calling it again on markup already marked changes nothing. Returns how many mentions it drew.
 */
export function markMentions(root: Element, handles: readonly string[], mine = ""): number {
  const known = new Set(handles.map((handle) => handle.toLowerCase()).filter(Boolean));
  if (!known.size) return 0;
  const me = mine.toLowerCase();
  const doc = root.ownerDocument;
  const texts: Text[] = [];
  const walker = doc.createTreeWalker(root, 4 /* NodeFilter.SHOW_TEXT */);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const parent = node.parentElement;
    if (parent && !parent.closest("code, pre, a, .mention")) texts.push(node as Text);
  }
  let drawn = 0;
  for (const node of texts) {
    const value = node.data;
    const pattern = /(^|[\s(（"“'‘>])@([\p{L}\p{N}_-]+)/gu;
    let last = 0;
    let found: RegExpExecArray | null;
    const parts: Node[] = [];
    while ((found = pattern.exec(value))) {
      const word = found[2]!;
      if (!known.has(word.toLowerCase())) continue;
      const start = found.index + found[1]!.length;
      if (start > last) parts.push(doc.createTextNode(value.slice(last, start)));
      const span = doc.createElement("span");
      span.className = word.toLowerCase() === me ? "mention me" : "mention";
      span.textContent = `@${word}`;
      parts.push(span);
      last = start + 1 + word.length;
      drawn += 1;
    }
    if (!parts.length) continue;
    if (last < value.length) parts.push(doc.createTextNode(value.slice(last)));
    node.replaceWith(...parts);
  }
  return drawn;
}
