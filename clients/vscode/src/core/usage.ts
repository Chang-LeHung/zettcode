/** What the usage page works out from the ledger: heat levels, streaks and the calendar grid. No editor, no DOM. */

import type { DayTotals } from "../../../typescript/src/types.js";

const DAY_MS = 86_400_000;

/** `YYYY-MM-DD` in the reader's own calendar. */
export function dayKey(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

function parse(day: string): number {
  const [year, month, date] = day.split("-").map(Number);
  return Date.UTC(year ?? 1970, (month ?? 1) - 1, date ?? 1);
}

function format(time: number): string {
  const date = new Date(time);
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  const day = String(date.getUTCDate()).padStart(2, "0");
  return `${date.getUTCFullYear()}-${month}-${day}`;
}

/**
 * A shade from 1 to 4 for each day something was spent, cut at the quartiles of the days that were used, so the palette
 * spreads over a person's own range: someone who spends a million a day and someone who spends a thousand both get dark
 * days and pale ones. This is the terminal's rule.
 */
export function dayLevels(days: DayTotals[]): Map<string, number> {
  const used = days
    .map((entry) => entry.tokens.total_tokens)
    .filter((total) => total > 0)
    .sort((left, right) => left - right);
  const shades = new Map<string, number>();
  if (used.length === 0) {
    return shades;
  }
  const cuts = [1, 2, 3].map((numerator) => used[Math.min(used.length - 1, Math.floor((used.length * numerator) / 4))] ?? 0);
  for (const entry of days) {
    const total = entry.tokens.total_tokens;
    if (total > 0) {
      shades.set(entry.day, 1 + cuts.filter((cut) => total > cut).length);
    }
  }
  return shades;
}

/**
 * The longest run of used days and the run that reaches today. A run still counts when today has not been used yet but
 * yesterday was, so a streak is not reported as broken at midnight, before there was a chance to continue it.
 */
export function streaks(days: DayTotals[], today: string): { longest: number; current: number } {
  const used = new Set(days.filter((entry) => entry.tokens.total_tokens > 0).map((entry) => entry.day));
  const ordered = [...used].sort();
  let longest = 0;
  let run = 0;
  let previous: number | null = null;
  for (const day of ordered) {
    const time = parse(day);
    run = previous !== null && time - previous === DAY_MS ? run + 1 : 1;
    longest = Math.max(longest, run);
    previous = time;
  }
  let current = 0;
  let cursor = parse(today);
  if (!used.has(today)) {
    cursor -= DAY_MS;
  }
  while (used.has(format(cursor))) {
    current += 1;
    cursor -= DAY_MS;
  }
  return { longest, current };
}

export interface Cell {
  day: string;
  tokens: number;
  requests: number;
  input: number;
  output: number;
  /** Input the provider served from its cache. */
  cached: number;
  level: number;
  /** After today: drawn as nothing at all. */
  future: boolean;
}

export interface Calendar {
  /** One column per week, Sunday first, seven cells each. */
  columns: Cell[][];
  /** Which column starts a new month, and what to call it. */
  months: { column: number; name: string }[];
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** The last `weeks` weeks ending with the week of `today`, each day with its shade. */
export function calendar(days: DayTotals[], today: string, weeks: number): Calendar {
  const byDay = new Map(days.map((entry) => [entry.day, entry]));
  const levels = dayLevels(days);
  const now = parse(today);
  const weekday = new Date(now).getUTCDay();
  const start = now - weekday * DAY_MS - (weeks - 1) * 7 * DAY_MS;
  const columns: Cell[][] = [];
  const months: { column: number; name: string }[] = [];
  let lastMonth = -1;
  for (let column = 0; column < weeks; column += 1) {
    const cells: Cell[] = [];
    for (let row = 0; row < 7; row += 1) {
      const time = start + (column * 7 + row) * DAY_MS;
      const key = format(time);
      const entry = byDay.get(key);
      cells.push({
        day: key,
        tokens: entry?.tokens.total_tokens ?? 0,
        requests: entry?.tokens.requests ?? 0,
        input: entry?.tokens.input_tokens ?? 0,
        output: entry?.tokens.output_tokens ?? 0,
        cached: entry?.tokens.cache_read_tokens ?? 0,
        level: levels.get(key) ?? 0,
        future: time > now,
      });
    }
    const first = new Date(start + column * 7 * DAY_MS).getUTCMonth();
    if (first !== lastMonth) {
      months.push({ column, name: MONTHS[first] ?? "" });
      lastMonth = first;
    }
    columns.push(cells);
  }
  // A month name is about three columns wide: one that is followed too soon by the next would be drawn over it.
  const spaced = months.filter((month, index) => {
    const next = months[index + 1];
    return next === undefined || next.column - month.column >= 3;
  });
  return { columns, months: spaced };
}

/** `Mon, Oct 19, 2026` for a `YYYY-MM-DD` key, in the calendar's own days: the same day wherever the reader is. */
export function dayTitle(day: string): string {
  return new Date(parse(day)).toLocaleDateString("en-US", {
    timeZone: "UTC",
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

/** A share as the terminal writes it: one decimal, or a dash when there is nothing to divide. */
export function share(value: number | null): string {
  return value === null ? "—" : `${(value * 100).toFixed(1)}%`;
}

/** A bar's fill, 0 to 1, on a square-root scale, so a small session is still a visible bar beside a huge one. */
export function rootScale(value: number, maximum: number): number {
  if (maximum <= 0 || value <= 0) {
    return 0;
  }
  return Math.min(1, Math.sqrt(value / maximum));
}
