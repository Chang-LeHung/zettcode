// Times and sizes the way a chat writes them.

const TIME = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" });
const WEEKDAY = new Intl.DateTimeFormat(undefined, { weekday: "short" });
const DATE = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });

function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

/** A time as a chat list writes it: the hour today, the weekday this week, the date after that. */
export function listTime(seconds: number, now: Date = new Date()): string {
  if (!seconds) return "";
  const then = new Date(seconds * 1000);
  const days = Math.round((startOfDay(now) - startOfDay(then)) / 86_400_000);
  if (days <= 0) return TIME.format(then);
  if (days < 7) return WEEKDAY.format(then);
  return DATE.format(then);
}

export function clockTime(milliseconds: number): string {
  return TIME.format(new Date(milliseconds));
}

/** How long something has lasted, in the short form a row has room for: `45s`, `8m`, `2h 05m`, `3d`. */
export function duration(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  if (total < 60) return `${total}s`;
  const minutes = Math.floor(total / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours}h ${String(minutes % 60).padStart(2, "0")}m`;
  return `${Math.floor(hours / 24)}d`;
}

/** The last part of a path: the folder a session works in. */
export function folderName(path: string): string {
  const parts = path.split("/").filter(Boolean);
  return parts[parts.length - 1] ?? "";
}

/** A path with the home directory written as `~`, when it is under it. */
export function shortPath(path: string, home = ""): string {
  if (home && (path === home || path.startsWith(`${home}/`))) return `~${path.slice(home.length)}`;
  return path;
}

export function tokens(count: number): string {
  if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(count % 1_000_000 ? 1 : 0)}M`;
  if (count >= 1_000) return `${(count / 1_000).toFixed(count % 1_000 ? 1 : 0)}K`;
  return String(count);
}
