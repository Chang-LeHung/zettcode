import assert from "node:assert/strict";
import test from "node:test";

import { JSDOM } from "jsdom";

import type { Totals, WorkspaceUsage } from "../../typescript/src/types.js";
import { PAGE_CSS, usagePage } from "../src/core/usage-page.js";

const totals = (input: number, output: number, cached: number, reasoning: number): Totals => ({
  requests: 3,
  input_tokens: input,
  output_tokens: output,
  cache_read_tokens: cached,
  reasoning_tokens: reasoning,
  total_tokens: input + output,
  cache_share: input > 0 ? cached / input : null,
});

const usage = (models: { model: string; tokens: Totals }[]): WorkspaceUsage => ({
  sessions: [],
  models,
  days: [],
  total: totals(1000, 100, 500, 40),
});

const pageOf = (data: WorkspaceUsage): Document => new JSDOM(usagePage(data).body).window.document;

test("a model's input bar dims the part the cache served, and its output bar the part spent thinking", () => {
  const document = pageOf(usage([{ model: "deepseek-flash", tokens: totals(1000, 200, 750, 50) }]));
  const dim = (selector: string): string | undefined =>
    document.querySelector(`#body-models ${selector} .fill i.dim`)?.getAttribute("style") ?? undefined;
  const rows = Array.from(document.querySelectorAll("#body-models .line"));
  assert.equal(rows.length, 2);
  assert.ok(rows[0]!.querySelector(".fill i.dim")?.getAttribute("style")?.includes("width:75.0%"), "75% of the input was cached");
  assert.ok(rows[1]!.querySelector(".fill i.dim")?.getAttribute("style")?.includes("width:25.0%"), "25% of the output was reasoning");
  assert.equal(dim(".nothing"), undefined);
  // The key says what the dimmed parts mean.
  assert.ok(document.querySelector("#body-models .key")?.textContent?.includes("cached"));
  assert.ok(document.querySelector("#body-models .key")?.textContent?.includes("reasoning"));
});

test("nothing cached or reasoned draws no dimmed part, and a single model's bars are full", () => {
  const document = pageOf(usage([{ model: "m", tokens: totals(100, 10, 0, 0) }]));
  assert.equal(document.querySelectorAll("#body-models .fill i.dim").length, 0);
  for (const fill of Array.from(document.querySelectorAll("#body-models .fill"))) {
    assert.ok(fill.getAttribute("style")?.includes("width:100.0%"));
  }
});

test("no rule styles a bare .in or .out: those names are the bars' own, and a page-wide rule shoved them sideways", () => {
  // The summary line once used `.in` and `.out`, which also matched the bars' `fill in` and `fill out` and gave them a
  // margin, so every bar began with a stub of empty track.
  const bare = [...PAGE_CSS.matchAll(/(^|\n|\})\s*\.(in|out)\s*\{/g)];
  assert.equal(bare.length, 0, "a bare .in or .out rule");
  const rule = /\.fill\.(?:in|out)[^{]*\{([^}]*)\}/g;
  for (const match of PAGE_CSS.matchAll(rule)) {
    assert.ok(!/margin|padding/.test(match[1] ?? ""), "a bar's fill has no margin of its own");
  }
});
