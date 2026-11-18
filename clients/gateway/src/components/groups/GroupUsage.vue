<script setup lang="ts">
import { computed } from "vue";
import { t } from "../../i18n";
import { tokens } from "../../lib/format";
import { href } from "../../stores/route";
import { usage, useUsage } from "../../stores/usage";
import CacheRing from "../dashboard/CacheRing.vue";

const props = defineProps<{ name: string }>();

const mine = computed(() => usage.data?.groups.find((group) => group.name === props.name));

useUsage();
</script>

<template>
  <div v-if="mine" class="gusage" :title="t('What this group\'s members have spent, from their stored conversations')">
    <CacheRing :share="mine.cache_rate" :size="52" />
    <span class="gchip"><b>{{ mine.requests.toLocaleString() }}</b>{{ t("Requests") }}</span>
    <span class="gchip"><b>{{ tokens(mine.input_tokens) }}</b>{{ t("Input") }}</span>
    <span class="gchip"><b>{{ tokens(mine.output_tokens) }}</b>{{ t("Output") }}</span>
    <span class="gchip"><b>{{ tokens(mine.cache_read_tokens) }}</b>{{ t("Cached tokens") }}</span>
    <span v-if="!mine.measured" class="gnote">{{ t("Nothing has been measured for this group yet.") }}</span>
    <a class="gmore" :href="href('dashboard', 'overview')">{{ t("Dashboard") }}</a>
  </div>
</template>

<style>
.gusage { display: flex; align-items: center; gap: 8px 14px; flex-wrap: wrap; padding: 8px 16px; background: var(--surface); border-bottom: 1px solid var(--divider); font-size: 0.8rem; color: var(--muted); }
.gchip { display: inline-flex; flex-direction: column; line-height: 1.15; }
.gchip b { color: var(--text); font-size: 0.95rem; font-weight: 650; font-variant-numeric: tabular-nums; }
.gnote { font-size: 0.78rem; }
.gmore { margin-left: auto; color: var(--accent); text-decoration: none !important; }
</style>
