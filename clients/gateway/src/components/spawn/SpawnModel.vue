<script setup lang="ts">
import { computed, watch } from "vue";
import { t } from "../../i18n";
import { tokens } from "../../lib/format";
import { settings } from "../../stores/config";
import { draft } from "../../stores/spawn";
import { openSheet } from "../../stores/ui";
import Icon from "../common/Icon.vue";
import Segmented from "../common/Segmented.vue";
import ModelPickerSheet from "./ModelPickerSheet.vue";

const models = computed(() => settings.data?.models ?? []);
const chosen = computed(() => models.value.find((model) => model.name === draft.model) ?? models.value.find((model) => model.default) ?? models.value[0]);
const efforts = computed(() => chosen.value?.efforts ?? []);
const levels = computed(() => [
  { value: "", label: t("Default") },
  ...efforts.value.map((level) => ({ value: level, label: level })),
]);
const facts = computed(() => {
  const model = chosen.value;
  if (!model) return "";
  return [model.model, `${tokens(model.context_window)} ${t("context")}`, model.multimodal ? t("images") : ""].filter(Boolean).join(" · ");
});

// A level the chosen model does not have is not kept.
watch(chosen, (model) => {
  if (draft.effort && model && !model.efforts.includes(draft.effort)) draft.effort = "";
});

async function pick(): Promise<void> {
  const value = await openSheet<string>(t("Model"), ModelPickerSheet, { models: models.value, current: draft.model });
  if (value !== undefined) draft.model = value;
}
</script>

<template>
  <div class="card">
    <div class="card-title">{{ t("Model") }}</div>
    <button type="button" class="model-pick" :disabled="!models.length" :aria-label="t('Choose a model')" @click="pick">
      <span class="model-pick-copy">
        <b>{{ chosen?.name ?? t("No model") }}<em v-if="!draft.model && chosen" class="model-pick-tag">{{ t("Default") }}</em></b>
        <small v-if="facts" class="mono">{{ facts }}</small>
      </span>
      <Icon name="chevron" size="sm" />
    </button>
    <template v-if="efforts.length">
      <div class="model-pick-label">{{ t("Effort") }}</div>
      <Segmented v-model="draft.effort" class="effort-seg" :options="levels" :label="t('Effort')" />
    </template>
    <p v-if="!models.length && !settings.loading" class="card-hint warn">
      {{ t("No models are configured. Add one with /config in ZettCode, or in the config file.") }}
    </p>
  </div>
</template>

<style>
.model-pick { display: flex; align-items: center; gap: 10px; width: calc(100% - 28px); margin: 6px 14px 10px; padding: 12px 14px; border-radius: 13px; background: var(--surface-2); text-align: left; color: inherit; transition: background 0.15s, box-shadow 0.15s; }
.model-pick:hover:not(:disabled) { box-shadow: inset 0 0 0 1px var(--accent); }
.model-pick:disabled { opacity: 0.55; }
.model-pick-copy { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.model-pick-copy b { display: flex; align-items: center; gap: 8px; font-size: 1.02rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.model-pick-copy small { color: var(--muted); font-size: 0.8rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.model-pick-tag { padding: 0 7px; border-radius: 8px; background: var(--accent-soft); color: var(--accent); font-size: 0.7rem; font-style: normal; font-weight: 600; }
.model-pick > .i { color: var(--muted); }
.model-pick-label { padding: 2px 16px 0; color: var(--muted); font-size: 0.8rem; font-weight: 600; }
/* Up to nine levels: they wrap on a narrow screen instead of being squeezed. */
.effort-seg { flex-wrap: wrap; }
.effort-seg button { flex: 1 0 auto; min-width: 3.4rem; padding: 0 10px; }
</style>
