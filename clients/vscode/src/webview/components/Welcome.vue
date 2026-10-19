<script setup lang="ts">
import { computed } from "vue";

import { openOverlay, post, state } from "../store.js";
import Logo from "./Logo.vue";

const SUGGESTIONS = [
  { label: "Explain this codebase", text: "Explain the structure of this codebase and where the entry points are." },
  { label: "Fix the failing tests", text: "Run the tests, find what fails, and fix it." },
  { label: "Review my changes", text: "Review the uncommitted changes for bugs and missing tests." },
];

const ui = computed(() => state.ui);
const meta = computed(() => {
  const current = ui.value;
  if (current === null) {
    return "";
  }
  return [current.version ? `v${current.version}` : null, current.models.length ? `${current.models.length} models` : "no models"]
    .filter(Boolean)
    .join(" · ");
});

function suggest(text: string): void {
  state.draft = text;
  state.focus += 1;
}
</script>

<template>
  <section v-if="state.turns.length === 0" id="welcome" class="welcome">
    <div class="welcome-mark"><Logo :size="30" /></div>
    <h1>What are we building?</h1>
    <p>ZettCode reads the workspace, edits files, runs commands and keeps the conversation in this folder.</p>

    <div v-if="ui?.ready" id="suggestions" class="suggestions">
      <button v-for="item in SUGGESTIONS" :key="item.label" type="button" @click="suggest(item.text)">
        {{ item.label }}
      </button>
    </div>

    <div v-else-if="ui" id="setup" class="setup">
      <template v-if="ui.server.status === 'starting'">
        <span class="spinner" />
        <span>{{ ui.server.message }}</span>
      </template>
      <template v-else-if="ui.server.status === 'error' || ui.server.status === 'idle'">
        <div class="setup-copy">
          <strong>The server is not running.</strong>
          <span>{{ ui.server.message }}</span>
        </div>
        <button class="btn solid" type="button" @click="post({ type: 'restart-server' })">Start the server</button>
      </template>
      <template v-else>
        <div class="setup-copy">
          <strong>No model is configured yet.</strong>
          <span>Add a model id and its API key to start. It is written to the ZettCode configuration file.</span>
        </div>
        <button class="btn solid" type="button" @click="openOverlay('add-model')">Add a model</button>
      </template>
    </div>

    <div id="welcome-meta" class="welcome-meta">{{ meta }}</div>
  </section>
</template>

<style>
.welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 9vh 8px 24px;
}

.welcome-mark {
  display: grid;
  place-items: center;
  width: 54px;
  height: 54px;
  margin-bottom: 18px;
  border-radius: 16px;
  border: 1px solid color-mix(in srgb, var(--accent) 38%, transparent);
  background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 14%, transparent), color-mix(in srgb, var(--accent-2) 8%, transparent));
  box-shadow: 0 0 40px color-mix(in srgb, var(--accent) 16%, transparent);
}

.welcome h1 {
  margin: 0 0 8px;
  font-size: 21px;
  font-weight: 650;
  letter-spacing: -0.02em;
}

.welcome p {
  margin: 0;
  max-width: 330px;
  color: var(--muted);
  line-height: 1.55;
}

.suggestions {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: min(100%, 340px);
  margin-top: 26px;
}

.suggestions button {
  display: flex;
  align-items: center;
  padding: 10px 14px;
  border: 1px solid var(--line);
  border-radius: var(--r-m);
  background: transparent;
  text-align: left;
  font-size: 13.5px;
  transition: background 0.12s, border-color 0.12s;
}

.suggestions button:hover {
  background: var(--wash);
  border-color: var(--line-strong);
}

.setup {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  margin-top: 24px;
  max-width: 340px;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: var(--r-l);
  background: var(--wash);
}

.setup-copy {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: var(--small);
}

.setup-copy span {
  color: var(--muted);
}

.welcome-meta {
  margin-top: 28px;
  color: var(--faint);
  font-size: var(--tiny);
}
</style>
