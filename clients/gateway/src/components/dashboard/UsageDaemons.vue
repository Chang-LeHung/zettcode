<script setup lang="ts">
import { computed } from "vue";
import { t } from "../../i18n";
import { folderName, tokens } from "../../lib/format";
import { href } from "../../stores/route";
import { lobby } from "../../stores/threads";
import { percent } from "../../stores/usage";
import type { Usage, UsageRow } from "../../types";
import { canRestart, restartNow, restarting } from "../chat/threadActions";
import Avatar from "../common/Avatar.vue";
import Icon from "../common/Icon.vue";
import CacheRing from "./CacheRing.vue";

const props = defineProps<{ usage: Usage }>();

const parts = computed(() => [
  { title: t("Daemons"), rows: props.usage.sessions.filter((row) => row.kind === "daemon") },
  { title: t("Terminal sessions"), rows: props.usage.sessions.filter((row) => row.kind !== "daemon") },
]);

/** The stopped daemon a row is, when one press can start it again. */
const stopped = (row: UsageRow) => {
  const thread = lobby.threads.find((item) => item.id === row.id);
  return canRestart(thread) ? thread : undefined;
};
/** How full the newest context was, as a share of the model's window, when both are known. */
const fill = (row: UsageRow): number | null =>
  row.context_tokens !== null && row.context_window ? Math.min(1, row.context_tokens / row.context_window) : null;
const word = (row: UsageRow): string => (row.online ? (row.status === "working" ? t("typing…") : t("online")) : t("offline"));
const tone = (row: UsageRow): string => (!row.online ? "off" : row.status === "working" ? "busy" : "on");
</script>

<template>
  <template v-for="part in parts" :key="part.title">
    <template v-if="part.rows.length">
      <h3 class="dash-title">{{ part.title }} <small>{{ part.rows.length }}</small></h3>
      <div class="grid">
        <article v-for="row in part.rows" :key="row.id" class="ucard">
          <header class="ucard-head">
            <Avatar :thread="{ id: row.id, name: row.name, kind: row.kind, status: row.online ? row.status : 'dead' }" size="sm" />
            <a class="ucard-name" :href="href('chats', row.id)">{{ row.name }}</a>
            <span class="pill" :class="tone(row)">{{ word(row) }}</span>
            <button
              v-if="stopped(row)"
              class="btn sm"
              type="button"
              :disabled="restarting.has(row.id)"
              :title="t('Restart {name}', { name: row.name })"
              @click="restartNow(stopped(row)!)"
            >
              <span v-if="restarting.has(row.id)" class="spin" /><Icon v-else name="refresh" size="sm" />{{ t("Restart it") }}
            </button>
          </header>
          <p class="ucard-sub">
            <template v-if="row.model">{{ row.model }}</template>
            <template v-if="row.workspace"> · {{ folderName(row.workspace) }}</template>
          </p>
          <div class="ucard-body">
            <CacheRing :share="row.cache_rate" />
            <dl class="nums">
              <div><dt>{{ t("Requests") }}</dt><dd>{{ row.requests.toLocaleString() }}</dd></div>
              <div><dt>{{ t("Input") }}</dt><dd>{{ tokens(row.input_tokens) }}</dd></div>
              <div><dt>{{ t("Output") }}</dt><dd>{{ tokens(row.output_tokens) }}</dd></div>
            </dl>
          </div>
          <div v-if="fill(row) !== null" class="ctx" :title="t('context {share}', { share: percent(fill(row), 0) })">
            <span>{{ t("Context") }}</span>
            <span class="meter"><i :class="{ low: fill(row)! > 0.8 }" :style="{ width: `${fill(row)! * 100}%` }" /></span>
            <span>{{ percent(fill(row), 0) }}</span>
          </div>
        </article>
      </div>
    </template>
  </template>
  <p v-if="!usage.sessions.length" class="card-hint">{{ t("No session is listed.") }}</p>
</template>
