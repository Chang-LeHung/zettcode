<script setup lang="ts">
import { computed, reactive } from "vue";

import type { ModelInput } from "../../../../typescript/src/types.js";
import {
  type Api,
  APIS,
  apiKeys,
  defaultSearchName,
  maxTemperature,
  parseTemperature,
  searchKeys,
  searchProblem,
} from "../../core/model-form.js";
import { closeOverlay, post, toast } from "../store.js";
import Popover from "./Popover.vue";

const form = reactive({
  model: "",
  name: "",
  token: "",
  url: "",
  context: "",
  efforts: "",
  compact: "",
  temperature: "",
  multimodal: false,
  webSearch: false,
  searchName: "",
  api: "chat" as Api,
});

const temperatureLabel = computed(() => `Temperature (0 to ${maxTemperature(form.api)})`);
/** The tool type a search is sent as when none is typed, shown as the placeholder of its field. */
const searchDefault = computed(() => defaultSearchName(form.api, form.model, form.url));
/** Why search cannot be switched on for what is typed so far, or `null`. */
const searchWarning = computed(() => (form.webSearch ? searchProblem(form.api, form.model, form.url) : null));

function number(value: string): number | undefined {
  const trimmed = value.trim();
  return trimmed && Number.isFinite(Number(trimmed)) ? Number(trimmed) : undefined;
}

function submit(): void {
  const model = form.model.trim();
  if (!model) {
    toast("A model id is required.", "warn");
    return;
  }
  const temperature = parseTemperature(form.temperature, form.api);
  if (temperature.kind === "error") {
    toast(temperature.message, "warn");
    return;
  }
  const problem = form.webSearch ? searchProblem(form.api, model, form.url) : null;
  if (problem !== null) {
    toast(problem, "warn");
    return;
  }
  const input: ModelInput = { model };
  if (form.name.trim()) {
    input.display_model = form.name.trim();
  }
  if (form.token.trim()) {
    input.token = form.token.trim();
  }
  if (form.url.trim()) {
    input.base_url = form.url.trim();
  }
  const window = number(form.context);
  if (window !== undefined) {
    input.context_window = window;
  }
  const compact = number(form.compact);
  if (compact !== undefined) {
    input.compact_percent = compact;
  }
  if (temperature.kind === "value") {
    input.temperature = temperature.value;
  }
  const efforts = form.efforts
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  if (efforts.length) {
    input.reasoning_efforts = efforts;
  }
  if (form.multimodal) {
    input.multimodal = true;
  }
  Object.assign(input, searchKeys(form.webSearch, form.searchName));
  Object.assign(input, apiKeys(form.api));
  post({ type: "add-model", model: input });
}
</script>

<template>
  <Popover id="add-model-panel" title="Add a model" :width="420" :tall="680">
    <form class="form" @submit.prevent="submit">
      <label>Model id<input id="m-model" v-model="form.model" placeholder="claude-sonnet-4-5" autocomplete="off" autofocus /></label>
      <div class="form-pair">
        <label>Display name<input id="m-name" v-model="form.name" placeholder="sonnet" autocomplete="off" /></label>
        <label>API key<input id="m-token" v-model="form.token" type="password" placeholder="optional" autocomplete="off" /></label>
      </div>
      <div class="form-pair">
        <label>API
          <select id="m-api" v-model="form.api">
            <option v-for="api in APIS" :key="api.value" :value="api.value">{{ api.label }}</option>
          </select>
        </label>
        <label>{{ temperatureLabel }}<input id="m-temperature" v-model="form.temperature" inputmode="decimal" placeholder="optional" autocomplete="off" /></label>
      </div>
      <label>Base URL<input id="m-url" v-model="form.url" placeholder="optional" autocomplete="off" /></label>
      <div class="form-pair">
        <label>Context window<input id="m-context" v-model="form.context" inputmode="numeric" placeholder="200000" autocomplete="off" /></label>
        <label>Compact at (%)<input id="m-compact" v-model="form.compact" inputmode="numeric" placeholder="80" autocomplete="off" /></label>
      </div>
      <label>Reasoning efforts<input id="m-efforts" v-model="form.efforts" placeholder="low, medium, high" autocomplete="off" /></label>
      <div class="form-checks">
        <label class="check"><input id="m-multimodal" v-model="form.multimodal" type="checkbox" /> Images</label>
        <label class="check"><input id="m-search" v-model="form.webSearch" type="checkbox" /> Web search</label>
      </div>
      <label v-if="form.webSearch">Search tool name<input id="m-search-name" v-model="form.searchName" :placeholder="searchDefault" autocomplete="off" /></label>
      <p v-if="searchWarning" id="m-search-warning" class="form-note warn">{{ searchWarning }}</p>
      <p v-else-if="form.webSearch" class="form-note">The provider runs the search; nothing is fetched here. Leave the name empty to send {{ searchDefault }}.</p>
      <p class="form-note">Written to the ZettCode configuration file. Only the model id is required: leave the key empty for a local server (Ollama, LM Studio, vLLM) or to use the environment's. The key is stored there and never returned by the server.</p>
      <div class="form-actions">
        <button class="btn solid" type="submit" data-action="submit-model">Add model</button>
        <button class="btn ghost" type="button" @click="closeOverlay">Cancel</button>
      </div>
    </form>
  </Popover>
</template>

<style>
.form {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 4px 8px 8px;
}

.form label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  color: var(--muted);
  font-size: var(--tiny);
  font-weight: 600;
}

.form input:not([type="checkbox"]),
.form select {
  height: 30px;
  padding: 0 10px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-s);
  background: var(--input);
  color: var(--fg);
  font-size: var(--small);
  font-weight: 400;
  outline: none;
}

.form input:not([type="checkbox"]):focus,
.form select:focus {
  border-color: color-mix(in srgb, var(--fg) 45%, transparent);
}

.form-pair {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.form-checks {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 16px;
}

.form label.check {
  flex-direction: row;
  align-items: center;
  gap: 6px;
  color: var(--fg);
  font-size: var(--small);
  font-weight: 400;
}

.form-note {
  margin: 0;
  color: var(--faint);
  font-size: var(--tiny);
  line-height: 1.5;
}

.form-note.warn {
  color: var(--amber);
}

.form-actions {
  display: flex;
  gap: 8px;
}
</style>
