/** A long press on a touch screen, as a messenger opens a message's menu: the finger stays down, nearly still, for a moment. */
export interface Press {
  down(event: PointerEvent): void;
  move(event: PointerEvent): void;
  /** Lift, cancel or leave: no menu any more. */
  end(): void;
  /**
   * Whether the last press opened the menu, so the `contextmenu` event some browsers add after it (however late) is not a
   * second one. It stays set until the next pointer goes down, which is also what a mouse's right click does first.
   */
  recent(): boolean;
}

/** How long a finger must stay down, and how far it may drift (CSS pixels) before it is a scroll or a drag instead. */
export const PRESS_MS = 450;
export const PRESS_SLOP = 10;

/**
 * Call `open` when a touch stays down for {@link PRESS_MS}. A mouse and a pen are left alone: they have a right click, and
 * a double tap is no longer a menu because it also selects a word. A change of the page's text selection while the finger
 * is down means the system has begun selecting (a press on text does that on iOS), so the press is dropped rather than
 * opening a menu under the system's own.
 */
export function longPress(open: (event: PointerEvent) => void): Press {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let x = 0;
  let y = 0;
  let fired = false;
  const watching = typeof document !== "undefined";
  const stop = (): void => {
    if (timer !== undefined) clearTimeout(timer);
    timer = undefined;
    if (watching) document.removeEventListener("selectionchange", stop);
  };
  return {
    down(event) {
      stop();
      fired = false;
      if (event.pointerType !== "touch" || !event.isPrimary) return;
      x = event.clientX;
      y = event.clientY;
      if (watching) document.addEventListener("selectionchange", stop);
      timer = setTimeout(() => {
        stop();
        fired = true;
        open(event);
      }, PRESS_MS);
    },
    move(event) {
      if (timer !== undefined && Math.hypot(event.clientX - x, event.clientY - y) > PRESS_SLOP) stop();
    },
    end: stop,
    recent: () => fired,
  };
}
