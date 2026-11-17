// The Dashboard's data: what each session and each group has spent. The gateway reads it back from the stored
// conversations, so it is read when the page opens and then again every few seconds while it stays open.

import { reactive } from "vue";
import { gateway } from "../api/gateway";
import { ApiError } from "../api/http";
import type { Usage } from "../types";

export const usage = reactive({
  data: null as Usage | null,
  loading: false,
  error: "",
});

/** How often an open Dashboard reads again. */
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
    usage.data = await gateway.usage();
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

/** A share as a percentage, or a dash when it was not measured. */
export const percent = (share: number | null, digits = 1): string =>
  share === null ? "–" : `${(share * 100).toFixed(share >= 0.9995 ? 0 : digits)}%`;
