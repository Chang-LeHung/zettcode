<script setup lang="ts">
import { computed, watch, type Component } from "vue";
import { t } from "../../i18n";
import { SETTINGS_SECTIONS } from "../../sections";
import { route } from "../../stores/route";
import { servers } from "../../stores/servers";
import PageBar from "../common/PageBar.vue";
import AppearanceSection from "./AppearanceSection.vue";
import ConnectionSection from "./ConnectionSection.vue";
import DataSection from "./DataSection.vue";
import NotificationsSection from "./NotificationsSection.vue";
import ServersSection from "./ServersSection.vue";

const pages: Record<string, Component> = {
  servers: ServersSection,
  connection: ConnectionSection,
  appearance: AppearanceSection,
  notifications: NotificationsSection,
  data: DataSection,
};
const id = computed(() => {
  if (route.arg === "servers" && servers.mode !== "app") return "connection";
  return route.arg in pages ? route.arg : "connection";
});
watch(
  id,
  (value) => {
    if (route.arg === "servers" && value !== "servers") location.replace(`#/settings/${value}`);
  },
  { immediate: true },
);
const title = computed(() => t(SETTINGS_SECTIONS.find((section) => section.id === id.value)?.label ?? "Settings"));
</script>

<template>
  <PageBar :title="title" back />
  <div class="page"><div class="page-inner"><component :is="pages[id]" /></div></div>
</template>
