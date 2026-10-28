import assert from "node:assert/strict";
import { test } from "node:test";
import "./dom-setup";
import { normalizeMath } from "../src/lib/mathdelims";
import { renderMarkdown } from "../src/lib/render";

test("code is highlighted in the language it names, and an unknown language is escaped text", () => {
  const known = renderMarkdown("```python\ndef f(): return 1\n```");
  const unknown = renderMarkdown("```nonsense\n<b>x</b>\n```");

  assert.match(known, /hljs-keyword/);
  assert.match(unknown, /&lt;b&gt;x&lt;\/b&gt;/);
  assert.doesNotMatch(unknown, /<b>/);
});

test("math in either notation is typeset", () => {
  assert.match(renderMarkdown("$E=mc^2$"), /katex/);
  assert.match(renderMarkdown("\\(a^2\\)"), /katex/);
  assert.match(renderMarkdown("\\[x\\]"), /katex-display/);
});

test("the shapes KaTeX draws as inline svg survive the sanitizer", () => {
  assert.match(renderMarkdown("$\\sqrt{x}$"), /<svg/i);
  assert.match(renderMarkdown("$\\xrightarrow{f}$"), /<svg/i);
});

test("the svg profile lets KaTeX's drawings through and nothing that runs", () => {
  const html = renderMarkdown(
    '<svg><script>alert(1)</script><foreignObject><body onload="alert(1)"></body></foreignObject>' +
      '<a xlink:href="javascript:alert(1)"><text>x</text></a><use href="data:image/svg+xml,x"/></svg>',
  );

  assert.doesNotMatch(html, /<script|onload|javascript:|foreignObject|<use/i);
});

test("math delimiters inside code are left alone", () => {
  assert.equal(normalizeMath("`\\(x\\)`"), "`\\(x\\)`");
  assert.match(renderMarkdown("```\n\\(x\\)\n```"), /\\\(x\\\)/);
});

test("markup a message carries does not survive", () => {
  const html = renderMarkdown('<img src=x onerror="alert(1)"> <script>alert(1)</script> [a](javascript:alert(1))');

  assert.doesNotMatch(html, /onerror|<script|javascript:/i);
});

test("links open in a new tab without handing over the opener", () => {
  assert.match(renderMarkdown("[a](https://x.dev)"), /target="_blank" rel="noopener noreferrer"/);
});
