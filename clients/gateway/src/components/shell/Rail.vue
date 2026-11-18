<script setup lang="ts">
import { computed, ref } from "vue";
import { t } from "../../i18n";
import { go, href, route, type Nav } from "../../stores/route";
import { showMenu } from "../sheets/sheets";
import { badge } from "../../lib/unread";
import { chatsWithUnread as chatsUnread, lobby } from "../../stores/threads";
import Icon from "../common/Icon.vue";
import type { IconName } from "../common/icons";

/** `extra` tabs sit in the "More" menu on a phone, where seven tabs would not fit; the wide rail shows all of them. */
const tabs: { nav: Nav; label: string; icon: IconName; extra?: boolean }[] = [
  { nav: "chats", label: "Chats", icon: "chat" },
  { nav: "new", label: "New", icon: "plus" },
  { nav: "config", label: "Config", icon: "config", extra: true },
  { nav: "logs", label: "Logs", icon: "logs", extra: true },
  { nav: "graph", label: "Graph", icon: "graph", extra: true },
  { nav: "dashboard", label: "Dashboard", icon: "chart" },
  { nav: "settings", label: "Settings", icon: "settings" },
];

/** The section a person is in when it is one of those behind "More"; said to a screen reader after the button's name. */
const inMore = computed(() => tabs.find((tab) => tab.extra && tab.nav === route.nav));
const moreButton = ref<HTMLButtonElement | null>(null);
async function more(): Promise<void> {
  await showMenu(
    t("More"),
    tabs
      .filter((tab) => tab.extra)
      .map((tab) => ({ icon: tab.icon, label: t(tab.label), current: tab.nav === route.nav, run: () => go(tab.nav) })),
  );
  // The sheet took focus; give it back to the control that opened it (a no-op once the bar is hidden on a wide window).
  moreButton.value?.focus();
}

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
      :class="{ extra: tab.extra }"
      :href="href(tab.nav)"
      :aria-current="route.nav === tab.nav ? 'page' : undefined"
    >
      <Icon :name="tab.icon" />
      <span>{{ t(tab.label) }}</span>
      <span v-if="tab.nav === 'chats' && chatsUnread" class="badge">{{ badge(chatsUnread) }}</span>
    </a>
    <button ref="moreButton" class="rail-tab rail-more" :class="{ active: inMore }" type="button" aria-haspopup="dialog" @click="more">
      <Icon name="more" />
      <span>{{ t("More") }}</span>
      <span v-if="inMore" class="sr">{{ t(inMore.label) }}</span>
    </button>
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
  transition: background 0.15s, color 0.15s, transform 0.15s; text-decoration: none !important;
}
.rail-tab:hover { background: var(--hover); }
/* The wide rail marks the section with a tint; it has no indicator bar. */
.rail-tab[aria-current="page"], .rail-tab.active { color: var(--accent); background: var(--accent-soft); }
/* "More" only exists on a phone (the wide rail shows every tab); the doubled class keeps this independent of rule order. */
.rail-tab.rail-more { display: none; }
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
  .rail-tab.extra { display: none; }
  .rail-tab.rail-more { display: flex; }
  /* On a phone the current tab has no tint: its accent colour and a heavier label say where you are, so colour is not the
     only cue. */
  .rail-tab[aria-current="page"], .rail-tab.active { background: none; font-weight: 650; }
}
</style>
