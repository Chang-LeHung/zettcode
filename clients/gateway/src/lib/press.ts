/** A long press on a touch screen, as a messenger opens a message's menu: the finger stays down, nearly still, for a moment. */
export interface Press {
  down(event: PointerEvent): void;
  move(event: PointerEvent): void;
  /** Lift, cancel or leave: no menu any more. */
  end(): void;
  /** Whether a press has just opened the menu, so the `contextmenu` event some browsers add after it is not a second one. */
  recent(): boolean;
}

/** How long a finger must stay down, and how far it may drift (CSS pixels) before it is a scroll or a drag instead. */
export const PRESS_MS = 450;
export const PRESS_SLOP = 10;

/**
 * Call `open` when a touch stays down for {@link PRESS_MS}. A mouse and a pen are left alone: they have a right click, and
 * a double tap is no longer a menu because it also selects a word.
 */
export function longPress(open: (event: PointerEvent) => void, now: () => number = Date.now): Press {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let x = 0;
  let y = 0;
  let firedAt = -Infinity;
  const stop = (): void => {
    if (timer !== undefined) clearTimeout(timer);
    timer = undefined;
  };
  return {
    down(event) {
      stop();
      if (event.pointerType !== "touch" || !event.isPrimary) return;
      x = event.clientX;
      y = event.clientY;
      timer = setTimeout(() => {
        timer = undefined;
        firedAt = now();
        open(event);
      }, PRESS_MS);
    },
    move(event) {
      if (timer !== undefined && Math.hypot(event.clientX - x, event.clientY - y) > PRESS_SLOP) stop();
    },
    end: stop,
    recent: () => now() - firedAt < 1000,
  };
}
