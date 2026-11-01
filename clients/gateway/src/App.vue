<script setup lang="ts">
import { computed, type Component } from "vue";
import ChatPane from "./components/chats/ChatPane.vue";
import ChatView from "./components/chat/ChatView.vue";
import GraphPane from "./components/graph/GraphPane.vue";
import GraphView from "./components/graph/GraphView.vue";
import ConfigPage from "./components/config/ConfigPage.vue";
import LogsPane from "./components/logs/LogsPane.vue";
import LogView from "./components/logs/LogView.vue";
import SheetHost from "./components/common/SheetHost.vue";
import ToastHost from "./components/common/ToastHost.vue";
import NewForm from "./components/spawn/NewForm.vue";
import NewPane from "./components/spawn/NewPane.vue";
import SettingsPage from "./components/settings/SettingsPage.vue";
import LoginScreen from "./components/shell/LoginScreen.vue";
import Rail from "./components/shell/Rail.vue";
import SectionPane from "./components/shell/SectionPane.vue";
import WelcomeMain from "./components/shell/WelcomeMain.vue";
import { CONFIG_SECTIONS, SETTINGS_SECTIONS } from "./sections";
import { t } from "./i18n";
import { auth } from "./stores/auth";
import { route } from "./stores/route";

const pane = computed<{ component: Component; props: Record<string, unknown> }>(() => {
  switch (route.nav) {
    case "new":
      return { component: NewPane, props: {} };
    case "config":
      return { component: SectionPane, props: { nav: "config", title: t("Config"), sections: CONFIG_SECTIONS } };
    case "logs":
      return { component: LogsPane, props: {} };
    case "graph":
      return { component: GraphPane, props: {} };
    case "settings":
      return { component: SectionPane, props: { nav: "settings", title: t("Settings"), sections: SETTINGS_SECTIONS } };
    default:
      return { component: ChatPane, props: {} };
  }
});

const main = computed<{ component: Component; props: Record<string, unknown>; key: string } | null>(() => {
  switch (route.nav) {
    case "new":
      return { component: NewForm, props: {}, key: "new" };
    case "config":
      return { component: ConfigPage, props: {}, key: "config" };
    case "graph":
      return { component: GraphView, props: {}, key: "graph" };
    case "settings":
      return { component: SettingsPage, props: {}, key: "settings" };
    case "logs":
      return route.arg ? { component: LogView, props: { id: route.arg }, key: `logs:${route.arg}` } : null;
    default:
      return route.arg ? { component: ChatView, props: { id: route.arg }, key: `chat:${route.arg}` } : null;
  }
});

// On a phone only one of the list and the page is shown. A list-only section shows its list until something is chosen;
// the New form and the Graph have no list worth stopping at (the Graph's feed is its own panel on a phone).
const view = computed(() => (main.value && (route.arg || route.nav === "new" || route.nav === "graph") ? "main" : "pane"));
// A conversation takes the whole screen on a phone, as a messenger's does; the tab bar comes back with the list.
const fullscreen = computed(() => route.nav === "chats" && route.arg !== "");
</script>

<template>
  <div id="root">
    <LoginScreen v-if="auth.checked && !auth.signedIn" />
    <div v-else-if="auth.checked" class="app" :data-view="view" :data-fullscreen="fullscreen">
      <Rail />
      <section class="pane"><component :is="pane.component" v-bind="pane.props" /></section>
      <main class="main">
        <component :is="main.component" v-if="main" :key="main.key" v-bind="main.props" />
        <WelcomeMain v-else />
      </main>
    </div>
    <ToastHost />
    <SheetHost />
  </div>
</template>

<style>
.app { display: grid; grid-template-columns: var(--rail) var(--pane) minmax(0, 1fr); height: 100%; background: var(--bg); }
.pane { display: flex; flex-direction: column; min-width: 0; min-height: 0; background: var(--surface); border-right: 1px solid var(--divider); }
.main { display: flex; flex-direction: column; min-width: 0; min-height: 0; background: var(--surface); position: relative; }

@media (max-width: 719px) {
  .app { grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(0, 1fr) auto; }
  .pane, .main { grid-row: 1; grid-column: 1; border-right: 0; }
  .app[data-view="pane"] .main { display: none; }
  .app[data-view="main"] .pane { display: none; }
  .app[data-view="main"] .main { animation: slide 0.22s ease-out; }
  .app[data-fullscreen="true"] .rail { display: none; }
  .app[data-fullscreen="true"] { grid-template-rows: minmax(0, 1fr); }
}
</style>
