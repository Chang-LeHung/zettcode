<script setup lang="ts">
import { computed } from "vue";

import type { Permission } from "../../../../typescript/src/types.js";
import { permissionDescription, permissionLabel } from "../../core/format.js";
import { effortMeta, permissionMeta } from "../../core/levels.js";
import { closeOverlay, post, state } from "../store.js";
import EffortPips from "./EffortPips.vue";
import Icon from "./Icon.vue";
import Popover from "./Popover.vue";

const props = defineProps<{ kind: "effort" | "permission"; offset: number }>();

const settings = computed(() => state.ui?.settings ?? null);

const options = computed(() => {
  if (props.kind === "effort") {
    const current = settings.value?.effort ?? null;
    const values = settings.value?.efforts ?? [];
    return values.map((value, index) => {
      const meta = effortMeta(value, index, values.length);
      return {
        value,
        name: value,
        description: meta.note,
        current: value === current,
        motion: meta.motion,
        tone: meta.tone,
        index,
        total: values.length,
        icon: "",
      };
    });
  }
  const current = settings.value?.permission ?? "ask";
  return (settings.value?.permissions ?? ["deny", "ask", "safe", "auto"]).map((value, index, all) => {
    const meta = permissionMeta(value);
    return {
      value,
      name: permissionLabel(value),
      description: permissionDescription(value),
      current: value === current,
      motion: "plain" as const,
      tone: meta.tone,
      index,
      total: all.length,
      icon: meta.icon,
    };
  });
});

function choose(value: string): void {
  if (props.kind === "effort") {
    post({ type: "set-effort", effort: value });
  } else {
    post({ type: "set-permission", permission: value as Permission });
  }
  closeOverlay();
}
</script>

<template>
  <Popover
    :id="`${kind}-menu`"
    :title="kind === 'effort' ? 'Reasoning effort' : 'Shell permission'"
    :offset="offset"
    :width="kind === 'effort' ? 300 : 360"
  >
    <p v-if="!options.length" class="dropdown-empty">This model has no reasoning levels to choose.</p>
    <div class="option-list">
      <button
        v-for="option in options"
        :key="option.value"
        type="button"
        class="option"
        :class="[`tone-${option.tone}`, `fx-row-${option.motion}`, { current: option.current }]"
        :data-effort="kind === 'effort' ? option.value : undefined"
        :data-permission="kind === 'permission' ? option.value : undefined"
        @click="choose(option.value)"
      >
        <span v-if="kind === 'permission'" class="badge-icon" :class="`risk-${permissionMeta(option.value).risk}`">
          <Icon :name="option.icon" :size="15" />
        </span>
        <span class="option-copy">
          <span
            class="option-name"
            :class="{ 'fx-flow': option.motion === 'flow', 'fx-aurora': option.motion === 'aurora' }"
            >{{ option.name }}</span
          >
          <span v-if="option.description" class="option-desc">{{ option.description }}</span>
        </span>
        <EffortPips v-if="kind === 'effort'" :name="option.name" :index="option.index" :total="option.total" />
        <Icon v-if="option.current" name="check" :size="14" class="tick" />
      </button>
    </div>
  </Popover>
</template>

<style>
/* A permission's icon sits in a tinted tile, so the four read as four different things at a glance. */
.badge-icon {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  border-radius: 8px;
  color: var(--tone);
  background: color-mix(in srgb, var(--tone) 15%, transparent);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--tone) 28%, transparent);
}

.badge-icon.risk-3 {
  animation: tile-glow 2.6s ease-in-out 3;
}

@keyframes tile-glow {
  0%,
  100% {
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--tone) 28%, transparent), 0 0 0 0 transparent;
  }
  50% {
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--tone) 55%, transparent), 0 0 10px color-mix(in srgb, var(--tone) 40%, transparent);
  }
}

.option.tone-violet.current .badge-icon,
.option.tone-rose.current .badge-icon,
.option.tone-teal.current .badge-icon,
.option.tone-amber.current .badge-icon {
  background: color-mix(in srgb, var(--tone) 22%, transparent);
}

/* The two levels that move also move the row they sit in: a slow sheen crosses it. */
.option.fx-row-flow,
.option.fx-row-aurora {
  position: relative;
  overflow: hidden;
}

.option.fx-row-flow::after,
.option.fx-row-aurora::after {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
  background: linear-gradient(105deg, transparent 30%, color-mix(in srgb, var(--tone) 16%, transparent) 50%, transparent 70%);
  transform: translateX(-100%);
  animation: sheen 3.2s ease-in-out 2;
}

.option.fx-row-aurora::after {
  background: linear-gradient(105deg, transparent 25%, color-mix(in srgb, var(--accent) 20%, transparent) 42%, color-mix(in srgb, var(--accent-2) 22%, transparent) 58%, transparent 75%);
  animation-duration: 2.6s;
}

@keyframes sheen {
  0% {
    transform: translateX(-100%);
  }
  55%,
  100% {
    transform: translateX(100%);
  }
}
</style>
