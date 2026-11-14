// Where the window may go. The shell is only a server list (`app://-/`) and the gateway's own page, which is loaded
// at the gateway's origin like in a browser, so the page's cookie, fetches and socket are its ordinary same-origin
// ones. These rules are plain functions so they are tested without Electron.

export const ORIGIN = "app://-/";

export type Verdict = "allow" | "external" | "deny";

function originOf(url: string): string | null {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.origin : null;
  } catch {
    return null;
  }
}

/**
 * Decide what a navigation of the window does.
 *
 * The list may open any http(s) server (that is what choosing one is); a server's page may stay on its own origin,
 * and a link to anywhere else leaves for the system browser, so a page cannot turn the window into a browser.
 */
export function decide(current: string, target: string): Verdict {
  if (target.startsWith(ORIGIN)) return "allow";
  const to = originOf(target);
  if (to === null) return "deny";
  if (current.startsWith(ORIGIN)) return "allow";
  return originOf(current) === to ? "allow" : "external";
}

/** A link a page opens in a new window: only web addresses, and always in the system browser. */
export function opensExternally(target: string): boolean {
  return originOf(target) !== null;
}
