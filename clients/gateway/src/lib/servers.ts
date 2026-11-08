// The servers an app remembers, and the rules a new one has to pass before it is kept. Nothing here touches Vue,
// storage or the network, so a test can read every case without a window.

import { normalizeBaseUrl } from "../api/connection";

export interface ServerProfile {
  id: string;
  /** What the list calls it; the host when the person typed no name. */
  name: string;
  /** The gateway's origin, without a trailing slash. */
  url: string;
  /** The gateway's token, kept by the app's secure storage and never by the page's own store. */
  token: string;
}

export interface StoredServers {
  servers: ServerProfile[];
  /** The id of the server that was last used, or "" when the app should ask. */
  active: string;
  /** Why the store could not be read, when it could not; the list is then empty rather than silently replaced. */
  error?: string;
}

export const NO_SERVERS: StoredServers = { servers: [], active: "" };

/** A new id for a profile. A browser without `randomUUID` (an old WebView) still gets one that does not collide. */
export function newId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/**
 * Read what the store answered, keeping only what a server profile is.
 *
 * The store is a file the app owns, but a damaged one must open the server list rather than stop the app: a field of
 * the wrong kind is dropped, and an active id that names no kept server is forgotten.
 */
export function parseStored(raw: unknown): StoredServers {
  if (raw === null || raw === undefined || raw === "") return { ...NO_SERVERS };
  const source = typeof raw === "string" ? safeJson(raw) : raw;
  if (!isObject(source)) return damaged();
  const servers: ServerProfile[] = [];
  const seen = new Set<string>();
  for (const entry of Array.isArray(source.servers) ? source.servers : []) {
    if (!isObject(entry)) continue;
    const { id, name, url, token } = entry;
    if (typeof id !== "string" || typeof name !== "string" || typeof url !== "string" || typeof token !== "string") {
      continue;
    }
    if (!id || seen.has(id)) continue;
    let normalized: string;
    try {
      normalized = normalizeBaseUrl(url);
    } catch {
      continue;
    }
    seen.add(id);
    servers.push({ id, name, url: normalized, token });
  }
  const active = typeof source.active === "string" && seen.has(source.active) ? source.active : "";
  const error = typeof source.error === "string" ? source.error : !Array.isArray(source.servers) ? "unreadable" : "";
  return { servers, active, ...(error ? { error } : {}) };
}

/** Build a profile from what a form holds; a message key is translated where it is shown. */
export function makeProfile(input: { name: string; url: string; token: string }, id = newId()): ServerProfile {
  const url = normalizeBaseUrl(input.url);
  const token = input.token.trim();
  if (!token) throw new Error("The gateway's token is required");
  const name = input.name.trim() || new URL(url).host;
  return { id, name, url, token };
}

function damaged(): StoredServers {
  return { ...NO_SERVERS, error: "unreadable" };
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return null;
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
