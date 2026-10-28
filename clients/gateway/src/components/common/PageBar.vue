<script setup lang="ts">
import { href, route } from "../../stores/route";
import Icon from "./Icon.vue";
import { t } from "../../i18n";

defineProps<{ title: string; back?: boolean }>();
</script>

<template>
  <header class="bar page-bar">
    <a v-if="back" class="iconbtn back" :href="href(route.nav)" :aria-label="t('Back')"><Icon name="back" /></a>
    <h2>{{ title }}</h2>
    <slot />
  </header>
</template>

<style>
.page-bar h2 { flex: 1; margin: 0 0 0 6px; font-size: 1.1rem; font-weight: 650; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.page-bar .back + h2 { margin-left: 0; }
.page { flex: 1; overflow-y: auto; overscroll-behavior: contain; -webkit-overflow-scrolling: touch; background: var(--surface-2); }
.page-inner { max-width: 640px; margin: 0 auto; padding: 8px 12px calc(24px + var(--safe-bottom)); }
@media (max-width: 719px) {
  .page-inner { padding-left: 10px; padding-right: 10px; }
}
</style>
