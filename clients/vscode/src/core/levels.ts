/** What the reasoning levels and shell permissions look like: one place for their words, ranks, icons and tones. */

import type { Permission } from "../../../typescript/src/types.js";

export interface EffortMeta {
  /** 0 to 5 pips lit. */
  level: number;
  /** The one-line note the terminal shows beside the name. */
  note: string;
  /** `plain`, or `flow` / `aurora` for the two levels that move. */
  motion: "plain" | "flow" | "aurora";
  /** A CSS tone name from the palette. */
  tone: string;
}

const EFFORTS: Record<string, EffortMeta> = {
  off: { level: 0, note: "No deliberate reasoning", motion: "plain", tone: "faint" },
  minimal: { level: 1, note: "A token of thought, fastest", motion: "plain", tone: "sky" },
  low: { level: 1, note: "Quick answers", motion: "plain", tone: "teal" },
  medium: { level: 2, note: "The default balance", motion: "plain", tone: "green" },
  high: { level: 3, note: "More thought on hard problems", motion: "plain", tone: "amber" },
  xhigh: { level: 4, note: "A long think on hard problems", motion: "plain", tone: "orange" },
  max: { level: 5, note: "The highest budget the provider takes", motion: "flow", tone: "rose" },
  ultra: { level: 5, note: "Above max; a provider maps it down when it must", motion: "aurora", tone: "green" },
};

/**
 * Describe one level. A name the table does not know (a provider's own) is placed by its position among the
 * levels offered, so a custom list still reads from least to most.
 */
export function effortMeta(name: string, index = 0, total = 1): EffortMeta {
  const known = EFFORTS[name.toLowerCase()];
  if (known !== undefined) {
    return known;
  }
  const level = total <= 1 ? 2 : Math.round((index / (total - 1)) * 5);
  return { level, note: "", motion: "plain", tone: level >= 4 ? "orange" : level >= 2 ? "green" : "teal" };
}

export interface PermissionMeta {
  icon: string;
  tone: string;
  /** How loudly the level should read: the more a command can do unasked, the louder. */
  risk: 0 | 1 | 2 | 3;
}

const PERMISSIONS: Record<Permission, PermissionMeta> = {
  deny: { icon: "ban", tone: "rose", risk: 0 },
  ask: { icon: "hand", tone: "amber", risk: 1 },
  safe: { icon: "shield-check", tone: "teal", risk: 2 },
  auto: { icon: "bolt", tone: "orange", risk: 3 },
};

export function permissionMeta(permission: string): PermissionMeta {
  return PERMISSIONS[permission as Permission] ?? { icon: "shield", tone: "faint", risk: 1 };
}
