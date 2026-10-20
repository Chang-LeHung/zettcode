/** Rendering an answer: CommonMark with GitHub's tables, task lists and strike-through, coloured code, and no raw HTML. */

import { Marked, Renderer, type Tokens, type TokenizerAndRendererExtension } from "marked";

import { briefly, currentTheme, drawnFor } from "./diagram.js";
import { escapeHtml } from "./escape.js";
import { highlight, resolveLanguage } from "./highlight.js";
import { renderMath } from "./math.js";
import { looksLikePath, parsePathTarget } from "./paths.js";

const EXTERNAL = /^(?:https?|mailto):/i;

/**
 * `**bold**` the way people write it in Chinese and Japanese: CommonMark refuses `这是**“引号”**后` because the stars
 * touch a letter on one side and punctuation on the other. A model does not know that rule, so a pair of stars that
 * hug their text is bold wherever it stands, and what is inside is parsed as usual (code spans, links, emphasis).
 */
const strongAnywhere: TokenizerAndRendererExtension = {
  name: "strongAnywhere",
  level: "inline",
  start(source: string) {
    return source.indexOf("**");
  },
  tokenizer(source: string) {
    const match = /^\*\*(?![\s*])((?:`[^`\n]*`|[^*\n]|\*(?!\*))+?)(?<![\s*])\*\*(?!\*)/.exec(source);
    if (match?.[1] === undefined) {
      return undefined;
    }
    return {
      type: "strong",
      raw: match[0],
      text: match[1],
      tokens: this.lexer.inlineTokens(match[1]),
    } as Tokens.Strong;
  },
};

/**
 * A formula on lines of its own: `$$ … $$` or `\[ … \]`. A `$$` that shares its line with other text is left to the
 * inline rule below, which draws it as a block too.
 */
const mathBlock: TokenizerAndRendererExtension = {
  name: "mathBlock",
  level: "block",
  start(source: string) {
    return source.search(/^ {0,3}(?:\$\$|\\\[)/m);
  },
  tokenizer(source: string) {
    const match = /^ {0,3}(?:\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]) *(?:\n+|$)/.exec(source);
    const tex = match?.[1] ?? match?.[2];
    if (match === null || tex === undefined) {
      return undefined;
    }
    return { type: "mathBlock", raw: match[0], text: tex };
  },
  renderer(token) {
    return renderMath(String(token.text), true);
  },
};

/**
 * A formula inside a line: `$x$`, `\(x\)`, and `$$x$$` or `\[x\]` (drawn on its own line). A single `$` only opens a
 * formula when it hugs its text and its closing `$` is not followed by a digit, so a price such as `$5 and $6` stays
 * text. Code spans were already cut out by the time this runs, so a `$` in code is never a formula.
 */
const mathInline: TokenizerAndRendererExtension = {
  name: "mathInline",
  level: "inline",
  start(source: string) {
    return source.search(/\$|\\[([]/);
  },
  tokenizer(source: string) {
    const shapes: [RegExp, boolean][] = [
      [/^\$\$([^\n]+?)\$\$/, true],
      [/^\\\[([\s\S]+?)\\\]/, true],
      [/^\\\(([\s\S]+?)\\\)/, false],
      [/^\$(?![\s$])((?:\\.|[^$\\\n])+?)(?<![\s\\])\$(?!\d)/, false],
    ];
    for (const [pattern, display] of shapes) {
      const match = pattern.exec(source);
      if (match?.[1] !== undefined) {
        return { type: "mathInline", raw: match[0], text: match[1], display };
      }
    }
    return undefined;
  },
  renderer(token) {
    return renderMath(String(token.text), token.display === true);
  },
};

/** A domain with a path, like `openrouter.ai/api/v1`, is an address, not a file to open. */
const DOMAIN = /^(?:[a-z0-9-]+\.)+(?:com|net|org|io|ai|dev|app|co|cn|me|cloud|so|sh|xyz|gg|tv|us|uk|de|jp|ru|fr|eu|info|tech|ly|to|cc|ms|run|page|site|edu|gov)(?::\d+)?(?:\/|$)/i;

/** Whether a piece of inline code names a file in the workspace. */
export function isFileReference(code: string): boolean {
  const text = code.trim();
  if (!text || DOMAIN.test(text) || /^[a-z][a-z0-9+.-]*:\/\//i.test(text)) {
    return false;
  }
  return looksLikePath(text);
}

function fileLink(raw: string, body: string): string {
  const target = parsePathTarget(raw);
  return `<a class="file-link" data-open="${escapeHtml(raw)}" title="Open ${escapeHtml(target?.path ?? raw)}">${body}</a>`;
}

/** How a language is written in a block's header; a name not listed is capitalised. */
const DISPLAY: Record<string, string> = {
  javascript: "JavaScript",
  typescript: "TypeScript",
  json: "JSON",
  yaml: "YAML",
  xml: "XML",
  html: "HTML",
  css: "CSS",
  scss: "SCSS",
  less: "Less",
  sql: "SQL",
  php: "PHP",
  c: "C",
  cpp: "C++",
  csharp: "C#",
  fsharp: "F#",
  objectivec: "Objective-C",
  latex: "LaTeX",
  graphql: "GraphQL",
  powershell: "PowerShell",
  dockerfile: "Dockerfile",
  makefile: "Makefile",
  cmake: "CMake",
  ocaml: "OCaml",
  coffeescript: "CoffeeScript",
  protobuf: "Protocol Buffers",
  http: "HTTP",
  ini: "INI",
  dos: "Batch",
  vbnet: "VB.NET",
  plaintext: "Text",
  nginx: "Nginx",
  r: "R",
  d: "D",
};

export function languageName(label: string, resolved: string | null): string {
  const key = resolved ?? label.toLowerCase();
  if (!key) {
    return "Text";
  }
  return DISPLAY[key] ?? (resolved === null ? label : key.charAt(0).toUpperCase() + key.slice(1));
}

const SVG = (paths: string, extra = ""): string =>
  `<svg class="i" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"${extra}>${paths}</svg>`;
const ICON_CODE = SVG('<path d="m5.5 4-3.5 4 3.5 4M10.5 4l3.5 4-3.5 4M9 3 7 13"/>');
const ICON_WRAP = SVG('<path d="M2 4h12M2 8h9a2 2 0 0 1 0 4H8M9.5 10.5 8 12l1.5 1.5M2 12h2"/>');
const ICON_EXPAND = SVG('<path d="M9.5 2.5h4v4M6.5 13.5h-4v-4M13.5 2.5 9 7M2.5 13.5 7 9"/>');
const EXPAND = (what: string): string =>
  `<button class="code-btn" data-expand type="button" title="Open ${what} larger" aria-label="Open ${what} larger">${ICON_EXPAND}</button>`;
const ICON_COPY = SVG('<path d="M5.5 5.5h7v8h-7zM3.5 10.5v-8h7"/>', ' data-icon="copy"');
const ICON_CHECK = SVG('<path d="m3.5 8.5 3 3 6-7"/>', ' data-icon="check"');

function codeBlock(code: string, label: string): string {
  const language = label.trim().split(/\s+/)[0] ?? "";
  const resolved = resolveLanguage(language);
  const colored = highlight(code, language);
  const body = colored ?? escapeHtml(code);
  const mark = colored !== null ? ` hljs${resolved === null ? "" : ` language-${escapeHtml(resolved)}`}` : "";
  return (
    `<div class="code-block"><div class="code-head"><span class="code-lang">${ICON_CODE}<span>${escapeHtml(
      languageName(language, resolved),
    )}</span></span>` +
    `<span class="code-actions">` +
    EXPAND("the code") +
    `<button class="code-btn" data-wrap type="button" title="Wrap long lines" aria-label="Wrap long lines">${ICON_WRAP}</button>` +
    `<button class="code-btn" data-copy type="button" title="Copy" aria-label="Copy">${ICON_COPY}${ICON_CHECK}</button>` +
    `</span></div>` +
    `<pre><code class="code${mark}">${body}</code></pre></div>`
  );
}

/** Whether the fence being rendered may become a drawing; an answer still being typed holds its open fence back. */
let drawDiagrams = true;

const ICON_DIAGRAM = SVG('<circle cx="3.5" cy="3.5" r="1.5"/><circle cx="12.5" cy="3.5" r="1.5"/><circle cx="8" cy="12.5" r="1.5"/><path d="M5 3.5h6M4.3 4.8 7 11M11.7 4.8 9 11"/>');

/**
 * A ```` ```mermaid ```` fence. Drawn, it is the drawing; not drawn yet, it is the code with the source on the block so
 * the page can ask for it; refused, it is the code with the reason above it. The code is never lost: it is always one
 * press away, and the copy button gives the source.
 */
function diagramBlock(code: string): string | null {
  const known = drawnFor(code, currentTheme());
  if (known?.ok === true) {
    return (
      `<div class="code-block diagram"><div class="code-head"><span class="code-lang">${ICON_DIAGRAM}<span>Mermaid</span></span>` +
      `<span class="code-actions">` +
      EXPAND("the diagram") +
      `<button class="code-btn" data-source type="button" title="Show the source" aria-label="Show the source">${ICON_CODE}</button>` +
      `<button class="code-btn" data-copy type="button" title="Copy the source" aria-label="Copy the source">${ICON_COPY}${ICON_CHECK}</button>` +
      `</span></div>` +
      `<div class="diagram-body">${known.svg}</div>` +
      `<pre class="diagram-source" hidden><code class="code">${escapeHtml(code)}</code></pre></div>`
    );
  }
  const plain = codeBlock(code, "mermaid");
  if (known?.ok === false) {
    return plain.replace(
      '<div class="code-block">',
      `<div class="code-block diagram-failed" title="${escapeHtml(briefly(known.message))}">`,
    ).replace(
      /<pre>/,
      `<div class="diagram-note">This diagram could not be drawn: ${escapeHtml(briefly(known.message))}</div><pre>`,
    );
  }
  return plain.replace('<div class="code-block">', `<div class="code-block diagram-pending" data-diagram="${escapeHtml(code)}">`);
}

const marked = new Marked({
  gfm: true,
  breaks: true,
  extensions: [strongAnywhere, mathBlock, mathInline],
  renderer: {
    code({ text, lang }: Tokens.Code): string {
      if (drawDiagrams && /^mermaid\b/i.test((lang ?? "").trim())) {
        return diagramBlock(text) ?? codeBlock(text, lang ?? "");
      }
      return codeBlock(text, lang ?? "");
    },

    codespan({ text }: Tokens.Codespan): string {
      const body = `<code>${escapeHtml(text)}</code>`;
      if (/^https?:\/\/\S+$/i.test(text)) {
        return `<a href="${escapeHtml(text)}" data-external="${escapeHtml(text)}" rel="noreferrer">${body}</a>`;
      }
      return isFileReference(text) ? fileLink(text, body) : body;
    },

    html({ text }: Tokens.HTML | Tokens.Tag): string {
      return escapeHtml(text);
    },

    link(this: Renderer, { href, title, tokens }: Tokens.Link): string {
      const label = this.parser.parseInline(tokens);
      const url = href.trim();
      if (EXTERNAL.test(url)) {
        const attr = escapeHtml(url);
        const hint = title ? ` title="${escapeHtml(title)}"` : "";
        return `<a href="${attr}" data-external="${attr}" rel="noreferrer"${hint}>${label}</a>`;
      }
      const otherScheme = /^[a-z][a-z0-9+.-]*:/i.test(url) && !/^[a-z]:[\\/]/i.test(url);
      if (url.startsWith("#") || otherScheme) {
        return label;
      }
      return isFileReference(url) ? fileLink(url, label) : label;
    },

    image({ text }: Tokens.Image): string {
      // A webview with a strict policy loads no pictures from the web, so say what the picture was.
      return `<span class="md-image">${escapeHtml(text || "image")}</span>`;
    },

    table(this: Renderer, token: Tokens.Table): string {
      return `<div class="table-box">${EXPAND("the table").replace("code-btn", "code-btn table-expand")}<div class="table-wrap">${Renderer.prototype.table.call(this, token)}</div></div>`;
    },
  },
});

/** Render an answer. Raw HTML in the text is shown as text, never run. */
export function renderMarkdown(text: string): string {
  return marked.parse(text.replace(/\r\n?/g, "\n"), { async: false }).trimEnd();
}

/**
 * Render an answer that is still arriving. A code fence that has not closed yet is already a coloured block (CommonMark
 * runs it to the end of the text), and the first one or two backticks of the closing fence, which would otherwise show
 * for a moment as the last line of the code, are left out until the third arrives.
 */
export function renderStreaming(text: string): string {
  const source = text.replace(/\r\n?/g, "\n");
  const fences = source.match(/^ {0,3}(?:`{3,}|~{3,})/gm)?.length ?? 0;
  const open = fences % 2 === 1;
  if (!open) {
    return renderMarkdown(source);
  }
  const trimmed = source.replace(/\n {0,3}(?:`{1,2}|~{1,2})$/, "");
  // What comes before the open fence is finished and may hold drawings; the open fence itself is only code until it
  // closes, or the diagram would be drawn, and fail, with every letter typed into it.
  let start = -1;
  for (const match of trimmed.matchAll(/^ {0,3}(?:`{3,}|~{3,})/gm)) {
    start = match.index ?? start;
  }
  if (start <= 0) {
    return renderUndrawn(trimmed);
  }
  const head = renderMarkdown(trimmed.slice(0, start));
  return `${head}\n${renderUndrawn(trimmed.slice(start))}`;
}

function renderUndrawn(text: string): string {
  drawDiagrams = false;
  try {
    return renderMarkdown(text);
  } finally {
    drawDiagrams = true;
  }
}

/** Render one line of Markdown without the paragraph around it. */
export function inline(text: string): string {
  return marked.parseInline(text, { async: false }).trimEnd();
}
