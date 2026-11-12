// What can be done with a thread from its header: the menu, and each action in it.

import { gateway } from "../../api/gateway";
import { ApiError } from "../../api/http";
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

/** Pin or archive a thread. Both are kept at the gateway, so every browser sees the same list. */
async function setFlag(thread: Thread, flag: "pinned" | "archived", on: boolean): Promise<void> {
  try {
    await gateway.updateProfile(thread.id, { [flag]: on });
    await loadThreads();
    if (flag === "pinned") toast(on ? t("Pinned") : t("Unpinned"));
    else {
      toast(on ? t("Archived. Search or open Archived to find it.") : t("Moved back to the list"));
      // The conversation that was open leaves the list, so the page leaves it too, as after a delete.
      if (on && route.nav === "chats" && route.arg === thread.id) go("chats");
    }
  } catch (error) {
    toast(error instanceof ApiError ? error.message : String(error), "bad");
  }
}

/** The menu behind the dots in a conversation's header. */
export function showThreadMenu(thread: Thread): void {
  const daemon = thread.kind === "daemon";
  const alive = daemon && thread.online;
  showMenu(thread.name, [
    { icon: "info", label: t("Info"), run: () => showInfo(thread) },
    { icon: "pin", label: thread.pinned ? t("Unpin") : t("Pin to the top"), run: () => void setFlag(thread, "pinned", !thread.pinned) },
    {
      icon: "archive",
      label: thread.archived ? t("Move back to the list") : t("Archive"),
      run: () => void setFlag(thread, "archived", !thread.archived),
    },
    daemon && { icon: "logs", label: t("Logs"), run: () => go("logs", thread.id) },
    { icon: "copy", label: t("Copy session id"), run: () => void copyId(thread) },
    daemon && { icon: "refresh", label: t("Restart with a new configuration"), run: () => restart(thread) },
    alive && { icon: "stop", label: t("Stop daemon"), run: () => void stopDaemon(thread), danger: true },
    daemon && !alive && { icon: "trash", label: t("Delete daemon"), run: () => void deleteDaemon(thread), danger: true },
  ]);
}

export { stopDaemon, deleteDaemon, restart as restartDaemon };
