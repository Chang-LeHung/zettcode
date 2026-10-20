/** The arithmetic of the message rail: when its bars are too close to tell apart, and how they are grouped then. */

/** Messages that one bar stands for when the bars would otherwise touch. */
export const GROUP = 10;

/** Pixels the rail gives each bar when there is room. */
export const ROW_PITCH = 11;

/** The share of the view's height the rail may take. */
export const RAIL_SHARE = 0.72;

/** Bars closer than this (in pixels, centre to centre) cannot be aimed at with a pointer. */
export const MIN_PITCH = 6;

/** How tall the rail is for this many bars in a view this high: a bar's own room, or the share of the view. */
export function railHeight(bars: number, viewport: number): number {
  return Math.min(bars * ROW_PITCH, viewport * RAIL_SHARE);
}

/**
 * Whether one bar per message would be too close: more than one group of messages, and a view that leaves each less
 * than {@link MIN_PITCH}. A view whose height is not known (not laid out yet) is never dense.
 */
export function isDense(count: number, viewport: number): boolean {
  return viewport > 0 && count > GROUP && railHeight(count, viewport) / count < MIN_PITCH;
}

/** A run of messages one bar stands for: `first` to `last`, both inclusive. */
export interface Unit {
  first: number;
  last: number;
}

/** The bars of the rail: one for each message, or one for each group of ten when `dense`. */
export function unitsOf(count: number, dense: boolean): Unit[] {
  const size = dense ? GROUP : 1;
  const units: Unit[] = [];
  for (let first = 0; first < count; first += size) {
    units.push({ first, last: Math.min(count, first + size) - 1 });
  }
  return units;
}

/** Where the list of a group's messages starts so that it lies beside its bar and stays inside the view. */
export function popupTop(centre: number, height: number, viewport: number, margin = 8): number {
  const room = Math.max(0, viewport - height - margin);
  return Math.max(margin, Math.min(centre - height / 2, room));
}
