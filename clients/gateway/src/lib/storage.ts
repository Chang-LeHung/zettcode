// Small things kept in the browser: local storage that may be missing or full, and a debounce. In the desktop app the
// keys are scoped to the active server, so preferences and drafts from one gateway are not offered to another.

let prefix = "zg.";

/** Point storage at one server's keys; `""` is the page served by a gateway (and the app's server picker). */
export function useScope(id: string): void {
  prefix = id ? `zg.${id}.` : "zg.";
}

export const storage = {
  get<T>(key: string, fallback: T): T {
    try {
      const raw = localStorage.getItem(`${prefix}${key}`);
      return raw === null ? fallback : (JSON.parse(raw) as T);
    } catch {
      return fallback;
    }
  },
  /** A value about this device, not one server; `prefs` uses it for theme, language and the avatar. */
  getGlobal<T>(key: string, fallback: T): T {
    try {
      const raw = localStorage.getItem(`zg.${key}`);
      return raw === null ? fallback : (JSON.parse(raw) as T);
    } catch {
      return fallback;
    }
  },
  setGlobal(key: string, value: unknown): void {
    try {
      localStorage.setItem(`zg.${key}`, JSON.stringify(value));
    } catch {
      // A full or blocked store only costs what would have been remembered.
    }
  },
  set(key: string, value: unknown): void {
    try {
      localStorage.setItem(`${prefix}${key}`, JSON.stringify(value));
    } catch {
      // A full or blocked store only costs what would have been remembered.
    }
  },
  remove(key: string): void {
    try {
      localStorage.removeItem(`${prefix}${key}`);
    } catch {
      // Nothing to forget.
    }
  },
  clear(): void {
    try {
      for (const key of Object.keys(localStorage)) if (key.startsWith("zg.")) localStorage.removeItem(key);
    } catch {
      // Nothing to forget.
    }
  },
};

export function debounce<A extends unknown[]>(fn: (...args: A) => void, ms: number): (...args: A) => void {
  let timer: ReturnType<typeof setTimeout> | undefined;
  return (...args: A) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}
