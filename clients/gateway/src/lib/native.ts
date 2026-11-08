// The small bridge between the page and the desktop shell: where the server list is kept, and what the platform can
// do that a browser cannot. Electron installs `window.__zettcodeNative` from its preload script; a page served by a
// gateway, and the Android shell's remote gateway page, has no such object and stays web.

import type { StoredServers } from "./servers";

export interface NativeBridge {
  /** The servers this device remembers, and the one it used last; the store's own shape, parsed by the caller. */
  loadServers(): Promise<unknown>;
  /** Keep them; the shell encrypts the token with the platform's own key store. */
  saveServers(state: StoredServers): Promise<void>;
  /** A notice from the conversation, where the platform has one of its own. */
  notify?(title: string, body: string): void;
}

declare global {
  interface Window {
    __zettcodeNative?: NativeBridge;
  }
}

/** The desktop shell's bridge, or `null` for a page that no shell carries. */
export function nativeBridge(): NativeBridge | null {
  if (typeof window === "undefined") return null;
  return window.__zettcodeNative ?? null;
}
