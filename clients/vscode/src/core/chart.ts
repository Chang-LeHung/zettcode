/** Donut geometry for the context and usage charts: exact percentages, readable tiny slices. */

import { escapeHtml } from "./format.js";

export interface DonutItem {
  name: string;
  value: number;
  /** A CSS tone name: green, teal, gold, blue, violet, red or muted. */
  tone: string;
}

export interface DonutSlice extends DonutItem {
  /** The exact share of the total, one decimal. */
  percent: number;
  /** The share drawn in the ring; tiny slices are raised to a visible minimum. */
  visualPercent: number;
  /** The circle's stroke pattern, ready for `stroke-dasharray`. */
  dasharray: string;
  /** Where the segment starts, ready for `stroke-dashoffset`. */
  dashoffset: string;
}

export interface DonutResult {
  slices: DonutSlice[];
  total: number;
  /** Whether at least one slice was enlarged, so the page can say so. */
  expanded: boolean;
}

export interface DonutOptions {
  /** The smallest drawn share in percent; exact percentages are never changed. */
  minPercent?: number;
  radius?: number;
  /** A gap between slices, in the SVG's units. */
  gap?: number;
}

export interface DonutSvgOptions {
  size?: number;
  radius?: number;
  stroke?: number;
  className?: string;
  label?: string;
}

const TONES = new Set(["green", "teal", "gold", "blue", "violet", "red", "muted"]);

/**
 * Turn values into ring segments.
 *
 * Tiny slices are raised to `minPercent` for drawing and the whole ring is then scaled back to 100%, so the picture
 * stays a ring even when one source is 0.1%. The exact percentages stay in `percent`, which is what the legend says.
 */
export function donutSlices(items: DonutItem[], options: DonutOptions = {}): DonutResult {
  const positive = items.filter((item) => item.value > 0 && Number.isFinite(item.value));
  const total = positive.reduce((sum, item) => sum + item.value, 0);
  if (positive.length === 0 || total <= 0) {
    return { slices: [], total: 0, expanded: false };
  }
  const minPercent = Math.max(0, options.minPercent ?? 1.5);
  const radius = Math.max(1, options.radius ?? 52);
  const gap = Math.max(0, options.gap ?? 2.5);
  const raw = positive.map((item) => (item.value / total) * 100);
  const raised = raw.map((percent) => Math.max(percent, minPercent));
  const raisedTotal = raised.reduce((sum, percent) => sum + percent, 0);
  const visual = raised.map((percent) => (percent / raisedTotal) * 100);
  const circumference = 2 * Math.PI * radius;
  let cursor = 0;
  const slices = positive.map((item, index) => {
    const share = visual[index] ?? 0;
    const length = (circumference * share) / 100;
    const cut = Math.min(gap, length / 3);
    const visible = Math.max(0, length - cut);
    const slice: DonutSlice = {
      ...item,
      percent: round1(raw[index] ?? 0),
      visualPercent: round1(share),
      dasharray: `${visible.toFixed(2)} ${(circumference - visible).toFixed(2)}`,
      dashoffset: `${(-cursor).toFixed(2)}`,
    };
    cursor += length;
    return slice;
  });
  const expanded = raw.some((percent, index) => (visual[index] ?? 0) > percent + 0.05);
  return { slices, total, expanded };
}

/** Render a donut result as inline SVG; the center is left for the caller's label. */
export function donutSvg(result: DonutResult, options: DonutSvgOptions = {}): string {
  const size = Math.max(8, options.size ?? 120);
  const radius = Math.max(1, options.radius ?? 52);
  const stroke = Math.max(1, options.stroke ?? 10);
  const center = size / 2;
  const className = options.className ?? "donut";
  const label = options.label ?? "Share of the total";
  const slices = result.slices
    .map((slice, index) => {
      const tone = TONES.has(slice.tone) ? slice.tone : "muted";
      return `<circle class="donut-slice tone-${tone}" data-slice="${index}" cx="${center}" cy="${center}" r="${radius}" stroke-width="${stroke}" stroke-dasharray="${slice.dasharray}" stroke-dashoffset="${slice.dashoffset}" transform="rotate(-90 ${center} ${center})"><title>${escapeHtml(
        slice.name,
      )}: ${slice.percent}%</title></circle>`;
    })
    .join("");
  return `<svg class="${escapeHtml(className)}" viewBox="0 0 ${size} ${size}" role="img" aria-label="${escapeHtml(
    label,
  )}"><circle class="donut-track" cx="${center}" cy="${center}" r="${radius}" stroke-width="${stroke}"></circle>${slices}</svg>`;
}

/** Round to one decimal, without a pointless `.0`. */
export function round1(value: number): number {
  return Math.round(value * 10) / 10;
}
