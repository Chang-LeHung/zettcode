<script setup lang="ts">
import { computed, ref } from "vue";
import { t } from "../../i18n";
import { tokens } from "../../lib/format";
import type { ModelOption } from "../../types";
import Icon from "../common/Icon.vue";

const props = defineProps<{ models: ModelOption[]; current: string }>();
const emit = defineEmits<{ close: [value: string] }>();
const query = ref("");

const wanted = computed(() => query.value.trim().toLowerCase());
const shown = computed(() =>
  props.models.filter((model) => !wanted.value || [model.name, model.model, model.api].some((field) => field.toLowerCase().includes(wanted.value))),
);
const fallback = computed(() => props.models.find((model) => model.default) ?? props.models[0]);
const searchable = computed(() => props.models.length > 6);
</script>

<template>
  <div class="mpick">
    <input v-if="searchable" v-model="query" type="search" :placeholder="t('Search models')" :aria-label="t('Search models')" autocomplete="off" />
    <div class="mpick-list" role="listbox" :aria-label="t('Model')">
      <button v-if="!wanted" type="button" class="mpick-row" role="option" :aria-selected="current === ''" @click="emit('close', '')">
        <span class="mpick-copy">
          <b>{{ t("Default") }}</b>
          <small>{{ fallback ? t("Uses {name}", { name: fallback.name }) : t("The configured default") }}</small>
        </span>
        <Icon v-if="current === ''" class="mpick-check" name="check" size="sm" />
      </button>
      <button
        v-for="model in shown"
        :key="model.name"
        type="button"
        class="mpick-row"
        role="option"
        :aria-selected="current === model.name"
        @click="emit('close', model.name)"
      >
        <span class="mpick-copy">
          <b>{{ model.name }}<em v-if="model.default" class="mpick-tag">{{ t("default") }}</em></b>
          <small class="mono">{{ model.model }}</small>
          <span class="mpick-facts">
            <i>{{ model.api }}</i>
            <i>{{ tokens(model.context_window) }} {{ t("context") }}</i>
            <i v-if="model.multimodal">{{ t("images") }}</i>
            <i v-if="model.web_search || model.can_search">{{ t("search") }}</i>
            <i v-if="model.efforts.length">{{ t("{count} effort levels", { count: model.efforts.length }) }}</i>
          </span>
        </span>
        <Icon v-if="current === model.name" class="mpick-check" name="check" size="sm" />
      </button>
      <div v-if="wanted && !shown.length" class="empty">{{ t("Nothing matches") }}</div>
    </div>
  </div>
</template>

<style>
.mpick { display: flex; flex-direction: column; gap: 6px; padding: 4px 12px 12px; }
.mpick > input { min-height: 42px; padding: 8px 12px; border: 1px solid var(--divider); border-radius: 11px; outline: none; background: var(--bg); color: var(--text); font: inherit; }
.mpick > input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
.mpick-list { display: flex; flex-direction: column; gap: 2px; max-height: 58dvh; overflow-y: auto; overscroll-behavior: contain; }
.mpick-row { display: flex; align-items: center; gap: 10px; width: 100%; padding: 10px 12px; border-radius: 12px; text-align: left; color: inherit; transition: background 0.12s; }
.mpick-row:hover { background: var(--hover); }
.mpick-row[aria-selected="true"] { background: var(--accent-soft); box-shadow: inset 3px 0 0 var(--accent); }
.mpick-copy { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.mpick-copy b { display: flex; align-items: center; gap: 8px; font-weight: 650; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mpick-copy small { color: var(--muted); font-size: 0.8rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mpick-tag { padding: 0 7px; border-radius: 8px; background: var(--accent-soft); color: var(--accent); font-size: 0.7rem; font-style: normal; font-weight: 600; }
.mpick-facts { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 3px; }
.mpick-facts i { padding: 1px 8px; border-radius: 8px; background: var(--surface-2); color: var(--muted); font-size: 0.72rem; font-style: normal; }
.mpick-check { flex: none; color: var(--accent); }
</style>
