// What the gateway was configured with: the models, the folders agents may work in, and whether full access is allowed.
// It does not change while the gateway runs, so it is read once and again only when asked.

import { reactive } from "vue";
import { gateway } from "../api/gateway";
import { ApiError } from "../api/http";
import type { GatewayConfig } from "../types";

export const settings = reactive({
  data: null as GatewayConfig | null,
  loading: false,
  error: "",
});

export async function loadConfig(force = false): Promise<void> {
  if (settings.loading || (settings.data && !force)) return;
  settings.loading = true;
  try {
    settings.data = await gateway.config();
    settings.error = "";
  } catch (error) {
    settings.error = error instanceof ApiError ? error.message : String(error);
  } finally {
    settings.loading = false;
  }
}
