<script setup lang="ts">
import { computed } from "vue";
import { t } from "../../i18n";
import { tokens } from "../../lib/format";
import { groupArg, groupThread } from "../../stores/groups";
import { href } from "../../stores/route";
import type { Usage } from "../../types";
import { restartable, restartAll, restarting } from "../chat/threadActions";
import Avatar from "../common/Avatar.vue";
import CacheRing from "./CacheRing.vue";

const props = defineProps<{ usage: Usage }>();

/** Each group with the stopped daemons a press can start and whether one of them is being started now. */
const cards = computed(() =>
  props.usage.groups.map((group) => {
    const ids = restartable(group.offline_ids).map((thread) => thread.id);
    return { group, ids, busy: ids.some((id) => restarting.has(id)) };
  }),
);
</script>

<template>
  <section class="hero">
    <CacheRing :share="usage.total.cache_rate" :size="92" />
    <div class="hero-text">
      <b>{{ t("Cache hit") }}</b>
      <span>{{ t("The part of the input the provider served from its cache. Higher is cheaper and faster.") }}</span>
    </div>
    <div class="tiles">
      <div class="tile"><b>{{ usage.total.requests.toLocaleString() }}</b><span>{{ t("Requests") }}</span></div>
      <div class="tile"><b>{{ tokens(usage.total.input_tokens) }}</b><span>{{ t("Input tokens") }}</span></div>
      <div class="tile"><b>{{ tokens(usage.total.output_tokens) }}</b><span>{{ t("Output tokens") }}</span></div>
      <div class="tile"><b>{{ tokens(usage.total.cache_read_tokens) }}</b><span>{{ t("Cached tokens") }}</span></div>
    </div>
  </section>

  <h3 class="dash-title">{{ t("Groups") }}</h3>
  <p v-if="!usage.groups_known" class="card-hint warn">{{ t("The session broker did not answer, so the groups are not known right now.") }}</p>
  <p v-else-if="!usage.groups.length" class="card-hint">{{ t("There are no groups.") }}</p>
  <div v-else class="grid">
    <article v-for="{ group, ids, busy } in cards" :key="group.name" class="ucard">
      <header class="ucard-head">
        <Avatar :thread="groupThread(group.name)" size="sm" />
        <a class="ucard-name" :href="href('chats', groupArg(group.name))">#{{ group.name }}</a>
        <button v-if="ids.length" class="btn sm" :disabled="busy" @click="restartAll(ids)">
          <span v-if="busy" class="spin" />{{ t("Restart offline") }}
        </button>
      </header>
      <p class="ucard-sub">
        {{ t("{count} members", { count: group.members }) }}
        <template v-if="group.offline_ids.length"> · <span class="warn">{{ t("{count} offline", { count: group.offline_ids.length }) }}</span></template>
        <template v-if="group.measured < group.members"> · {{ t("{count} not measured", { count: group.members - group.measured }) }}</template>
      </p>
      <div class="ucard-body">
        <CacheRing :share="group.cache_rate" />
        <dl class="nums">
          <div><dt>{{ t("Requests") }}</dt><dd>{{ group.requests.toLocaleString() }}</dd></div>
          <div><dt>{{ t("Input") }}</dt><dd>{{ tokens(group.input_tokens) }}</dd></div>
          <div><dt>{{ t("Output") }}</dt><dd>{{ tokens(group.output_tokens) }}</dd></div>
        </dl>
      </div>
      <p v-if="group.cache_input_tokens < group.input_tokens" class="ucard-foot">
        {{ t("Cache hit is over {input} of the {all} input: the rest did not report it.", { input: tokens(group.cache_input_tokens), all: tokens(group.input_tokens) }) }}
      </p>
    </article>
  </div>
</template>
