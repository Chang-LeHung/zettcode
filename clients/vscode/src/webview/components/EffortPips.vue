<script setup lang="ts">
import { computed } from "vue";

import { effortMeta } from "../../core/levels.js";

const props = withDefaults(defineProps<{ name: string; index?: number; total?: number }>(), { index: 0, total: 1 });
const meta = computed(() => effortMeta(props.name, props.index, props.total));
</script>

<template>
  <span class="pips" :class="[`tone-${meta.tone}`, `motion-${meta.motion}`]" :title="`${name} · ${meta.level} of 5`" aria-hidden="true">
    <i v-for="n in 5" :key="n" :class="{ lit: n <= meta.level }" :style="{ '--i': n }" />
  </span>
</template>

<style>
.pips {
  display: inline-flex;
  align-items: flex-end;
  gap: 2px;
  height: 14px;
  flex-shrink: 0;
}

.pips i {
  width: 3px;
  border-radius: 1.5px;
  background: var(--line-strong);
  height: calc(4px + var(--i) * 2px);
  transition: background 0.15s;
}

.pips i.lit {
  background: var(--tone, var(--muted));
}

/* max: the lit bars carry a warm gradient that travels along them. The motion plays when a level is chosen and
   settles after a few seconds; a finite count, so a level left on does not keep the eye. */
.pips.motion-flow i.lit {
  background: linear-gradient(180deg, var(--rose), var(--orange), var(--rose));
  background-size: 100% 300%;
  animation: pip-flow 1.6s linear 3;
  animation-delay: calc(var(--i) * -0.18s);
  box-shadow: 0 0 6px color-mix(in srgb, var(--rose) 55%, transparent);
}

/* ultra: the whole palette, climbing, with a glow that breathes. */
.pips.motion-aurora i.lit {
  background: linear-gradient(180deg, var(--accent), var(--accent-2), var(--rose), var(--sky), var(--accent));
  background-size: 100% 400%;
  animation:
    pip-flow 1.9s linear 3,
    pip-glow 1.6s ease-in-out 3;
  animation-delay: calc(var(--i) * -0.22s), calc(var(--i) * -0.16s);
}

@keyframes pip-flow {
  from {
    background-position: 0 0;
  }
  to {
    background-position: 0 -300%;
  }
}

@keyframes pip-glow {
  0%,
  100% {
    box-shadow: 0 0 3px color-mix(in srgb, var(--accent-2) 40%, transparent);
  }
  50% {
    box-shadow: 0 0 9px color-mix(in srgb, var(--accent-2) 85%, transparent);
  }
}

/* The name of a level that moves is drawn in the same light. */
.fx-flow,
.fx-aurora {
  background-clip: text;
  -webkit-background-clip: text;
  color: transparent !important;
  background-size: 250% 100%;
  animation: text-flow 3s linear 2;
}

.fx-flow {
  background-image: linear-gradient(90deg, var(--rose), var(--orange), var(--amber), var(--orange), var(--rose));
}

.fx-aurora {
  background-image: linear-gradient(90deg, var(--accent), var(--accent-2), var(--rose), var(--sky), var(--accent));
  animation-duration: 2.4s;
  filter: drop-shadow(0 0 5px color-mix(in srgb, var(--accent-2) 45%, transparent));
}

@keyframes text-flow {
  from {
    background-position: 0 0;
  }
  to {
    background-position: -250% 0;
  }
}
</style>
