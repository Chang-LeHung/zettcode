// The Dashboard's data: what each session and each group has spent. The gateway reads it back from the stored
// conversations, so it is read when a page that shows it opens and then again every few seconds while one stays open.

import { onBeforeUnmount, onMounted, reactive } from "vue";
import { gateway } from "../api/gateway";
import { ApiError } from "../api/http";
import type { Usage } from "../types";

export const usage = reactive({
  data: null as Usage | null,
  loading: false,
  error: "",
});

/** How often the numbers are read again while a page that shows them is open. */
export const REFRESH_MS = 10_000;

let again = false;

/** Read the numbers. A request made while one is in flight is not dropped: it runs once more when that one ends. */
export async function loadUsage(): Promise<void> {
  if (usage.loading) {
    again = true;
    return;
  }
  usage.loading = true;
  try {
    const fresh = await gateway.usage();
    // A poll the broker did not answer has no groups because it could not be asked: keep the last ones the page had, so a
    // strip and the member numbers do not blank for one bad poll. The Dashboard says the groups are not known right now.
    // The total goes with them: the server's was computed without the members only a group knew, so beside the old group
    // cards it could read lower than their sum.
    if (!fresh.groups_known && usage.data) {
      fresh.groups = usage.data.groups;
      fresh.total = usage.data.total;
    }
    usage.data = fresh;
    usage.error = "";
  } catch (error) {
    usage.error = error instanceof ApiError ? error.message : String(error);
  } finally {
    usage.loading = false;
    if (again) {
      again = false;
      void loadUsage();
    }
  }
}

let watchers = 0;
let timer = 0;

/**
 * Keep the numbers current while the calling component is mounted: read them now, and every `REFRESH_MS` while the page
 * is visible. However many components ask at once (the Dashboard, a group's strip), there is one timer.
 */
export function useUsage(): void {
  onMounted(() => {
    void loadUsage();
    if (watchers++ === 0) {
      timer = window.setInterval(() => {
        if (!document.hidden) void loadUsage();
      }, REFRESH_MS);
    }
  });
  onBeforeUnmount(() => {
    if (--watchers === 0) window.clearInterval(timer);
  });
}
