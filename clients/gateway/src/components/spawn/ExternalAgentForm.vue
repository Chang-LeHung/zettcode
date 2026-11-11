<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { gateway } from "../../api/gateway";
import { ApiError } from "../../api/http";
import { t } from "../../i18n";
import { go } from "../../stores/route";
import { loadThreads } from "../../stores/threads";
import { toast } from "../../stores/ui";
import type { AgentType } from "../../types";

const types = ref<AgentType[]>([]);
const kind = ref("");
const title = ref("");
const group = ref("");
const busy = ref(false);
const failure = ref("");
const ready = computed(() => !!kind.value && !busy.value);

onMounted(async () => {
  try {
    const answer = await gateway.agents();
    types.value = answer.agents;
    kind.value = answer.agents[0]?.name ?? "";
  } catch (error) {
    failure.value = error instanceof ApiError ? error.message : String(error);
  }
});

async function start(): Promise<void> {
  if (!ready.value) return;
  busy.value = true;
  failure.value = "";
  try {
    const made = await gateway.createAgent({ kind: kind.value, title: title.value.trim(), group: group.value.trim() });
    await loadThreads();
    toast(t("External agent started"));
    go("chats", made.thread?.id ?? made.agent.session_id);
  } catch (error) {
    failure.value = error instanceof ApiError ? error.message : String(error);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <section class="card external-agent">
    <div class="card-title">{{ t("External agent") }}</div>
    <p class="card-hint">
      {{ t("A plugin installed in the gateway can start a session that answers by itself. It appears in Chats and can join a group on start.") }}
    </p>
    <p v-if="!types.length" class="card-hint warn">
      {{ t("No external agent plugins are installed.") }}
    </p>
    <form v-else @submit.prevent="start">
      <label class="field-row">
        <span>{{ t("Type") }}</span>
        <select v-model="kind">
          <option v-for="agent in types" :key="agent.name" :value="agent.name">
            {{ agent.title }} — {{ agent.description }}
          </option>
        </select>
      </label>
      <label class="field-row">
        <span>{{ t("Title") }}</span>
        <input v-model="title" type="text" autocomplete="off" :placeholder="t('Optional')" maxlength="120" />
      </label>
      <label class="field-row">
        <span>{{ t("Join group") }}</span>
        <input v-model="group" type="text" autocomplete="off" :placeholder="t('Optional, without #')" maxlength="40" />
      </label>
      <p v-if="failure" class="errcard" role="alert">{{ failure }}</p>
      <button class="btn block" type="submit" :disabled="!ready">
        <span v-if="busy" class="spin" />
        {{ busy ? t("Starting…") : t("Start external agent") }}
      </button>
    </form>
  </section>
</template>

<style>
.external-agent { margin: 16px; padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; }
.external-agent .field-row { display: flex; flex-direction: column; gap: 4px; }
.external-agent .field-row > span { color: var(--muted); font-size: 0.78rem; font-weight: 600; }
.external-agent select, .external-agent input { min-height: 40px; padding: 8px 10px; border: 1px solid var(--divider); border-radius: 10px; background: var(--bg); color: var(--text); font: inherit; }
</style>
