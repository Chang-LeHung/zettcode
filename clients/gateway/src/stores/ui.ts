// Things that float above a page: the toasts, and the sheets (a bottom sheet on a phone, a dialog on a desktop).
// A sheet is a component with a title; opening one returns a promise that is settled when it closes.

import { markRaw, reactive, type Component } from "vue";

export interface Toast {
  id: number;
  text: string;
  kind: "" | "bad";
}

export interface SheetEntry {
  id: number;
  title: string;
  component: Component;
  props: Record<string, unknown>;
  settle: (value: unknown) => void;
  /** An action in the sheet is under way. */
  busy?: boolean;
}

export const toasts = reactive<Toast[]>([]);
export const sheets = reactive<SheetEntry[]>([]);

let counter = 0;

export function toast(text: string, kind: Toast["kind"] = ""): void {
  const id = ++counter;
  toasts.push({ id, text, kind });
  setTimeout(
    () => {
      const at = toasts.findIndex((item) => item.id === id);
      if (at >= 0) toasts.splice(at, 1);
    },
    kind === "bad" ? 6000 : 3200,
  );
}

/** Open a sheet. The promise resolves with what the sheet closed with, or `undefined` if it was dismissed. */
export function openSheet<R = undefined>(title: string, component: Component, props: Record<string, unknown> = {}) {
  return new Promise<R | undefined>((resolve) => {
    sheets.push({
      id: ++counter,
      title,
      component: markRaw(component),
      props,
      settle: (value) => resolve(value as R | undefined),
    });
  });
}

/** A sheet with an action under way says so, and is then not dismissed (Escape, the backdrop, the ✕) until it is done. */
export function setSheetBusy(id: number, busy: boolean): void {
  const entry = sheets.find((item) => item.id === id);
  if (entry) entry.busy = busy;
}

export function closeSheet(id: number, value?: unknown): void {
  const at = sheets.findIndex((entry) => entry.id === id);
  if (at < 0) return;
  // Only the sheet itself answers while it is busy: a dismissal would report "no" for something that is still happening.
  if (value === undefined && sheets[at]?.busy) return;
  const [entry] = sheets.splice(at, 1);
  entry?.settle(value);
}

export function closeTopSheet(): boolean {
  const top = sheets[sheets.length - 1];
  if (!top) return false;
  closeSheet(top.id);
  return true;
}

/** A full-screen or otherwise closable layer that is not a sheet, with the order it was opened in. */
const overlays: { id: number; close: () => void }[] = [];

/** Register a layer's close; returns the function that takes it off the stack. */
export function openOverlay(close: () => void): () => void {
  const entry = { id: ++counter, close };
  overlays.push(entry);
  return () => {
    const at = overlays.indexOf(entry);
    if (at >= 0) overlays.splice(at, 1);
  };
}

/** Close whichever is newest, a sheet or an overlay; say whether anything was closed. */
export function closeTopOverlay(): boolean {
  const sheet = sheets[sheets.length - 1];
  const overlay = overlays[overlays.length - 1];
  if (!sheet && !overlay) return false;
  if (sheet && (!overlay || sheet.id > overlay.id)) {
    closeSheet(sheet.id);
    return true;
  }
  overlays.pop()?.close();
  return true;
}
