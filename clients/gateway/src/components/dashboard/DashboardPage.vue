<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, watch } from "vue";
import { t } from "../../i18n";
import { DASHBOARD_SECTIONS } from "../../sections";
import { route } from "../../stores/route";
import { lobby } from "../../stores/threads";
import { loadUsage, REFRESH_MS, usage } from "../../stores/usage";
import PageBar from "../common/PageBar.vue";
import Skeleton from "../common/Skeleton.vue";
import UsageDaemons from "./UsageDaemons.vue";
import UsageOverview from "./UsageOverview.vue";

const id = computed(() => (route.arg === "daemons" ? "daemons" : "overview"));
const title = computed(() => t(DASHBOARD_SECTIONS.find((section) => section.id === id.value)?.label ?? "Dashboard"));

// A daemon that started or stopped changes what the rows say, so they are read again at once, not at the next tick.
watch(() => lobby.threads.map((thread) => `${thread.id}:${thread.status}`).join(), () => void loadUsage());

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
  <PageBar :title="title" back />
  <div class="page">
    <div class="page-inner dash">
      <p v-if="usage.error" class="errcard">{{ usage.error }}</p>
      <Skeleton v-if="!usage.data && !usage.error" kind="cards" :count="3" />
      <template v-else-if="usage.data">
        <UsageOverview v-if="id === 'overview'" :usage="usage.data" />
        <UsageDaemons v-else :usage="usage.data" />
      </template>
    </div>
  </div>
</template>

<style>
.page-inner.dash { max-width: 980px; padding-top: 14px; }
.dash-title { margin: 22px 4px 10px; font-size: 0.95rem; font-weight: 650; letter-spacing: 0.01em; display: flex; align-items: baseline; gap: 8px; }
.dash-title small { color: var(--muted); font-weight: 500; }

.hero { display: flex; align-items: center; flex-wrap: wrap; gap: 14px 20px; padding: 20px 22px; border-radius: 20px; color: var(--text);
  background: linear-gradient(135deg, var(--accent-soft, rgba(47, 124, 246, 0.12)), var(--surface) 70%); border: 1px solid var(--divider); box-shadow: var(--shadow); }
.hero-text { flex: 1 1 200px; display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.hero-text b { font-size: 1.15rem; }
.hero-text span { color: var(--muted); font-size: 0.85rem; line-height: 1.4; }
.tiles { flex: 1 1 100%; display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; }
.tile { background: var(--surface); border: 1px solid var(--divider); border-radius: 14px; padding: 12px 14px; display: flex; flex-direction: column; gap: 2px; }
.tile b { font-size: 1.45rem; font-weight: 680; font-variant-numeric: tabular-nums; letter-spacing: -0.01em; }
.tile span { color: var(--muted); font-size: 0.78rem; }

.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(290px, 1fr)); gap: 12px; }
.ucard { background: var(--surface); border: 1px solid var(--divider); border-radius: 18px; padding: 14px 16px 16px; display: flex; flex-direction: column; gap: 6px; box-shadow: var(--shadow);
  transition: transform 0.18s ease, box-shadow 0.18s ease; }
.ucard:hover { transform: translateY(-2px); }
.ucard-head { display: flex; align-items: center; gap: 10px; min-width: 0; }
.ucard-name { flex: 1; min-width: 0; font-weight: 650; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: inherit; text-decoration: none !important; }
.ucard-name:hover { color: var(--accent); }
.ucard-sub { margin: 0 0 6px 42px; color: var(--muted); font-size: 0.8rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ucard-sub .warn { color: var(--warn); }
.ucard-body { display: flex; align-items: center; gap: 16px; }
.nums { flex: 1; margin: 0; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; }
.nums dt { color: var(--muted); font-size: 0.72rem; }
.nums dd { margin: 0; font-size: 1.05rem; font-weight: 650; font-variant-numeric: tabular-nums; }

.pill { flex: none; font-size: 0.7rem; font-weight: 600; padding: 2px 9px; border-radius: 999px; background: var(--hover); color: var(--muted); }
.pill.on { background: color-mix(in srgb, var(--ok) 16%, transparent); color: var(--ok); }
.pill.busy { background: color-mix(in srgb, var(--accent) 16%, transparent); color: var(--accent); }
.pill.off { background: color-mix(in srgb, var(--warn) 18%, transparent); color: var(--warn); }

.ctx { display: flex; align-items: center; gap: 10px; margin-top: 6px; color: var(--muted); font-size: 0.75rem; }
.meter { flex: 1; display: block; height: 6px; border-radius: 3px; background: var(--divider); overflow: hidden; }
.meter i { display: block; height: 100%; border-radius: 3px; background: var(--accent); }
.meter i.low { background: var(--warn); }
@media (max-width: 719px) {
  .hero { padding: 16px; }
  .grid { grid-template-columns: minmax(0, 1fr); }
}
</style>
