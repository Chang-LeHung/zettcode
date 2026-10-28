<script setup lang="ts">
import { computed } from "vue";
import { t } from "../../i18n";
import { settings } from "../../stores/config";
import { prefs } from "../../stores/prefs";
import Segmented from "../common/Segmented.vue";

const models = computed(() => settings.data?.models ?? []);
const efforts = computed(() => models.value.find((model) => model.name === prefs.defaults.model)?.efforts ?? []);
const allowFull = computed(() => settings.data?.allow_full === true);
const levels = computed(() => [
  { value: "deny", label: t("No shell") },
  { value: "safe", label: t("Sandboxed") },
  { value: "full", label: t("Full"), disabled: !allowFull.value },
]);
</script>

<template>
  <p class="card-hint">{{ t("What the New page starts with. Kept in this browser.") }}</p>
  <div class="card">
    <div class="field-row">
      <label for="def-model">{{ t("Model") }}</label>
      <select id="def-model" v-model="prefs.defaults.model" @change="prefs.defaults.effort = ''">
        <option value="">{{ t("Default") }}</option>
        <option v-for="model in models" :key="model.name" :value="model.name">{{ model.name }}</option>
      </select>
    </div>
    <div class="field-row">
      <label for="def-effort">{{ t("Effort") }}</label>
      <select id="def-effort" v-model="prefs.defaults.effort" :disabled="!efforts.length">
        <option value="">{{ t("Model default") }}</option>
        <option v-for="level in efforts" :key="level" :value="level">{{ level }}</option>
      </select>
    </div>
    <Segmented v-model="prefs.defaults.permission" :options="levels" :label="t('Shell access')" />
  </div>
</template>
