// What can be done with a thread from its header: the menu, and each action in it.

import { gateway } from "../../api/gateway";
import { t } from "../../i18n";
import { copyText } from "../../lib/clipboard";
import { go, route } from "../../stores/route";
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
  const working = thread.status === "working";
  const sure = await confirmAction({
    title: working ? t("{name} is working. Stop it anyway?", { name: thread.name }) : t("Stop {name}?", { name: thread.name }),
    text: working
      ? t("It is in the middle of a turn, and stopping it now throws that turn away. It stays in the list, offline.")
      : t("The daemon stops, and stays in the list as offline with its conversation, so it can be started again."),
    ok: working ? t("Stop anyway") : t("Stop"),
    danger: true,
    run: async () => {
      await gateway.stop(thread.id, working);
      await loadThreads();
    },
  });
  if (sure) toast(t("Stopped"));
}

async function deleteDaemon(thread: Thread): Promise<void> {
  const sure = await confirmAction({
    title: t("Delete {name}?", { name: thread.name }),
    text: t("The daemon and its whole conversation are removed for good. This cannot be undone."),
    ok: t("Delete"),
    danger: true,
    run: async () => {
      await gateway.remove(thread.id);
      await loadThreads();
    },
  });
  if (!sure) return;
  toast(t("Deleted"));
  if (route.nav === "chats" && route.arg === thread.id) go("chats");
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
  const alive = daemon && thread.online;
  showMenu(thread.name, [
    { icon: "info", label: t("Info"), run: () => showInfo(thread) },
    daemon && { icon: "logs", label: t("Logs"), run: () => go("logs", thread.id) },
    { icon: "copy", label: t("Copy session id"), run: () => void copyId(thread) },
    daemon && { icon: "refresh", label: t("Restart with a new configuration"), run: () => restart(thread) },
    alive && { icon: "stop", label: t("Stop daemon"), run: () => void stopDaemon(thread), danger: true },
    daemon && !alive && { icon: "trash", label: t("Delete daemon"), run: () => void deleteDaemon(thread), danger: true },
  ]);
}

export { stopDaemon, deleteDaemon, restart as restartDaemon };
