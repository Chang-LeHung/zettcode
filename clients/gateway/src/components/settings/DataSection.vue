<script setup lang="ts">
import { t } from "../../i18n";
import { storage } from "../../lib/storage";
import { resetPrefs } from "../../stores/prefs";
import { toast } from "../../stores/ui";
import { confirmAction } from "../sheets/sheets";

async function wipe(): Promise<void> {
  const sure = await confirmAction({
    title: t("Clear what this browser remembers?"),
    text: t("Drafts, templates, recent folders and preferences are removed from this browser. Sessions and daemons are not touched."),
    ok: t("Clear"),
    danger: true,
  });
  if (!sure) return;
  storage.clear();
  resetPrefs();
  toast(t("Cleared"));
}
</script>

<template>
  <p class="card-hint">{{ t("The gateway itself keeps only which messages you have read. Everything else here lives in this browser.") }}</p>
  <div class="actions"><button class="btn danger" @click="wipe">{{ t("Clear browser data") }}</button></div>
</template>
