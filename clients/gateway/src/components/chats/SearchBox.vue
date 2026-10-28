<script setup lang="ts">
import { t } from "../../i18n";
import Icon from "../common/Icon.vue";

const model = defineModel<string>({ required: true });
</script>

<template>
  <label class="search">
    <Icon name="search" size="sm" />
    <input v-model="model" type="search" :placeholder="t('Search')" :aria-label="t('Search')" autocomplete="off" />
  </label>
</template>

<style>
.search {
  display: flex; align-items: center; gap: 8px; margin: 0 12px 8px; padding: 0 12px; height: 40px; border-radius: 20px;
  background: var(--surface-2); color: var(--muted);
}
.search input { flex: 1; min-width: 0; height: 100%; border: 0; outline: 0; background: none; color: var(--text); font-size: 1rem; }
.search input::placeholder { color: var(--muted); }
</style>
