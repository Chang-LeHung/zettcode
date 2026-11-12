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
const loading = ref(true);
const failure = ref("");
const ready = computed(() => !!kind.value && !busy.value);

onMounted(async () => {
  try {
    const answer = await gateway.agents();
    types.value = answer.agents;
    kind.value = answer.agents[0]?.name ?? "";
  } catch (error) {
    failure.value = error instanceof ApiError ? error.message : String(error);
  } finally {
    loading.value = false;
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

function initial(agent: AgentType): string {
  return (agent.title || agent.name).slice(0, 1).toUpperCase();
}
</script>

<template>
  <div class="agent-setup">
    <header class="agent-lead">
      <p>
        {{ t("An installed gateway plugin starts a session that answers on its own. It appears in Chats and can join a group on start.") }}
      </p>
    </header>

    <div v-if="loading" class="agent-card agent-loading" aria-busy="true">
      <span class="spin" />
      {{ t("Loading…") }}
    </div>

    <div v-else-if="!types.length" class="agent-card agent-empty">
      <b>{{ t("No external agent plugins are installed.") }}</b>
      <span>{{ t("Install one, then restart the gateway. Codex and Claude Code come with zettcode-code-agents.") }}</span>
      <p v-if="failure" class="errcard" role="alert">{{ failure }}</p>
    </div>

    <form v-else class="agent-card" @submit.prevent="start">
      <div class="agent-types" role="radiogroup" :aria-label="t('Choose the kind of agent')">
        <button
          v-for="agent in types"
          :key="agent.name"
          type="button"
          class="agent-type"
          :class="{ on: kind === agent.name }"
          role="radio"
          :aria-checked="kind === agent.name"
          @click="kind = agent.name"
        >
          <img v-if="agent.avatar" class="agent-avatar" :src="agent.avatar" alt="" />
          <span v-else class="agent-avatar fallback">{{ initial(agent) }}</span>
          <span class="agent-copy">
            <strong>{{ agent.title }}</strong>
            <span v-if="agent.description">{{ agent.description }}</span>
          </span>
          <span class="agent-radio" aria-hidden="true" />
        </button>
      </div>

      <div class="agent-fields">
        <label class="agent-field">
          <span>{{ t("Title") }} <em>{{ t("Optional") }}</em></span>
          <input v-model="title" type="text" autocomplete="off" :placeholder="t('What this agent is for')" maxlength="120" />
        </label>
        <label class="agent-field">
          <span>{{ t("Join group") }} <em>{{ t("Optional, without #") }}</em></span>
          <input v-model="group" type="text" autocomplete="off" placeholder="frontend" maxlength="40" />
        </label>
      </div>

      <p v-if="failure" class="errcard" role="alert">{{ failure }}</p>

      <div class="agent-actions">
        <button class="btn block" type="submit" :disabled="!ready">
          <span v-if="busy" class="spin" />
          {{ busy ? t("Starting…") : t("Start external agent") }}
        </button>
      </div>
    </form>
  </div>
</template>

<style>
.agent-setup { display: flex; flex-direction: column; gap: 12px; }
.agent-lead { padding: 2px 4px 0; }
.agent-lead p { margin: 0; color: var(--muted); font-size: 0.9rem; line-height: 1.5; }

.agent-card { margin: 0; padding: 8px; overflow: hidden; border: 1px solid var(--divider); border-radius: 18px; background: var(--surface); box-shadow: var(--shadow); }

.agent-types { display: flex; flex-direction: column; gap: 6px; }
.agent-type {
  display: flex; align-items: center; gap: 12px; width: 100%; padding: 12px; border: 1px solid transparent;
  border-radius: 13px; text-align: left; transition: background 0.15s, border-color 0.15s, box-shadow 0.15s;
}
.agent-type:hover { background: var(--surface-2); }
.agent-type.on { border-color: var(--accent); background: var(--accent-soft); }
.agent-avatar { width: 42px; height: 42px; border-radius: 12px; flex: none; object-fit: cover; background: var(--surface-2); }
.agent-avatar.fallback { display: grid; place-items: center; color: var(--accent); font-size: 1.05rem; font-weight: 700; background: var(--accent-soft); }
.agent-copy { display: flex; flex: 1; flex-direction: column; gap: 2px; min-width: 0; }
.agent-copy strong { color: var(--text); font-size: 0.98rem; font-weight: 650; }
.agent-copy span { color: var(--muted); font-size: 0.82rem; line-height: 1.4; }
.agent-radio { position: relative; width: 20px; height: 20px; flex: none; border: 1.5px solid var(--divider); border-radius: 50%; transition: border-color 0.15s; }
.agent-type.on .agent-radio { border-color: var(--accent); }
.agent-type.on .agent-radio::after { content: ''; position: absolute; inset: 4px; border-radius: 50%; background: var(--accent); }

.agent-fields { display: flex; flex-direction: column; margin-top: 6px; border-top: 1px solid var(--divider); }
.agent-field { display: flex; flex-direction: column; gap: 7px; padding: 12px 12px 8px; }
.agent-field > span { color: var(--muted); font-size: 0.79rem; font-weight: 650; letter-spacing: 0.02em; }
.agent-field em { color: var(--muted); font-style: normal; font-weight: 400; opacity: 0.75; }
.agent-field input {
  width: 100%; height: 44px; padding: 0 13px; border: 1px solid var(--divider); border-radius: 12px;
  outline: none; background: var(--surface-2); color: var(--text); font-size: 1rem; transition: border-color 0.15s, box-shadow 0.15s, background 0.15s;
}
.agent-field input::placeholder { color: var(--muted); opacity: 0.8; }
.agent-field input:focus { border-color: var(--accent); background: var(--surface); box-shadow: 0 0 0 3px var(--accent-soft); }

.agent-card .errcard { margin: 6px 12px; }
.agent-actions { padding: 8px 12px 4px; }
.agent-actions .btn { min-height: 48px; border-radius: 13px; }

.agent-loading, .agent-empty { display: flex; align-items: center; justify-content: center; gap: 10px; min-height: 150px; padding: 24px; color: var(--muted); text-align: center; }
.agent-empty { flex-direction: column; gap: 4px; font-size: 0.9rem; line-height: 1.45; }
.agent-empty b { color: var(--text); font-size: 0.98rem; }

@media (max-width: 480px) {
  .agent-type { padding: 10px; }
  .agent-avatar { width: 38px; height: 38px; }
}
</style>
