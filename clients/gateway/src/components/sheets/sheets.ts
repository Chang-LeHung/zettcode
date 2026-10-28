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
}

/** Ask a question. Resolves true only when the person chose the action. */
export async function confirmAction(options: { title: string; text: string; ok: string; danger?: boolean }): Promise<boolean> {
  const answer = await openSheet<boolean>(options.title, ConfirmSheet, {
    text: options.text,
    ok: options.ok,
    danger: options.danger ?? false,
  });
  return answer === true;
}

export function showMenu(title: string, items: (MenuEntry | false | null | undefined)[]): void {
  void openSheet(title, MenuSheet, { items: items.filter((item): item is MenuEntry => Boolean(item)) });
}
