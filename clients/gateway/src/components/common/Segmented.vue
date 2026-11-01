<script setup lang="ts">
defineProps<{ options: { value: string; label: string; disabled?: boolean }[]; label: string }>();
const model = defineModel<string>({ required: true });
</script>

<template>
  <div class="seg" role="radiogroup" :aria-label="label">
    <button
      v-for="option in options"
      :key="option.value"
      type="button"
      role="radio"
      :aria-checked="model === option.value"
      :disabled="option.disabled"
      @click="model = option.value"
    >
      {{ option.label }}
    </button>
  </div>
</template>

<style>
.seg { display: flex; margin: 8px 14px 12px; padding: 3px; border-radius: 11px; background: var(--surface-2); gap: 2px; }
.seg button { flex: 1; min-height: 38px; border-radius: 9px; font-weight: 550; color: var(--muted); transition: background 0.25s ease, color 0.2s, box-shadow 0.25s, transform 0.15s; }
.seg button:active:not(:disabled) { transform: scale(0.96); }
.seg button[aria-checked="true"] { background: var(--surface); color: var(--text); box-shadow: 0 1px 4px rgba(0, 0, 0, 0.14); }
.seg button:disabled { opacity: 0.4; }
</style>
