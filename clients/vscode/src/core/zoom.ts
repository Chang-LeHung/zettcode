/** The arithmetic of the lightbox: how big a picture starts, and where it goes when it is zoomed or dragged. */

/** Where the content is: its scale, and how far its centre lies from the centre of the stage, in pixels. */
export interface View {
  scale: number;
  x: number;
  y: number;
}

export const MIN_SCALE = 0.1;
export const MAX_SCALE = 16;

/** Each press of + or − multiplies the scale by this. */
export const STEP = 1.25;

/** The room left around the content when it is fitted: a margin and the toolbar. */
export const MARGIN = 32;

export function clampScale(scale: number): number {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale));
}

/**
 * The scale that makes content of `width` × `height` fit in a stage of `room`. A raster picture is not blown up past its
 * own size (it would only blur); a drawing is, up to `cap` times, because it stays sharp.
 */
export function fitScale(width: number, height: number, roomW: number, roomH: number, cap = 1): number {
  if (width <= 0 || height <= 0 || roomW <= 0 || roomH <= 0) {
    return 1;
  }
  const fit = Math.min((roomW - MARGIN * 2) / width, (roomH - MARGIN * 2) / height);
  return clampScale(Math.min(cap, Math.max(fit, MIN_SCALE)));
}

export function fitted(scale: number): View {
  return { scale, x: 0, y: 0 };
}

/**
 * Zoom by `factor` keeping the point under the pointer where it is. `px` and `py` are the pointer's distance from the
 * centre of the stage, which is also the origin of `x` and `y`.
 */
export function zoomAt(view: View, factor: number, px: number, py: number): View {
  const scale = clampScale(view.scale * factor);
  const ratio = scale / view.scale;
  return { scale, x: px - (px - view.x) * ratio, y: py - (py - view.y) * ratio };
}

/** The size a drawing declares: the last two numbers of its `viewBox`, or its width and height; `null` if neither. */
export function drawingSize(svg: string): { width: number; height: number } | null {
  const box = /viewBox\s*=\s*"\s*[-\d.e]+[\s,]+[-\d.e]+[\s,]+([\d.e]+)[\s,]+([\d.e]+)\s*"/i.exec(svg);
  if (box?.[1] !== undefined && box[2] !== undefined) {
    const width = Number(box[1]);
    const height = Number(box[2]);
    if (width > 0 && height > 0) {
      return { width, height };
    }
  }
  const w = /<svg[^>]*\swidth\s*=\s*"([\d.]+)(?:px)?"/i.exec(svg)?.[1];
  const h = /<svg[^>]*\sheight\s*=\s*"([\d.]+)(?:px)?"/i.exec(svg)?.[1];
  return w !== undefined && h !== undefined && Number(w) > 0 && Number(h) > 0 ? { width: Number(w), height: Number(h) } : null;
}

/** "125%" for a scale of 1.25. */
export function percent(scale: number): string {
  return `${Math.round(scale * 100)}%`;
}
