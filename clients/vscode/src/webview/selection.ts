/**
 * Keeping the reader's selection while the text under it is written again.
 *
 * An answer that is still arriving is drawn again with every few words: the block's HTML is replaced, the nodes the
 * selection pointed into are thrown away, and the selection collapses to nothing. Someone who selects a sentence of an
 * answer being written then finds Ctrl+C has nothing to copy. Here the two ends of the selection are remembered as
 * character positions in the block's text, which the new HTML shares for everything already written, and put back once
 * it has been drawn.
 */

/** One end of a selection: a position in the block's text, or a place outside the block, which the redraw leaves alone. */
type End = { inside: number } | { node: Node; offset: number };

/** What was selected before a redraw. */
export interface Saved {
  anchor: End;
  focus: End;
}

/** The text before a point, as a count of characters from the start of `root`. */
function textBefore(root: Node, node: Node, offset: number): number {
  const range = document.createRange();
  range.setStart(root, 0);
  range.setEnd(node, offset);
  return range.toString().length;
}

/** Where `position` falls in `root`'s text: the text node, and how far into it; the end of the text when it is past it. */
function locate(root: Node, position: number): { node: Node; offset: number } {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let left = position;
  let last: Node | null = null;
  for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
    const length = node.textContent?.length ?? 0;
    if (left <= length) {
      return { node, offset: left };
    }
    left -= length;
    last = node;
  }
  return last === null ? { node: root, offset: root.childNodes.length } : { node: last, offset: last.textContent?.length ?? 0 };
}

function endOf(root: Node, node: Node | null, offset: number): End | null {
  if (node === null) {
    return null;
  }
  return root.contains(node) ? { inside: textBefore(root, node, offset) } : { node, offset };
}

/**
 * Remember the selection if either end of it is in `root`; ``null`` when nothing is selected there, so that a redraw
 * of a block the reader is not touching costs nothing.
 */
export function saveSelection(root: Node): Saved | null {
  const selection = window.getSelection();
  if (selection === null || selection.rangeCount === 0 || selection.isCollapsed) {
    return null;
  }
  const anchor = endOf(root, selection.anchorNode, selection.anchorOffset);
  const focus = endOf(root, selection.focusNode, selection.focusOffset);
  if (anchor === null || focus === null || !("inside" in anchor || "inside" in focus)) {
    return null;
  }
  return { anchor, focus };
}

/** Select again what `saved` describes, now that `root` holds its new HTML. The direction of the selection is kept. */
export function restoreSelection(root: Node, saved: Saved | null): void {
  const selection = window.getSelection();
  if (saved === null || selection === null) {
    return;
  }
  const place = (end: End): { node: Node; offset: number } => ("inside" in end ? locate(root, end.inside) : end);
  const anchor = place(saved.anchor);
  const focus = place(saved.focus);
  selection.setBaseAndExtent(anchor.node, anchor.offset, focus.node, focus.offset);
}
