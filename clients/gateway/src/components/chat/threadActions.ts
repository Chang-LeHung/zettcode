// What can be done with a thread from its header: the menu, and each action in it.

import { gateway } from "../../api/gateway";
import { ApiError } from "../../api/http";
import { t } from "../../i18n";
import { copyText } from "../../lib/clipboard";
import { go } from "../../stores/route";
import { fromThread } from "../../stores/spawn";
import { loadThreads } from "../../stores/threads";
import { openSheet, toast } from "../../stores/ui";
import type { Thread } from "../../types";
import { confirmAction, showMenu } from "../sheets/sheets";
import ThreadInfo from "./ThreadInfo.vue";

async function copyId(thread: Thread): Promise<void> {
  toast((await copyText(thread.id)) ? t("Session id copied") : thread.id);
}

async function stopDaemon(thread: Thread): Promise<void> {
  const sure = await confirmAction({
    title: t("Stop {name}?", { name: thread.name }),
    text: t("The daemon stops and its record is removed. Its conversation stays, and it can be started again."),
    ok: t("Stop"),
    danger: true,
  });
  if (!sure) return;
  try {
    await gateway.stop(thread.id);
    toast(t("Stopped"));
    await loadThreads();
  } catch (error) {
    toast(error instanceof ApiError ? error.message : String(error), "bad");
  }
}

function restart(thread: Thread): void {
  fromThread(thread);
  go("new");
}

export function showInfo(thread: Thread): void {
  void openSheet(thread.name, ThreadInfo, { thread });
}

/** The menu behind the dots in a conversation's header. */
export function showThreadMenu(thread: Thread): void {
  const daemon = thread.kind === "daemon";
  const alive = daemon && thread.status !== "dead";
  showMenu(thread.name, [
    { icon: "info", label: t("Info"), run: () => showInfo(thread) },
    daemon && { icon: "logs", label: t("Logs"), run: () => go("logs", thread.id) },
    { icon: "copy", label: t("Copy session id"), run: () => void copyId(thread) },
    daemon && { icon: "refresh", label: t("Restart with a new configuration"), run: () => restart(thread) },
    alive && { icon: "stop", label: t("Stop daemon"), run: () => void stopDaemon(thread), danger: true },
  ]);
}

export { stopDaemon, restart as restartDaemon };
