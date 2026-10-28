<script setup lang="ts">
import { t } from "../../i18n";
import { lobby } from "../../stores/threads";
</script>

<template>
  <p class="card-hint">{{ t("What the session broker accepts from one sender. These are fixed by the broker.") }}</p>
  <div v-if="lobby.status" class="card">
    <div class="kv"><span>{{ t("Message length") }}</span><span>{{ lobby.status.limits.max_text.toLocaleString() }} {{ t("characters") }}</span></div>
    <div class="kv"><span>{{ t("Rate") }}</span><span>{{ lobby.status.limits.rate_limit }} / {{ lobby.status.limits.rate_window }}s</span></div>
    <div class="kv"><span>{{ t("Used now") }}</span><span>{{ lobby.status.limits.used }}</span></div>
  </div>
</template>
