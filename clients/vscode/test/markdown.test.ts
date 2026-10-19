import assert from "node:assert/strict";
import test from "node:test";

import { highlightedLanguages, resolveLanguage } from "../src/core/highlight.js";
import { isFileReference, renderMarkdown } from "../src/core/markdown.js";

const strong = (html: string): string[] =>
  [...html.matchAll(/<strong>(.*?)<\/strong>/g)].map((match) => match[1] ?? "");

test("bold works next to Chinese text and punctuation, where CommonMark gives up", () => {
  assert.deepEqual(strong(renderMarkdown("这是**“引号”**后面")), ["“引号”"]);
  assert.deepEqual(strong(renderMarkdown("先**读完代码**再动手")), ["读完代码"]);
  assert.deepEqual(strong(renderMarkdown("结果：**成功（已验证）**。")), ["成功（已验证）"]);
  assert.deepEqual(strong(renderMarkdown("**只在第一个事件发出前重试**；一旦发出就不再重试")), ["只在第一个事件发出前重试"]);
  assert.deepEqual(strong(renderMarkdown("日本語の**強調**です")), ["強調"]);
});

test("bold can hold code, links and emphasis, and survives a code span that holds stars", () => {
  const withCode = renderMarkdown("改 **`pyproject.toml` 的配置**，然后跑 `make test`");
  const [inner] = strong(withCode);
  assert.ok(inner?.includes("<code>pyproject.toml</code>") && inner.endsWith("的配置"));
  assert.ok(withCode.includes("<code>make test</code>"));
  assert.ok(renderMarkdown("**[docs](https://example.com)**").includes("<strong><a"));
  assert.ok(renderMarkdown("**a *b* c**").includes("<strong>a <em>b</em> c</strong>"));
  assert.equal(strong(renderMarkdown("run `a**b**c` now")).length, 0);
});

test("stars that do not hug text are left alone", () => {
  assert.equal(strong(renderMarkdown("2 ** 3 ** 4")).length, 0);
  assert.equal(strong(renderMarkdown("a ** b")).length, 0);
  assert.equal(strong(renderMarkdown("**")).length, 0);
});

test("the mainstream languages are coloured, whatever name the fence uses", () => {
  const names = [
    "python", "py", "javascript", "js", "jsx", "typescript", "ts", "tsx", "java", "kotlin", "scala", "go", "golang",
    "rust", "rs", "ruby", "rb", "c", "cpp", "c++", "csharp", "cs", "php", "swift", "objectivec", "dart", "lua", "perl",
    "r", "julia", "haskell", "elixir", "erlang", "clojure", "ocaml", "fsharp", "bash", "sh", "zsh", "shell",
    "powershell", "sql", "json", "jsonc", "yaml", "yml", "toml", "ini", "xml", "html", "vue", "css", "scss", "less",
    "markdown", "md", "diff", "patch", "dockerfile", "makefile", "nginx", "latex", "tex", "protobuf", "graphql",
    "vim", "cmake", "gradle", "groovy", "dos", "bat",
  ];
  for (const name of names) {
    assert.ok(resolveLanguage(name) !== null, `${name} has no colours`);
  }
  assert.ok(highlightedLanguages().length >= 60);
  assert.equal(resolveLanguage("klingon"), null);
  assert.equal(resolveLanguage(""), null);
});

test("code is coloured by token, and the text itself is escaped", () => {
  const python = renderMarkdown("```python\ndef add(a, b):\n    return a + b  # <sum>\n```");
  assert.ok(python.includes('<span class="hljs-keyword">def</span>'));
  assert.ok(python.includes("hljs-comment"));
  assert.ok(python.includes("&lt;sum&gt;"));
  const rust = renderMarkdown('```rust\nfn main() { println!("hi"); }\n```');
  assert.ok(rust.includes('<span class="hljs-keyword">fn</span>'));
  const latex = renderMarkdown("```latex\n\\begin{equation} E = mc^2 \\end{equation}\n```");
  assert.ok(latex.includes("hljs-"));
  const json = renderMarkdown('```json\n{"a": 1, "b": [true, null]}\n```');
  assert.ok(json.includes("hljs-attr") && json.includes("hljs-number"));
});

test("an unknown or missing language still makes a code block, with nothing coloured", () => {
  const plain = renderMarkdown("```\nls <dir>\n```");
  assert.ok(plain.includes("code-block") && plain.includes("ls &lt;dir&gt;") && !plain.includes("hljs-"));
  const odd = renderMarkdown("```klingon\nnuqneH\n```");
  assert.ok(odd.includes("klingon") && odd.includes("nuqneH") && !odd.includes("hljs-"));
});

test("a fence that is still being written renders as code, so streaming never flickers into prose", () => {
  const open = renderMarkdown("Here:\n\n```ts\nconst a = 1;\nconst b =");
  assert.ok(open.includes("code-block"));
  assert.ok(open.includes("const"));
});

test("tables render with alignment, inline markup and an overflow wrapper", () => {
  const html = renderMarkdown(
    "| 名称 | 说明 | 数量 |\n| :--- | :---: | ---: |\n| **粗体** | `code` | 3 |\n| [链接](https://example.com) | ~~删除~~ | 40 |",
  );
  assert.ok(html.includes('<div class="table-wrap"><table>'));
  assert.ok(html.includes("<th"));
  assert.ok(html.includes("align=\"center\"") || html.includes("text-align"));
  assert.ok(html.includes("<strong>粗体</strong>"));
  assert.ok(html.includes("<code>code</code>"));
  assert.ok(html.includes("<del>删除</del>"));
  assert.ok(html.includes('data-external="https://example.com"'));
});

test("task lists, nested lists, ordered lists, rules and quotes render", () => {
  const html = renderMarkdown("- [x] done\n- [ ] todo\n  - nested\n\n1. one\n2. two\n\n---\n\n> a\n> b");
  assert.ok(html.includes('type="checkbox"'));
  assert.ok(html.includes("<ol>"));
  assert.equal((html.match(/<ul>/g) ?? []).length, 2);
  assert.ok(html.includes("<hr>"));
  assert.ok(html.includes("<blockquote>"));
});

test("a domain with a path is an address, not a file to open", () => {
  for (const address of ["openrouter.ai/api/v1", "api.moonshot.ai/anthropic", "localhost:11434", "https://x.dev/a", "github.com/a/b"]) {
    assert.equal(isFileReference(address), false, address);
    assert.ok(!renderMarkdown(`call \`${address}\` now`).includes("data-open"), address);
  }
  for (const file of ["src/a.ts", "src/a.ts:12", "pyproject.toml", "./run.sh", "docs/guide/index.md", "tool_images.py:9"]) {
    assert.equal(isFileReference(file), true, file);
  }
  assert.ok(renderMarkdown("`https://example.com/x`").includes('data-external="https://example.com/x"'));
});

test("raw HTML, scripts and unsafe links never run", () => {
  const html = renderMarkdown('<img src=x onerror="alert(1)"> <script>alert(1)</script> [a](javascript:alert(1)) ![p](http://e.com/p.png)');
  assert.ok(!html.includes("<img"));
  assert.ok(!html.includes("<script"));
  assert.ok(!html.includes('href="javascript:'));
  assert.ok(html.includes("md-image"));
  assert.ok(html.includes("&lt;img"));
});

const mathOf = (html: string): string[] => [...html.matchAll(/<math[ >]/g)].map((match) => match[0]);

test("formulas are typeset in all four spellings, inline or on their own line", () => {
  const inline = renderMarkdown("能量 $E = mc^2$ 与 \\(a^2 + b^2\\) 相等");
  assert.equal(mathOf(inline).length, 2);
  assert.ok(inline.includes('class="math-inline"'));
  assert.ok(!inline.includes("$E"), "the dollar signs are consumed");

  const block = renderMarkdown("公式：\n\n$$\n\\int_0^1 x^2\\,dx = \\frac{1}{3}\n$$\n\n完。");
  assert.equal(mathOf(block).length, 1);
  assert.ok(block.includes('class="math-display"'));
  assert.ok(block.includes("<p>完。</p>"));

  const bracket = renderMarkdown("\\[\n\\sum_{i=1}^{n} i\n\\]");
  assert.ok(bracket.includes('class="math-display"') && mathOf(bracket).length === 1);

  const middle = renderMarkdown("见 $$x^2$$ 这里");
  assert.ok(middle.includes('class="math-display"'));
});

test("prices, shell variables and code are never read as formulas", () => {
  assert.equal(mathOf(renderMarkdown("它卖 $5 和 $6，共 $11")).length, 0);
  assert.equal(mathOf(renderMarkdown("It costs $5 and then $10.")).length, 0);
  assert.equal(mathOf(renderMarkdown("`$x$` and `$HOME and $PATH`")).length, 0);
  assert.equal(mathOf(renderMarkdown("```sh\necho $HOME $$ $PATH\n```")).length, 0);
  assert.equal(mathOf(renderMarkdown("a \\$x\\$ b")).length, 0);
  assert.equal(mathOf(renderMarkdown("price: $ 5 $")).length, 0);
});

test("a formula KaTeX cannot read shows its source and leaves the rest of the answer alone", () => {
  const html = renderMarkdown("前 $\\frac{1}{$ 后 $x^2$");
  assert.ok(html.includes("math-error"), html);
  assert.ok(html.includes("前") && html.includes("后"));
  assert.equal(mathOf(html).length, 1);
  // A formula that asks to run something, or to load a link, is plain text, never a live element.
  const unsafe = renderMarkdown("$\\href{javascript:alert(1)}{x}$ $\\includegraphics{a.png}$");
  assert.ok(!/<a[ >]/.test(unsafe) && !/<img/.test(unsafe) && !/href=/.test(unsafe), unsafe);
});
