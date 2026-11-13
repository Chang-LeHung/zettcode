// Pull down on a list to read it again, as a phone's lists do. The arithmetic is here, apart from the DOM, so it is tested.

/** How far the indicator must be drawn down (not how far the finger went: that is twice this) before letting go refreshes. */
export const THRESHOLD = 64;
/** The most the indicator is drawn pulled, however far the finger goes. */
export const MAX_PULL = 96;
/** A pull is the finger moving down this many times more than sideways, so a swipe along a row is not one. */
const STEEPNESS = 1.5;

export interface Pull {
  /** How far the indicator is drawn down, 0 when nothing is being pulled. */
  distance: number;
  /** Letting go now would refresh. */
  ready: boolean;
}

/** The indicator for a finger that moved ``dy`` down and ``dx`` across from where it landed; ``null`` is no pull. */
export function pullOf(dy: number, dx: number, scrollTop: number): Pull | null {
  if (scrollTop > 0 || dy <= 0 || dy < Math.abs(dx) * STEEPNESS) return null;
  // Resistance: the indicator follows the finger at half speed, so it feels pulled against something.
  const distance = Math.min(MAX_PULL, dy / 2);
  return { distance, ready: distance >= THRESHOLD };
}

export interface PullHandlers {
  change(pull: Pull | null): void;
  refresh(): Promise<void> | void;
}

/**
 * Attach the gesture to a scrolling element; returns a function that removes it. Only a touch that starts with the list
 * scrolled to its top is a pull, so scrolling up the list never refreshes it. A mouse never pulls.
 */
export function attachPull(el: HTMLElement, handlers: PullHandlers): () => void {
  let startY = 0;
  let startX = 0;
  let tracking = false;
  let busy = false;
  let last: Pull | null = null;

  const set = (pull: Pull | null): void => {
    last = pull;
    handlers.change(pull);
  };

  const onStart = (event: TouchEvent): void => {
    tracking = !busy && el.scrollTop <= 0 && event.touches.length === 1;
    if (!tracking) return;
    startY = event.touches[0]!.clientY;
    startX = event.touches[0]!.clientX;
  };

  const onMove = (event: TouchEvent): void => {
    if (!tracking) return;
    const touch = event.touches[0]!;
    const pull = pullOf(touch.clientY - startY, touch.clientX - startX, el.scrollTop);
    if (!pull) {
      if (last) set(null);
      return;
    }
    // The page must not scroll or bounce under a pull that is being drawn.
    if (event.cancelable) event.preventDefault();
    set(pull);
  };

  const onEnd = async (): Promise<void> => {
    if (!tracking) return;
    tracking = false;
    const fire = last?.ready === true;
    if (!fire) {
      set(null);
      return;
    }
    busy = true;
    set({ distance: THRESHOLD / 2, ready: true });
    try {
      await handlers.refresh();
    } finally {
      busy = false;
      set(null);
    }
  };

  const onCancel = (): void => {
    tracking = false;
    if (last) set(null);
  };

  el.addEventListener("touchstart", onStart, { passive: true });
  el.addEventListener("touchmove", onMove, { passive: false });
  el.addEventListener("touchend", onEnd);
  el.addEventListener("touchcancel", onCancel);
  return () => {
    el.removeEventListener("touchstart", onStart);
    el.removeEventListener("touchmove", onMove);
    el.removeEventListener("touchend", onEnd);
    el.removeEventListener("touchcancel", onCancel);
  };
}
