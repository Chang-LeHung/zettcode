<script setup lang="ts">
import { t } from "../../i18n";
import { prefs } from "../../stores/prefs";
import SwitchRow from "../common/SwitchRow.vue";
</script>

<template>
  <div class="card">
    <SwitchRow
      v-model="prefs.askReply"
      :label="t('Ask daemons to answer')"
      :hint="t('A daemon answers into its own conversation unless its model calls send_message. This adds a line asking it to. The line is not shown in the chat.')"
    />
    <SwitchRow
      v-model="prefs.confirmSession"
      :label="t('Confirm before writing to a session')"
      :hint="t('A session other than a daemon may have a person at it. Your message starts a turn there and spends that session\'s tokens.')"
    />
  </div>
  <p class="card-hint">{{ t("A message is delivered at most once. If the gateway cannot tell whether one arrived, it says so and never sends it again by itself.") }}</p>
</template>
