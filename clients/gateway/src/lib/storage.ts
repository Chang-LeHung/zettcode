// Small things kept in the browser: local storage that may be missing or full, and a debounce.

export const storage = {
  get<T>(key: string, fallback: T): T {
    try {
      const raw = localStorage.getItem(`zg.${key}`);
      return raw === null ? fallback : (JSON.parse(raw) as T);
    } catch {
      return fallback;
    }
  },
  set(key: string, value: unknown): void {
    try {
      localStorage.setItem(`zg.${key}`, JSON.stringify(value));
    } catch {
      // A full or blocked store only costs what would have been remembered.
    }
  },
  remove(key: string): void {
    try {
      localStorage.removeItem(`zg.${key}`);
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
