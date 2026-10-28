// Models write math in two dialects: `$...$` / `$$...$$` and `\(...\)` / `\[...\]`. The renderer understands the first, so
// the second is rewritten to it, outside code (a regex in a code block is not a formula).

/** Rewrite `\( \)` and `\[ \]` to `$ $` and `$$ $$`, leaving fenced and inline code alone. */
export function normalizeMath(text: string): string {
  return text
    .split(/(```[\s\S]*?(?:```|$)|`[^`\n]*`)/g)
    .map((part, index) => (index % 2 === 1 ? part : rewrite(part)))
    .join("");
}

function rewrite(text: string): string {
  return text
    .replace(/\\\[([\s\S]+?)\\\]/g, (_, body: string) => `\n$$\n${body.trim()}\n$$\n`)
    .replace(/\\\(([^\n]+?)\\\)/g, (_, body: string) => `$${body.trim()}$`);
}
