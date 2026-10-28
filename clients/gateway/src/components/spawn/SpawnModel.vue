<script setup lang="ts">
import { computed, watch } from "vue";
import { t } from "../../i18n";
import { settings } from "../../stores/config";
import { draft } from "../../stores/spawn";

const models = computed(() => settings.data?.models ?? []);
const chosen = computed(() => models.value.find((model) => model.name === draft.model) ?? models.value.find((model) => model.default));
const efforts = computed(() => chosen.value?.efforts ?? []);

// A level the chosen model does not have is not kept.
watch(chosen, (model) => {
  if (draft.effort && model && !model.efforts.includes(draft.effort)) draft.effort = "";
});
</script>

<template>
  <div class="card">
    <div class="card-title">{{ t("Model") }}</div>
    <div class="field-row">
      <label for="spawn-model">{{ t("Model") }}</label>
      <select id="spawn-model" v-model="draft.model">
        <option value="">{{ t("Default") }}{{ models[0] ? ` (${models[0].name})` : "" }}</option>
        <option v-for="model in models" :key="model.name" :value="model.name">{{ model.name }}</option>
      </select>
    </div>
    <div class="field-row">
      <label for="spawn-effort">{{ t("Effort") }}</label>
      <select id="spawn-effort" v-model="draft.effort" :disabled="!efforts.length">
        <option value="">{{ t("Model default") }}</option>
        <option v-for="level in efforts" :key="level" :value="level">{{ level }}</option>
      </select>
    </div>
    <p v-if="!models.length && !settings.loading" class="card-hint warn">
      {{ t("No models are configured. Add one with /config in ZettCode, or in the config file.") }}
    </p>
  </div>
</template>
