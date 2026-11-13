import assert from "node:assert/strict";
import { test } from "node:test";
import { dayName, sameDay } from "../src/lib/day";

const at = (y: number, m: number, d: number, h = 12) => new Date(y, m - 1, d, h).getTime();

test("two moments are the same day by the calendar, not by 24 hours", () => {
  assert.ok(sameDay(at(2026, 11, 12, 0), at(2026, 11, 12, 23)));
  assert.ok(!sameDay(at(2026, 11, 12, 23), at(2026, 11, 13, 1)));
});

test("a day is today, yesterday, a weekday within the week, or a date", () => {
  const now = at(2026, 11, 12, 1);
  assert.deepEqual(dayName(at(2026, 11, 12, 0), now), { kind: "today" });
  assert.deepEqual(dayName(at(2026, 11, 11, 23), now), { kind: "yesterday" }, "an hour of difference can be another day");
  assert.equal(dayName(at(2026, 11, 8), now, "en-US").kind, "weekday");
  assert.equal(dayName(at(2026, 11, 5), now, "en-US").kind, "date", "a week back is a date");
});

test("a date from another year says the year, and one from this year does not", () => {
  const now = at(2026, 11, 12);
  const here = dayName(at(2026, 3, 1), now, "en-US");
  const there = dayName(at(2025, 3, 1), now, "en-US");
  assert.ok(here.kind === "date" && !here.text.includes("2026"));
  assert.ok(there.kind === "date" && there.text.includes("2025"));
});
