<script setup lang="ts">
import { computed } from "vue";
import { t } from "../../i18n";
import { href, route, type Nav } from "../../stores/route";
import { lobby, totalUnread } from "../../stores/threads";
import Icon from "../common/Icon.vue";
import type { IconName } from "../common/icons";

const tabs: { nav: Nav; label: string; icon: IconName }[] = [
  { nav: "chats", label: "Chats", icon: "chat" },
  { nav: "new", label: "New", icon: "plus" },
  { nav: "config", label: "Config", icon: "config" },
  { nav: "logs", label: "Logs", icon: "logs" },
  { nav: "settings", label: "Settings", icon: "settings" },
];

const dot = computed(() => (!lobby.live ? "warn" : lobby.status?.broker.reachable === false ? "bad" : "ok"));
const caption = computed(() =>
  !lobby.live ? t("Connecting") : lobby.status?.broker.reachable === false ? t("No broker") : t("Online"),
);
</script>

<template>
  <nav class="rail" :aria-label="t('Sections')">
    <div class="rail-logo"><img src="/static/logo.svg" alt="" width="36" height="36" /></div>
    <a
      v-for="tab in tabs"
      :key="tab.nav"
      class="rail-tab"
      :href="href(tab.nav)"
      :aria-current="route.nav === tab.nav ? 'page' : undefined"
    >
      <Icon :name="tab.icon" />
      <span>{{ t(tab.label) }}</span>
      <span v-if="tab.nav === 'chats' && totalUnread" class="badge">{{ totalUnread > 99 ? "99+" : totalUnread }}</span>
    </a>
    <div class="rail-spacer" />
    <div class="rail-status" :title="caption">
      <span class="rail-dot" :class="dot" />
      <span>{{ caption }}</span>
    </div>
  </nav>
</template>

<style>
.rail {
  display: flex; flex-direction: column; align-items: stretch; gap: 2px;
  padding: calc(var(--safe-top) + 10px) 6px 10px calc(var(--safe-left) + 6px);
  background: var(--rail-bg); border-right: 1px solid var(--divider); min-height: 0;
}
.rail-logo { display: grid; place-items: center; height: 44px; margin-bottom: 6px; }
.rail-logo img { object-fit: contain; }
.rail-tab {
  position: relative; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 3px;
  min-height: 56px; border-radius: 12px; color: var(--muted); font-size: 0.68rem; font-weight: 500;
  transition: background 0.15s, color 0.15s; text-decoration: none !important;
}
.rail-tab:hover { background: var(--hover); }
.rail-tab[aria-current="page"] { color: var(--accent); }
.rail-tab .badge { position: absolute; top: 5px; left: calc(50% + 6px); }
.rail-spacer { flex: 1; }
.rail-status { display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 8px 0; font-size: 0.62rem; color: var(--muted); }
.rail-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--muted); }
.rail-dot.ok { background: var(--ok); }
.rail-dot.warn { background: var(--warn); }
.rail-dot.bad { background: var(--bad); }

@media (max-width: 719px) {
  .rail {
    grid-row: 2; grid-column: 1; flex-direction: row; align-items: stretch; justify-content: space-around; gap: 0;
    padding: 4px calc(var(--safe-right) + 4px) calc(4px + var(--safe-bottom)) calc(var(--safe-left) + 4px);
    border-right: 0; border-top: 1px solid var(--divider);
  }
  .rail-logo, .rail-spacer, .rail-status { display: none; }
  .rail-tab { flex: 1; min-height: 50px; }
}
</style>
