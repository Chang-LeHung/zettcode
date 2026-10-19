<script setup lang="ts">
import { computed } from "vue";

import type { ReasoningBlock, Turn } from "../../core/state.js";
import { state, toggleIn } from "../store.js";
import Icon from "./Icon.vue";
import Markdown from "./Markdown.vue";
import Shimmer from "./Shimmer.vue";

const props = defineProps<{ turn: Turn; block: ReasoningBlock; index: number }>();

const id = computed(() => `${props.turn.id}:${props.index}`);
const open = computed(() => state.openReasoning.has(id.value));
/** Only the step the model is still on reads as thinking; the ones behind it are done. */
const live = computed(() => props.turn.status === "running" && props.index === props.turn.blocks.length - 1);
</script>

<template>
  <!-- `thinking` rather than `live`: the status line below the transcript is `.live`, and a shared class name would give
       this block its row layout. -->
  <div class="reasoning step" :class="{ thinking: live, open }" :data-reasoning="id">
    <button class="reasoning-head" type="button" :aria-expanded="open" @click="toggleIn(state.openReasoning, id)">
      <span class="step-dot teal" />
      <span class="reasoning-label" data-reasoning-label><Shimmer v-if="live" text="Thinking" /><template v-else>Thought</template></span>
      <Icon name="down" :size="12" class="reasoning-caret" />
    </button>
    <Markdown v-if="open" class="reasoning-body" :text="block.text" />
  </div>
</template>

<style>
.reasoning {
  margin-bottom: 4px;
}

.reasoning-head {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  padding: 5px 8px 5px 6px;
  border: 0;
  border-radius: 999px;
  background: none;
  color: var(--muted);
  font-size: var(--small);
  line-height: 1.4;
  text-align: left;
}

.reasoning-head:hover {
  background: var(--wash-2);
  color: var(--fg);
}

/* An open thought is a quiet note under its label, not a second card. */
.reasoning.open .reasoning-head {
  color: var(--fg);
}

.reasoning-caret {
  opacity: 0;
  transition: transform 0.12s, opacity 0.12s;
}

.reasoning-head:hover .reasoning-caret,
.reasoning.open .reasoning-caret {
  opacity: 0.8;
}

.reasoning.open .reasoning-caret {
  transform: rotate(180deg);
}

.reasoning-body {
  margin: 4px 0 8px 12px;
  padding-left: 12px;
  max-height: 320px;
  overflow-y: auto;
  border-left: 2px solid color-mix(in srgb, var(--teal) 40%, transparent);
  color: var(--muted);
  font-size: 13px;
}
</style>
