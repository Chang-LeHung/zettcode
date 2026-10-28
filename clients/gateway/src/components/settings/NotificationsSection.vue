<script setup lang="ts">
import { ref } from "vue";
import { t } from "../../i18n";
import { enableNotifications, notificationState } from "../../stores/live";
import { prefs } from "../../stores/prefs";
import { toast } from "../../stores/ui";
import SwitchRow from "../common/SwitchRow.vue";

const state = ref(notificationState());

async function toggle(on: boolean): Promise<void> {
  if (on && !(await enableNotifications())) {
    prefs.notify = false;
    toast(t("Notifications are blocked in this browser."), "bad");
  }
  state.value = notificationState();
}
</script>

<template>
  <div class="card">
    <SwitchRow
      :model-value="prefs.notify"
      :label="t('Notify when a session replies')"
      :hint="t('Only while this page is open, and only for a chat you are not looking at.')"
      @update:model-value="(on: boolean) => { prefs.notify = on; void toggle(on); }"
    />
    <div class="kv"><span>{{ t("Permission") }}</span><span>{{ state }}</span></div>
  </div>
</template>
