// Markdown to safe HTML: GitHub-flavoured markdown, highlighted code in every language highlight.js knows, and math
// through KaTeX. It is loaded on demand (it is most of the page's weight), and everything it produces passes through
// DOMPurify, because the text is whatever a model or another session wrote.

import DOMPurify from "dompurify";
import hljs from "highlight.js";
import { Marked, type Tokens } from "marked";
import markedKatex from "marked-katex-extension";
import { normalizeMath } from "./mathdelims";

/** Code longer than this is shown unhighlighted: highlighting is linear but not free. */
const HIGHLIGHT_LIMIT = 40_000;
/** Rendered results are kept up to this many characters of HTML: a long answer is a few of them, a short one many. */
const CACHE_CHARS = 1_500_000;

export interface Labels {
  copy: string;
}

function escapeHtml(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

/** Names people give a language that highlight.js knows by another. */
const ALIASES: Record<string, string> = { sh: "bash", shell: "bash", zsh: "bash", console: "shell", py: "python", js: "javascript", ts: "typescript", yml: "yaml", rs: "rust", tex: "latex", "c++": "cpp", "c#": "csharp", golang: "go" };

function highlight(text: string, language: string): string {
  const name = ALIASES[language.toLowerCase()] ?? language.toLowerCase();
  if (text.length > HIGHLIGHT_LIMIT || !name || !hljs.getLanguage(name)) return escapeHtml(text);
  try {
    return hljs.highlight(text, { language: name, ignoreIllegals: true }).value;
  } catch {
    return escapeHtml(text);
  }
}

let copyLabel = "Copy";

const marked = new Marked({ gfm: true, breaks: true });
marked.use(markedKatex({ throwOnError: false, nonStandard: true, output: "htmlAndMathml" }));
marked.use({
  renderer: {
    code({ text, lang }: Tokens.Code): string {
      const language = (lang ?? "").trim().split(/\s+/)[0] ?? "";
      return (
        `<div class="code"><div class="code-head"><span class="code-lang">${escapeHtml(language || "text")}</span>` +
        `<button type="button" class="code-copy" data-copy>${escapeHtml(copyLabel)}</button></div>` +
        `<pre><code class="hljs">${highlight(text, language)}</code></pre></div>`
      );
    },
  },
});

// KaTeX draws radicals, hats and stretchy arrows as inline <svg> in its HTML output, so that profile stays (the page's
// policy forbids scripts and foreign images whatever a message holds).
// The sanitizer does not stop a message from loading an image from another site (that is what a tracking pixel is); the
// page's CSP does (`img-src 'self' data:`), so the two go together.
DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName === "A") {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener noreferrer");
  }
});

const cache = new Map<string, string>();
let cached = 0;

/** Render markdown text to sanitized HTML. The same text gives the same HTML, so results are kept. */
export function renderMarkdown(text: string, labels: Labels = { copy: "Copy" }): string {
  const key = `${labels.copy}\u0000${text}`;
  const kept = cache.get(key);
  if (kept !== undefined) return kept;
  copyLabel = labels.copy;
  let html: string;
  try {
    html = marked.parse(normalizeMath(text), { async: false });
  } catch {
    html = `<p>${escapeHtml(text)}</p>`;
  }
  const clean = DOMPurify.sanitize(html, { USE_PROFILES: { html: true, mathMl: true, svg: true } });
  cache.set(key, clean);
  cached += clean.length;
  for (const [oldest, html] of cache) {
    if (cached <= CACHE_CHARS || oldest === key) break;
    cache.delete(oldest);
    cached -= html.length;
  }
  return clean;
}
