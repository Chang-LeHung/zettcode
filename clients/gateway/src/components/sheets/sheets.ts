// Opening the two sheets almost every view uses: a question with two answers, and a list of actions.

import { openSheet } from "../../stores/ui";
import type { IconName } from "../common/icons";
import ConfirmSheet from "./ConfirmSheet.vue";
import MenuSheet from "./MenuSheet.vue";

export interface MenuEntry {
  icon: IconName;
  label: string;
  run: () => void;
  danger?: boolean;
  /** The entry is where the person already is (a section they are in): drawn in the accent colour. */
  current?: boolean;
}

/** Ask a question. Resolves true only when the person chose the action; with `run`, only when the action then succeeded. */
export async function confirmAction(options: { title: string; text: string; ok: string; danger?: boolean; run?: () => Promise<void> }): Promise<boolean> {
  const answer = await openSheet<boolean>(options.title, ConfirmSheet, {
    text: options.text,
    ok: options.ok,
    danger: options.danger ?? false,
    run: options.run,
  });
  return answer === true;
}

/** Open a menu. Resolves when the sheet is gone, so a caller that opened it from a control can put focus back there. */
export async function showMenu(title: string, items: (MenuEntry | false | null | undefined)[]): Promise<void> {
  await openSheet(title, MenuSheet, { items: items.filter((item): item is MenuEntry => Boolean(item)) });
}
