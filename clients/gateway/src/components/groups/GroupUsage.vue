<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from "vue";
import { t } from "../../i18n";
import { tokens } from "../../lib/format";
import { loadUsage, REFRESH_MS, usage } from "../../stores/usage";
import CacheRing from "../dashboard/CacheRing.vue";

const props = defineProps<{ name: string }>();

const mine = computed(() => usage.data?.groups.find((group) => group.name === props.name));

let timer = 0;
onMounted(() => {
  void loadUsage();
  timer = window.setInterval(() => {
    if (!document.hidden) void loadUsage();
  }, REFRESH_MS);
});
onBeforeUnmount(() => window.clearInterval(timer));
</script>

<template>
  <div v-if="mine && mine.measured" class="gusage" :title="t('What this group\'s members have spent, from their stored conversations')">
    <CacheRing :share="mine.cache_rate" :size="52" />
    <span class="gchip"><b>{{ mine.requests.toLocaleString() }}</b>{{ t("Requests") }}</span>
    <span class="gchip"><b>{{ tokens(mine.input_tokens) }}</b>{{ t("Input") }}</span>
    <span class="gchip"><b>{{ tokens(mine.output_tokens) }}</b>{{ t("Output") }}</span>
    <span class="gchip"><b>{{ tokens(mine.cache_read_tokens) }}</b>{{ t("Cached tokens") }}</span>
    <a class="gmore" href="#/dashboard/overview">{{ t("Dashboard") }}</a>
  </div>
</template>

<style>
.gusage { display: flex; align-items: center; gap: 8px 14px; flex-wrap: wrap; padding: 8px 16px; background: var(--surface); border-bottom: 1px solid var(--divider); font-size: 0.8rem; color: var(--muted); }
.gchip { display: inline-flex; flex-direction: column; line-height: 1.15; }
.gchip b { color: var(--text); font-size: 0.95rem; font-weight: 650; font-variant-numeric: tabular-nums; }
.gmore { margin-left: auto; color: var(--accent); text-decoration: none !important; }
</style>
