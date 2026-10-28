<script setup lang="ts">
import Icon from "../common/Icon.vue";
import type { MenuEntry } from "./sheets";

defineProps<{ items: MenuEntry[] }>();
const emit = defineEmits<{ close: [] }>();
</script>

<template>
  <button
    v-for="item in items"
    :key="item.label"
    class="menu-item"
    :class="{ danger: item.danger }"
    @click="
      emit('close');
      item.run();
    "
  >
    <Icon :name="item.icon" />
    <span>{{ item.label }}</span>
  </button>
</template>

<style>
.menu-item { display: flex; align-items: center; gap: 14px; width: 100%; min-height: 50px; padding: 0 18px; text-align: left; font-size: 1rem; }
.menu-item:hover { background: var(--hover); }
.menu-item.danger { color: var(--bad); }
.menu-item svg { color: var(--muted); }
.menu-item.danger svg { color: var(--bad); }
</style>
