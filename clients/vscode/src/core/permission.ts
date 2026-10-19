/** How the shell permission a person chose becomes the policy one prompt runs under. */

import type { ApprovalPolicy, Permission } from "../../../typescript/src/types.js";

/**
 * Map a permission level to the approval policy of the next run.
 *
 * `ask` and `safe` both defer to the server, which knows which commands are read-only; `deny` and `auto` answer
 * before the stream opens, so no approval event is sent at all.
 */
export function approvalsFor(permission: Permission): ApprovalPolicy {
  switch (permission) {
    case "deny":
      return { mode: "deny" };
    case "auto":
      return { mode: "auto" };
    default:
      return { mode: "ask" };
  }
}
