<script setup lang="ts">
import { t } from "../../i18n";
import { settings } from "../../stores/config";
import { prefs } from "../../stores/prefs";
</script>

<template>
  <p class="card-hint">{{ t("Agents can be started in these folders or below them. With no --root the gateway allows any folder; --root narrows it.") }}</p>
  <div class="card">
    <div class="card-title">{{ t("Allowed roots") }}</div>
    <div v-for="root in settings.data?.roots ?? []" :key="root" class="kv"><span class="mono">{{ root }}</span></div>
  </div>
  <div v-if="prefs.recent.length" class="card">
    <div class="card-title">{{ t("Recently used") }}</div>
    <div v-for="path in prefs.recent" :key="path" class="kv"><span class="mono">{{ path }}</span></div>
    <div class="actions"><button class="btn sm ghost" @click="prefs.recent = []">{{ t("Clear") }}</button></div>
  </div>
</template>
