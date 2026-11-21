// What can be done with a thread from its header: the menu, and each action in it.

import { reactive } from "vue";
import { gateway } from "../../api/gateway";
import { ApiError } from "../../api/http";
import { t } from "../../i18n";
import { copyText } from "../../lib/clipboard";
import { go, route } from "../../stores/route";
import { fromThread } from "../../stores/spawn";
import { loadThreads } from "../../stores/threads";
import { canRestart, restartable } from "../../lib/restart";
import { openSheet, toast } from "../../stores/ui";
import type { Thread } from "../../types";
import { confirmAction, showMenu, type MenuEntry } from "../sheets/sheets";
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

export { canStartAgain, canRestart, restartable } from "../../lib/restart";

/** The daemons being started right now, for a spinner and so that a second press does nothing. */
export const restarting = reactive(new Set<string>());

/** Ask for one daemon to be started; returns what the gateway said (`note`: what it could not keep) or the error's message. */
async function startOne(thread: Thread): Promise<{ note?: string } | { error: string }> {
  try {
    return await gateway.restart(thread.id);
  } catch (error) {
    return { error: error instanceof ApiError ? error.message : String(error) };
  }
}

/** Start a stopped daemon again as it was (its folder, model, level and label), on its own conversation. */
export async function restartNow(thread: Thread): Promise<boolean> {
  if (restarting.has(thread.id)) return false;
  restarting.add(thread.id);
  try {
    const answer = await startOne(thread);
    if ("error" in answer) {
      toast(answer.error, "bad");
      return false;
    }
    // A list that fails to reload must not swallow the confirmation: the daemon is running, and the list catches up.
    await loadThreads().catch(() => {});
    // The daemon is back either way; a note only says what it could not keep, so it is not styled as a failure.
    toast(answer.note ?? t("Started {name}", { name: thread.name }));
    return true;
  } finally {
    restarting.delete(thread.id);
  }
}

/**
 * Start every stopped daemon among `ids`, one after another, with one list reload and one toast at the end ("Started 3
 * of 5": a partial failure is said, not shown by a strip that shrinks). Those that cannot be restarted from here are not
 * tried. Returns how many started.
 */
export async function restartAll(ids: readonly string[]): Promise<number> {
  const todo = restartable(ids).filter((thread) => !restarting.has(thread.id));
  if (!todo.length) return 0;
  let started = 0;
  let failure = "";
  for (const thread of todo) restarting.add(thread.id);
  try {
    for (const thread of todo) {
      const answer = await startOne(thread);
      if ("error" in answer) failure = answer.error;
      else started += 1;
    }
    await loadThreads().catch(() => {});
  } finally {
    for (const thread of todo) restarting.delete(thread.id);
  }
  if (started === todo.length) {
    toast(started === 1 ? t("Started {name}", { name: todo[0]!.name }) : t("Started {count} daemons", { count: started }));
  }
  else toast(t("Started {started} of {total}: {error}", { started, total: todo.length, error: failure }), "bad");
  return started;
}

/** The long way, for changing something: the New form filled in from the daemon, started on the same conversation. */
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
    const answer = await gateway.updateProfile(thread.id, { [flag]: on });
    // A gateway older than this page answers 200 and ignores a field it does not know: say so, rather than toast a change that was not made.
    if (answer.thread && Boolean(answer.thread[flag]) !== on) {
      toast(t("The gateway did not keep that. It may be an older version: restart it."), "bad");
      return;
    }
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

/** The two entries of a thread's menus that keep a list tidy, so the header's menu and the list's cannot differ. */
const pinEntry = (thread: Thread): MenuEntry => ({
  icon: "pin",
  label: thread.pinned ? t("Unpin") : t("Pin to the top"),
  run: () => void setFlag(thread, "pinned", !thread.pinned),
});
const archiveEntry = (thread: Thread): MenuEntry => ({
  icon: "archive",
  label: thread.archived ? t("Move back to the list") : t("Archive"),
  run: () => void setFlag(thread, "archived", !thread.archived),
});

/** The menu behind the dots in a conversation's header. */
export function showThreadMenu(thread: Thread): void {
  const daemon = thread.kind === "daemon";
  const alive = daemon && thread.online;
  showMenu(thread.name, [
    { icon: "info", label: t("Info"), run: () => showInfo(thread) },
    pinEntry(thread),
    archiveEntry(thread),
    daemon && { icon: "logs", label: t("Logs"), run: () => go("logs", thread.id) },
    { icon: "copy", label: t("Copy session id"), run: () => void copyId(thread) },
    canRestart(thread) && { icon: "refresh", label: t("Restart it"), run: () => void restartNow(thread) },
    daemon && { icon: "refresh", label: t("Change settings and restart"), run: () => restart(thread) },
    alive && { icon: "stop", label: t("Stop daemon"), run: () => void stopDaemon(thread), danger: true },
    daemon && !alive && { icon: "trash", label: t("Delete daemon"), run: () => void deleteDaemon(thread), danger: true },
  ]);
}

/** The menu a right click on a row of the chat list opens: the two things a list is kept tidy with. */
export function showRowMenu(thread: Thread): void {
  showMenu(thread.name, [pinEntry(thread), archiveEntry(thread)]);
}

export { stopDaemon, deleteDaemon, restart as restartDaemon };
