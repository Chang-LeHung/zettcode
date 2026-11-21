import { auth } from "../stores/auth";
import { settings } from "../stores/config";
import { lobby } from "../stores/threads";
import type { Thread } from "../types";

/** Why a one-press restart is unavailable. English keys are translated by the view. */
export function restartBlocker(thread: Thread | undefined): string | undefined {
  if (!thread || thread.kind !== "daemon") return "No saved daemon record is available on this gateway.";
  if (thread.status !== "dead") return "This daemon is not marked as stopped.";
  if (thread.locked) return "This conversation is open in another process.";
  if (auth.readOnly) return "Read-only access cannot restart daemons.";
  if (thread.permission === "full" && settings.data?.allow_full === false) {
    return "Full access is disabled. Change settings before restarting.";
  }
  return undefined;
}

export const canStartAgain = (thread: Thread | undefined): thread is Thread =>
  !!thread && thread.kind === "daemon" && thread.status === "dead" && !thread.locked && !auth.readOnly;

export const canRestart = (thread: Thread | undefined): thread is Thread => restartBlocker(thread) === undefined;

/** Eligible threads only from the caller's visible scope, not other sections or search results. */
export const restartable = (ids: readonly string[]): Thread[] =>
  ids.map((id) => lobby.threads.find((thread) => thread.id === id)).filter(canRestart);
