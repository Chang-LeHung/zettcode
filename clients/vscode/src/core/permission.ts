/** How the shell permission a person chose becomes the policy one prompt runs under. */

import type { ApprovalPolicy, Permission } from "../../../typescript/src/types.js";

/**
 * Map a permission level to the approval policy of the next run.
 *
 * `ask` and `safe` both defer to the server: `ask` puts each command to the reader, and `safe` runs every command
 * in the operating-system sandbox, so the server never raises an approval for it. `deny` and `full` answer before
 * the stream opens, so no approval event is sent at all. `auto`, the old name of `full`, is read as `full`.
 */
export function approvalsFor(permission: Permission | "auto"): ApprovalPolicy {
  switch (permission) {
    case "deny":
      return { mode: "deny" };
    case "full":
    case "auto":
      return { mode: "auto" };
    default:
      return { mode: "ask" };
  }
}
