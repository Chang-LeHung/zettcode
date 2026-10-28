<script setup lang="ts">
import { t } from "../../i18n";
import { href, route, type Nav } from "../../stores/route";
import type { Section } from "../../sections";
import SimpleRow from "../common/SimpleRow.vue";
import PaneHeader from "./PaneHeader.vue";

defineProps<{ nav: Nav; title: string; sections: Section[] }>();
</script>

<template>
  <PaneHeader :title="title" />
  <div class="pane-list">
    <SimpleRow
      v-for="section in sections"
      :key="section.id"
      :icon="section.icon"
      :title="t(section.label)"
      :href="href(nav, section.id)"
      :current="route.nav === nav && route.arg === section.id"
    />
  </div>
</template>
