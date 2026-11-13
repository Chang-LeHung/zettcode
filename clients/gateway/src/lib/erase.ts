/** What a backspace removes, when it removes a whole thing rather than one character, as a messenger's does. */
export interface Erased {
  value: string;
  caret: number;
  /** The span of the old text that went, `[from, to)`: what a native delete is asked to remove so the browser can undo it. */
  from: number;
  to: number;
}

/**
 * What a Backspace keydown in a text field should do when it takes a whole unit (see {@link eraseWhole}): the new text, or
 * `null` to leave the key to the browser. A selection, a modifier (word and line deletes) and an IME composition are the
 * browser's.
 */
export function backspaceWhole(event: KeyboardEvent, field: HTMLTextAreaElement, handles: readonly string[] = []): Erased | null {
  if (event.key !== "Backspace" || event.isComposing || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return null;
  if (field.selectionStart !== field.selectionEnd) return null;
  return eraseWhole(field.value, field.selectionStart, handles);
}

/**
 * The text after a Backspace at `caret` when it should take a whole unit, or `null` when it is an ordinary one-character
 * delete. A unit is:
 *
 * - a mention the person picked, `@handle ` with the caret just after its space (only a `handle` the caller says is a
 *   member's: a word the person typed that merely starts with `@` is text and is erased as text); and
 * - a quote, the `> ` lines of one with the caret at the start of the line after it, along with the blank line that
 *   follows the quote.
 *
 * `handles` are compared without regard to case.
 */
export function eraseWhole(value: string, caret: number, handles: readonly string[] = []): Erased | null {
  const before = value.slice(0, caret);
  const after = value.slice(caret);

  const mention = /(^|\s)@([\p{L}\p{N}_-]+) $/u.exec(before);
  if (mention && handles.some((handle) => handle.toLowerCase() === mention[2]!.toLowerCase())) {
    const start = before.length - mention[0].length + mention[1]!.length;
    return { value: before.slice(0, start) + after, caret: start, from: start, to: caret };
  }

  if (before.endsWith("\n")) {
    const lines = before.replace(/\n+$/, "").split("\n");
    let first = lines.length;
    while (first > 0 && /^>/.test(lines[first - 1]!)) first -= 1;
    if (first < lines.length) {
      const kept = lines.slice(0, first).join("\n").replace(/\n+$/, "");
      // The blank line that separated the quote from what came before it goes too, so nothing is left dangling.
      const head = kept ? `${kept}\n` : "";
      return { value: head + after, caret: head.length, from: head.length, to: caret };
    }
  }
  return null;
}

/**
 * Carry out `whole` in `field` through the browser's own delete, so Ctrl/Cmd+Z brings the quote or mention back: the span
 * is selected and `execCommand("delete")` removes it, which also fires the `input` event a `v-model` listens to. Returns
 * `false` when the browser would not (the command is unavailable, or left a different text), and the caller then sets the
 * value itself, losing the undo but not the effect.
 */
export function applyErase(field: HTMLTextAreaElement, whole: Erased): boolean {
  try {
    // `execCommand` acts on the focused element's selection, and setting a range does not focus a textarea everywhere.
    field.focus({ preventScroll: true });
    field.setSelectionRange(whole.from, whole.to);
    if (typeof document.execCommand === "function" && document.execCommand("delete") && field.value === whole.value) {
      field.setSelectionRange(whole.caret, whole.caret);
      return true;
    }
  } catch {
    // Fall through to the caller's own write.
  }
  return false;
}
