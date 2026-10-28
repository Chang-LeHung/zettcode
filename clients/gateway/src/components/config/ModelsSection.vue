<script setup lang="ts">
import { t } from "../../i18n";
import { tokens } from "../../lib/format";
import { settings } from "../../stores/config";
</script>

<template>
  <p class="card-hint">{{ t("Models are read from the ZettCode config file. Edit it with /config in a terminal or by hand; a new daemon picks the change up.") }}</p>
  <div v-for="model in settings.data?.models ?? []" :key="model.name" class="card">
    <div class="card-title">{{ model.name }}<template v-if="model.default"> · {{ t("default") }}</template></div>
    <div class="kv"><span>{{ t("Model id") }}</span><span class="mono">{{ model.model }}</span></div>
    <div class="kv"><span>{{ t("Protocol") }}</span><span>{{ model.api }}</span></div>
    <div class="kv"><span>{{ t("Context") }}</span><span>{{ tokens(model.context_window) }}</span></div>
    <div class="kv"><span>{{ t("Images") }}</span><span>{{ model.multimodal ? t("yes") : t("no") }}</span></div>
    <div class="kv"><span>{{ t("Effort levels") }}</span><span>{{ model.efforts.join(", ") || "–" }}</span></div>
  </div>
  <div v-if="settings.data && !settings.data.models.length" class="empty"><b>{{ t("No models") }}</b>{{ t("Add one in the config file.") }}</div>
</template>
