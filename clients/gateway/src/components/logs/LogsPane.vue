<script setup lang="ts">
import { t } from "../../i18n";
import { folderName } from "../../lib/format";
import { daemons } from "../../stores/threads";
import { href, route } from "../../stores/route";
import Avatar from "../common/Avatar.vue";
import PaneHeader from "../shell/PaneHeader.vue";
</script>

<template>
  <PaneHeader :title="t('Logs')" />
  <div class="pane-list">
    <div v-if="!daemons.length" class="empty"><b>{{ t("No daemons") }}</b>{{ t("A daemon's state and log appear here.") }}</div>
    <a v-for="thread in daemons" :key="thread.id" class="row" :href="href('logs', thread.id)" :aria-current="route.arg === thread.id ? 'true' : undefined">
      <Avatar :thread="thread" size="sm" />
      <div class="row-body">
        <span class="row-name">{{ thread.name }}</span>
        <span class="row-sub">{{ t(thread.status) }} · {{ folderName(thread.workspace) }}</span>
      </div>
    </a>
  </div>
</template>
