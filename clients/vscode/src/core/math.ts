/** TeX in an answer, drawn by KaTeX as MathML: the editor's browser typesets it, so no font or style sheet ships. */

import katex from "katex";

import { escapeHtml } from "./escape.js";

/** A formula that is longer than this is shown as the text it is; typesetting it would only hang the view. */
const MAX_LENGTH = 4000;

/** What KaTeX drew for a formula, kept: an answer is rendered again from the top on every streamed piece. */
const cache = new Map<string, string>();
const CACHE_LIMIT = 300;

/**
 * Typeset TeX. A formula KaTeX cannot read, or one that asks for too much, comes back as its own source in a
 * `.math-error` element and never throws, so one bad formula does not blank the answer around it.
 */
export function renderMath(tex: string, display: boolean): string {
  const source = tex.trim();
  const key = `${display ? "d" : "i"}:${source}`;
  const known = cache.get(key);
  if (known !== undefined) {
    return known;
  }
  let html: string;
  if (source.length > MAX_LENGTH) {
    html = failed(source, display);
  } else {
    try {
      const drawn = katex.renderToString(source, {
        displayMode: display,
        output: "mathml",
        throwOnError: true,
        trust: false,
        strict: "ignore",
        maxSize: 20,
        maxExpand: 1000,
      });
      html = display ? `<div class="math-display">${drawn}</div>` : `<span class="math-inline">${drawn}</span>`;
    } catch {
      html = failed(source, display);
    }
  }
  if (cache.size >= CACHE_LIMIT) {
    cache.clear();
  }
  cache.set(key, html);
  return html;
}

function failed(source: string, display: boolean): string {
  const body = `<code class="math-error" title="This formula could not be typeset">${escapeHtml(source)}</code>`;
  return display ? `<div class="math-display">${body}</div>` : body;
}
