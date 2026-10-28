<script setup lang="ts">
import { computed, type Component } from "vue";
import { t } from "../../i18n";
import { SETTINGS_SECTIONS } from "../../sections";
import { route } from "../../stores/route";
import PageBar from "../common/PageBar.vue";
import AppearanceSection from "./AppearanceSection.vue";
import ConnectionSection from "./ConnectionSection.vue";
import DataSection from "./DataSection.vue";
import NotificationsSection from "./NotificationsSection.vue";

const pages: Record<string, Component> = {
  connection: ConnectionSection,
  appearance: AppearanceSection,
  notifications: NotificationsSection,
  data: DataSection,
};
const id = computed(() => (route.arg in pages ? route.arg : "connection"));
const title = computed(() => t(SETTINGS_SECTIONS.find((section) => section.id === id.value)?.label ?? "Settings"));
</script>

<template>
  <PageBar :title="title" back />
  <div class="page"><div class="page-inner"><component :is="pages[id]" /></div></div>
</template>
