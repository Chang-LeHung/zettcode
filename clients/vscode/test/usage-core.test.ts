import assert from "node:assert/strict";
import test from "node:test";

import type { DayTotals, Totals } from "../../typescript/src/types.js";
import { calendar, dayLevels, rootScale, share, streaks } from "../src/core/usage.js";

const totals = (tokens: number): Totals => ({
  requests: 1,
  input_tokens: tokens,
  output_tokens: 0,
  cache_read_tokens: 0,
  reasoning_tokens: 0,
  total_tokens: tokens,
  cache_share: null,
});

const days = (spec: Record<string, number>): DayTotals[] =>
  Object.entries(spec).map(([day, tokens]) => ({ day, tokens: totals(tokens) }));

test("shades are the quartiles of the days that were used, and an unused day has none", () => {
  const shades = dayLevels(
    days({
      "2026-10-01": 1,
      "2026-10-02": 2,
      "2026-10-03": 3,
      "2026-10-04": 4,
      "2026-10-05": 5,
      "2026-10-06": 6,
      "2026-10-07": 7,
      "2026-10-08": 8,
      "2026-10-09": 0,
    }),
  );
  assert.equal(shades.get("2026-10-01"), 1);
  assert.equal(shades.get("2026-10-08"), 4);
  assert.equal(shades.has("2026-10-09"), false);
  assert.ok([...shades.values()].every((level) => level >= 1 && level <= 4));
  assert.equal(dayLevels([]).size, 0);
});

test("a streak survives a morning that has not been used yet", () => {
  const spent = days({ "2026-10-15": 5, "2026-10-16": 5, "2026-10-17": 5, "2026-10-10": 5, "2026-10-11": 5 });
  assert.deepEqual(streaks(spent, "2026-10-18"), { longest: 3, current: 3 });
  assert.deepEqual(streaks(spent, "2026-10-17"), { longest: 3, current: 3 });
  assert.deepEqual(streaks(spent, "2026-10-20"), { longest: 3, current: 0 });
  assert.deepEqual(streaks([], "2026-10-18"), { longest: 0, current: 0 });
});

test("a streak counts across a month end", () => {
  const spent = days({ "2026-09-29": 1, "2026-09-30": 1, "2026-10-01": 1, "2026-10-02": 1 });
  assert.deepEqual(streaks(spent, "2026-10-02"), { longest: 4, current: 4 });
});

test("the calendar is weeks of Sunday-first columns ending in today's week", () => {
  // 2026-10-19 is a Monday.
  const grid = calendar(days({ "2026-10-19": 100, "2026-10-12": 50 }), "2026-10-19", 4);
  assert.equal(grid.columns.length, 4);
  assert.ok(grid.columns.every((week) => week.length === 7));
  const last = grid.columns[3]!;
  assert.equal(last[0]!.day, "2026-10-18");
  assert.equal(last[1]!.day, "2026-10-19");
  assert.equal(last[1]!.tokens, 100);
  assert.equal(last[1]!.future, false);
  assert.equal(last[2]!.future, true);
  assert.equal(grid.columns[2]![1]!.tokens, 50);
  assert.deepEqual(grid.months, [{ column: 1, name: "Oct" }]);
});

test("a month name that the next month would be drawn over is left out", () => {
  // 30 weeks back from 2026-10-19 starts on 2026-03-29: March has one column before April begins.
  const grid = calendar([], "2026-10-19", 30);
  assert.deepEqual(
    grid.months.map((month) => month.name).slice(0, 3),
    ["Apr", "May", "Jun"],
  );
  const columns = grid.months.map((month) => month.column);
  assert.ok(columns.every((column, index) => index === 0 || column - columns[index - 1]! >= 3));
});

test("a bar on a square-root scale keeps a small value visible and a share keeps a decimal", () => {
  assert.equal(rootScale(25, 100), 0.5);
  assert.equal(rootScale(0, 100), 0);
  assert.equal(rootScale(500, 100), 1);
  assert.equal(share(0.6667), "66.7%");
  assert.equal(share(null), "—");
});
