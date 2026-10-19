/**
 * Remembering the shell permission a reader chose. The server holds it only in memory, so it falls back to the
 * configured one whenever the server restarts, and the reader would have to pick `safe` or `auto` again for every
 * window. The extension keeps the choice itself: per session, and as the last choice for a session that has none.
 */

import type { Permission } from "../../../typescript/src/types.js";

const LEVELS: readonly string[] = ["deny", "ask", "safe", "auto"];

/** What is kept in the workspace's state. */
export interface RememberedPermissions {
  /** The permission each session was last set to, by session id. */
  bySession: Record<string, Permission>;
  /** The last permission chosen in this workspace. */
  last?: Permission;
}

/** The most sessions remembered; the oldest are forgotten first. */
export const REMEMBERED_SESSIONS = 200;

function valid(value: unknown): value is Permission {
  return typeof value === "string" && LEVELS.includes(value);
}

/** Read what was stored, ignoring anything that is not a permission level (an old or hand-edited value). */
export function readRemembered(stored: unknown): RememberedPermissions {
  const out: RememberedPermissions = { bySession: {} };
  if (typeof stored !== "object" || stored === null) {
    return out;
  }
  const record = stored as { bySession?: unknown; last?: unknown };
  if (typeof record.bySession === "object" && record.bySession !== null) {
    for (const [id, value] of Object.entries(record.bySession)) {
      if (valid(value)) {
        out.bySession[id] = value;
      }
    }
  }
  if (valid(record.last)) {
    out.last = record.last;
  }
  return out;
}

/** Record a choice for a session. Setting it again moves the session to the newest end, so the oldest go first. */
export function remember(
  current: RememberedPermissions,
  sessionId: string | null,
  permission: Permission,
): RememberedPermissions {
  const bySession = { ...current.bySession };
  if (sessionId !== null) {
    delete bySession[sessionId];
    bySession[sessionId] = permission;
  }
  const ids = Object.keys(bySession);
  for (const id of ids.slice(0, Math.max(0, ids.length - REMEMBERED_SESSIONS))) {
    delete bySession[id];
  }
  return { bySession, last: permission };
}

/**
 * The permission a session should run with: the one it was last set to, else the last one chosen in this workspace,
 * else `null` (leave the server's own). A level the server does not offer is not wanted.
 */
export function wantedPermission(
  current: RememberedPermissions,
  sessionId: string | null,
  offered: readonly string[],
): Permission | null {
  const own = sessionId === null ? undefined : current.bySession[sessionId];
  const wanted = own ?? current.last;
  return wanted !== undefined && offered.includes(wanted) ? wanted : null;
}
