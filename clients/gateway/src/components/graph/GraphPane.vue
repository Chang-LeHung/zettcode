<script setup lang="ts">
import { t } from "../../i18n";
import PaneHeader from "../shell/PaneHeader.vue";
import GraphPanel from "./GraphPanel.vue";
</script>

<template>
  <PaneHeader :title="t('Graph')" />
  <GraphPanel />
</template>
