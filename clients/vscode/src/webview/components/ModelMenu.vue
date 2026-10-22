<script setup lang="ts">
import { computed, nextTick, ref } from "vue";

import { formatTokens } from "../../core/format.js";
import { closeOverlay, openOverlay, post, state } from "../store.js";
import Icon from "./Icon.vue";
import Popover from "./Popover.vue";

defineProps<{ offset: number }>();

const models = computed(() => state.ui?.models ?? []);

/**
 * The model in use is the one the chip names, so the tick can never be somewhere else. The list's own `active` flag is
 * what the server said when the list was read, and a session that is opened puts back the model it last used.
 */
function inUse(model: { name: string; active: boolean }): boolean {
  const named = state.ui?.currentModel ?? null;
  return named === null ? model.active : model.name === named;
}
/** The model whose row is asking "remove it?" right where it sits; there is no dialog for this. */
const confirming = ref<string | null>(null);
const cancel = ref<HTMLButtonElement[] | HTMLButtonElement | null>(null);

async function ask(name: string): Promise<void> {
  confirming.value = name;
  await nextTick();
  (Array.isArray(cancel.value) ? cancel.value[0] : cancel.value)?.focus();
}

function remove(name: string): void {
  confirming.value = null;
  post({ type: "remove-model", name });
}

function use(name: string, active: boolean): void {
  if (!active) {
    post({ type: "set-model", name });
  }
  closeOverlay();
}
</script>

<template>
  <Popover id="model-menu" title="Model" :offset="offset" :width="340">
    <p v-if="!models.length" class="dropdown-empty">No model is configured yet.</p>
    <div class="option-list">
      <div v-for="model in models" :key="model.name" class="option-row" :class="{ confirming: confirming === model.name }">
        <div v-if="confirming === model.name" class="confirm" role="alertdialog" :aria-label="`Remove ${model.name}`" @keydown.esc.stop="confirming = null">
          <span class="confirm-text">Remove <strong>{{ model.name }}</strong>?</span>
          <button ref="cancel" class="btn small" type="button" @click="confirming = null">Cancel</button>
          <button class="btn small danger-solid" type="button" data-confirm="remove" @click="remove(model.name)">Remove</button>
        </div>
        <template v-else>
          <button type="button" class="option" :class="{ current: inUse(model) }" @click="use(model.name, inUse(model))">
            <span class="option-copy">
              <span class="option-name">{{ model.name }}</span>
              <span class="option-desc"
                >{{ model.model }} · {{ formatTokens(model.context_window) }}{{ model.multimodal ? " · images" : "" }}{{ model.web_search ? " · search" : "" }}</span
              >
            </span>
            <Icon v-if="inUse(model)" name="check" :size="14" class="tick" />
          </button>
          <button
            class="icon-btn row-remove"
            type="button"
            title="Remove this model"
            aria-label="Remove this model"
            @click="ask(model.name)"
          >
            <Icon name="x" :size="12" />
          </button>
        </template>
      </div>
    </div>
    <div class="dropdown-rule" />
    <button type="button" class="option" @click="openOverlay('add-model')">
      <Icon name="plus" :size="14" />
      <span class="option-copy"><span class="option-name">Add a model…</span></span>
    </button>
  </Popover>
</template>

<style>
.option-row.confirming {
  border-radius: var(--r-s);
  background: color-mix(in srgb, var(--red) 9%, transparent);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--red) 32%, transparent);
  animation: rise 0.12s ease-out;
}

.confirm {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  min-height: 46px;
  padding: 6px 8px 6px 12px;
}

.confirm-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--small);
}

.btn.danger-solid {
  border-color: var(--red);
  background: var(--red);
  color: #fff;
}

.btn.danger-solid:hover:not(:disabled) {
  background: color-mix(in srgb, var(--red) 88%, #000);
}
.option-row {
  position: relative;
  display: flex;
  align-items: center;
}

.option-row .option {
  flex: 1;
  min-width: 0;
}

.row-remove {
  position: absolute;
  right: 30px;
  width: 22px;
  height: 22px;
  opacity: 0;
}

.option-row:hover .row-remove,
.row-remove:focus-visible {
  opacity: 1;
}

.dropdown-empty {
  margin: 4px 9px 8px;
  color: var(--muted);
  font-size: var(--small);
}
</style>
