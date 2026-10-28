<script setup lang="ts">
defineProps<{ title: string }>();
</script>

<template>
  <header class="pane-head">
    <h1>{{ title }}</h1>
    <slot />
  </header>
</template>

<style>
.pane-head {
  display: flex; align-items: center; gap: 8px; min-height: 56px;
  padding: calc(var(--safe-top) + 8px) 12px 8px;
}
.pane-head h1 { flex: 1; margin: 0; font-size: 1.2rem; font-weight: 650; letter-spacing: -0.01em; }
.pane-list { flex: 1; overflow-y: auto; overscroll-behavior: contain; -webkit-overflow-scrolling: touch; padding-bottom: 8px; }
.pane-group { padding: 12px 16px 4px; font-size: 0.8rem; font-weight: 600; color: var(--accent); letter-spacing: 0.02em; }
</style>
