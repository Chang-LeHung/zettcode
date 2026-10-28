<script setup lang="ts">
import { computed, onMounted, type Component } from "vue";
import { t } from "../../i18n";
import { CONFIG_SECTIONS } from "../../sections";
import { loadConfig, settings } from "../../stores/config";
import { route } from "../../stores/route";
import PageBar from "../common/PageBar.vue";
import DefaultsSection from "./DefaultsSection.vue";
import LimitsSection from "./LimitsSection.vue";
import ModelsSection from "./ModelsSection.vue";
import SendingSection from "./SendingSection.vue";
import WorkspacesSection from "./WorkspacesSection.vue";

const pages: Record<string, Component> = {
  models: ModelsSection,
  defaults: DefaultsSection,
  workspaces: WorkspacesSection,
  sending: SendingSection,
  limits: LimitsSection,
};
const id = computed(() => (route.arg in pages ? route.arg : "models"));
const title = computed(() => t(CONFIG_SECTIONS.find((section) => section.id === id.value)?.label ?? "Config"));
onMounted(() => void loadConfig());
</script>

<template>
  <PageBar :title="title" back />
  <div class="page">
    <div class="page-inner">
      <p v-if="settings.error" class="errcard">{{ settings.error }}</p>
      <component :is="pages[id]" />
    </div>
  </div>
</template>
