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

export function closeSheet(id: number, value?: unknown): void {
  const at = sheets.findIndex((entry) => entry.id === id);
  if (at < 0) return;
  const [entry] = sheets.splice(at, 1);
  entry?.settle(value);
}

export function closeTopSheet(): boolean {
  const top = sheets[sheets.length - 1];
  if (!top) return false;
  closeSheet(top.id);
  return true;
}
