// Where this page talks to, and who it says it is. The page served by a gateway leaves both empty and keeps using
// cookies at its own address; the desktop and mobile apps fill them in and carry the token on every request.

export interface ConnectionConfig {
  /** The gateway's address, without a trailing slash; empty means the address this page was served from. */
  baseUrl: string;
  /** The token the app carries as a bearer; empty in the page, which is signed in by its cookie. */
  token: string;
}

/** The one connection every API call reads. It is a plain object so the API layer needs no Vue and no store. */
export const connection: ConnectionConfig = { baseUrl: "", token: "" };

/** Point the API layer at a gateway; called once at start and again when a server is chosen. */
export function configure(next: Partial<ConnectionConfig>): void {
  Object.assign(connection, next);
}

/** The absolute address of a path the gateway serves, or the path itself for the page that was served by it. */
export function apiUrl(path: string): string {
  return connection.baseUrl ? `${connection.baseUrl}${path}` : path;
}

/** The headers that carry the token, when there is one. A page in the browser has none and uses its cookie. */
export function authorization(): Record<string, string> {
  return connection.token ? { authorization: `Bearer ${connection.token}` } : {};
}

/**
 * Read a server address as the one origin the gateway is served from.
 *
 * The gateway's routes are at the root of its address, so a path is refused rather than silently dropped: a page at
 * `https://host/gateway/` would call `/api` above it and fail in a way that looks like a broken server.
 */
export function normalizeBaseUrl(value: string): string {
  let url: URL;
  try {
    url = new URL(value.trim());
  } catch {
    throw new Error("Write the address as http://host:port");
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error("The address starts with http:// or https://");
  }
  if (url.username || url.password) {
    throw new Error("The address cannot carry a user name or a password");
  }
  if (!/^\/+$/.test(url.pathname)) {
    throw new Error("The gateway is served at the root of its address, without a path");
  }
  if (url.hash) throw new Error("Leave the #token=... off the address; the token goes in the Token field");
  if (url.search) throw new Error("The address cannot carry a query");
  return url.origin;
}

/** The token as a WebSocket protocol name: base64url is made of the characters a protocol name may hold. */
export function tokenProtocol(token: string): string {
  const bytes = new TextEncoder().encode(token);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return `zettcode.token.${btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "")}`;
}
