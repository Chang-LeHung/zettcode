<script setup lang="ts">
// The shape of what is about to appear, so a slow answer does not show an empty page.
// `rows`: the chat list; `bubbles`: a conversation; `cards`: a settings page.
withDefaults(defineProps<{ kind: "rows" | "bubbles" | "cards"; count?: number }>(), { count: 6 });
</script>

<template>
  <div class="skeleton" :class="kind" aria-busy="true" role="status">
    <span class="sr">…</span>
    <template v-if="kind === 'rows'">
      <div v-for="n in count" :key="n" class="sk-row" :style="{ animationDelay: `${n * 60}ms` }">
        <i class="skel sk-avatar" />
        <div class="sk-lines">
          <i class="skel" :style="{ width: `${38 + ((n * 17) % 30)}%` }" />
          <i class="skel" :style="{ width: `${62 + ((n * 11) % 30)}%` }" />
        </div>
      </div>
    </template>
    <template v-else-if="kind === 'bubbles'">
      <div v-for="n in count" :key="n" class="sk-msg" :class="n % 3 === 0 ? 'out' : 'in'">
        <i class="skel sk-bubble" :style="{ width: `${30 + ((n * 23) % 40)}%`, height: `${36 + ((n * 13) % 40)}px` }" />
      </div>
    </template>
    <template v-else>
      <div v-for="n in count" :key="n" class="sk-card">
        <i class="skel" :style="{ width: '30%', height: '12px' }" />
        <i class="skel" :style="{ width: '90%' }" />
        <i class="skel" :style="{ width: `${50 + ((n * 19) % 40)}%` }" />
      </div>
    </template>
  </div>
</template>

<style>
.skel {
  display: block; height: 12px; border-radius: 8px; background: var(--hover);
  background-image: linear-gradient(90deg, transparent, color-mix(in srgb, var(--surface) 70%, transparent), transparent);
  background-size: 220% 100%; background-repeat: no-repeat; animation: shimmer 1.3s ease-in-out infinite;
}
@keyframes shimmer { from { background-position: 160% 0; } to { background-position: -60% 0; } }
.sk-row { display: flex; align-items: center; gap: 12px; margin: 2px 6px; padding: 8px 12px; min-height: var(--row); animation: fade 0.3s both; }
.sk-avatar { width: 46px; height: 46px; border-radius: 50%; flex: none; }
.sk-lines { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 9px; }
.sk-msg { display: flex; padding: 5px 14px; }
.sk-msg.out { justify-content: flex-end; }
.sk-bubble { border-radius: 16px; max-width: 100%; }
.skeleton.cards { padding: 4px 0; }
.sk-card { display: flex; flex-direction: column; gap: 12px; margin: 10px 0; padding: 18px 16px; border-radius: var(--radius); background: var(--surface); }
</style>
