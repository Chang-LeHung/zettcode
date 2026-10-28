<script setup lang="ts">
import Icon from "./Icon.vue";
import type { IconName } from "./icons";

defineProps<{ icon: IconName; title: string; subtitle?: string; href?: string; current?: boolean }>();
</script>

<template>
  <component
    :is="href ? 'a' : 'button'"
    class="simple-row"
    :href="href"
    :type="href ? undefined : 'button'"
    :aria-current="current ? 'true' : undefined"
  >
    <span class="simple-icon"><Icon :name="icon" /></span>
    <span class="simple-text">
      <b>{{ title }}</b>
      <small v-if="subtitle">{{ subtitle }}</small>
    </span>
    <Icon class="simple-chev" name="chevron" size="sm" />
  </component>
</template>

<style>
.simple-row {
  display: flex; align-items: center; gap: 14px; width: 100%; min-height: 58px; padding: 6px 16px;
  text-align: left; color: inherit; text-decoration: none !important; transition: background 0.12s;
}
.simple-row:hover { background: var(--hover); }
.simple-row[aria-current="true"] { background: var(--accent-soft); }
.simple-icon { display: grid; place-items: center; width: 36px; height: 36px; border-radius: 10px; background: var(--accent-soft); color: var(--accent); flex: none; }
.simple-text { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.simple-text b { font-weight: 600; font-size: 1rem; }
.simple-text small { color: var(--muted); font-size: 0.84rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.simple-chev { color: var(--muted); flex: none; }
</style>
