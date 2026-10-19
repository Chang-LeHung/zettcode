import assert from "node:assert/strict";
import test from "node:test";

import { JSDOM } from "jsdom";

import type { Totals, WorkspaceUsage } from "../../typescript/src/types.js";
import { CALENDAR_WEEKS, PAGE_CSS, usagePage } from "../src/core/usage-page.js";
import { dayTitle } from "../src/core/usage.js";

const spent = (input: number, output: number, cached: number, requests: number): Totals => ({
  requests,
  input_tokens: input,
  output_tokens: output,
  cache_read_tokens: cached,
  reasoning_tokens: 0,
  total_tokens: input + output,
  cache_share: input > 0 ? cached / input : null,
});

// 2026-10-19 is a Monday.
const NOW = new Date(2026, 9, 19, 12);
const usage: WorkspaceUsage = {
  sessions: [],
  models: [],
  days: [
    { day: "2026-10-19", tokens: spent(1_100_000, 124_000, 733_000, 100) },
    { day: "2026-10-12", tokens: spent(400, 100, 0, 1) },
  ],
  total: spent(1_100_400, 124_100, 733_000, 101),
};

const calendarOf = (): Document => new JSDOM(usagePage(usage, NOW).body).window.document;

test("a day is named by its weekday, and the same wherever the reader is", () => {
  assert.equal(dayTitle("2026-10-19"), "Mon, Oct 19, 2026");
  assert.equal(dayTitle("2025-11-08"), "Sat, Nov 8, 2025");
  assert.equal(dayTitle("2026-01-01"), "Thu, Jan 1, 2026");
});

test("hovering a day shows that day's date, tokens, input and output, requests and cached share", () => {
  const cells = Array.from(calendarOf().querySelectorAll<HTMLElement>("#body-calendar .days .cell-day[data-tip]"));
  const busy = cells.find((cell) => cell.dataset.tip?.startsWith("Mon, Oct 19, 2026"));
  assert.ok(busy, "today is in the calendar");
  assert.deepEqual(busy.dataset.tip?.split("\n"), [
    "Mon, Oct 19, 2026",
    "1.2M tokens · ↑ 1.1M · ↓ 124k",
    "100 requests · 66.6% cached",
  ]);
  const quiet = cells.find((cell) => cell.dataset.tip?.startsWith("Mon, Oct 12, 2026"));
  assert.deepEqual(quiet?.dataset.tip?.split("\n"), ["Mon, Oct 12, 2026", "500 tokens · ↑ 400 · ↓ 100", "1 request · 0.0% cached"]);
  const idle = cells.find((cell) => cell.dataset.tip?.startsWith("Tue, Oct 13, 2026"));
  assert.deepEqual(idle?.dataset.tip?.split("\n"), ["Tue, Oct 13, 2026", "Nothing spent"]);
});

test("every day up to today has a box, a day after today has none, and the slow native title is gone", () => {
  const document = calendarOf();
  const days = Array.from(document.querySelectorAll<HTMLElement>("#body-calendar .days .cell-day"));
  assert.equal(days.length, CALENDAR_WEEKS * 7);
  const future = days.filter((cell) => cell.classList.contains("future"));
  assert.ok(future.length > 0 && future.every((cell) => cell.dataset.tip === undefined));
  assert.equal(days.filter((cell) => !cell.classList.contains("future") && cell.dataset.tip === undefined).length, 0);
  assert.equal(days.filter((cell) => cell.hasAttribute("title")).length, 0);
  // The legend's squares are not days.
  assert.equal(document.querySelectorAll("#body-calendar .legend [data-tip]").length, 0);
});

test("the box opens away from the nearest edge, so no day's figures are cut off", () => {
  const columns = Array.from(calendarOf().querySelectorAll<HTMLElement>("#body-calendar .days .cell-day[data-tip]"));
  const byClass = (name: string) => columns.filter((cell) => cell.classList.contains(name));
  assert.ok(byClass("tip-start").length > 0 && byClass("tip-mid").length > 0 && byClass("tip-end").length > 0);
  // Every shown day has exactly one horizontal and one vertical placement.
  for (const cell of columns) {
    assert.equal(["tip-start", "tip-mid", "tip-end"].filter((name) => cell.classList.contains(name)).length, 1);
    assert.equal(["tip-below", "tip-above"].filter((name) => cell.classList.contains(name)).length, 1);
  }
  // The top rows open downward and the bottom rows upward: a box above the first row has no room.
  const first = columns[0]!;
  const last = columns.at(-1)!;
  assert.ok(first.classList.contains("tip-start") && first.classList.contains("tip-below"));
  assert.ok(last.classList.contains("tip-end"));
  assert.ok(columns.some((cell) => cell.classList.contains("tip-above")));
});

test("the box is drawn by CSS from the day's own text, with no script", () => {
  assert.ok(/\.cell-day\[data-tip\]:hover::after\s*\{[^}]*content:\s*attr\(data-tip\)/.test(PAGE_CSS));
  assert.ok(/white-space:\s*pre/.test(PAGE_CSS), "the three lines stay three lines");
  assert.ok(/pointer-events:\s*none/.test(PAGE_CSS), "the box never takes the pointer from the day");
  assert.equal(new JSDOM(usagePage(usage, NOW).body).window.document.querySelectorAll("script").length, 0);
});
