/** Turning a context report into the rows and the ring the composition card draws. */

import type { ContextReport } from "../../../typescript/src/types.js";
import { donutSlices, type DonutResult } from "../core/chart.js";

export interface ContextRow {
  name: string;
  tokens: number;
  items: number;
  tone: string;
  /** Not known until a request has been sent (environment notes, tool schemas). */
  pending: boolean;
  /** Its slice in the ring, or `null` when it has none. */
  slice?: number | null;
  /** Its exact share of the ring, in percent. */
  percent?: number | null;
}

/** One colour per source, so a source keeps its colour from the legend to the ring. */
export function contextTone(name: string): string {
  switch (name) {
    case "System prompt":
      return "green";
    case "Environment notes":
      return "teal";
    case "Tool schemas":
      return "amber";
    case "User messages":
      return "blue";
    case "Assistant messages":
      return "violet";
    case "Tool output":
      return "red";
    default:
      return "muted";
  }
}

/** The sources in the order a request is assembled; the terminal lists them the same way. */
const SOURCES = [
  "System prompt",
  "Environment notes",
  "Tool schemas",
  "User messages",
  "Assistant messages",
  "Tool output",
  "Compaction summary",
];

/** The two only an assembled request carries: until one has been sent they are unknown, not zero. */
const FROM_THE_REQUEST = ["Environment notes", "Tool schemas"];

/**
 * One row per source. Every row is a share of what was counted, so the shares add up to the whole ring; when the
 * provider reported the request's size, the tokens shown are that total divided by those shares, as in the terminal.
 * A source that is not known yet says so ("pending") instead of being folded into a catch-all row.
 */
export function contextRows(report: ContextReport): { rows: ContextRow[]; ring: DonutResult } {
  const measured = report.shares.reduce((sum, share) => sum + share.tokens, 0);
  const scale = report.from_provider && !report.partial && measured > 0 ? report.used / measured : 1;
  const known = new Map(report.shares.map((share) => [share.name, share]));
  const rows: ContextRow[] = [];
  for (const name of SOURCES) {
    const share = known.get(name);
    if (share === undefined) {
      if (report.partial && FROM_THE_REQUEST.includes(name)) {
        rows.push({ name, tokens: 0, items: 0, tone: contextTone(name), pending: true });
      }
      continue;
    }
    rows.push({ name, tokens: Math.round(share.tokens * scale), items: share.items, tone: contextTone(name), pending: false });
  }
  const drawn = rows.filter((row) => !row.pending && row.tokens > 0);
  const ring = donutSlices(
    drawn.map((row) => ({ name: row.name, value: row.tokens, tone: row.tone })),
    { minPercent: 1.2, radius: 52, gap: 3 },
  );
  let slice = 0;
  for (const row of rows) {
    row.slice = !row.pending && row.tokens > 0 ? slice++ : null;
    row.percent = row.slice === null ? null : (ring.slices[row.slice]?.percent ?? 0);
  }
  return { rows, ring };
}

/** How full the window is, in percent, never outside 0–100 and not rounded: the thresholds read it exactly. */
export function contextPercent(report: ContextReport): number {
  return report.window > 0 ? Math.max(0, Math.min(100, (report.used / report.window) * 100)) : 0;
}

/** A percentage as the card shows it: one decimal, and `<0.1` for a little that would otherwise read as nothing. */
export function formatPercent(value: number): string {
  if (value > 0 && value < 0.05) {
    return "<0.1";
  }
  return value.toFixed(1);
}
