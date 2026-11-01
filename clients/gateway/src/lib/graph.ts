// The geometry and the small rules of the Graph page: where the sessions sit, how an edge bends, the outline of a group,
// where a tooltip may go. Plain numbers in and out, no DOM, so every one of them can be tested.

export interface Point {
  x: number;
  y: number;
}

export interface Size {
  width: number;
  height: number;
}

/** A quadratic curve: the ends and the one control point that bends it. */
export interface Curve {
  a: Point;
  c: Point;
  b: Point;
}

/** An order that does not depend on the locale, so every browser lays the same ids out the same way. */
export function byId(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

/** The key of an unordered pair. */
export function pairKey(a: string, b: string): string {
  return byId(a, b) <= 0 ? `${a}\u0000${b}` : `${b}\u0000${a}`;
}

/**
 * Put the ids on a circle, in id order, the first at twelve o'clock. The order is the ids' own and not the order they
 * arrived in, so a session that joins takes its place in the ring and every other one only slides along it.
 */
export function layoutCircle(
  ids: readonly string[],
  size: Size,
  margin = 88,
  inset: { top: number; bottom: number } = { top: 0, bottom: 0 },
): Map<string, Point> {
  const sorted = [...new Set(ids)].sort(byId);
  const out = new Map<string, Point>();
  // The ring is drawn in the room that is left once the bars at the top and the bottom have taken theirs, so no node is
  // under one of them.
  const room = Math.max(0, size.height - inset.top - inset.bottom);
  const cx = size.width / 2;
  const cy = inset.top + room / 2;
  const radius = Math.max(0, Math.min(size.width, room) / 2 - margin);
  sorted.forEach((id, index) => {
    if (sorted.length === 1) {
      out.set(id, { x: cx, y: cy });
      return;
    }
    const angle = -Math.PI / 2 + (index / sorted.length) * Math.PI * 2;
    out.set(id, { x: cx + Math.cos(angle) * radius, y: cy + Math.sin(angle) * radius });
  });
  return out;
}

/** The curve from `from` to `to`. Its bend does not depend on which end is which, so two ways along a pair share a line. */
export function edgeCurve(idFrom: string, from: Point, idTo: string, to: Point, bend = 0.16): Curve {
  const forward = byId(idFrom, idTo) <= 0;
  const p = forward ? from : to;
  const q = forward ? to : from;
  const dx = q.x - p.x;
  const dy = q.y - p.y;
  return { a: from, b: to, c: { x: (p.x + q.x) / 2 - dy * bend, y: (p.y + q.y) / 2 + dx * bend } };
}

export function curvePoint(curve: Curve, t: number): Point {
  const u = 1 - t;
  return {
    x: u * u * curve.a.x + 2 * u * t * curve.c.x + t * t * curve.b.x,
    y: u * u * curve.a.y + 2 * u * t * curve.c.y + t * t * curve.b.y,
  };
}

/** `steps + 1` points along the curve, the ends included. */
export function sampleCurve(curve: Curve, steps: number): Point[] {
  const n = Math.max(1, Math.floor(steps));
  return Array.from({ length: n + 1 }, (_, i) => curvePoint(curve, i / n));
}

export function curvePath(curve: Curve): string {
  const f = (n: number): string => (Math.round(n * 100) / 100).toString();
  return `M${f(curve.a.x)} ${f(curve.a.y)}Q${f(curve.c.x)} ${f(curve.c.y)} ${f(curve.b.x)} ${f(curve.b.y)}`;
}

export function distance(a: Point, b: Point): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

/** The convex hull (Andrew's monotone chain), without the points that lie along an edge. */
export function convexHull(points: readonly Point[]): Point[] {
  const sorted = [...points].sort((p, q) => p.x - q.x || p.y - q.y);
  const unique = sorted.filter((p, i) => i === 0 || p.x !== sorted[i - 1]!.x || p.y !== sorted[i - 1]!.y);
  if (unique.length < 3) return unique;
  const cross = (o: Point, a: Point, b: Point): number => (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
  const lower: Point[] = [];
  for (const p of unique) {
    while (lower.length >= 2 && cross(lower[lower.length - 2]!, lower[lower.length - 1]!, p) <= 0) lower.pop();
    lower.push(p);
  }
  const upper: Point[] = [];
  for (const p of [...unique].reverse()) {
    while (upper.length >= 2 && cross(upper[upper.length - 2]!, upper[upper.length - 1]!, p) <= 0) upper.pop();
    upper.push(p);
  }
  lower.pop();
  upper.pop();
  return [...lower, ...upper];
}

/** The outline of a rounded blob that holds a disc of radius `pad` around each centre: the hull of circles. */
export function roundedHull(centers: readonly Point[], pad: number, steps = 24): Point[] {
  const cloud: Point[] = [];
  for (const c of centers) {
    for (let i = 0; i < steps; i += 1) {
      const angle = (i / steps) * Math.PI * 2;
      cloud.push({ x: c.x + Math.cos(angle) * pad, y: c.y + Math.sin(angle) * pad });
    }
  }
  return convexHull(cloud);
}

export function polygonPath(points: readonly Point[]): string {
  if (!points.length) return "";
  const f = (n: number): string => (Math.round(n * 10) / 10).toString();
  return `M${points.map((p) => `${f(p.x)} ${f(p.y)}`).join("L")}Z`;
}

export function centroid(points: readonly Point[]): Point {
  if (!points.length) return { x: 0, y: 0 };
  return {
    x: points.reduce((sum, p) => sum + p.x, 0) / points.length,
    y: points.reduce((sum, p) => sum + p.y, 0) / points.length,
  };
}

/** The point of a polygon furthest along `direction`: where a label sits on the outer side of a group. */
export function supportPoint(polygon: readonly Point[], direction: Point): Point {
  let best = polygon[0] ?? { x: 0, y: 0 };
  let score = -Infinity;
  for (const p of polygon) {
    const s = p.x * direction.x + p.y * direction.y;
    if (s > score) {
      score = s;
      best = p;
    }
  }
  return best;
}

/** Where the label of a group goes: on the hull, out from the middle of the ring (straight up for a group in the middle). */
export function hullLabelAnchor(polygon: readonly Point[], members: readonly Point[], middle: Point): Point {
  const c = centroid(members);
  const dx = c.x - middle.x;
  const dy = c.y - middle.y;
  const length = Math.hypot(dx, dy);
  const direction = length < 1 ? { x: 0, y: -1 } : { x: dx / length, y: dy / length };
  return supportPoint(polygon, direction);
}

/** Where a tooltip of `card` size goes for a pointer at `anchor`: beside it, flipped when it would leave `view`, and kept in. */
export function clampTooltip(anchor: Point, card: Size, view: Size, offset = 14, margin = 8): Point {
  let left = anchor.x + offset;
  if (left + card.width > view.width - margin) left = anchor.x - offset - card.width;
  let top = anchor.y + offset;
  if (top + card.height > view.height - margin) top = anchor.y - offset - card.height;
  const fit = (value: number, size: number, room: number): number =>
    Math.max(margin, Math.min(value, room - size - margin));
  return { x: fit(left, card.width, view.width), y: fit(top, card.height, view.height) };
}

/** A group's hue, 0..359, the same for the same name everywhere. */
export function hueOfName(name: string): number {
  let value = 7;
  for (const char of name) value = (value * 33 + (char.codePointAt(0) ?? 0)) >>> 0;
  return (value * 137) % 360;
}

const EDGE_HALF_LIFE = 20 * 60;

/** How an edge looks: thicker for more messages, fainter the longer ago the last one was. */
export function edgeStyle(count: number, last: number, now: number): { width: number; opacity: number } {
  const width = Math.min(4, 1 + Math.log2(1 + Math.max(0, count)) * 0.55);
  const age = Math.max(0, now - last);
  const opacity = Math.max(0.22, 0.8 * Math.pow(0.5, age / EDGE_HALF_LIFE));
  return { width, opacity };
}

export function easeInOut(t: number): number {
  const x = Math.max(0, Math.min(1, t));
  return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
}

/** One step of an exponential glide from `current` towards `target` over `dt` seconds. */
export function approach(current: number, target: number, dt: number, rate = 9): number {
  const next = current + (target - current) * (1 - Math.exp(-rate * dt));
  return Math.abs(target - next) < 0.2 ? target : next;
}

/** A text on one line, cut to `max` characters. */
export function preview(text: string, max: number): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, Math.max(0, max - 1)).trimEnd()}…` : flat;
}
