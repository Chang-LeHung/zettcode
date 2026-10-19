/** Searching the conversation on show: where a query occurs in the text a reader can see, and how to step between hits. */

export interface Hit {
  node: Text;
  start: number;
  end: number;
}

/** Text that is never prose: scripts, styles and the buttons drawn on a code block. */
const SKIPPED = new Set(["SCRIPT", "STYLE", "BUTTON", "SVG"]);

/**
 * Every place `query` occurs in the text under `root`, in reading order, ignoring case. A hit lies inside one run of
 * text, so a phrase split by bold or a link in the middle is not found as one; the words either side of it are.
 */
export function findHits(root: Node, query: string): Hit[] {
  const needle = query.toLowerCase();
  if (!needle.trim()) {
    return [];
  }
  const doc = root.ownerDocument ?? (root as Document);
  const walker = doc.createTreeWalker(root, 4 /* NodeFilter.SHOW_TEXT */, {
    acceptNode(node: Node): number {
      const parent = node.parentElement;
      if (!parent || SKIPPED.has(parent.tagName.toUpperCase()) || !(node as Text).data.trim()) {
        return 2; // FILTER_REJECT
      }
      return 1; // FILTER_ACCEPT
    },
  });
  const hits: Hit[] = [];
  for (let node = walker.nextNode() as Text | null; node !== null; node = walker.nextNode() as Text | null) {
    const text = node.data.toLowerCase();
    // A case change that alters the length would shift every offset after it; such text is searched as it is.
    const haystack = text.length === node.data.length ? text : node.data;
    let from = 0;
    for (let at = haystack.indexOf(needle, from); at >= 0; at = haystack.indexOf(needle, from)) {
      hits.push({ node, start: at, end: at + needle.length });
      from = at + needle.length;
    }
  }
  return hits;
}

/** The hit after (or, with a negative step, before) `index`, wrapping round at both ends. */
export function stepIndex(index: number, count: number, step: number): number {
  if (count <= 0) {
    return 0;
  }
  return (((index + step) % count) + count) % count;
}

/** The label beside the box: where the reader is among the hits, or that there are none. */
export function findLabel(query: string, index: number, count: number): string {
  if (!query.trim()) {
    return "";
  }
  return count === 0 ? "No results" : `${index + 1} of ${count}`;
}
