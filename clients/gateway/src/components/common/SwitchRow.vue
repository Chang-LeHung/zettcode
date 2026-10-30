<script setup lang="ts">
defineProps<{ label: string; hint?: string }>();
const model = defineModel<boolean>({ required: true });
</script>

<template>
  <div class="switch-row">
    <div class="grow">
      {{ label }}
      <small v-if="hint">{{ hint }}</small>
    </div>
    <button class="switch" role="switch" :aria-checked="model" :aria-label="label" @click="model = !model" />
  </div>
</template>

<style>
.switch-row { display: flex; align-items: center; gap: 12px; min-height: 54px; padding: 8px 16px; }
.switch-row + .switch-row, .field-row + .switch-row, .switch-row + .field-row { border-top: 1px solid var(--divider); }
.switch-row .grow { flex: 1; min-width: 0; }
.switch-row small { display: block; color: var(--muted); font-size: 0.82rem; margin-top: 2px; line-height: 1.3; }
.switch { position: relative; flex: none; width: 46px; height: 28px; border-radius: 14px; background: var(--divider); transition: background 0.25s ease; }
.switch::after {
  content: ""; position: absolute; top: 2px; left: 2px; width: 24px; height: 24px; border-radius: 50%;
  background: #fff; box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3); transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), width 0.15s;
}
.switch[aria-checked="true"] { background: var(--ok); }
.switch:active::after { width: 28px; }
.switch[aria-checked="true"]::after { transform: translateX(18px); }
.switch[aria-checked="true"]:active::after { transform: translateX(14px); }
</style>
